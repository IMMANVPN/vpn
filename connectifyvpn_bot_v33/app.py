from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
from datetime import datetime, timedelta
from typing import Any, Optional, Tuple

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
import uvicorn

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from core.settings import settings
from core import db
from bot.handlers import router
from bot.logic import make_vless_username, reseller_quota, reseller_period
from services.toyyibpay import ToyyibPayClient, ToyyibPayConfig
from services.vpn_vless_ntls import (
    add_vless_user_to_xray_config,
    VlessLinkConfig,
    build_vless_ws_ntls_link,
)
from services.rate_limit import SlidingRateLimiter
from services.scheduler import loop as scheduler_loop
from ui.texts import RULES_TEXT

# -------------------------
# Init
# -------------------------
db.init_db()

bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
dp.include_router(router)

app = FastAPI()
# basic protection for callback/health endpoints
limiter = SlidingRateLimiter(limit=60, window_sec=60)


def _vless_cfg() -> VlessLinkConfig:
    return VlessLinkConfig(settings.VLESS_ADDRESS, settings.VLESS_PORT, settings.VLESS_HOST, settings.VLESS_PATH)


def _tp() -> ToyyibPayClient:
    cb = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/toyyibpay/callback?token={settings.CALLBACK_TOKEN}"
    ret = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/thank-you"
    return ToyyibPayClient(ToyyibPayConfig(settings.TOYYIBPAY_SECRET_KEY, settings.TOYYIBPAY_CATEGORY_CODE, cb, ret))


def _get_order_by_billcode(billcode: str) -> Optional[dict]:
    """Fallback lookup by billcode (db layer may not expose helper)."""
    if not billcode:
        return None
    try:
        conn = sqlite3.connect(db.DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM orders WHERE billcode=? ORDER BY id DESC LIMIT 1", (billcode,)).fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None


def _safe_iso(x: Any) -> str:
    return str(x) if x is not None else ""


async def fulfill_paid_order(bot_: Bot, order: dict) -> None:
    """Provision VPN / activate reseller after payment confirmed.
    Must be idempotent together with db.fulfill_order_once(order_id).
    """
    order_type = str(order.get("order_type") or "").upper()
    plan_code = str(order.get("plan_code") or "").upper()
    tg_id = int(order.get("tg_id") or 0)
    if tg_id <= 0:
        return

    # ---- PLAN purchase ----
    if order_type == "PLAN":
        # allow bonus days on upgrade (Lite -> Pro)
        bonus_days = 0
        try:
            meta = json.loads(order.get("meta_json") or "{}")
            bonus_days = int(meta.get("bonus_pro_days") or 0)
        except Exception:
            bonus_days = 0

        username = make_vless_username(tg_id, plan_code)

        # Validity: 365 days + optional bonus for upgrade
        expires_at = (datetime.utcnow() + timedelta(days=365 + max(0, bonus_days))).isoformat()

        uuid = add_vless_user_to_xray_config(
            xray_config_path=settings.XRAY_CONFIG_PATH,
            restart_cmd=settings.XRAY_RESTART_CMD,
            username=username,
            expire_date=expires_at[:10],
        )
        link = build_vless_ws_ntls_link(uuid, username, _vless_cfg())

        # Store account
        db.insert_vpn_account(tg_id, plan_code, uuid, username, link, expires_at)
        db.audit("fulfilled_plan", f"oid={order.get('id')} tg={tg_id} plan={plan_code} u={username} bonus={bonus_days}")

        await bot_.send_message(
            tg_id,
            "<b>✅ Akaun siap & aktif!</b>\n\n"
            f"Plan: <b>{plan_code}</b>\n"
            f"Expiry: <b>{expires_at[:10]}</b>\n\n"
            "<b>VLESS Link</b>\n"
            f"<code>{link}</code>\n\n"
            f"{RULES_TEXT}",
        )
        return

    # ---- RESELLER activation ----
    if order_type == "RESELLER":
        quota = reseller_quota(plan_code)
        start_at, end_at = reseller_period()
        db.upsert_reseller(tg_id, plan_code, quota, start_at, end_at)

        ym = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m")
        db.ensure_monthly_credit(tg_id, ym, quota)

        db.audit("fulfilled_reseller", f"oid={order.get('id')} tg={tg_id} pack={plan_code} quota={quota}")

        await bot_.send_message(
            tg_id,
            "<b>✅ Reseller Activated!</b>\n\n"
            f"Pakej: <b>{plan_code}</b>\n"
            f"Quota: <b>{quota} ID/bulan</b>\n"
            f"Tempoh: <b>{start_at}</b> → <b>{end_at}</b>\n\n"
            "Anda boleh terus claim ID dari <b>Dashboard Reseller</b> dalam bot.",
        )
        return


# -------------------------
# FastAPI endpoints
# -------------------------
@app.get("/healthz")
async def healthz():
    return {"ok": True, "ts": datetime.utcnow().isoformat()}


@app.get("/thank-you")
async def thank_you():
    # simple return page after payment
    return HTMLResponse(
        """<!doctype html>
<html lang='ms'>
<head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>
<title>Payment Received</title></head>
<body style='font-family:system-ui;margin:32px;max-width:720px'>
<h2>✅ Pembayaran diterima</h2>
<p>Terima kasih! Sistem sedang proses dan akan aktifkan akaun anda secara automatik.</p>
<p>Jika anda belum terima mesej dalam Telegram dalam 1–2 minit, tekan butang <b>Semak Status</b> dalam bot.</p>
</body></html>"""
    )


@app.api_route("/toyyibpay/callback", methods=["GET", "POST"])
async def toyyibpay_callback(req: Request):
    # simple rate limit by client ip (best-effort; behind CF may show CF IP)
    client_ip = req.headers.get("cf-connecting-ip") or (req.client.host if req.client else "unknown")
    if not limiter.allow(f"cb:{client_ip}"):
        return PlainTextResponse("ok", status_code=200)

    token = req.query_params.get("token") or ""
    if token != settings.CALLBACK_TOKEN:
        raise HTTPException(status_code=401, detail="bad token")

    # ToyyibPay commonly sends application/x-www-form-urlencoded
    form = {}
    try:
        form = dict(await req.form())
    except Exception:
        form = {}

    # Common fields seen across implementations
    billcode = (form.get("billcode") or form.get("BillCode") or form.get("billCode") or "").strip()
    refno = (form.get("refno") or form.get("RefNo") or form.get("referenceNo") or "").strip()
    ext = (
        form.get("billExternalReferenceNo")
        or form.get("BillExternalReferenceNo")
        or form.get("externalReferenceNo")
        or ""
    )
    ext = str(ext).strip()

    # Determine order
    order: Optional[dict] = None
    if ext.isdigit():
        order = db.get_order_by_id(int(ext))
    if not order and billcode:
        order = _get_order_by_billcode(billcode)

    # Always return 200 to prevent repeated retries if data incomplete
    if not order:
        db.audit("callback_no_order", f"ip={client_ip} bill={billcode} ext={ext}")
        return PlainTextResponse("ok", status_code=200)

    # Ensure billcode stored (if missing)
    try:
        if billcode and not order.get("billcode"):
            db.set_order_bill(int(order["id"]), billcode)
    except Exception:
        pass

    # Double-check with API (most reliable)
    try:
        tx = await _tp().get_transactions(str(order.get("billcode") or billcode))
        paid = any(str(t.get("billpaymentStatus")) == "1" for t in (tx or []))
    except Exception as e:
        db.audit("callback_tx_err", f"oid={order.get('id')} err={e}")
        paid = False

    if not paid:
        db.audit("callback_not_paid", f"oid={order.get('id')} bill={billcode} ref={refno}")
        return PlainTextResponse("ok", status_code=200)

    # Mark paid & fulfill once
    try:
        db.mark_order_by_bill(str(order.get("billcode") or billcode), refno or None, float(order.get("amount_rm") or 0.0))
    except Exception:
        pass

    if db.fulfill_order_once(int(order["id"])):
        # Fetch latest order row after paid mark
        order2 = db.get_order_by_id(int(order["id"])) or order
        try:
            await fulfill_paid_order(bot, order2)
        except Exception as e:
            db.audit("fulfill_err", f"oid={order.get('id')} err={e}")

    return PlainTextResponse("ok", status_code=200)


@app.on_event("startup")
async def startup():
    asyncio.create_task(dp.start_polling(bot))
    asyncio.create_task(scheduler_loop(bot))
    db.audit("startup", "bot_started")


# ==========================
# XRAY BACKUP / ROLLBACK
# ==========================
def backup_xray_config(xray_config_path: str) -> str | None:
    try:
        if not os.path.exists(xray_config_path):
            return None
        ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        bdir = os.path.join(os.path.dirname(xray_config_path), "backups")
        os.makedirs(bdir, exist_ok=True)
        dst = os.path.join(bdir, f"config.json.{ts}.bak")
        with open(xray_config_path, "rb") as fsrc, open(dst, "wb") as fdst:
            fdst.write(fsrc.read())
        return dst
    except Exception:
        return None


def restore_latest_backup(xray_config_path: str) -> bool:
    try:
        bdir = os.path.join(os.path.dirname(xray_config_path), "backups")
        if not os.path.isdir(bdir):
            return False
        files = [f for f in os.listdir(bdir) if f.startswith("config.json.") and f.endswith(".bak")]
        if not files:
            return False
        files.sort(reverse=True)
        latest = os.path.join(bdir, files[0])
        with open(latest, "rb") as fsrc, open(xray_config_path, "wb") as fdst:
            fdst.write(fsrc.read())
        return True
    except Exception:
        return False


def run_cmd(cmd: str) -> Tuple[int, str]:
    try:
        p = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=8)
        out = (p.stdout or b"").decode("utf-8", "ignore").strip()
        return int(p.returncode), out[:1200]
    except Exception as e:
        return 1, str(e)[:1200]


def probe_http(host: str, port: int, path: str, timeout: float = 2.5) -> Tuple[bool, int, float, str]:
    """Best-effort HTTP probe. Returns (ok, status, ms, err)."""
    import http.client, time

    t0 = time.time()
    try:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conn.request("GET", path, headers={"User-Agent": "health-check", "Connection": "close"})
        resp = conn.getresponse()
        status = int(resp.status)
        resp.read(32)
        conn.close()
        ms = (time.time() - t0) * 1000.0
        return True, status, ms, ""
    except Exception as e:
        ms = (time.time() - t0) * 1000.0
        return False, 0, ms, str(e)[:120]


def self_check_report() -> str:
    lines = []
    cfg = settings.XRAY_CONFIG_PATH
    needle = str(getattr(settings, "VLESS_PATH", "/vlessws") or "/vlessws")
    lines.append(f"• XRAY_CONFIG_PATH: <code>{cfg}</code>")
    if not os.path.exists(cfg):
        lines.append("• Config file: ❌ NOT FOUND")
        return "<b>🩺 Self-Check Report</b>\n\n" + "\n".join(lines)

    lines.append("• Config file: ✅ OK")
    try:
        txt = open(cfg, "r", encoding="utf-8", errors="ignore").read()
        markers = ["#vlessWS", "#vlessWSTLS", "#vless"]
        found = [m for m in markers if m in txt]
        lines.append(
            "• Marker VLESS: "
            + ("✅ " + ", ".join(found) if found else "❌ (tiada marker)")
        )
        lines.append(f'• Path "{needle}": {"✅" if needle in txt else "❓"}')
    except Exception:
        lines.append("• Read config: ❌ FAIL")

    # Probe local endpoints (latency)
    ok80, st80, ms80, err80 = probe_http("127.0.0.1", 80, needle)
    lines.append(f"• Probe {needle} @127.0.0.1:80: {'✅' if ok80 else '❌'} {st80 if ok80 else err80} ({ms80:.0f}ms)")
    ok1010, st1010, ms1010, err1010 = probe_http("127.0.0.1", 1010, needle)
    lines.append(f"• Probe {needle} @127.0.0.1:1010: {'✅' if ok1010 else '⚠️'} {st1010 if ok1010 else err1010} ({ms1010:.0f}ms)")

    for svc in ["xray", "nginx", "haproxy"]:
        rc, out = run_cmd(f"systemctl is-active {svc}")
        if rc == 0 and "active" in out:
            lines.append(f"• {svc}: ✅ active")
        else:
            lines.append(f"• {svc}: ⚠️ {out or 'unknown'}")
    return "<b>🩺 Self-Check Report</b>\n\n" + "\n".join(lines)


if __name__ == "__main__":
    uvicorn.run(app, host=settings.WEB_HOST, port=settings.WEB_PORT)

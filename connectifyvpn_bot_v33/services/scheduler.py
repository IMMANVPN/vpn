from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import sqlite3

from aiogram import Bot
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.settings import settings
from core import db
from services.vpn_vless_ntls import (
    add_vless_user_to_xray_config,
    remove_vless_user_from_xray_config,
    VlessLinkConfig,
    build_vless_ws_ntls_link,
    parse_recent_ips_from_access_log,
)

# -------- Helpers --------
def _vless_cfg() -> VlessLinkConfig:
    return VlessLinkConfig(settings.VLESS_ADDRESS, settings.VLESS_PORT, settings.VLESS_HOST, settings.VLESS_PATH)

def _my_today() -> datetime:
    # Malaysia time approx: UTC+8 (tanpa pytz dependency)
    return datetime.utcnow() + timedelta(hours=8)

def _kb_upgrade() -> object:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔥 Upgrade ke Pro (RM49/Year)", callback_data="plan:PRO")
    kb.button(text="🧑‍💻 Live Agent", callback_data="agent")
    kb.adjust(1)
    return kb.as_markup()

# -------- Reseller auto-release --------
async def reseller_auto_release(bot: Bot):
    if int(settings.AUTO_RELEASE_RESELLER) != 1:
        return

    today = _my_today()
    if today.day != int(settings.RESELLER_RELEASE_DAY):
        return

    ym = today.strftime("%Y-%m")
    for r in db.list_resellers():
        tg_id = int(r["tg_id"])
        quota = int(r["monthly_quota"])
        credit = db.ensure_monthly_credit(tg_id, ym, quota)
        if int(credit.get("released", 0)) == 1:
            continue

        links = []
        for idx in range(1, quota + 1):
            username = f"r{tg_id}_{ym.replace('-','')}_{idx}"
            try:
                expires_at = (datetime.utcnow() + timedelta(days=30)).isoformat()
                uuid = add_vless_user_to_xray_config(
                    xray_config_path=settings.XRAY_CONFIG_PATH,
                    restart_cmd=settings.XRAY_RESTART_CMD,
                    username=username,
                    expire_date=expires_at[:10],
                )
                link = build_vless_ws_ntls_link(uuid, username, _vless_cfg())
                db.insert_vpn_account(tg_id, "PRO", uuid, username, link, expires_at)
                links.append(link)
            except Exception as e:
                db.audit("release_err", f"tg={tg_id} u={username} err={e}")

        db.set_credit_released(tg_id, ym)
        db.audit("reseller_release", f"tg={tg_id} ym={ym} quota={quota} delivered={len(links)}")

        if links:
            header = f"<b>📦 Auto Release Reseller ({ym})</b>\nQuota: <b>{quota}</b>\n\nLink (30 hari):\n\n"
            chunk = ""
            for link in links:
                line = f"<code>{link}</code>\n\n"
                if len(header) + len(chunk) + len(line) > 3500:
                    await bot.send_message(tg_id, header + chunk, parse_mode="HTML")
                    chunk = ""
                chunk += line
            if chunk:
                await bot.send_message(tg_id, header + chunk, parse_mode="HTML")

# -------- Device limit (3-scan rule + warning) --------
async def device_limit_scan(bot: Bot):
    window = int(db.get_setting('DEVICE_WINDOW_MINUTES', str(settings.DEVICE_WINDOW_MINUTES)))

    conn = sqlite3.connect(db.DB_PATH); conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT vless_username, plan_code, tg_id, status FROM vpn_accounts ORDER BY id DESC LIMIT 1200"
    ).fetchall()
    conn.close()

    seen = set()
    accounts = []
    for r in rows:
        u = r["vless_username"]
        if u in seen:
            continue
        seen.add(u)
        if str(r["status"]) != "ACTIVE":
            continue
        accounts.append((u, str(r["plan_code"]), int(r["tg_id"])))

    for username, plan, tg_id in accounts:
        limit = 1 if plan == "LITE" else 2
        ips = parse_recent_ips_from_access_log(settings.XRAY_ACCESS_LOG, username, window)

        if len(ips) <= limit:
            try:
                db.reset_device_state(username)
            except Exception:
                pass
            continue

        st = db.get_device_state(username)
        count = int(st.get("violation_count", 0)) + 1
        warned = int(st.get("warned", 0))

        db.set_device_state(
            username,
            violation_count=count,
            last_violation_ts=datetime.utcnow().isoformat(),
            warned=warned,
        )

        if count == 2 and warned == 0:
            try:
                await bot.send_message(
                    tg_id,
                    f"<b>⚠️ Amaran Device Limit</b>\n\n"
                    f"Akaun: <b>{username}</b>\n"
                    f"Kami kesan lebih daripada <b>{limit}</b> device/IP dalam {window} minit.\n\n"
                    f"Plan anda: <b>{plan}</b>\n"
                    f"• Lite: 1 device sahaja\n"
                    f"• Pro: max 2 device (hotspot)\n\n"
                    f"Jika anda perlukan hotspot / multi-device, upgrade ke <b>Pro</b> untuk elak suspend.",
                    reply_markup=_kb_upgrade(),
                    parse_mode="HTML",
                )
                db.set_device_state(
                    username,
                    violation_count=count,
                    last_violation_ts=datetime.utcnow().isoformat(),
                    warned=1,
                )
                db.audit("warn_limit", f"user={username} plan={plan} ips={sorted(list(ips))}")
            except Exception as e:
                db.audit("warn_err", f"user={username} err={e}")
            continue

        if count >= 3:
            try:
                remove_vless_user_from_xray_config(
                    xray_config_path=settings.XRAY_CONFIG_PATH,
                    restart_cmd=settings.XRAY_RESTART_CMD,
                    username=username
                )
                db.set_vpn_status(username, "SUSPENDED")
                until = (datetime.utcnow() + timedelta(hours=int(db.get_setting('AUTO_UNSUSPEND_HOURS', str(settings.AUTO_UNSUSPEND_HOURS))))).isoformat()
                db.set_suspended_until(username, until)
                db.audit("auto_suspend", f"user={username} plan={plan} ips={sorted(list(ips))} until={until}")

                await bot.send_message(
                    tg_id,
                    f"<b>⛔ Akaun Disuspend (Device Limit)</b>\n\n"
                    f"Akaun: <b>{username}</b>\n"
                    f"Sebab: melebihi had device selama <b>3 scan berturut-turut</b>.\n"
                    f"Plan {plan}: limit <b>{limit}</b> device/IP.\n\n"
                    f"<b>Auto-unsuspend</b> akan cuba aktif semula selepas <b>{db.get_setting('AUTO_UNSUSPEND_HOURS', str(settings.AUTO_UNSUSPEND_HOURS))} jam</b>.\n\n"
                    f"Untuk penggunaan hotspot/multi-device yang lebih stabil, upgrade ke <b>Pro</b>.",
                    reply_markup=_kb_upgrade(),
                    parse_mode="HTML",
                )
            except Exception as e:
                db.audit("auto_suspend_err", f"user={username} err={e}")

# -------- Auto-unsuspend --------
async def auto_unsuspend_scan(bot: Bot):
    now_iso = datetime.utcnow().isoformat()
    due = db.list_suspended_due_for_unsuspend(now_iso)

    seen = set()
    for acc in due:
        username = acc["vless_username"]
        if username in seen:
            continue
        seen.add(username)

        tg_id = int(acc["tg_id"])
        plan = str(acc["plan_code"])
        expires_at = str(acc["expires_at"])

        try:
            uuid = add_vless_user_to_xray_config(
                xray_config_path=settings.XRAY_CONFIG_PATH,
                restart_cmd=settings.XRAY_RESTART_CMD,
                username=username,
                expire_date=str(expires_at)[:10],
            )
            link = build_vless_ws_ntls_link(uuid, username, _vless_cfg())

            db.insert_vpn_account(tg_id, plan, uuid, username, link, expires_at)
            db.set_vpn_status(username, "ACTIVE")
            db.set_suspended_until(username, None)
            db.reset_device_state(username)

            await bot.send_message(
                tg_id,
                f"<b>✅ Akaun Aktif Semula</b>\n\n"
                f"Akaun: <b>{username}</b>\n"
                f"Plan: <b>{plan}</b>\n"
                f"Expiry: <b>{expires_at}</b>\n\n"
                f"<b>Link baru:</b>\n<code>{link}</code>\n\n"
                f"Tip: Jika anda kerap guna hotspot/multi-device, upgrade ke <b>Pro</b> untuk elak suspend berulang.",
                reply_markup=_kb_upgrade(),
                parse_mode="HTML",
            )
            db.audit("auto_unsuspend", f"user={username} tg={tg_id}")
        except Exception as e:
            db.audit("auto_unsuspend_err", f"user={username} err={e}")

# -------- Main loop --------
async def loop(bot: Bot):
    while True:
        try:
            await reseller_auto_release(bot)
        except Exception as e:
            db.audit("sched_err", f"release err={e}")
        try:
            await device_limit_scan(bot)
        except Exception as e:
            db.audit("sched_err", f"scan err={e}")
        try:
            await auto_unsuspend_scan(bot)
        except Exception as e:
            db.audit("sched_err", f"unsuspend err={e}")

        await asyncio.sleep(600)  # 10 min


async def run_scheduled_broadcasts(bot):
    now_iso=datetime.utcnow().isoformat()
    due=db.fetch_due_broadcasts(now_iso, limit=5)
    for b in due:
        target=b["target"]
        text=b["text_html"]
        sent=0
        # reuse broadcast targets
        users=db.list_users_for_broadcast(target)
        for u in users:
            try:
                await bot.send_message(int(u["tg_id"]), text, parse_mode="HTML")
                sent += 1
            except Exception:
                pass
            await asyncio.sleep(0.05)
        db.mark_broadcast_done(int(b["id"]), sent)
        db.audit("sched_bcast", f"id={b['id']} target={target} sent={sent}")

async def run_expiry_reminders(bot, within_days:int=7):
    # send once per account
    rows=db.expiring_accounts(within_days=within_days, limit=500)
    for a in rows:
        key=f"expiry7:{a['vless_username']}:{a['expires_at']}"
        if not db.notice_once(key):
            continue
        tg_id=int(a["tg_id"])
        try:
            # days left
            try:
                exp=datetime.fromisoformat(a["expires_at"])
                left=max(0, (exp - datetime.utcnow()).days)
            except Exception:
                left=7
            msg=(
                "<b>⏰ Reminder: Akaun akan tamat</b>\n\n"
                f"ID: <b>{a['vless_username']}</b>\n"
                f"Baki: <b>{left} hari</b>\n\n"
                "Nak sambung validity? Buka menu & renew sebelum tamat ya ✅"
            )
            await bot.send_message(tg_id, msg, parse_mode="HTML")
        except Exception:
            pass
        await asyncio.sleep(0.05)


async def run_reseller_auto_release(bot):
    """Auto-release reseller quota monthly (once per month)."""
    now_local=datetime.utcnow()+timedelta(hours=8)
    ym=now_local.strftime("%Y-%m")
    # run only day 1 around 00:05-00:20 MY
    if not (now_local.day==1 and now_local.hour==0 and now_local.minute<20):
        return
    # idempotent key per month
    if not db.notice_once(f"auto_release:{ym}"):
        return
    resellers=db.list_active_resellers(now_local.date().isoformat(), limit=2000)
    for r in resellers:
        tg_id=int(r["tg_id"])
        quota=int(r["monthly_quota"])
        credit=db.ensure_monthly_credit(tg_id, ym, quota)
        if int(credit.get("released",0))==1:
            continue
        links=[]
        for idx in range(1, quota+1):
            username=f"r{tg_id}_{ym.replace('-','')}_{idx}"
            try:
                expires_at = (datetime.utcnow() + timedelta(days=30)).isoformat()
                uuid = add_vless_user_to_xray_config(
                    xray_config_path=settings.XRAY_CONFIG_PATH,
                    restart_cmd=settings.XRAY_RESTART_CMD,
                    username=username,
                    expire_date=expires_at[:10],
                )
                link = build_vless_ws_ntls_link(uuid, username, _vless_cfg())
                db.insert_vpn_account(tg_id, "PRO", uuid, username, link, expires_at)
                links.append(link)
            except Exception as e:
                db.audit("auto_release_err", f"tg={tg_id} ym={ym} u={username} err={e}")
        db.set_credit_released(tg_id, ym)
        if links:
            header=f"<b>📦 Auto Release ({ym})</b>\nQuota: <b>{quota}</b>\n\n"
            chunk=""
            for link in links:
                line=f"<code>{link}</code>\n\n"
                if len(header)+len(chunk)+len(line)>3500:
                    await bot.send_message(tg_id, header+chunk, parse_mode="HTML")
                    chunk=""
                chunk+=line
            if chunk:
                await bot.send_message(tg_id, header+chunk, parse_mode="HTML")
        await asyncio.sleep(0.05)
    db.audit("auto_release_done", f"ym={ym} resellers={len(resellers)}")


async def run_unpaid_followups(bot):
    checkpoints=[("30m",30),("2h",120),("24h",1440)]
    for tag, mins in checkpoints:
        rows=db.pending_orders_older_than(mins, limit=200)
        for o in rows:
            oid=int(o["id"])
            key=f"unpaid:{oid}:{tag}"
            if not db.notice_once(key):
                continue
            tg=int(o["tg_id"])
            bill=o.get("billcode")
            if not bill:
                continue
            link=f"https://toyyibpay.com/{bill}"
            tpl_key={"30m":"unpaid30m","2h":"unpaid2h","24h":"unpaid24h"}.get(tag, "unpaid30m")
            base=db.get_template(tpl_key)
            if not base:
                base="<b>⏳ Reminder Pembayaran</b>\n\nOrder anda masih pending. Klik link pembayaran untuk teruskan ✅"
            msg=(
                base+"\n\n"
                f"Order: <b>#{oid}</b> (Plan <b>{o.get('plan_code')}</b>)\n"
                f"Jumlah: <b>RM{float(o.get('amount_rm') or 0):.2f}</b>\n\n"
                "Klik untuk teruskan pembayaran:\n"
                f"{link}\n\n"
                "Kalau dah bayar tapi belum auto-update, tekan Live Agent ya ✅"
            )
            try:
                await bot.send_message(tg, msg, parse_mode="HTML")
            except Exception:
                pass
            await asyncio.sleep(0.05)

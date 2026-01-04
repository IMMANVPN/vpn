from __future__ import annotations
import json
from datetime import datetime, timedelta

from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery

from core.settings import settings
from core import db
from ui.texts import WELCOME_TEXT, MENU_TEXT, PLANS_TEXT, RESELLER_TEXT, RULES_TEXT, UPGRADE_NOTE
from ui.keyboards import kb_start, kb_menu, kb_plans, kb_reseller_packages, kb_confirm_pay, kb_payment_link, kb_reseller_dashboard, kb_admin_main, kb_admin_orders, kb_admin_order_detail, kb_admin_users, kb_admin_account_actions, kb_admin_settings, kb_admin_bcast, kb_admin_sales, kb_admin_export_menu, kb_admin_export_plan, kb_admin_export_months, kb_admin_resellers, kb_admin_reseller_detail, kb_admin_reseller_credits, kb_admin_reseller_release_months
from bot.logic import plan_amount, reseller_amount, reseller_quota, make_vless_username, ym_now, reseller_period, lite_to_pro_bonus_days
from services.toyyibpay import ToyyibPayClient, ToyyibPayConfig
from services.vpn_vless_ntls import add_vless_user_to_xray_config, remove_vless_user_from_xray_config, VlessLinkConfig, build_vless_ws_ntls_link

from bot.admin_fsm import set_state, get_state, clear_state

router=Router()

def is_admin(tg_id:int)->bool:
    return tg_id in settings.admin_id_set

def _tp():
    cb=f"{settings.PUBLIC_BASE_URL.rstrip('/')}/toyyibpay/callback?token={settings.CALLBACK_TOKEN}"
    ret=f"{settings.PUBLIC_BASE_URL.rstrip('/')}/thank-you"
    return ToyyibPayClient(ToyyibPayConfig(settings.TOYYIBPAY_SECRET_KEY, settings.TOYYIBPAY_CATEGORY_CODE, cb, ret))

def _vless_cfg():
    return VlessLinkConfig(settings.VLESS_ADDRESS, settings.VLESS_PORT, settings.VLESS_HOST, settings.VLESS_PATH)

@router.message(CommandStart())
async def start(m:Message):
    db.upsert_user(m.from_user.id, m.from_user.username, m.from_user.first_name)
    await m.answer(WELCOME_TEXT, reply_markup=kb_start(settings.OWNER_TELEGRAM), parse_mode="HTML")

@router.callback_query(F.data=="menu")
async def menu(c:CallbackQuery):
    await c.message.edit_text(MENU_TEXT, reply_markup=kb_menu(is_admin=is_admin(c.from_user.id)), parse_mode="HTML")
    await c.answer()

@router.callback_query(F.data=="buy")
async def buy(c:CallbackQuery):
    await c.message.edit_text(PLANS_TEXT, reply_markup=kb_plans(), parse_mode="HTML")
    await c.answer()

@router.callback_query(F.data.startswith("plan:"))
async def plan_pick(c:CallbackQuery):
    plan=c.data.split(":",1)[1]
    amt=plan_amount(plan)

    # --- Upgrade preview (Lite -> Pro) ---
    if plan == "PRO":
        now_iso = datetime.utcnow().isoformat()
        lite_acc = db.get_latest_active_account(c.from_user.id, "LITE", now_iso)
        if lite_acc:
            try:
                lite_exp = datetime.fromisoformat(str(lite_acc["expires_at"]))
            except Exception:
                lite_exp = datetime.utcnow()
            remaining_days = max(0, (lite_exp - datetime.utcnow()).days)
            bonus_days = lite_to_pro_bonus_days(remaining_days)
            pro_exp = (datetime.utcnow() + timedelta(days=365 + bonus_days))
            meta = {
                "tg_username": c.from_user.username,
                "upgrade_from": "LITE",
                "remaining_lite_days": remaining_days,
                "bonus_pro_days": bonus_days,
                "note": "Pro starts now; bonus days added"
            }
            oid=db.create_order(c.from_user.id,"PLAN","PRO",amt,meta_json=json.dumps(meta))
            await c.message.edit_text(
                f"{UPGRADE_NOTE}\n"
                f"<b>📌 Status akaun anda</b>\n"
                f"• Lite aktif sampai: <b>{lite_exp.date().isoformat()}</b>\n"
                f"• Baki: <b>{remaining_days}</b> hari\n"
                f"• Bonus Pro: <b>+{bonus_days}</b> hari\n\n"
                f"<b>✅ Pro validity (anggaran)</b>: sampai <b>{pro_exp.date().isoformat()}</b>\n\n"
                f"<b>Harga Upgrade:</b> RM{amt:.0f}/setahun\n\nTekan Bayar untuk proceed.",
                reply_markup=kb_confirm_pay(oid, amt), parse_mode="HTML"
            )
            await c.answer()
            return

    # normal purchase
    oid=db.create_order(c.from_user.id,"PLAN",plan,amt,meta_json=json.dumps({"tg_username":c.from_user.username}))
    await c.message.edit_text(
        f"<b>Anda pilih:</b> {plan}\n<b>Harga:</b> RM{amt:.0f}/setahun\n\nTekan Bayar untuk proceed.",
        reply_markup=kb_confirm_pay(oid, amt), parse_mode="HTML"
    )
    await c.answer()

@router.callback_query(F.data=="reseller")
async def reseller(c:CallbackQuery):
    r=db.get_reseller(c.from_user.id)
    if r:
        await c.message.edit_text("<b>🤝 Dashboard Reseller</b>", reply_markup=kb_reseller_dashboard(), parse_mode="HTML")
    else:
        await c.message.edit_text(RESELLER_TEXT, reply_markup=kb_reseller_packages(), parse_mode="HTML")
    await c.answer()

@router.callback_query(F.data.startswith("rpack:"))
async def rpack_pick(c:CallbackQuery):
    code=c.data.split(":",1)[1]
    amt=reseller_amount(code)
    q=reseller_quota(code)
    oid=db.create_order(c.from_user.id,"RESELLER",code,amt,meta_json=json.dumps({"tg_username":c.from_user.username}))
    await c.message.edit_text(
        f"<b>Anda pilih:</b> {code}\n<b>Harga:</b> RM{amt:.0f} (sekali)\n<b>Quota:</b> {q} ID/bulan\n\nTekan Bayar untuk proceed.",
        reply_markup=kb_confirm_pay(oid, amt), parse_mode="HTML"
    )
    await c.answer()

@router.callback_query(F.data.startswith("pay:"))
async def pay(c:CallbackQuery):
    oid=int(c.data.split(":",1)[1])
    order=db.get_order(oid)
    if not order or int(order["tg_id"])!=c.from_user.id:
        await c.answer("Order tak jumpa", alert=True); return
    billcode=await _tp().create_bill(bill_name=f"Order_{oid}", bill_desc=f"{order['order_type']} {order['plan_code']}", amount_rm=float(order["amount_rm"]), external_ref=str(oid))
    db.set_order_bill(oid, billcode)
    db.audit("create_bill", f"oid={oid} bill={billcode} tg={c.from_user.id}")
    await c.message.edit_text(
        f"<b>💳 Payment</b>\n\nLink: https://toyyibpay.com/{billcode}\n\nLepas bayar, sistem auto-aktif (callback).",
        reply_markup=kb_payment_link(billcode, oid), parse_mode="HTML"
    )
    await c.answer()

@router.callback_query(F.data.startswith("check:"))
async def check(c:CallbackQuery):
    oid=int(c.data.split(":",1)[1])
    order=db.get_order(oid)
    if not order or int(order["tg_id"])!=c.from_user.id:
        await c.answer("Order tak jumpa", alert=True); return
    tx=await _tp().get_transactions(order["billcode"])
    paid=any(str(t.get("billpaymentStatus"))=="1" for t in tx)
    await c.answer("✅ Paid" if paid else "⏳ Pending", alert=True)

@router.callback_query(F.data.startswith("cancel:"))
async def cancel(c:CallbackQuery):
    oid=int(c.data.split(":",1)[1])
    order=db.get_order(oid)
    if order and int(order["tg_id"])==c.from_user.id:
        import sqlite3
        conn=sqlite3.connect(db.DB_PATH)
        conn.execute("UPDATE orders SET status=3 WHERE id=?", (oid,))
        conn.commit(); conn.close()
        db.audit("cancel", f"oid={oid} tg={c.from_user.id}")
    await c.message.edit_text("Order dibatalkan.", reply_markup=kb_menu(is_admin=is_admin(c.from_user.id)), parse_mode="HTML")
    await c.answer()

@router.callback_query(F.data=="tutorial")
async def tutorial(c:CallbackQuery):
    await c.message.edit_text(
        "<b>📘 Tutorial</b>\n1) Copy link VLESS\n2) Paste dalam apps client\n3) Connect\n\nLite: 1 device\nPro: max 2 device",
        reply_markup=kb_menu(is_admin=is_admin(c.from_user.id)), parse_mode="HTML"
    ); await c.answer()

@router.callback_query(F.data=="faq")
async def faq(c:CallbackQuery):
    await c.message.edit_text(
        "<b>❓ FAQ</b>\n• Validity 1 tahun\n• Lite 1 device\n• Pro hotspot 2 device\n• Payment ToyyibPay auto",
        reply_markup=kb_menu(is_admin=is_admin(c.from_user.id)), parse_mode="HTML"
    ); await c.answer()

@router.callback_query(F.data=="agent")
async def agent(c:CallbackQuery):
    await c.message.edit_text(
        f"<b>🧑‍💻 Live Agent</b>\nDM: {settings.OWNER_TELEGRAM}",
        reply_markup=kb_menu(is_admin=is_admin(c.from_user.id)), parse_mode="HTML"
    ); await c.answer()

# reseller actions (manual claim still available)
@router.callback_query(F.data.startswith("r:"))
async def r_actions(c:CallbackQuery):
    r=db.get_reseller(c.from_user.id)
    if not r:
        await c.answer("Belum reseller", alert=True); return
    act=c.data.split(":",1)[1]
    ym=ym_now()
    credit=db.ensure_monthly_credit(c.from_user.id, ym, int(r["monthly_quota"]))
    if act=="dash":
        baki=int(credit["quota"])-int(credit["claimed"])
        await c.message.edit_text(f"<b>📊 Reseller</b>\nYM: {ym}\nQuota: {credit['quota']}\nClaimed: {credit['claimed']}\nBaki: {baki}",
                                  reply_markup=kb_reseller_dashboard(), parse_mode="HTML"); await c.answer(); return
    if act=="claim":
        baki=int(credit["quota"])-int(credit["claimed"])
        if baki<=0:
            await c.answer("Quota habis", alert=True); return
        idx=int(credit["claimed"])+1
        username=f"r{c.from_user.id}_{ym.replace('-','')}_{idx}"
        expires_at=(datetime.utcnow()+timedelta(days=30)).isoformat()
        uuid=add_vless_user_to_xray_config(
            xray_config_path=settings.XRAY_CONFIG_PATH,
            restart_cmd=settings.XRAY_RESTART_CMD,
            username=username,
            expire_date=expires_at[:10],
        )
        link=build_vless_ws_ntls_link(uuid, username, _vless_cfg())
        db.insert_vpn_account(c.from_user.id,"PRO",uuid,username,link,expires_at)
        db.add_claimed(c.from_user.id, ym, 1)
        db.audit("reseller_claim", f"tg={c.from_user.id} ym={ym} u={username}")
        await c.message.answer(f"<b>✅ ID Reseller (30 hari)</b>\n<code>{link}</code>\n\n{RULES_TEXT}", parse_mode="HTML")
        await c.answer("Done"); return
    await c.answer("OK")



# --------------------------
# Admin Panel (Inline Premium)
# --------------------------
def _fmt_ts(x):
    try:
        return datetime.fromisoformat(str(x)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(x)

@router.callback_query(F.data=="admin")
async def admin_open(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    # init defaults in DB if missing
    from core import db as _db
    _db.set_setting("DEVICE_WINDOW_MINUTES", _db.get_setting("DEVICE_WINDOW_MINUTES", str(settings.DEVICE_WINDOW_MINUTES)))
    _db.set_setting("AUTO_UNSUSPEND_HOURS", _db.get_setting("AUTO_UNSUSPEND_HOURS", str(getattr(settings,'AUTO_UNSUSPEND_HOURS',6))))
    await c.message.edit_text("<b>🛡️ Admin Panel</b>\nPilih menu:", reply_markup=kb_admin_main(), parse_mode="HTML")
    await c.answer()

@router.callback_query(F.data=="a:home")
async def admin_home(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    await c.message.edit_text("<b>🛡️ Admin Panel</b>\nPilih menu:", reply_markup=kb_admin_main(), parse_mode="HTML")
    await c.answer()

@router.callback_query(F.data=="a:dash")
async def admin_dash(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    from core import db as _db
    users=_db.count_users()
    active_lite=_db.count_accounts(status="ACTIVE", plan="LITE")
    active_pro=_db.count_accounts(status="ACTIVE", plan="PRO")
    suspended=_db.count_accounts(status="SUSPENDED", plan=None)
    paid20=sum(1 for o in _db.list_orders(20) if int(o["status"])==1)

    window=int(_db.get_setting("DEVICE_WINDOW_MINUTES", str(settings.DEVICE_WINDOW_MINUTES)))
    uns_h=int(_db.get_setting("AUTO_UNSUSPEND_HOURS", str(getattr(settings,'AUTO_UNSUSPEND_HOURS',6))))

    txt=(
        "<b>📊 Dashboard</b>\n\n"
        f"👤 Users: <b>{users}</b>\n"
        f"🟢 Active Lite: <b>{active_lite}</b>\n"
        f"🔵 Active Pro: <b>{active_pro}</b>\n"
        f"⛔ Suspended: <b>{suspended}</b>\n"
        f"✅ Paid (last 20 orders): <b>{paid20}</b>\n\n"
        f"⚙️ Window: <b>{window} min</b> | Auto-unsuspend: <b>{uns_h} jam</b>"
    )
    await c.message.edit_text(txt, reply_markup=kb_admin_main(), parse_mode="HTML")
    await c.answer()

@router.callback_query(F.data.startswith("a:orders:"))
async def admin_orders(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    from core import db as _db
    page=int(c.data.split(":")[2])
    page=max(0,page)
    limit=10
    offset=page*limit
    orders=_db.list_recent_orders(limit=limit, offset=offset)
    lines=[]
    for o in orders:
        st=int(o["status"])
        icon="✅" if st==1 else ("⏳" if st==0 else "❌")
        lines.append(f"{icon} <b>#{o['id']}</b> {o['order_type']}/{o['plan_code']} RM{o['amount_rm']:.0f} • {_fmt_ts(o['created_at'])}")
    body="\n".join(lines) if lines else "Tiada orders."
    has_prev=page>0
    has_next=len(orders)==limit
    await c.message.edit_text("<b>🧾 Orders</b>\n\n"+body+"\n\nKlik order ID untuk detail (reply dengan ID).",
                              reply_markup=kb_admin_orders(page,has_prev,has_next), parse_mode="HTML")
    # set state to wait order id input if admin wants
    set_state(c.from_user.id, "ADMIN_WAIT_ORDER_ID", {"page":page})
    await c.answer()

@router.callback_query(F.data=="a:find_order")
async def admin_find_order(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    set_state(c.from_user.id, "ADMIN_WAIT_ORDER_ID", {})
    await c.message.edit_text("<b>🔎 Find Order</b>\nHantar nombor Order ID (contoh: <code>12</code>)",
                              reply_markup=kb_admin_main(), parse_mode="HTML")
    await c.answer()

@router.callback_query(F.data=="a:users")
async def admin_users(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    await c.message.edit_text("<b>👥 Users / Accounts</b>", reply_markup=kb_admin_users(), parse_mode="HTML")
    await c.answer()

@router.callback_query(F.data=="a:find_user")
async def admin_find_user(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    set_state(c.from_user.id, "ADMIN_WAIT_USER_QUERY", {})
    await c.message.edit_text("<b>🔎 Find User</b>\nHantar <b>Telegram ID</b> atau <b>@username</b>.",
                              reply_markup=kb_admin_users(), parse_mode="HTML")
    await c.answer()

@router.callback_query(F.data=="a:find_account")
async def admin_find_account(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    set_state(c.from_user.id, "ADMIN_WAIT_ACCOUNT_USERNAME", {})
    await c.message.edit_text("<b>📌 Find Account</b>\nHantar <b>vless username</b> (email dalam xray) contoh: <code>cfy123_lite</code>",
                              reply_markup=kb_admin_users(), parse_mode="HTML")
    await c.answer()

@router.callback_query(F.data.startswith("a:acc_suspend:"))
async def admin_acc_suspend(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    username=c.data.split(":",2)[2]
    try:
        remove_vless_user_from_xray_config(xray_config_path=settings.XRAY_CONFIG_PATH, restart_cmd=settings.XRAY_RESTART_CMD, username=username)
        db.set_vpn_status(username,"SUSPENDED")
        db.set_suspended_until(username, (datetime.utcnow()+timedelta(hours=24)).isoformat())
        await c.answer("Suspended", alert=True)
    except Exception as e:
        await c.answer(f"Fail: {e}", alert=True)

@router.callback_query(F.data.startswith("a:acc_unsuspend:"))
async def admin_acc_unsuspend(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    username=c.data.split(":",2)[2]
    acc=db.find_account_by_username(username)
    if not acc:
        await c.answer("Tak jumpa db", alert=True); return
    try:
        uuid=add_vless_user_to_xray_config(
            xray_config_path=settings.XRAY_CONFIG_PATH,
            restart_cmd=settings.XRAY_RESTART_CMD,
            username=username,
            expire_date=str(acc.get("expires_at") or "")[:10] or None,
        )
        link=build_vless_ws_ntls_link(uuid, username, _vless_cfg())
        db.insert_vpn_account(int(acc["tg_id"]), acc["plan_code"], uuid, username, link, acc["expires_at"])
        db.set_vpn_status(username,"ACTIVE")
        db.set_suspended_until(username, None)
        db.reset_device_state(username)
        await c.message.edit_text(f"<b>✅ Unsuspended</b>\n<code>{link}</code>", reply_markup=kb_admin_account_actions(username), parse_mode="HTML")
        await c.answer()
    except Exception as e:
        await c.answer(f"Fail: {e}", alert=True)

@router.callback_query(F.data.startswith("a:acc_reset:"))
async def admin_acc_reset(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    username=c.data.split(":",2)[2]
    db.reset_device_state(username)
    await c.answer("Reset OK", alert=True)

@router.callback_query(F.data.startswith("a:acc_renew:"))
async def admin_acc_renew(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    username=c.data.split(":",2)[2]
    set_state(c.from_user.id, "ADMIN_WAIT_RENEW_DAYS", {"username":username})
    await c.message.edit_text(f"<b>♻️ Renew</b>\nAkaun: <b>{username}</b>\nHantar nombor hari untuk tambah (contoh <code>30</code>).",
                              reply_markup=kb_admin_account_actions(username), parse_mode="HTML")
    await c.answer()

@router.callback_query(F.data.startswith("a:acc_regen:"))
async def admin_acc_regen(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    username=c.data.split(":",2)[2]
    acc=db.find_account_by_username(username)
    if not acc:
        await c.answer("Tak jumpa db", alert=True); return
    try:
        # remove then add to force new uuid/link
        try:
            remove_vless_user_from_xray_config(xray_config_path=settings.XRAY_CONFIG_PATH, restart_cmd=settings.XRAY_RESTART_CMD, username=username)
        except Exception:
            pass
        uuid=add_vless_user_to_xray_config(
            xray_config_path=settings.XRAY_CONFIG_PATH,
            restart_cmd=settings.XRAY_RESTART_CMD,
            username=username,
            expire_date=str(acc.get("expires_at") or "")[:10] or None,
        )
        link=build_vless_ws_ntls_link(uuid, username, _vless_cfg())
        db.insert_vpn_account(int(acc["tg_id"]), acc["plan_code"], uuid, username, link, acc["expires_at"])
        db.set_vpn_status(username,"ACTIVE")
        await c.message.edit_text(f"<b>🔁 Link Baru</b>\n<code>{link}</code>", reply_markup=kb_admin_account_actions(username), parse_mode="HTML")
        await c.answer()
    except Exception as e:
        await c.answer(f"Fail: {e}", alert=True)

@router.callback_query(F.data.startswith("a:acc_switch:"))
async def admin_acc_switch(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    username=c.data.split(":",2)[2]
    set_state(c.from_user.id, "ADMIN_WAIT_SWITCH_PLAN", {"username":username})
    await c.message.edit_text(
        f"<b>🔄 Switch Plan</b>\nAkaun: <b>{username}</b>\nHantar plan baru: <code>LITE</code> atau <code>PRO</code>",
        reply_markup=kb_admin_account_actions(username), parse_mode="HTML"
    )
    await c.answer()

@router.callback_query(F.data=="a:settings")
async def admin_settings(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    from core import db as _db
    window=int(_db.get_setting("DEVICE_WINDOW_MINUTES", str(settings.DEVICE_WINDOW_MINUTES)))
    uns=int(_db.get_setting("AUTO_UNSUSPEND_HOURS", str(getattr(settings,'AUTO_UNSUSPEND_HOURS',6))))
    await c.message.edit_text("<b>⚙️ Settings</b>\nAdjust settings live:", reply_markup=kb_admin_settings(window, uns), parse_mode="HTML")
    await c.answer()

@router.callback_query(F.data.startswith("a:set_window:"))
async def admin_set_window(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    from core import db as _db
    delta=c.data.split(":")[2]
    window=int(_db.get_setting("DEVICE_WINDOW_MINUTES", str(settings.DEVICE_WINDOW_MINUTES)))
    if delta.startswith("+"):
        window += int(delta[1:])
    else:
        window += int(delta)
    window=max(5, min(60, window))
    _db.set_setting("DEVICE_WINDOW_MINUTES", str(window))
    uns=int(_db.get_setting("AUTO_UNSUSPEND_HOURS", str(getattr(settings,'AUTO_UNSUSPEND_HOURS',6))))
    await c.message.edit_text("<b>⚙️ Settings</b>\nAdjust settings live:", reply_markup=kb_admin_settings(window, uns), parse_mode="HTML")
    await c.answer("Saved", alert=True)

@router.callback_query(F.data.startswith("a:set_unsuspend:"))
async def admin_set_unsuspend(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    from core import db as _db
    delta=c.data.split(":")[2]
    uns=int(_db.get_setting("AUTO_UNSUSPEND_HOURS", str(getattr(settings,'AUTO_UNSUSPEND_HOURS',6))))
    if delta.startswith("+"):
        uns += int(delta[1:])
    else:
        uns += int(delta)
    uns=max(1, min(72, uns))
    _db.set_setting("AUTO_UNSUSPEND_HOURS", str(uns))
    window=int(_db.get_setting("DEVICE_WINDOW_MINUTES", str(settings.DEVICE_WINDOW_MINUTES)))
    await c.message.edit_text("<b>⚙️ Settings</b>\nAdjust settings live:", reply_markup=kb_admin_settings(window, uns), parse_mode="HTML")
    await c.answer("Saved", alert=True)

@router.callback_query(F.data=="a:bcast")
async def admin_bcast(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    await c.message.edit_text("<b>📣 Broadcast</b>\nPilih target:", reply_markup=kb_admin_bcast(), parse_mode="HTML")
    await c.answer()

@router.callback_query(F.data.startswith("a:bcast_"))
async def admin_bcast_pick(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    target=c.data.split(":",1)[0].split("_",1)[1] if ":" in c.data else c.data.split("_",1)[1]
    # store state
    mapping={"all":"ALL","lite":"LITE","pro":"PRO","reseller":"RESELLER"}
    set_state(c.from_user.id, "ADMIN_WAIT_BCAST_TEXT", {"target":mapping.get(target,target)})
    await c.message.edit_text("<b>📣 Broadcast</b>\nHantar teks broadcast sekarang (1 message).",
                              reply_markup=kb_admin_bcast(), parse_mode="HTML")
    await c.answer()



@router.callback_query(F.data.startswith("a:sales"))
async def admin_sales(c:CallbackQuery, bot:Bot):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    from core import db as _db
    parts=(c.data or '').split(':')
    range_days=14
    if len(parts)==3:
        try:
            range_days=int(parts[2])
        except Exception:
            range_days=14
    # Malaysia time boundaries
    tz=8
    now_utc=datetime.utcnow()
    now_local=now_utc + timedelta(hours=tz)
    # today
    d0_local=now_local.replace(hour=0,minute=0,second=0,microsecond=0)
    d1_local=d0_local + timedelta(days=1)
    d0_utc=d0_local - timedelta(hours=tz)
    d1_utc=d1_local - timedelta(hours=tz)
    today=_db.sales_totals(d0_utc.isoformat(), d1_utc.isoformat())

    # month
    m0_local=now_local.replace(day=1, hour=0,minute=0,second=0,microsecond=0)
    m1_local=(m0_local + timedelta(days=32)).replace(day=1)
    m0_utc=m0_local - timedelta(hours=tz)
    m1_utc=m1_local - timedelta(hours=tz)
    month=_db.sales_totals(m0_utc.isoformat(), m1_utc.isoformat())
    breakdown=_db.sales_breakdown_by_plan(m0_utc.isoformat(), m1_utc.isoformat())

    last14=_db.sales_last_n_days(range_days, tz_offset_hours=tz)
    spark=" ".join([("█" if d["total_rm"]>0 else "·") for d in last14])

    b_lines=[]
    for b in breakdown[:8]:
        b_lines.append(f"• <b>{b['plan_code']}</b>: RM{b['total_rm']:.0f} ({b['cnt']})")
    b_txt="\n".join(b_lines) if b_lines else "—"

    txt=(
        "<b>📈 Sales Report</b>\n\n"
        f"🗓️ Today ({d0_local.date().isoformat()}): <b>RM{today['total_rm']:.0f}</b> ({today['cnt']} paid)\n"
        f"📅 This Month ({m0_local.strftime('%Y-%m')}): <b>RM{month['total_rm']:.0f}</b> ({month['cnt']} paid)\n\n"
        "<b>Breakdown (Month)</b>\n"
        f"{b_txt}\n\n"
        "<b>Last {range_days} days</b>\n"
        f"{spark}\n"
        "<i>█ = ada sales, · = tiada</i>"
    )
    await c.message.edit_text(txt.format(range_days=range_days), reply_markup=kb_admin_sales(range_days), parse_mode="HTML")
    await c.answer()



@router.callback_query(F.data=="a:export:menu")
async def admin_export_menu(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    await c.message.edit_text("<b>📤 Export</b>\nPilih data yang nak export:", reply_markup=kb_admin_export_menu(), parse_mode="HTML")
    await c.answer()



@router.callback_query(F.data=="a:export:orders_by_plan")
async def admin_export_by_plan_menu(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    await c.message.edit_text("<b>🧩 Export Orders (By Plan)</b>\nPilih plan:", reply_markup=kb_admin_export_plan(), parse_mode="HTML")
    await c.answer()

@router.callback_query(F.data.startswith("a:export_plan:"))
async def admin_export_by_plan(c:CallbackQuery, bot:Bot):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    plan=c.data.split(":")[2].upper()
    from core import db as _db
    # paid only, filter by plan_code when plan != ALL
    conn=_sqlite3.connect(db.DB_PATH); conn.row_factory=_sqlite3.Row
    if plan=="ALL":
        rows=conn.execute("SELECT * FROM orders WHERE status=1 AND paid_at IS NOT NULL ORDER BY id DESC LIMIT 10000").fetchall()
        fname="orders_paid_all.csv"
    else:
        rows=conn.execute("SELECT * FROM orders WHERE status=1 AND paid_at IS NOT NULL AND plan_code=? ORDER BY id DESC LIMIT 10000", (plan,)).fetchall()
        fname=f"orders_paid_{plan}.csv"
    conn.close()
    if not rows:
        csv_text="id,created_at\n"
    else:
        cols=list(rows[0].keys())
        buf=io.StringIO(); w=csv.writer(buf); w.writerow(cols)
        for r in rows:
            w.writerow([r[c] for c in cols])
        csv_text=buf.getvalue()
    data=csv_text.encode("utf-8")
    from aiogram.types import BufferedInputFile
    await bot.send_document(c.from_user.id, BufferedInputFile(data, filename=fname), caption="✅ Export by plan siap.")
    await c.answer("Sent", alert=True)

@router.callback_query(F.data=="a:export:orders_by_month")
async def admin_export_by_month_menu(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    await c.message.edit_text("<b>🗓️ Export Orders (By Month)</b>\nPilih bulan:", reply_markup=kb_admin_export_months(0), parse_mode="HTML")
    await c.answer()

@router.callback_query(F.data.startswith("a:export_months:"))
async def admin_export_months_page(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    page=int(c.data.split(":")[2])
    await c.message.edit_text("<b>🗓️ Export Orders (By Month)</b>\nPilih bulan:", reply_markup=kb_admin_export_months(page), parse_mode="HTML")
    await c.answer()

@router.callback_query(F.data.startswith("a:export_month:"))
async def admin_export_month(c:CallbackQuery, bot:Bot):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    ym=c.data.split(":")[2]
    # export paid orders in that month (Malaysia time)
    tz=8
    y=int(ym.split("-")[0]); m=int(ym.split("-")[1])
    start_local=datetime(y,m,1,0,0,0)
    end_local=(start_local+timedelta(days=32)).replace(day=1)
    start_utc=(start_local - timedelta(hours=tz)).isoformat()
    end_utc=(end_local - timedelta(hours=tz)).isoformat()
    from core import db as _db
    csv_text=_db.export_orders_csv_filtered(True, start_utc, end_utc)
    data=csv_text.encode("utf-8")
    from aiogram.types import BufferedInputFile
    await bot.send_document(c.from_user.id, BufferedInputFile(data, filename=f"orders_paid_{ym}.csv"), caption="✅ Export month siap.")
    await c.answer("Sent", alert=True)

@router.callback_query(F.data.startswith("a:res_release_pick:"))
async def admin_res_release_pick(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    parts=c.data.split(":")
    tg_id=int(parts[2]); page=int(parts[3]) if len(parts)>3 else 0
    await c.message.edit_text("<b>🗓️ Release Reseller Month</b>\nPilih bulan:", reply_markup=kb_admin_reseller_release_months(tg_id, page), parse_mode="HTML")
    await c.answer()

@router.callback_query(F.data.startswith("a:res_release_do:"))
async def admin_res_release_do(c:CallbackQuery, bot:Bot):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    _,_,_,tg,ym=c.data.split(":")
    await _admin_release_reseller_month(bot, int(tg), ym)
    await c.answer("Released", alert=True)

@router.callback_query(F.data.startswith("a:export:"))
async def admin_export(c:CallbackQuery, bot:Bot):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    kind=c.data.split(":")[2]
    from core import db as _db
    tz=8
    now_local=datetime.utcnow()+timedelta(hours=tz)

    if kind=="orders_range":
        set_state(c.from_user.id, "ADMIN_WAIT_EXPORT_RANGE", {})
        await c.message.edit_text(
            "<b>📅 Export Orders (Paid Range)</b>\n"
            "Hantar range ikut format:\n<code>YYYY-MM-DD|YYYY-MM-DD</code>\n"
            "Contoh: <code>2025-12-01|2025-12-31</code>\n\n"
            "Nota: end date exclusive.",
            reply_markup=kb_admin_export_menu(),
            parse_mode="HTML"
        )
        await c.answer()
        return

    if kind=="orders_all":
        csv_text=_db.export_orders_csv_filtered(paid_only=False)
        filename="orders_all.csv"
    elif kind=="orders_paid":
        m0=now_local.replace(day=1, hour=0,minute=0,second=0,microsecond=0)
        m1=(m0+timedelta(days=32)).replace(day=1)
        csv_text=_db.export_orders_csv_filtered(True, (m0-timedelta(hours=tz)).isoformat(), (m1-timedelta(hours=tz)).isoformat())
        filename=f"orders_paid_{m0.strftime('%Y-%m')}.csv"
    elif kind=="users":
        csv_text=_db.export_users_csv()
        filename="users.csv"
    else:
        csv_text=_db.export_resellers_csv()
        filename="resellers.csv"

    data=csv_text.encode("utf-8")
    from aiogram.types import BufferedInputFile
    await bot.send_document(c.from_user.id, BufferedInputFile(data, filename=filename), caption="✅ Export siap.")
    await c.answer("Export sent", alert=True)

@router.callback_query(F.data.startswith("a:resellers:"))
async def admin_resellers(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    from core import db as _db
    page=int(c.data.split(":")[2])
    page=max(0,page)
    limit=10
    offset=page*limit
    items=_db.list_resellers_paged(limit=limit, offset=offset)
    has_prev=page>0
    has_next=len(items)==limit
    lines=[]
    for r in items:
        lines.append(f"• <b>{r['tg_id']}</b> pkg=<b>{r['package_code']}</b> quota=<b>{r['monthly_quota']}</b> end={r['end_at']}")
    body="\n".join(lines) if lines else "Tiada reseller."
    await c.message.edit_text(
        "<b>🤝 Resellers</b>\n\n"
        f"{body}\n\n"
        "Klik <b>Find Reseller</b> untuk buka detail (atau Add/Update).",
        reply_markup=kb_admin_resellers(page, has_prev, has_next),
        parse_mode="HTML"
    )
    await c.answer()

@router.callback_query(F.data=="a:res_find")
async def admin_res_find(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    set_state(c.from_user.id, "ADMIN_WAIT_RESELLER_ID", {})
    await c.message.edit_text("<b>🔎 Find Reseller</b>\nHantar Telegram ID reseller (nombor).",
                              reply_markup=kb_admin_main(), parse_mode="HTML")
    await c.answer()

@router.callback_query(F.data=="a:res_add")
async def admin_res_add(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    set_state(c.from_user.id, "ADMIN_WAIT_RESELLER_UPSERT", {})
    await c.message.edit_text(
        "<b>➕ Add/Update Reseller</b>\n"
        "Hantar format 1 line:\n"
        "<code>tg_id|package_code|monthly_quota|start(YYYY-MM-DD)|end(YYYY-MM-DD)</code>\n\n"
        "Contoh:\n<code>123456789|LITE|5|2025-01-01|2025-12-31</code>",
        reply_markup=kb_admin_main(), parse_mode="HTML"
    )
    await c.answer()

@router.callback_query(F.data.startswith("a:res_view:"))
async def admin_res_view(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    tg_id=int(c.data.split(":")[2])
    from core import db as _db
    r=_db.get_reseller(tg_id)
    if not r:
        await c.answer("Tak jumpa", alert=True); return
    txt=(
        "<b>🤝 Reseller Detail</b>\n\n"
        f"TG ID: <b>{r['tg_id']}</b>\n"
        f"Package: <b>{r['package_code']}</b>\n"
        f"Quota/Month: <b>{r['monthly_quota']}</b>\n"
        f"Start: <b>{r['start_at']}</b>\n"
        f"End: <b>{r['end_at']}</b>"
    )
    await c.message.edit_text(txt, reply_markup=kb_admin_reseller_detail(tg_id), parse_mode="HTML")
    await c.answer()

@router.callback_query(F.data.startswith("a:res_edit:"))
async def admin_res_edit(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    tg_id=int(c.data.split(":")[2])
    set_state(c.from_user.id, "ADMIN_WAIT_RESELLER_EDIT", {"tg_id":tg_id})
    await c.message.edit_text(
        "<b>✏️ Edit Reseller</b>\n"
        "Hantar format 1 line:\n"
        "<code>package_code|monthly_quota|start(YYYY-MM-DD)|end(YYYY-MM-DD)</code>\n\n"
        "Contoh:\n<code>PRO|10|2025-01-01|2025-12-31</code>",
        reply_markup=kb_admin_reseller_detail(tg_id), parse_mode="HTML"
    )
    await c.answer()

@router.callback_query(F.data.startswith("a:res_del:"))
async def admin_res_del(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    tg_id=int(c.data.split(":")[2])
    from core import db as _db
    _db.delete_reseller(tg_id)
    await c.answer("Removed", alert=True)
    await c.message.edit_text("<b>✅ Reseller removed.</b>", reply_markup=kb_admin_main(), parse_mode="HTML")



@router.callback_query(F.data.startswith("a:res_credits_hist:"))
async def admin_res_credits_hist(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    tg_id=int(c.data.split(":")[2])
    from core import db as _db
    rows=_db.reseller_credits_last_months(tg_id, months=12)
    lines=[]
    for r in rows:
        icon="✅" if int(r.get("released",0))==1 else "⏳"
        lines.append(f"{icon} <b>{r['ym']}</b> quota={r.get('quota',0)} claimed={r.get('claimed',0)} released={r.get('released',0)}")
    body="\n".join(lines) if lines else "—"
    await c.message.edit_text(
        "<b>📆 Reseller Credits (12 Months)</b>\n\n"
        f"TG ID: <b>{tg_id}</b>\n\n{body}",
        reply_markup=kb_admin_reseller_detail(tg_id),
        parse_mode="HTML"
    )
    await c.answer()

@router.callback_query(F.data.startswith("a:res_credits:"))
async def admin_res_credits(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    tg_id=int(c.data.split(":")[2])
    from core import db as _db
    # current ym
    now_local=datetime.utcnow()+timedelta(hours=8)
    ym=now_local.strftime("%Y-%m")
    r=_db.get_reseller(tg_id)
    if not r:
        await c.answer("Tak jumpa", alert=True); return
    credit=_db.ensure_monthly_credit(tg_id, ym, int(r["monthly_quota"]))
    txt=(
        "<b>🧾 Reseller Credits</b>\n\n"
        f"TG ID: <b>{tg_id}</b>\n"
        f"Month: <b>{ym}</b>\n"
        f"Quota: <b>{credit['quota']}</b>\n"
        f"Claimed: <b>{credit['claimed']}</b>\n"
        f"Released: <b>{credit['released']}</b>"
    )
    await c.message.edit_text(txt, reply_markup=kb_admin_reseller_credits(tg_id, ym), parse_mode="HTML")
    await c.answer()

@router.callback_query(F.data.startswith("a:res_release:"))
async def admin_res_release(c:CallbackQuery, bot:Bot):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    tg_id=int(c.data.split(":")[2])
    now_local=datetime.utcnow()+timedelta(hours=8)
    ym=now_local.strftime("%Y-%m")
    await _admin_release_reseller_month(bot, tg_id, ym)
    await c.answer("Release done", alert=True)

@router.callback_query(F.data.startswith("a:res_release_ym:"))
async def admin_res_release_ym(c:CallbackQuery, bot:Bot):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    _,_,_,tg,ym=c.data.split(":")
    await _admin_release_reseller_month(bot, int(tg), ym)
    await c.answer("Release done", alert=True)

async def _admin_release_reseller_month(bot:Bot, tg_id:int, ym:str):
    from core import db as _db
    r=_db.get_reseller(tg_id)
    if not r:
        return
    quota=int(r["monthly_quota"])
    credit=_db.ensure_monthly_credit(tg_id, ym, quota)
    if int(credit.get("released",0))==1:
        await bot.send_message(tg_id, f"ℹ️ Credit {ym} dah released sebelum ni.")
        return
    links=[]
    for idx in range(1, quota+1):
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
            _db.insert_vpn_account(tg_id, "PRO", uuid, username, link, expires_at)
            links.append(link)
        except Exception as e:
            _db.audit("admin_release_err", f"tg={tg_id} ym={ym} u={username} err={e}")
    _db.set_credit_released(tg_id, ym)
    if links:
        header=f"<b>📦 Manual Release ({ym})</b>\nQuota: <b>{quota}</b>\n\n"
        chunk=""
        for link in links:
            line=f"<code>{link}</code>\n\n"
            if len(header)+len(chunk)+len(line)>3500:
                await bot.send_message(tg_id, header+chunk, parse_mode="HTML")
                chunk=""
            chunk+=line
        if chunk:
            await bot.send_message(tg_id, header+chunk, parse_mode="HTML")
    _db.audit("admin_release", f"tg={tg_id} ym={ym} delivered={len(links)}")



@router.callback_query(F.data=="a:device_settings")
async def admin_device_settings(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    auto_en = int(db.get_setting_int("AUTO_UNSUSPEND_ENABLED", 1))==1
    th = int(db.get_setting_int("DEVICE_SCAN_THRESHOLD", 3))
    await c.message.edit_text("<b>🧯 Device Enforcement</b>\nAdjust threshold & auto-unsuspend.", reply_markup=kb_admin_device_settings(auto_en, th), parse_mode="HTML")
    await c.answer()



@router.callback_query(F.data=="a:health:run")
async def admin_health(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    from app import self_check_report
    await c.message.edit_text(self_check_report(), reply_markup=kb_admin_health_actions(), parse_mode="HTML")
    await c.answer()

@router.callback_query(F.data=="a:xray:rollback")
async def admin_xray_rollback(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    from app import restore_latest_backup, settings, self_check_report
    ok=restore_latest_backup(settings.XRAY_CONFIG_PATH)
    try:
        os.system(settings.XRAY_RESTART_CMD)
    except Exception:
        pass
    await c.answer("Rollback OK" if ok else "No backup found", alert=True)
    await c.message.edit_text(self_check_report(), reply_markup=kb_admin_health_actions(), parse_mode="HTML")



@router.callback_query(F.data.startswith("a:svc:ask:"))
async def admin_service_restart_ask(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    svc=c.data.split(":")[3]
    await c.message.edit_text(
        f"<b>♻️ Restart Service</b>\n\nService: <b>{svc}</b>\n\nTeruskan?",
        reply_markup=kb_confirm_service(svc),
        parse_mode="HTML"
    )
    await c.answer()

@router.callback_query(F.data.startswith("a:svc:do:"))
async def admin_service_restart_do(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    svc=c.data.split(":")[3]
    from app import run_cmd, self_check_report
    # try systemctl then fallback service
    rc,out=run_cmd(f"systemctl restart {svc}")
    if rc!=0:
        rc,out=run_cmd(f"service {svc} restart")
    await c.answer("Restart sent ✅" if rc==0 else "Restart failed ⚠️", alert=True)
    await c.message.edit_text(self_check_report(), reply_markup=kb_admin_health_actions(), parse_mode="HTML")

@router.callback_query(F.data.startswith("a:sched:list:"))
async def admin_sched_list(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    page=int(c.data.split(":")[3])
    jobs=db.list_scheduled_broadcasts(status=0, limit=12, offset=page*12)
    has_prev=page>0
    has_next=len(jobs)==12
    lines=[]
    for j in jobs:
        try:
            run_my=(datetime.fromisoformat(j["run_at"])+timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            run_my=j.get("run_at","?")
        lines.append(f"• <b>#{j['id']}</b> <b>{j['target']}</b> @ <code>{run_my}</code>")
    body="\n".join(lines) if lines else "Tiada scheduled broadcast."
    await c.message.edit_text("<b>🗓️ Scheduled Broadcasts</b>\n\n"+body, reply_markup=kb_admin_sched_list(page, jobs, has_prev, has_next), parse_mode="HTML")
    await c.answer()

@router.callback_query(F.data.startswith("a:sched:view:"))
async def admin_sched_view(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    bid=int(c.data.split(":")[3])
    b=db.get_scheduled_broadcast(bid)
    if not b:
        await c.answer("Not found", alert=True); return
    try:
        run_my=(datetime.fromisoformat(b["run_at"])+timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        run_my=b.get("run_at","?")
    txt=(b.get("text_html") or "")
    if len(txt)>700:
        txt=txt[:700]+"…"
    await c.message.edit_text(
        "<b>🗓️ Broadcast Detail</b>\n\n"
        f"ID: <b>#{b['id']}</b>\n"
        f"Target: <b>{b['target']}</b>\n"
        f"Run (MY): <code>{run_my}</code>\n"
        f"Status: <b>{b['status']}</b>\n\n"
        f"<b>Preview</b>\n{txt}",
        reply_markup=kb_admin_sched_detail(bid),
        parse_mode="HTML"
    )
    await c.answer()



@router.callback_query(F.data.startswith("a:schedwiz:edit:"))
async def schedwiz_edit_start(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    bid=int(c.data.split(":")[3])
    b=db.get_scheduled_broadcast(bid)
    if not b:
        await c.answer("Not found", alert=True); return
    try:
        dt_my=(datetime.fromisoformat(b["run_at"]) + timedelta(hours=8))
        date_iso=dt_my.date().isoformat()
        time_str=dt_my.strftime("%H:%M")
    except Exception:
        date_iso=(datetime.utcnow()+timedelta(hours=8)).date().isoformat()
        time_str="09:00"
    payload={"bid":bid, "target":(b.get("target") or "ALL"), "date":date_iso, "time":time_str, "text_html":(b.get("text_html") or "")}
    set_state(c.from_user.id, "ADMIN_SCHED_EDIT_WIZ_TARGET", payload)
    await c.message.edit_text(
        "<b>🧙 Edit Scheduled Broadcast</b>\n\nPilih target baru (atau kekalkan):",
        reply_markup=kb_sched_target_picker(prefix="a:schedwiz:edittgt"),
        parse_mode="HTML"
    )
    await c.answer()

@router.callback_query(F.data.startswith("a:schedwiz:edittgt:"))
async def schedwiz_edittgt(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    tgt=c.data.split(":")[3]
    st=get_state(c.from_user.id); payload=st.get("payload") or {}
    payload["target"]=tgt
    set_state(c.from_user.id, "ADMIN_SCHED_EDIT_WIZ_DATE", payload)
    await c.message.edit_text("<b>🧙 Edit Wizard</b>\nPilih tarikh (MY):", reply_markup=kb_sched_date_picker(prefix="a:schedwiz:editdate"), parse_mode="HTML")
    await c.answer()

@router.callback_query(F.data.startswith("a:schedwiz:editdate:"))
async def schedwiz_editdate(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    date_iso=c.data.split(":")[3]
    st=get_state(c.from_user.id); payload=st.get("payload") or {}
    payload["date"]=date_iso
    set_state(c.from_user.id, "ADMIN_SCHED_EDIT_WIZ_TIME", payload)
    await c.message.edit_text("<b>🧙 Edit Wizard</b>\nPilih masa (MY):", reply_markup=kb_sched_time_picker(date_iso, prefix="a:schedwiz:edittime"), parse_mode="HTML")
    await c.answer()

@router.callback_query(F.data.startswith("a:schedwiz:edittime:"))
async def schedwiz_edittime(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    _,_,_,date_iso,hh,mm = c.data.split(":")
    st=get_state(c.from_user.id); payload=st.get("payload") or {}
    payload["date"]=date_iso
    payload["time"]=f"{hh}:{mm}"
    set_state(c.from_user.id, "ADMIN_SCHED_EDIT_WIZ_TEXTSRC", payload)
    await c.message.edit_text("<b>🧙 Edit Wizard</b>\nPilih teks (template / type):", reply_markup=kb_sched_text_source(prefix="a:schedwiz:edittextsrc"), parse_mode="HTML")
    await c.answer()

@router.callback_query(F.data.startswith("a:schedwiz:edittextsrc:"))
async def schedwiz_edittextsrc(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    mode=c.data.split(":")[3]
    st=get_state(c.from_user.id); payload=st.get("payload") or {}
    if mode=="tpl":
        set_state(c.from_user.id, "ADMIN_SCHED_EDIT_WIZ_TPL", payload)
        await c.message.edit_text("<b>🧙 Edit Wizard</b>\nPilih template:", reply_markup=kb_sched_template_picker(prefix="a:schedwiz:edittpl"), parse_mode="HTML")
    else:
        set_state(c.from_user.id, "ADMIN_WAIT_SCHED_EDIT_WIZ_TEXT", payload)
        await c.message.edit_text("<b>🧙 Edit Wizard</b>\nHantar teks baru (HTML ok).", reply_markup=kb_admin_campaign(), parse_mode="HTML")
    await c.answer()

@router.callback_query(F.data.startswith("a:schedwiz:edittpl:"))
async def schedwiz_edittpl(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    key=c.data.split(":")[3]
    st=get_state(c.from_user.id); payload=st.get("payload") or {}
    txt=db.get_template(key) or payload.get("text_html") or "<b>📣 Broadcast</b>"
    payload["text_html"]=txt
    payload["tpl_key"]=key
    set_state(c.from_user.id, "ADMIN_SCHED_EDIT_WIZ_CONFIRM", payload)
    bid=int(payload.get("bid") or 0)
    await c.message.edit_text(
        "<b>✅ Confirm Edit</b>\n\n"
        f"ID: <b>#{bid}</b>\n"
        f"Target: <b>{payload.get('target')}</b>\n"
        f"Time (MY): <code>{payload.get('date')} {payload.get('time')}</code>\n"
        f"Template: <b>{key}</b>\n\n"
        f"<b>Preview</b>\n{txt[:900]}{'…' if len(txt)>900 else ''}",
        reply_markup=kb_sched_confirm(prefix="a:schedwiz:editconfirm"),
        parse_mode="HTML"
    )
    await c.answer()

@router.callback_query(F.data.startswith("a:schedwiz:editconfirm:yes"))
async def schedwiz_editconfirm(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    st=get_state(c.from_user.id); payload=st.get("payload") or {}
    bid=int(payload.get("bid") or 0)
    dt_local=datetime.strptime(f"{payload.get('date')} {payload.get('time')}", "%Y-%m-%d %H:%M")
    run_at=(dt_local - timedelta(hours=8)).isoformat()
    db.update_scheduled_broadcast_time(bid, run_at)
    db.update_scheduled_broadcast_target(bid, payload.get("target","ALL"))
    db.update_scheduled_broadcast_text(bid, payload.get("text_html") or "<b>📣 Broadcast</b>")
    clear_state(c.from_user.id)
    await c.answer("Updated ✅", alert=True)
    b=db.get_scheduled_broadcast(bid)
    if b:
        try:
            run_my=(datetime.fromisoformat(b["run_at"])+timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            run_my=b.get("run_at","?")
        txt=(b.get("text_html") or "")
        if len(txt)>700: txt=txt[:700]+"…"
        await c.message.edit_text(
            "<b>🗓️ Broadcast Detail</b>\n\n"
            f"ID: <b>#{b['id']}</b>\n"
            f"Target: <b>{b['target']}</b>\n"
            f"Run (MY): <code>{run_my}</code>\n"
            f"Status: <b>{b['status']}</b>\n\n"
            f"<b>Preview</b>\n{txt}",
            reply_markup=kb_admin_sched_detail(bid),
            parse_mode="HTML"
        )

@router.callback_query(F.data.startswith("a:sched:cancel:"))
async def admin_sched_cancel(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    bid=int(c.data.split(":")[3])
    db.cancel_scheduled_broadcast(bid)
    await c.answer("Cancelled", alert=True)
    await admin_sched_list(c)



@router.callback_query(F.data.startswith("a:sched:edittarget:"))
async def admin_sched_edit_target(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    bid=int(c.data.split(":")[3])
    set_state(c.from_user.id, "ADMIN_WAIT_SCHED_EDIT_TARGET", {"bid":bid})
    await c.message.edit_text(
        "<b>🎯 Edit Target</b>\n"
        "Hantar target baru: <code>ALL</code> / <code>LITE</code> / <code>PRO</code> / <code>RESELLER</code>",
        reply_markup=kb_admin_campaign(),
        parse_mode="HTML"
    )
    await c.answer()

@router.callback_query(F.data.startswith("a:sched:edittext:"))
async def admin_sched_edit_text(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    bid=int(c.data.split(":")[3])
    set_state(c.from_user.id, "ADMIN_WAIT_SCHED_EDIT_TEXT", {"bid":bid})
    await c.message.edit_text(
        "<b>📝 Edit Text</b>\n"
        "Hantar teks baru (HTML ok).",
        reply_markup=kb_admin_campaign(),
        parse_mode="HTML"
    )
    await c.answer()

@router.callback_query(F.data.startswith("a:sched:edit:"))
async def admin_sched_edit(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    bid=int(c.data.split(":")[3])
    set_state(c.from_user.id, "ADMIN_WAIT_SCHED_EDIT_TIME", {"bid":bid})
    await c.message.edit_text(
        "<b>✏️ Edit Broadcast Time</b>\n"
        "Hantar masa baru (waktu Malaysia):\n<code>YYYY-MM-DD HH:MM</code>",
        reply_markup=kb_admin_campaign(),
        parse_mode="HTML"
    )
    await c.answer()

@router.callback_query(F.data=="noop")
async def noop(c:CallbackQuery):
    await c.answer()

@router.message()
async def admin_input_router(m:Message, bot:Bot):
    if not is_admin(m.from_user.id):
        return
    st=get_state(m.from_user.id)
    if not st:
        return

    action=st.get("action")
    payload=st.get("payload") or {}

    # ORDER DETAIL
    if action=="ADMIN_WAIT_ORDER_ID":
        clear_state(m.from_user.id)
        txt=(m.text or "").strip()
        if not txt.isdigit():
            await m.reply("Sila hantar nombor Order ID sahaja.")
            return
        oid=int(txt)
        o=db.get_order_by_id(oid) if hasattr(db,"get_order_by_id") else db.get_order(oid)
        if not o:
            await m.reply("Order tak jumpa.")
            return
        bill=o.get("billcode")
        meta=o.get("meta_json") or ""
        await m.reply(
            "<b>🧾 Order Detail</b>\n"
            f"ID: <b>#{o['id']}</b>\n"
            f"Type: <b>{o['order_type']}</b> / <b>{o['plan_code']}</b>\n"
            f"Amount: <b>RM{o['amount_rm']:.0f}</b>\n"
            f"Status: <b>{o['status']}</b> | Fulfilled: <b>{o.get('fulfilled')}</b>\n"
            f"Bill: <code>{bill}</code>\n"
            f"Created: {_fmt_ts(o['created_at'])}\nPaid: {_fmt_ts(o.get('paid_at'))}\n\n"
            f"<b>Meta</b>:\n<code>{meta[:1200]}</code>",
            reply_markup=kb_admin_order_detail(int(o['id']), bill),
            parse_mode="HTML"
        )
        return

    # USER SEARCH
    if action=="ADMIN_WAIT_USER_QUERY":
        clear_state(m.from_user.id)
        q=(m.text or "").strip()
        u=db.find_user_by_tg_or_username(q)
        if not u:
            await m.reply("User tak jumpa.")
            return
        accounts=db.list_accounts_by_tg(int(u["tg_id"]))
        lines=[]
        for a in accounts[:10]:
            lines.append(f"• <b>{a['vless_username']}</b> {a['plan_code']} {a['status']} exp={a['expires_at']}")
        body="\n".join(lines) if lines else "Tiada akaun."
        await m.reply(
            f"<b>👤 User</b>\nTG: <b>{u['tg_id']}</b>\n@{u.get('username') or '-'}\n\n<b>Accounts</b>\n{body}\n\nUntuk manage akaun, guna Find Account.",
            reply_markup=kb_admin_users(),
            parse_mode="HTML"
        )
        return

    # ACCOUNT FIND
    if action=="ADMIN_WAIT_ACCOUNT_USERNAME":
        clear_state(m.from_user.id)
        username=(m.text or "").strip()
        acc=db.find_account_by_username(username)
        if not acc:
            await m.reply("Akaun tak jumpa.")
            return
        await m.reply(
            "<b>📌 Account</b>\n"
            f"User: <b>{acc['vless_username']}</b>\n"
            f"Plan: <b>{acc['plan_code']}</b>\n"
            f"Status: <b>{acc['status']}</b>\n"
            f"Expiry: <b>{acc['expires_at']}</b>\n\n"
            f"<b>Link</b>\n<code>{acc['vless_link']}</code>",
            reply_markup=kb_admin_account_actions(acc["vless_username"]),
            parse_mode="HTML"
        )
        return

    # RENEW DAYS
    if action=="ADMIN_WAIT_RENEW_DAYS":
        username=payload.get("username")
        txt=(m.text or "").strip()
        if not txt.isdigit():
            await m.reply("Sila hantar nombor hari sahaja.")
            return
        days=int(txt)
        clear_state(m.from_user.id)
        acc=db.find_account_by_username(username)
        if not acc:
            await m.reply("Akaun tak jumpa.")
            return
        try:
            old=datetime.fromisoformat(str(acc["expires_at"]))
        except Exception:
            old=datetime.utcnow()
        new=(max(old, datetime.utcnow()) + timedelta(days=days)).isoformat()
        db.update_account_expiry(username, new)
        await m.reply(f"✅ Renewed <b>{username}</b> +{days} hari\nNew expiry: <b>{new}</b>", parse_mode="HTML",
                      reply_markup=kb_admin_account_actions(username))
        return

    # SWITCH PLAN
    if action=="ADMIN_WAIT_SWITCH_PLAN":
        username=payload.get("username")
        plan=(m.text or "").strip().upper()
        if plan not in ("LITE","PRO"):
            await m.reply("Sila pilih plan: LITE atau PRO")
            return
        clear_state(m.from_user.id)
        db.update_account_plan(username, plan)
        await m.reply(f"✅ Plan updated: <b>{username}</b> → <b>{plan}</b>", parse_mode="HTML",
                      reply_markup=kb_admin_account_actions(username))
        return

    # BROADCAST
    if action=="ADMIN_WAIT_BCAST_TEXT":
        clear_state(m.from_user.id)
        target=payload.get("target","ALL")
        text=(m.text or "")
        sent=0
        import sqlite3 as _sqlite3
        import io, csv
        conn=_sqlite3.connect(db.DB_PATH); conn.row_factory=_sqlite3.Row
        if target=="ALL":
            rows=conn.execute("SELECT tg_id FROM users").fetchall()
        elif target=="RESELLER":
            rows=conn.execute("SELECT tg_id FROM resellers").fetchall()
        else:
            # LITE/PRO: target by accounts
            rows=conn.execute("SELECT DISTINCT tg_id FROM vpn_accounts WHERE plan_code=? AND status='ACTIVE'", (target,)).fetchall()
        conn.close()
        for r in rows:
            try:
                await bot.send_message(int(r["tg_id"]), text)
                sent += 1
            except Exception:
                pass
        db.audit("admin_bcast", f"by={m.from_user.id} target={target} sent={sent}")
        await m.reply(f"✅ Broadcast sent: <b>{sent}</b> (target={target})", parse_mode="HTML",
                      reply_markup=kb_admin_main())
        return
    # ORDER SEARCH
    if action=="ADMIN_WAIT_ORDER_SEARCH":
        clear_state(m.from_user.id)
        q=(m.text or "").strip()
        rows=db.find_orders(q, limit=15)
        if not rows:
            await m.reply("Tiada result.")
            return
        lines=[]
        def st_label(s):
            return {0:"PENDING",1:"PAID",-1:"FAILED",2:"REFUND"}.get(int(s),str(s))
        for o in rows:
            lines.append(f"• <b>#{o['id']}</b> {st_label(o['status'])} RM{o['amount_rm']:.2f} tg={o['tg_id']} plan={o['plan_code']}")
        await m.reply("<b>🔎 Results</b>\n\n"+"\n".join(lines)+"\n\nReply nombor Order ID untuk buka detail.", parse_mode="HTML")
        return

    # SCHEDULE BROADCAST step 1: text
    if action=="ADMIN_WAIT_SCHED" and (payload or {}).get("text") is None:
        payload["text"]=m.html_text or (m.text or "")
        set_state(m.from_user.id, "ADMIN_WAIT_SCHED_TIME", payload)
        await m.reply("Okay ✅ sekarang hantar masa ikut format:\n<code>TARGET|YYYY-MM-DD HH:MM</code>\nContoh: <code>ALL|2025-12-28 21:30</code>", parse_mode="HTML")
        return

    # SCHEDULE BROADCAST step 2: time
    if action=="ADMIN_WAIT_SCHED_TIME":
        clear_state(m.from_user.id)
        line=(m.text or "").strip()
        parts=[p.strip() for p in line.split("|")]
        if len(parts)!=2:
            await m.reply("Format salah. Guna TARGET|YYYY-MM-DD HH:MM")
            return
        target=parts[0].upper()
        dt_str=parts[1]
        try:
            dt_local=datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
        except Exception:
            await m.reply("Tarikh/masa tak valid. Format: YYYY-MM-DD HH:MM")
            return
        # convert MY local to UTC
        run_at=(dt_local - timedelta(hours=8)).isoformat()
        text_html=(payload or {}).get("text") or ""
        if not text_html:
            await m.reply("Tiada teks broadcast.")
            return
        bid=db.add_scheduled_broadcast(target, text_html, run_at)
        await m.reply(
            f"✅ Scheduled broadcast ID <b>{bid}</b> untuk <b>{target}</b> pada <b>{dt_str}</b> (MY).",
            parse_mode="HTML",
        )
        return

    # ORDER ID quick open (admin reply with #id)
    if (m.text or "").strip().isdigit() and is_admin(m.from_user.id):
        oid=int((m.text or "0").strip())
        order=db.get_order(oid)
        if order:
            await m.reply(
                "<b>🧾 Order Detail</b>\n\n"
                f"ID: <b>#{order['id']}</b>\n"
                f"TG: <b>{order['tg_id']}</b>\n"
                f"Type: <b>{order['order_type']}</b>\n"
                f"Plan: <b>{order['plan_code']}</b>\n"
                f"Amount: <b>RM{float(order['amount_rm']):.2f}</b>\n"
                f"Billcode: <code>{order.get('billcode') or '-'}</code>\n"
                f"Refno: <code>{order.get('refno') or '-'}</code>\n"
                f"Status: <b>{order['status']}</b>\n"
                f"Created: <code>{order['created_at']}</code>\n"
                f"Paid: <code>{order.get('paid_at') or '-'}</code>\n",
                reply_markup=kb_admin_order_detail(int(order["id"]), order.get("billcode")),
                parse_mode="HTML",
            )
            return



@router.callback_query(F.data.startswith("a:order:view:"))
async def admin_order_view(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    oid=int(c.data.split(":")[3])
    order=db.get_order(oid)
    if not order:
        await c.answer("Order not found", alert=True); return
    await c.message.edit_text(
        "<b>🧾 Order Detail</b>\n\n"
        f"ID: <b>#{order['id']}</b>\n"
        f"TG: <b>{order['tg_id']}</b>\n"
        f"Type: <b>{order['order_type']}</b>\n"
        f"Plan: <b>{order['plan_code']}</b>\n"
        f"Amount: <b>RM{float(order['amount_rm']):.2f}</b>\n"
        f"Billcode: <code>{order.get('billcode') or '-'}</code>\n"
        f"Refno: <code>{order.get('refno') or '-'}</code>\n"
        f"Status: <b>{order['status']}</b>\n"
        f"Created: <code>{order['created_at']}</code>\n"
        f"Paid: <code>{order.get('paid_at') or '-'}</code>\n",
        reply_markup=kb_admin_order_detail(int(order["id"]), order.get("billcode")),
        parse_mode="HTML"
    )
    await c.answer()



@router.callback_query(F.data=="a:tpl:edit")
async def admin_tpl_edit(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    st=get_state(c.from_user.id)
    payload=(st.get("payload") or {})
    key=payload.get("tpl_key")
    txt=payload.get("tpl_text","")
    if not key:
        await c.answer("No template", alert=True); return
    set_state(c.from_user.id, "ADMIN_WAIT_TEMPLATE_EDIT", {"tpl_key":key})
    await c.message.edit_text(
        "<b>✏️ Edit Template</b>\n"
        f"Key: <b>{key}</b>\n\n"
        "Hantar teks baru (HTML ok).\n"
        "Tip: guna <b>, <i>, <code> untuk style.",
        reply_markup=kb_admin_templates(),
        parse_mode="HTML"
    )
    await c.answer()



@router.callback_query(F.data.startswith("a:schedwiz:tgt:"))
async def schedwiz_target(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    tgt=c.data.split(":")[3]
    set_state(c.from_user.id, "ADMIN_SCHED_WIZ_DATE", {"target":tgt})
    await c.message.edit_text("<b>🗓️ Wizard</b>\nPilih tarikh (MY):", reply_markup=kb_sched_date_picker(), parse_mode="HTML")
    await c.answer()

@router.callback_query(F.data.startswith("a:schedwiz:date:"))
async def schedwiz_date(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    date_iso=c.data.split(":")[3]
    st=get_state(c.from_user.id); payload=st.get("payload") or {}
    payload["date"]=date_iso
    set_state(c.from_user.id, "ADMIN_SCHED_WIZ_TIME", payload)
    await c.message.edit_text("<b>🗓️ Wizard</b>\nPilih masa (MY):", reply_markup=kb_sched_time_picker(date_iso), parse_mode="HTML")
    await c.answer()

@router.callback_query(F.data.startswith("a:schedwiz:time:"))
async def schedwiz_time(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    _,_,date_iso,hh,mm = c.data.split(":")
    st=get_state(c.from_user.id); payload=st.get("payload") or {}
    payload["time"]=f"{hh}:{mm}"
    set_state(c.from_user.id, "ADMIN_SCHED_WIZ_TEXTSRC", payload)
    await c.message.edit_text("<b>🗓️ Wizard</b>\nPilih sumber teks:", reply_markup=kb_sched_text_source(), parse_mode="HTML")
    await c.answer()

@router.callback_query(F.data.startswith("a:schedwiz:textsrc:"))
async def schedwiz_textsrc(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    mode=c.data.split(":")[3]
    st=get_state(c.from_user.id); payload=st.get("payload") or {}
    if mode=="tpl":
        set_state(c.from_user.id, "ADMIN_SCHED_WIZ_TPL", payload)
        await c.message.edit_text("<b>🗓️ Wizard</b>\nPilih template:", reply_markup=kb_sched_template_picker(), parse_mode="HTML")
    else:
        set_state(c.from_user.id, "ADMIN_WAIT_SCHED_WIZ_TEXT", payload)
        await c.message.edit_text("<b>🗓️ Wizard</b>\nHantar teks broadcast (HTML ok).", reply_markup=kb_admin_campaign(), parse_mode="HTML")
    await c.answer()

@router.callback_query(F.data.startswith("a:schedwiz:tpl:"))
async def schedwiz_tpl(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    key=c.data.split(":")[3]
    st=get_state(c.from_user.id); payload=st.get("payload") or {}
    txt=db.get_template(key) or (payload.get("tpl_defaults", {}).get(key,""))
    if not txt:
        # fallback minimal
        txt="<b>📣 Broadcast</b>\n\nTeks belum diset."
    payload["text_html"]=txt
    payload["tpl_key"]=key
    set_state(c.from_user.id, "ADMIN_SCHED_WIZ_CONFIRM", payload)
    # preview
    date_iso=payload.get("date"); t=payload.get("time"); tgt=payload.get("target")
    await c.message.edit_text(
        "<b>✅ Confirm Schedule</b>\n\n"
        f"Target: <b>{tgt}</b>\n"
        f"Time (MY): <code>{date_iso} {t}</code>\n"
        f"Template: <b>{key}</b>\n\n"
        f"<b>Preview</b>\n{txt[:900]}{'…' if len(txt)>900 else ''}",
        reply_markup=kb_sched_confirm(),
        parse_mode="HTML"
    )
    await c.answer()

@router.callback_query(F.data.startswith("a:schedwiz:confirm:yes"))
async def schedwiz_confirm(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    st=get_state(c.from_user.id); payload=st.get("payload") or {}
    tgt=payload.get("target","ALL")
    date_iso=payload.get("date")
    t=payload.get("time","09:00")
    text_html=payload.get("text_html") or "<b>📣 Broadcast</b>"
    # convert MY -> UTC
    dt_local=datetime.strptime(f"{date_iso} {t}", "%Y-%m-%d %H:%M")
    run_at=(dt_local - timedelta(hours=8)).isoformat()
    db.insert_scheduled_broadcast(tgt, run_at, text_html)
    clear_state(c.from_user.id)
    await c.answer("Saved ✅", alert=True)
    await admin_sched_list(c)

@router.callback_query(F.data.startswith("a:schedwiz:back:"))
async def schedwiz_back(c:CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("No access", alert=True); return
    step=c.data.split(":")[3]
    st=get_state(c.from_user.id); payload=st.get("payload") or {}
    if step=="date":
        set_state(c.from_user.id, "ADMIN_SCHED_WIZ_DATE", payload)
        await c.message.edit_text("<b>🗓️ Wizard</b>\nPilih tarikh (MY):", reply_markup=kb_sched_date_picker(), parse_mode="HTML")
    elif step=="time":
        date_iso=payload.get("date") or (datetime.utcnow()+timedelta(hours=8)).date().isoformat()
        set_state(c.from_user.id, "ADMIN_SCHED_WIZ_TIME", payload)
        await c.message.edit_text("<b>🗓️ Wizard</b>\nPilih masa (MY):", reply_markup=kb_sched_time_picker(date_iso), parse_mode="HTML")
    else:
        set_state(c.from_user.id, "ADMIN_SCHED_WIZ_TEXTSRC", payload)
        await c.message.edit_text("<b>🗓️ Wizard</b>\nPilih sumber teks:", reply_markup=kb_sched_text_source(), parse_mode="HTML")
    await c.answer()



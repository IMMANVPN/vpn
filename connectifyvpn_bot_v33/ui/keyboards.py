from datetime import datetime, timedelta
from aiogram.utils.keyboard import InlineKeyboardBuilder

def kb_start(owner_username: str):
    kb=InlineKeyboardBuilder()
    kb.button(text="✅ Menu", callback_data="menu")
    kb.button(text="💬 DM Owner", url=f"https://t.me/{owner_username.lstrip('@')}")
    kb.adjust(1,1)
    return kb.as_markup()

def kb_menu(is_admin: bool=False):
    kb=InlineKeyboardBuilder()
    kb.button(text="🛒 Buy ID", callback_data="buy")
    kb.button(text="🤝 Reseller", callback_data="reseller")
    kb.button(text="📘 Tutorial", callback_data="tutorial")
    kb.button(text="❓ FAQ", callback_data="faq")
    kb.button(text="🧑‍💻 Live Agent", callback_data="agent")
    if is_admin:
        kb.button(text="🛡️ Admin Panel", callback_data="admin")
    kb.adjust(1)
    return kb.as_markup()

def kb_plans():
    kb=InlineKeyboardBuilder()
    kb.button(text="🟢 Lite RM29/Year", callback_data="plan:LITE")
    kb.button(text="🔵 Pro RM49/Year", callback_data="plan:PRO")
    kb.button(text="⬅️ Back", callback_data="menu")
    kb.adjust(1)
    return kb.as_markup()

def kb_reseller_packages():
    kb=InlineKeyboardBuilder()
    kb.button(text="🟢 Reseller Lite RM99", callback_data="rpack:R_LITE")
    kb.button(text="🔵 Reseller Pro RM149", callback_data="rpack:R_PRO")
    kb.button(text="🔴 Reseller Elite RM249", callback_data="rpack:R_ELITE")
    kb.button(text="⬅️ Back", callback_data="menu")
    kb.adjust(1)
    return kb.as_markup()

def kb_confirm_pay(order_id:int, amount_rm:float):
    kb=InlineKeyboardBuilder()
    kb.button(text=f"💳 Bayar RM{amount_rm:.0f}", callback_data=f"pay:{order_id}")
    kb.button(text="⬅️ Back", callback_data="buy")
    kb.adjust(1)
    return kb.as_markup()

def kb_payment_link(billcode:str, order_id:int):
    kb=InlineKeyboardBuilder()
    kb.button(text="🔗 Open Payment", url=f"https://toyyibpay.com/{billcode}")
    kb.button(text="🔄 Saya Dah Bayar (Check)", callback_data=f"check:{order_id}")
    kb.button(text="❌ Cancel", callback_data=f"cancel:{order_id}")
    kb.adjust(1)
    return kb.as_markup()

def kb_reseller_dashboard():
    kb=InlineKeyboardBuilder()
    kb.button(text="📦 Claim ID Bulan Ini", callback_data="r:claim")
    kb.button(text="📊 Dashboard Reseller", callback_data="r:dash")
    kb.button(text="🧾 Rekod / History", callback_data="r:history")
    kb.button(text="📣 Material Promo", callback_data="r:promo")
    kb.button(text="⬅️ Menu", callback_data="menu")
    kb.adjust(1)
    return kb.as_markup()

def kb_admin():
    kb=InlineKeyboardBuilder()
    kb.button(text="📊 Dashboard", callback_data="a:dash")
    kb.button(text="🧾 Orders", callback_data="a:orders:all:0")
    kb.button(text="🔎 Search", callback_data="a:help_search")
    kb.button(text="⛔ Suspend", callback_data="a:help_suspend")
    kb.button(text="✅ Unsuspend", callback_data="a:help_unsuspend")
    kb.button(text="♻️ Renew", callback_data="a:help_renew")
    kb.button(text="📣 Broadcast", callback_data="a:help_bcast")
    kb.button(text="🤝 Resellers", callback_data="a:resellers:0")
    kb.button(text="📈 Sales Report", callback_data="a:sales")
    kb.button(text="⬅️ Menu", callback_data="menu")
    kb.adjust(2)
    return kb.as_markup()


# -------- Admin Premium Inline Dashboard --------
def kb_admin_main():
    kb=InlineKeyboardBuilder()
    kb.button(text="📊 Dashboard", callback_data="a:dash")
    kb.button(text="🧾 Orders", callback_data="a:orders:0")
    kb.button(text="👥 Users/Accounts", callback_data="a:users")
    kb.button(text="🤝 Resellers", callback_data="a:resellers:0")
    kb.button(text="📈 Sales Report", callback_data="a:sales")
    kb.button(text="⚙️ Settings", callback_data="a:settings")
    kb.button(text="📣 Broadcast", callback_data="a:bcast")
    kb.button(text="🎯 Campaign", callback_data="a:campaign")
    kb.button(text="⬅️ Menu", callback_data="menu")
    kb.adjust(2,2,2,3,1)
    return kb.as_markup()

def kb_admin_orders(page:int, has_prev:bool, has_next:bool):
    kb=InlineKeyboardBuilder()
    if has_prev:
        kb.button(text="⬅️ Prev", callback_data=f"a:orders:{page-1}")
    if has_next:
        kb.button(text="➡️ Next", callback_data=f"a:orders:{page+1}")
    kb.button(text="🔎 Find Order", callback_data="a:find_order")
    kb.button(text="🧯 Device Enforcement", callback_data="a:device_settings")
    kb.button(text="⬅️ Admin", callback_data="a:home")
    kb.adjust(2,1,1)
    return kb.as_markup()

def kb_admin_order_detail(oid:int, billcode:str|None):
    kb=InlineKeyboardBuilder()
    if billcode:
        kb.button(text="🔗 Payment Link", url=f"https://toyyibpay.com/{billcode}")
    kb.button(text="⬅️ Orders", callback_data="a:orders:0")
    kb.button(text="🧯 Device Enforcement", callback_data="a:device_settings")
    kb.button(text="⬅️ Admin", callback_data="a:home")
    kb.adjust(1,2)
    return kb.as_markup()

def kb_admin_users():
    kb=InlineKeyboardBuilder()
    kb.button(text="🔎 Find User", callback_data="a:find_user")
    kb.button(text="📌 Find Account", callback_data="a:find_account")
    kb.button(text="🧯 Device Enforcement", callback_data="a:device_settings")
    kb.button(text="⬅️ Admin", callback_data="a:home")
    kb.adjust(2,2,1)
    return kb.as_markup()

def kb_admin_account_actions(username:str):
    kb=InlineKeyboardBuilder()
    kb.button(text="⛔ Suspend", callback_data=f"a:acc_suspend:{username}")
    kb.button(text="✅ Unsuspend", callback_data=f"a:acc_unsuspend:{username}")
    kb.button(text="♻️ Renew +Days", callback_data=f"a:acc_renew:{username}")
    kb.button(text="🔁 Regen Link", callback_data=f"a:acc_regen:{username}")
    kb.button(text="🔄 Switch Plan", callback_data=f"a:acc_switch:{username}")
    kb.button(text="🧹 Reset Device State", callback_data=f"a:acc_reset:{username}")
    kb.button(text="⬅️ Users", callback_data="a:users")
    kb.button(text="🧯 Device Enforcement", callback_data="a:device_settings")
    kb.button(text="⬅️ Admin", callback_data="a:home")
    kb.adjust(2,2,2,2)
    return kb.as_markup()

def kb_admin_settings(curr_window:int, curr_unsuspend:int):
    kb=InlineKeyboardBuilder()
    kb.button(text=f"🕒 Window: {curr_window}m", callback_data="noop")
    kb.button(text="➖", callback_data="a:set_window:-5")
    kb.button(text="➕", callback_data="a:set_window:+5")
    kb.button(text=f"⏱️ Auto-Unsuspend: {curr_unsuspend}h", callback_data="noop")
    kb.button(text="➖", callback_data="a:set_unsuspend:-1")
    kb.button(text="➕", callback_data="a:set_unsuspend:+1")
    kb.button(text="🧯 Device Enforcement", callback_data="a:device_settings")
    kb.button(text="⬅️ Admin", callback_data="a:home")
    kb.adjust(3,3,1)
    return kb.as_markup()

def kb_admin_bcast():
    kb=InlineKeyboardBuilder()
    kb.button(text="📣 Broadcast All", callback_data="a:bcast_all")
    kb.button(text="🟢 Broadcast Lite", callback_data="a:bcast_lite")
    kb.button(text="🔵 Broadcast Pro", callback_data="a:bcast_pro")
    kb.button(text="🤝 Broadcast Reseller", callback_data="a:bcast_reseller")
    kb.button(text="🧯 Device Enforcement", callback_data="a:device_settings")
    kb.button(text="⬅️ Admin", callback_data="a:home")
    kb.adjust(2,2,1)
    return kb.as_markup()


def kb_admin_sales(range_days:int=14):
    kb=InlineKeyboardBuilder()
    kb.button(text="🗓️ 7d", callback_data="a:sales:7")
    kb.button(text="🗓️ 14d", callback_data="a:sales:14")
    kb.button(text="🗓️ 30d", callback_data="a:sales:30")
    kb.button(text="📤 Export", callback_data="a:export:menu")
    kb.button(text="📤 Export Users CSV", callback_data="a:export:users")
    kb.button(text="📤 Export Resellers CSV", callback_data="a:export:resellers")
    kb.button(text="🧯 Device Enforcement", callback_data="a:device_settings")
    kb.button(text="⬅️ Admin", callback_data="a:home")
    kb.adjust(1,1,1,1)
    return kb.as_markup()

def kb_admin_resellers(page:int, has_prev:bool, has_next:bool):
    kb=InlineKeyboardBuilder()
    if has_prev:
        kb.button(text="⬅️ Prev", callback_data=f"a:resellers:{page-1}")
    if has_next:
        kb.button(text="➡️ Next", callback_data=f"a:resellers:{page+1}")
    kb.button(text="➕ Add/Update", callback_data="a:res_add")
    kb.button(text="🔎 Find Reseller", callback_data="a:res_find")
    kb.button(text="🧯 Device Enforcement", callback_data="a:device_settings")
    kb.button(text="⬅️ Admin", callback_data="a:home")
    kb.adjust(2,2,1)
    return kb.as_markup()

def kb_admin_reseller_detail(tg_id:int):
    kb=InlineKeyboardBuilder()
    kb.button(text="🧾 View Credits", callback_data=f"a:res_credits:{tg_id}")
    kb.button(text="📦 Manual Release (this month)", callback_data=f"a:res_release:{tg_id}")
    kb.button(text="🗓️ Release Month", callback_data=f"a:res_release_pick:{tg_id}:0")
    kb.button(text="✏️ Edit", callback_data=f"a:res_edit:{tg_id}")
    kb.button(text="🗑️ Remove", callback_data=f"a:res_del:{tg_id}")
    kb.button(text="⬅️ Resellers", callback_data="a:resellers:0")
    kb.button(text="🧯 Device Enforcement", callback_data="a:device_settings")
    kb.button(text="⬅️ Admin", callback_data="a:home")
    kb.adjust(2,2,2,1)
    return kb.as_markup()

def kb_admin_reseller_credits(tg_id:int, ym:str):
    kb=InlineKeyboardBuilder()
    kb.button(text="📦 Release Now", callback_data=f"a:res_release_ym:{tg_id}:{ym}")
    kb.button(text="⬅️ Reseller", callback_data=f"a:res_view:{tg_id}")
    kb.adjust(1,1)
    return kb.as_markup()


def kb_admin_export_menu():
    kb=InlineKeyboardBuilder()
    kb.button(text="🧾 Orders (All)", callback_data="a:export:orders_all")
    kb.button(text="✅ Orders (Paid This Month)", callback_data="a:export:orders_paid")
    kb.button(text="📅 Orders (Paid Range)", callback_data="a:export:orders_range")
    kb.button(text="🧩 Orders (By Plan)", callback_data="a:export:orders_by_plan")
    kb.button(text="🗓️ Orders (By Month)", callback_data="a:export:orders_by_month")
    kb.button(text="👤 Users", callback_data="a:export:users")
    kb.button(text="🤝 Resellers", callback_data="a:export:resellers")
    kb.button(text="⬅️ Sales", callback_data="a:sales")
    kb.adjust(2,2,2,1)
    return kb.as_markup()


def kb_admin_export_plan():
    kb=InlineKeyboardBuilder()
    kb.button(text="🟢 LITE (Paid)", callback_data="a:export_plan:LITE")
    kb.button(text="🔵 PRO (Paid)", callback_data="a:export_plan:PRO")
    kb.button(text="🤝 RESELLER (Paid)", callback_data="a:export_plan:RESELLER")
    kb.button(text="✅ ALL PAID", callback_data="a:export_plan:ALL")
    kb.button(text="⬅️ Export", callback_data="a:export:menu")
    kb.adjust(2,2,1)
    return kb.as_markup()

def kb_admin_export_months(page:int=0):
    # last 12 months, paged 6 per page
    now_local=datetime.utcnow()+timedelta(hours=8)
    y=now_local.year; m=now_local.month
    months=[]
    for i in range(12):
        mm=m-i; yy=y
        while mm<=0:
            mm+=12; yy-=1
        months.append(f"{yy:04d}-{mm:02d}")
    per=6
    start=page*per
    chunk=months[start:start+per]
    kb=InlineKeyboardBuilder()
    for ym in chunk:
        kb.button(text=f"📅 {ym}", callback_data=f"a:export_month:{ym}")
    if page>0:
        kb.button(text="⬅️ Prev", callback_data=f"a:export_months:{page-1}")
    if start+per < len(months):
        kb.button(text="➡️ Next", callback_data=f"a:export_months:{page+1}")
    kb.button(text="⬅️ Export", callback_data="a:export:menu")
    kb.adjust(3,3,2,1)  # flexible
    return kb.as_markup()

def kb_admin_reseller_release_months(tg_id:int, page:int=0):
    now_local=datetime.utcnow()+timedelta(hours=8)
    y=now_local.year; m=now_local.month
    months=[]
    for i in range(12):
        mm=m-i; yy=y
        while mm<=0:
            mm+=12; yy-=1
        months.append(f"{yy:04d}-{mm:02d}")
    per=6
    start=page*per
    chunk=months[start:start+per]
    kb=InlineKeyboardBuilder()
    for ym in chunk:
        kb.button(text=f"📦 Release {ym}", callback_data=f"a:res_release_do:{tg_id}:{ym}")
    if page>0:
        kb.button(text="⬅️ Prev", callback_data=f"a:res_release_pick:{tg_id}:{page-1}")
    if start+per < len(months):
        kb.button(text="➡️ Next", callback_data=f"a:res_release_pick:{tg_id}:{page+1}")
    kb.button(text="⬅️ Reseller", callback_data=f"a:res_view:{tg_id}")
    kb.adjust(2,2,2,3,1)
    return kb.as_markup()


def kb_admin_orders_list(status:int|None, page:int, orders:list[dict], has_prev:bool, has_next:bool):
    kb=InlineKeyboardBuilder()
    # filters row
    kb.button(text="🕓 Pending", callback_data="a:orders:0:0")
    kb.button(text="✅ Paid", callback_data="a:orders:1:0")
    kb.button(text="❌ Failed", callback_data="a:orders:-1:0")
    kb.button(text="↩️ Refund", callback_data="a:orders:2:0")
    kb.button(text="📄 All", callback_data="a:orders:all:0")
    # orders buttons (2 cols)
    def st_icon(s:int):
        return {0:"🕓",1:"✅",-1:"❌",2:"↩️"}.get(int(s),"•")
    for o in orders:
        kb.button(text=f"{st_icon(o['status'])} #{o['id']} RM{o['amount_rm']:.0f}", callback_data=f"a:order:view:{o['id']}")
    # paging
    if has_prev:
        kb.button(text="⬅️ Prev", callback_data=f"a:orders:{status if status is not None else 'all'}:{page-1}")
    if has_next:
        kb.button(text="➡️ Next", callback_data=f"a:orders:{status if status is not None else 'all'}:{page+1}")
    kb.button(text="🔎 Search", callback_data="a:orders:search")
    kb.button(text="⬅️ Admin", callback_data="a:home")
    kb.adjust(5,2,2,2,2,2,2,2,2)  # flexible
    return kb.as_markup()

def kb_admin_template_actions():
    kb=InlineKeyboardBuilder()
    kb.button(text="✏️ Edit Template", callback_data="a:tpl:edit")
    kb.button(text="📣 Send Now", callback_data="a:tpl_send_now")
    kb.button(text="🗓️ Schedule", callback_data="a:tpl_schedule")
    kb.button(text="⬅️ Templates", callback_data="a:tpl:menu")
    kb.adjust(1,2,1)
    return kb.as_markup()


def kb_admin_health():
    # (legacy) kept for compatibility

    kb=InlineKeyboardBuilder()
    kb.button(text="🔄 Run Self-Check", callback_data="a:health:run")
    kb.button(text="↩️ Rollback Xray (Latest Backup)", callback_data="a:xray:rollback")
    kb.button(text="⬅️ Admin", callback_data="a:home")
    kb.adjust(1,1,1)
    return kb.as_markup()

def kb_admin_sched_list(page:int, jobs:list[dict], has_prev:bool, has_next:bool):
    kb=InlineKeyboardBuilder()
    for j in jobs:
        st = "⏳" if int(j.get("status",0))==0 else ("✅" if int(j.get("status",0))==1 else "🛑")
        try:
            run_at=datetime.fromisoformat(j["run_at"]) + timedelta(hours=8)
            label=run_at.strftime("%m-%d %H:%M")
        except Exception:
            label="?"
        kb.button(text=f"{st} #{j['id']} {j['target']} {label}", callback_data=f"a:sched:view:{j['id']}")
    if has_prev:
        kb.button(text="⬅️ Prev", callback_data=f"a:sched:list:{page-1}")
    if has_next:
        kb.button(text="➡️ Next", callback_data=f"a:sched:list:{page+1}")
    kb.button(text="➕ New Schedule", callback_data="a:sched:start")
    kb.button(text="⬅️ Campaign", callback_data="a:campaign")
    kb.adjust(2,2,2,2,2,2,2,2,2,2)
    return kb.as_markup()

def kb_admin_sched_detail(broadcast_id:int):
    kb=InlineKeyboardBuilder()
    kb.button(text="🧙 Edit Wizard", callback_data=f"a:schedwiz:edit:{broadcast_id}")
    kb.button(text="✏️ Edit Time", callback_data=f"a:sched:edit:{broadcast_id}")
    kb.button(text="🎯 Edit Target", callback_data=f"a:sched:edittarget:{broadcast_id}")
    kb.button(text="📝 Edit Text", callback_data=f"a:sched:edittext:{broadcast_id}")
    kb.button(text="🛑 Cancel", callback_data=f"a:sched:cancel:{broadcast_id}")
    kb.button(text="⬅️ Scheduled List", callback_data="a:sched:list:0")
    kb.adjust(2,2,1)
    return kb.as_markup()


def kb_admin_health_actions():
    kb=InlineKeyboardBuilder()
    kb.button(text="🔄 Run Self-Check", callback_data="a:health:run")
    kb.button(text="♻️ Restart Xray", callback_data="a:svc:ask:xray")
    kb.button(text="♻️ Restart Nginx", callback_data="a:svc:ask:nginx")
    kb.button(text="♻️ Restart HAProxy", callback_data="a:svc:ask:haproxy")
    kb.button(text="↩️ Rollback Xray (Latest Backup)", callback_data="a:xray:rollback")
    kb.button(text="⬅️ Admin", callback_data="a:home")
    kb.adjust(1,3,1,1)
    return kb.as_markup()

def kb_confirm_service(service:str):
    kb=InlineKeyboardBuilder()
    kb.button(text="✅ Yes, restart", callback_data=f"a:svc:do:{service}")
    kb.button(text="❌ Cancel", callback_data="a:health:run")
    kb.adjust(2)
    return kb.as_markup()

def kb_sched_target_picker(prefix:str="a:schedwiz:tgt"):
    kb=InlineKeyboardBuilder()
    kb.button(text="📣 ALL", callback_data=f"{prefix}:ALL")
    kb.button(text="🟢 LITE", callback_data=f"{prefix}:LITE")
    kb.button(text="🔵 PRO", callback_data=f"{prefix}:PRO")
    kb.button(text="🟣 RESELLER", callback_data=f"{prefix}:RESELLER")
    kb.button(text="⬅️ Cancel", callback_data="a:campaign")
    kb.adjust(2,2,1)
    return kb.as_markup()

def kb_sched_date_picker(prefix:str="a:schedwiz:date"):
    # next 7 days (MY)
    now=datetime.utcnow()+timedelta(hours=8)
    kb=InlineKeyboardBuilder()
    for i in range(0,7):
        d=(now+timedelta(days=i)).date()
        label=d.strftime("%a %d/%m")
        kb.button(text=label, callback_data=f"{prefix}:{d.isoformat()}")
    kb.button(text="⬅️ Back", callback_data="a:sched:list:0")
    kb.adjust(3,3,1,1)
    return kb.as_markup()

def kb_sched_time_picker(date_iso:str, prefix:str="a:schedwiz:time"):
    kb=InlineKeyboardBuilder()
    # hours 08-22, minutes fixed
    for h in range(8,23):
        kb.button(text=f"{h:02d}:00", callback_data=f"{prefix}:{date_iso}:{h:02d}:00")
        kb.button(text=f"{h:02d}:30", callback_data=f"{prefix}:{date_iso}:{h:02d}:30")
    kb.button(text="⬅️ Back", callback_data="a:schedwiz:back:date")
    kb.adjust(2,2,2,2,2,2,2,2,2,2,2,2,1)
    return kb.as_markup()

def kb_sched_text_source(prefix:str="a:schedwiz:textsrc"):
    kb=InlineKeyboardBuilder()
    kb.button(text="🧩 Use Template", callback_data=f"{prefix}:tpl")
    kb.button(text="✍️ Type Text", callback_data=f"{prefix}:type")
    kb.button(text="⬅️ Back", callback_data="a:schedwiz:back:time")
    kb.adjust(2,1)
    return kb.as_markup()

def kb_sched_template_picker(prefix:str="a:schedwiz:tpl"):
    kb=InlineKeyboardBuilder()
    kb.button(text="🔥 Promo", callback_data=f"{prefix}:promo")
    kb.button(text="🔔 Reminder", callback_data=f"{prefix}:reminder")
    kb.button(text="⚠️ Expiry 7D", callback_data=f"{prefix}:expiry7")
    kb.button(text="💳 Unpaid 30m", callback_data=f"{prefix}:unpaid30m")
    kb.button(text="💳 Unpaid 2h", callback_data=f"{prefix}:unpaid2h")
    kb.button(text="💳 Unpaid 24h", callback_data=f"{prefix}:unpaid24h")
    kb.button(text="⬅️ Back", callback_data="a:schedwiz:back:textsrc")
    kb.adjust(2,2,2,1)
    return kb.as_markup()

def kb_sched_confirm(prefix:str="a:schedwiz:confirm"):
    kb=InlineKeyboardBuilder()
    kb.button(text="✅ Confirm & Save", callback_data=f"{prefix}:yes")
    kb.button(text="❌ Cancel", callback_data="a:campaign")
    kb.adjust(2)
    return kb.as_markup()

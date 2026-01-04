from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import Optional
from datetime import datetime

DB_PATH = Path("data/bot.db")

def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize SQLite schema + lightweight migrations.

    This project evolves quickly; this function intentionally keeps migrations small and
    safe to run on every boot.
    """
    conn = _connect()
    cur = conn.cursor()

    # Use executescript because we create multiple tables at once.
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS users(
            tg_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id INTEGER NOT NULL,
            order_type TEXT NOT NULL,
            plan_code TEXT NOT NULL,
            amount_rm REAL NOT NULL,
            billcode TEXT,
            refno TEXT,
            status INTEGER NOT NULL DEFAULT 0,
            fulfilled INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            paid_at TEXT,
            meta_json TEXT
        );

        CREATE TABLE IF NOT EXISTS vpn_accounts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id INTEGER NOT NULL,
            plan_code TEXT NOT NULL,
            vless_uuid TEXT NOT NULL,
            vless_username TEXT NOT NULL,
            vless_link TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            suspended_until TEXT
        );

        CREATE TABLE IF NOT EXISTS resellers(
            tg_id INTEGER PRIMARY KEY,
            package_code TEXT NOT NULL,
            monthly_quota INTEGER NOT NULL,
            start_at TEXT NOT NULL,
            end_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS reseller_credits(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id INTEGER NOT NULL,
            ym TEXT NOT NULL,
            quota INTEGER NOT NULL,
            claimed INTEGER NOT NULL DEFAULT 0,
            released INTEGER NOT NULL DEFAULT 0,
            UNIQUE(tg_id, ym)
        );

        CREATE TABLE IF NOT EXISTS scheduled_broadcasts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target TEXT NOT NULL,
            text_html TEXT NOT NULL,
            run_at TEXT NOT NULL,
            status INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            sent_count INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS message_templates(
            key TEXT PRIMARY KEY,
            text_html TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS notice_log(
            key TEXT PRIMARY KEY,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS audit_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            kind TEXT NOT NULL,
            detail TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS settings_kv(
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS device_state(
            vless_username TEXT PRIMARY KEY,
            violation_count INTEGER NOT NULL DEFAULT 0,
            last_violation_ts TEXT,
            warned INTEGER NOT NULL DEFAULT 0
        );
        """
    )

    conn.commit()

    def col_exists(table: str, col: str) -> bool:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(r["name"] == col for r in rows)

    # migrations (keep in sync with schema definitions above)
    if not col_exists("orders", "fulfilled"):
        conn.execute("ALTER TABLE orders ADD COLUMN fulfilled INTEGER NOT NULL DEFAULT 0")
    if not col_exists("vpn_accounts", "status"):
        conn.execute("ALTER TABLE vpn_accounts ADD COLUMN status TEXT NOT NULL DEFAULT 'ACTIVE'")
    if not col_exists("vpn_accounts", "suspended_until"):
        conn.execute("ALTER TABLE vpn_accounts ADD COLUMN suspended_until TEXT")
    if not col_exists("reseller_credits", "released"):
        conn.execute("ALTER TABLE reseller_credits ADD COLUMN released INTEGER NOT NULL DEFAULT 0")

    conn.commit()
    conn.close()

def audit(kind:str, detail:str):
    conn=_connect()
    conn.execute("INSERT INTO audit_log(ts,kind,detail) VALUES(?,?,?)",
                 (datetime.utcnow().isoformat(), kind[:32], (detail or "")[:4000]))
    conn.commit(); conn.close()

def upsert_user(tg_id:int, username:Optional[str], first_name:Optional[str]):
    conn=_connect()
    conn.execute("""INSERT INTO users(tg_id,username,first_name,created_at)
        VALUES(?,?,?,?)
        ON CONFLICT(tg_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name
    """, (tg_id, username, first_name, datetime.utcnow().isoformat()))
    conn.commit(); conn.close()

def create_order(tg_id:int, order_type:str, plan_code:str, amount_rm:float, meta_json:str="") -> int:
    conn=_connect(); cur=conn.cursor()
    cur.execute("INSERT INTO orders(tg_id,order_type,plan_code,amount_rm,created_at,meta_json) VALUES(?,?,?,?,?,?)",
                (tg_id, order_type, plan_code, amount_rm, datetime.utcnow().isoformat(), meta_json))
    oid=cur.lastrowid
    conn.commit(); conn.close()
    return int(oid)

def get_order(oid:int) -> Optional[dict]:
    conn=_connect()
    row=conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    conn.close()
    return dict(row) if row else None

def set_order_bill(oid:int, billcode:str):
    conn=_connect()
    conn.execute("UPDATE orders SET billcode=? WHERE id=?", (billcode, oid))
    conn.commit(); conn.close()

def mark_order_by_bill(billcode:str, refno:str|None, amount_rm:float|None, status:int, reason:str|None) -> Optional[dict]:
    conn=_connect()
    row=conn.execute("SELECT * FROM orders WHERE billcode=?", (billcode,)).fetchone()
    if not row:
        conn.close(); return None
    paid_at = datetime.utcnow().isoformat() if status==1 else None
    meta=(row["meta_json"] or "") + f"\nCALLBACK refno={refno} status={status} reason={reason} amount={amount_rm}"
    conn.execute("UPDATE orders SET status=?, refno=?, paid_at=?, meta_json=? WHERE id=?",
                 (status, refno, paid_at, meta[:8000], row["id"]))
    conn.commit(); conn.close()
    return dict(row)

def fulfill_order_once(order_id:int) -> bool:
    conn=_connect(); cur=conn.cursor()
    cur.execute("UPDATE orders SET fulfilled=1 WHERE id=? AND fulfilled=0", (order_id,))
    conn.commit()
    ok = cur.rowcount==1
    conn.close()
    return ok

def list_orders(limit:int=20) -> list[dict]:
    conn=_connect()
    rows=conn.execute("SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def insert_vpn_account(tg_id:int, plan_code:str, vless_uuid:str, vless_username:str, vless_link:str, expires_at:str):
    conn=_connect()
    conn.execute("""INSERT INTO vpn_accounts(tg_id,plan_code,vless_uuid,vless_username,vless_link,created_at,expires_at,status)
        VALUES(?,?,?,?,?,?,?,'ACTIVE')""",
        (tg_id, plan_code, vless_uuid, vless_username, vless_link, datetime.utcnow().isoformat(), expires_at))
    conn.commit(); conn.close()

def set_vpn_status(vless_username:str, status:str):
    conn=_connect()
    conn.execute("UPDATE vpn_accounts SET status=? WHERE vless_username=?", (status, vless_username))
    conn.commit(); conn.close()

def find_account_by_username(vless_username:str) -> Optional[dict]:
    conn=_connect()
    row=conn.execute("SELECT * FROM vpn_accounts WHERE vless_username=? ORDER BY id DESC LIMIT 1", (vless_username,)).fetchone()
    conn.close()
    return dict(row) if row else None

def list_resellers() -> list[dict]:
    conn=_connect()
    rows=conn.execute("SELECT * FROM resellers ORDER BY tg_id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def upsert_reseller(tg_id:int, package_code:str, monthly_quota:int, start_at:str, end_at:str):
    conn=_connect()
    conn.execute("""INSERT INTO resellers(tg_id,package_code,monthly_quota,start_at,end_at)
        VALUES(?,?,?,?,?)
        ON CONFLICT(tg_id) DO UPDATE SET package_code=excluded.package_code, monthly_quota=excluded.monthly_quota,
        start_at=excluded.start_at, end_at=excluded.end_at""",
        (tg_id, package_code, monthly_quota, start_at, end_at))
    conn.commit(); conn.close()

def get_reseller(tg_id:int) -> Optional[dict]:
    conn=_connect()
    row=conn.execute("SELECT * FROM resellers WHERE tg_id=?", (tg_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def ensure_monthly_credit(tg_id:int, ym:str, quota:int) -> dict:
    conn=_connect()
    row=conn.execute("SELECT * FROM reseller_credits WHERE tg_id=? AND ym=?", (tg_id, ym)).fetchone()
    if row:
        conn.close(); return dict(row)
    conn.execute("INSERT INTO reseller_credits(tg_id,ym,quota,claimed,released) VALUES(?,?,?,0,0)", (tg_id, ym, quota))
    conn.commit()
    row=conn.execute("SELECT * FROM reseller_credits WHERE tg_id=? AND ym=?", (tg_id, ym)).fetchone()
    conn.close()
    return dict(row)

def get_credit(tg_id:int, ym:str) -> Optional[dict]:
    conn=_connect()
    row=conn.execute("SELECT * FROM reseller_credits WHERE tg_id=? AND ym=?", (tg_id, ym)).fetchone()
    conn.close()
    return dict(row) if row else None

def set_credit_released(tg_id:int, ym:str):
    conn=_connect()
    conn.execute("UPDATE reseller_credits SET released=1 WHERE tg_id=? AND ym=?", (tg_id, ym))
    conn.commit(); conn.close()

def add_claimed(tg_id:int, ym:str, n:int) -> dict:
    conn=_connect()
    conn.execute("UPDATE reseller_credits SET claimed=claimed+? WHERE tg_id=? AND ym=?", (n, tg_id, ym))
    conn.commit()
    row=conn.execute("SELECT * FROM reseller_credits WHERE tg_id=? AND ym=?", (tg_id, ym)).fetchone()
    conn.close()
    return dict(row)


def set_suspended_until(vless_username: str, until_iso: str|None):
    conn=_connect()
    conn.execute("UPDATE vpn_accounts SET suspended_until=? WHERE vless_username=?", (until_iso, vless_username))
    conn.commit(); conn.close()

def get_device_state(vless_username: str) -> dict:
    conn=_connect()
    row=conn.execute("SELECT * FROM device_state WHERE vless_username=?", (vless_username,)).fetchone()
    if not row:
        conn.execute("INSERT INTO device_state(vless_username, violation_count, last_violation_ts, warned) VALUES(?,0,NULL,0)", (vless_username,))
        conn.commit()
        row=conn.execute("SELECT * FROM device_state WHERE vless_username=?", (vless_username,)).fetchone()
    conn.close()
    return dict(row)

def set_device_state(vless_username: str, *, violation_count: int, last_violation_ts: str|None, warned: int):
    conn=_connect()
    conn.execute("UPDATE device_state SET violation_count=?, last_violation_ts=?, warned=? WHERE vless_username=?",
                 (violation_count, last_violation_ts, warned, vless_username))
    conn.commit(); conn.close()

def reset_device_state(vless_username: str):
    conn=_connect()
    conn.execute("UPDATE device_state SET violation_count=0, last_violation_ts=NULL, warned=0 WHERE vless_username=?", (vless_username,))
    conn.commit(); conn.close()

def list_suspended_due_for_unsuspend(now_iso: str) -> list[dict]:
    conn=_connect()
    rows=conn.execute(
        "SELECT * FROM vpn_accounts WHERE status='SUSPENDED' AND suspended_until IS NOT NULL AND suspended_until <= ? ORDER BY id DESC LIMIT 200",
        (now_iso,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_latest_active_account(tg_id: int, plan_code: str, now_iso: str) -> dict|None:
    """Return latest ACTIVE account for user+plan where expires_at > now."""
    conn=_connect()
    row=conn.execute(
        "SELECT * FROM vpn_accounts WHERE tg_id=? AND plan_code=? AND status='ACTIVE' AND expires_at > ? ORDER BY id DESC LIMIT 1",
        (tg_id, plan_code, now_iso)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# -------- Settings KV (DB override) --------
def get_setting(key: str, default: str) -> str:
    conn=_connect()
    row=conn.execute("SELECT value FROM settings_kv WHERE key=?", (key,)).fetchone()
    conn.close()
    return str(row["value"]) if row else default

def set_setting(key: str, value: str):
    conn=_connect()
    conn.execute(
        "INSERT INTO settings_kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value))
    )
    conn.commit(); conn.close()

# -------- Admin stats/helpers --------
def count_users() -> int:
    conn=_connect()
    row=conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
    conn.close()
    return int(row["c"]) if row else 0

def count_accounts(status: str|None=None, plan: str|None=None) -> int:
    conn=_connect()
    q="SELECT COUNT(DISTINCT vless_username) AS c FROM vpn_accounts WHERE 1=1"
    args=[]
    if status:
        q+=" AND status=?"; args.append(status)
    if plan:
        q+=" AND plan_code=?"; args.append(plan)
    row=conn.execute(q, tuple(args)).fetchone()
    conn.close()
    return int(row["c"]) if row else 0

def list_recent_orders(limit:int=20, status:int|None=None, offset:int=0) -> list[dict]:
    conn=_connect()
    q="SELECT * FROM orders"
    args=[]
    if status is not None:
        q += " WHERE status=?"
        args.append(int(status))
    q += " ORDER BY id DESC LIMIT ? OFFSET ?"
    args.extend([int(limit), int(offset)])
    rows=conn.execute(q, tuple(args)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_order_by_id(oid:int) -> dict|None:
    conn=_connect()
    row=conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    conn.close()
    return dict(row) if row else None

def list_accounts_by_tg(tg_id:int) -> list[dict]:
    conn=_connect()
    rows=conn.execute("SELECT * FROM vpn_accounts WHERE tg_id=? ORDER BY id DESC LIMIT 50", (tg_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def find_user_by_tg_or_username(q:str) -> dict|None:
    q=(q or "").strip()
    conn=_connect()
    row=None
    if q.isdigit():
        row=conn.execute("SELECT * FROM users WHERE tg_id=?", (int(q),)).fetchone()
    if not row:
        u=q.lstrip("@")
        row=conn.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", (u,)).fetchone()
    conn.close()
    return dict(row) if row else None

def update_account_plan(username:str, new_plan:str):
    conn=_connect()
    conn.execute("UPDATE vpn_accounts SET plan_code=? WHERE vless_username=?", (new_plan, username))
    conn.commit(); conn.close()

def update_account_expiry(username:str, new_expires_iso:str):
    conn=_connect()
    conn.execute("UPDATE vpn_accounts SET expires_at=? WHERE vless_username=?", (new_expires_iso, username))
    conn.commit(); conn.close()

def reset_device_state_by_username(username:str):
    reset_device_state(username)



# -------- Sales reports --------
def _utcnow():
    return datetime.utcnow()

def _ymd(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")

def sales_totals(start_iso: str, end_iso: str) -> dict:
    """Total paid revenue and count in [start,end)."""
    conn=_connect()
    row=conn.execute(
        "SELECT COALESCE(SUM(amount_rm),0) AS total_rm, COUNT(*) AS cnt FROM orders "
        "WHERE status=1 AND paid_at IS NOT NULL AND paid_at >= ? AND paid_at < ?",
        (start_iso, end_iso)
    ).fetchone()
    conn.close()
    return {"total_rm": float(row["total_rm"]), "cnt": int(row["cnt"])}

def sales_breakdown_by_plan(start_iso: str, end_iso: str) -> list[dict]:
    conn=_connect()
    rows=conn.execute(
        "SELECT plan_code, COALESCE(SUM(amount_rm),0) AS total_rm, COUNT(*) AS cnt "
        "FROM orders WHERE status=1 AND paid_at IS NOT NULL AND paid_at >= ? AND paid_at < ? "
        "GROUP BY plan_code ORDER BY total_rm DESC",
        (start_iso, end_iso)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def sales_last_n_days(n:int=14, tz_offset_hours:int=8) -> list[dict]:
    """Return list of days with totals in Malaysia-ish time (UTC+offset)."""
    # build day boundaries in UTC by subtracting offset
    now_utc=_utcnow()
    now_local = now_utc + timedelta(hours=tz_offset_hours)
    start_local = (now_local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=n-1))
    out=[]
    for i in range(n):
        d0_local = start_local + timedelta(days=i)
        d1_local = d0_local + timedelta(days=1)
        d0_utc = d0_local - timedelta(hours=tz_offset_hours)
        d1_utc = d1_local - timedelta(hours=tz_offset_hours)
        t=sales_totals(d0_utc.isoformat(), d1_utc.isoformat())
        out.append({"date": d0_local.strftime("%Y-%m-%d"), **t})
    return out

# -------- Export helpers --------
def export_orders_csv(limit:int=5000) -> str:
    conn=_connect()
    rows=conn.execute("SELECT * FROM orders ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
    conn.close()
    if not rows:
        return "id,created_at\n"
    cols=list(rows[0].keys())
    buf=io.StringIO()
    w=csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([r[c] for c in cols])
    return buf.getvalue()

def export_users_csv(limit:int=5000) -> str:
    conn=_connect()
    rows=conn.execute("SELECT * FROM users ORDER BY created_at DESC LIMIT ?", (int(limit),)).fetchall()
    conn.close()
    if not rows:
        return "tg_id,username,created_at\n"
    cols=list(rows[0].keys())
    buf=io.StringIO()
    w=csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([r[c] for c in cols])
    return buf.getvalue()

def export_resellers_csv(limit:int=5000) -> str:
    conn=_connect()
    rows=conn.execute(
        "SELECT r.tg_id, r.package_code, r.monthly_quota, r.start_at, r.end_at, "
        "COALESCE(u.username,'') AS username "
        "FROM resellers r LEFT JOIN users u ON u.tg_id=r.tg_id "
        "ORDER BY r.tg_id DESC LIMIT ?",
        (int(limit),)
    ).fetchall()
    conn.close()
    if not rows:
        return "tg_id,username,package_code,monthly_quota,start_at,end_at\n"
    cols=list(rows[0].keys())
    buf=io.StringIO()
    w=csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([r[c] for c in cols])
    return buf.getvalue()

# -------- Reseller admin helpers --------
def list_resellers_paged(limit:int=10, offset:int=0) -> list[dict]:
    conn=_connect()
    rows=conn.execute("SELECT * FROM resellers ORDER BY tg_id DESC LIMIT ? OFFSET ?", (int(limit), int(offset))).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_reseller(tg_id:int) -> dict|None:
    conn=_connect()
    row=conn.execute("SELECT * FROM resellers WHERE tg_id=?", (int(tg_id),)).fetchone()
    conn.close()
    return dict(row) if row else None

def upsert_reseller(tg_id:int, package_code:str, monthly_quota:int, start_at:str, end_at:str):
    conn=_connect()
    conn.execute(
        "INSERT INTO resellers(tg_id,package_code,monthly_quota,start_at,end_at) VALUES(?,?,?,?,?) "
        "ON CONFLICT(tg_id) DO UPDATE SET package_code=excluded.package_code, monthly_quota=excluded.monthly_quota, start_at=excluded.start_at, end_at=excluded.end_at",
        (int(tg_id), str(package_code), int(monthly_quota), str(start_at), str(end_at))
    )
    conn.commit(); conn.close()

def delete_reseller(tg_id:int):
    conn=_connect()
    conn.execute("DELETE FROM resellers WHERE tg_id=?", (int(tg_id),))
    conn.commit(); conn.close()

def get_credit(tg_id:int, ym:str) -> dict|None:
    conn=_connect()
    row=conn.execute("SELECT * FROM reseller_credits WHERE tg_id=? AND ym=?", (int(tg_id), str(ym))).fetchone()
    conn.close()
    return dict(row) if row else None

def set_credit_released(tg_id:int, ym:str):
    conn=_connect()
    conn.execute("UPDATE reseller_credits SET released=1 WHERE tg_id=? AND ym=?", (int(tg_id), str(ym)))
    conn.commit(); conn.close()



def export_orders_csv_filtered(paid_only: bool, start_iso: str|None=None, end_iso: str|None=None, limit:int=10000) -> str:
    conn=_connect()
    q="SELECT * FROM orders WHERE 1=1"
    args=[]
    if paid_only:
        q += " AND status=1 AND paid_at IS NOT NULL"
    if start_iso:
        q += " AND COALESCE(paid_at, created_at) >= ?"
        args.append(start_iso)
    if end_iso:
        q += " AND COALESCE(paid_at, created_at) < ?"
        args.append(end_iso)
    q += " ORDER BY id DESC LIMIT ?"
    args.append(int(limit))
    rows=conn.execute(q, tuple(args)).fetchall()
    conn.close()
    if not rows:
        return "id,created_at\n"
    cols=list(rows[0].keys())
    buf=io.StringIO()
    w=csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([r[c] for c in cols])
    return buf.getvalue()

def reseller_credits_last_months(tg_id:int, months:int=12) -> list[dict]:
    now_local=datetime.utcnow()+timedelta(hours=8)
    y=now_local.year; m=now_local.month
    yms=[]
    for i in range(months):
        mm=m - i
        yy=y
        while mm<=0:
            mm += 12
            yy -= 1
        yms.append(f"{yy:04d}-{mm:02d}")
    conn=_connect()
    rows=conn.execute(
        "SELECT * FROM reseller_credits WHERE tg_id=? AND ym IN (%s) ORDER BY ym DESC" % (",".join(["?"]*len(yms))),
        (int(tg_id), *yms)
    ).fetchall()
    conn.close()
    found={r["ym"]: dict(r) for r in rows}
    out=[]
    for ym in yms:
        r=found.get(ym) or {"tg_id": tg_id, "ym": ym, "quota": 0, "claimed": 0, "released": 0}
        out.append(r)
    return out


# -------- Orders helpers (filters/search/admin actions) --------
def list_orders_filtered(status: int|None=None, limit:int=10, offset:int=0) -> list[dict]:
    conn=_connect()
    if status is None:
        rows=conn.execute("SELECT * FROM orders ORDER BY id DESC LIMIT ? OFFSET ?", (int(limit), int(offset))).fetchall()
    else:
        rows=conn.execute("SELECT * FROM orders WHERE status=? ORDER BY id DESC LIMIT ? OFFSET ?", (int(status), int(limit), int(offset))).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def find_orders(query: str, limit:int=20) -> list[dict]:
    q=(query or "").strip()
    conn=_connect()
    rows=[]
    if q.isdigit():
        tg=int(q)
        rows=conn.execute("SELECT * FROM orders WHERE tg_id=? ORDER BY id DESC LIMIT ?", (tg, int(limit))).fetchall()
    else:
        # billcode/refno partial
        like=f"%{q}%"
        rows=conn.execute("SELECT * FROM orders WHERE billcode LIKE ? OR refno LIKE ? ORDER BY id DESC LIMIT ?", (like, like, int(limit))).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_order(order_id:int) -> dict|None:
    conn=_connect()
    row=conn.execute("SELECT * FROM orders WHERE id=?", (int(order_id),)).fetchone()
    conn.close()
    return dict(row) if row else None

def admin_mark_paid(order_id:int) -> dict|None:
    now=datetime.utcnow().isoformat()
    conn=_connect()
    row=conn.execute("SELECT * FROM orders WHERE id=?", (int(order_id),)).fetchone()
    if not row:
        conn.close(); return None
    conn.execute("UPDATE orders SET status=1, paid_at=? WHERE id=?", (now, int(order_id)))
    conn.commit()
    row2=conn.execute("SELECT * FROM orders WHERE id=?", (int(order_id),)).fetchone()
    conn.close()
    return dict(row2) if row2 else None

def set_order_status(order_id:int, status:int):
    conn=_connect()
    conn.execute("UPDATE orders SET status=? WHERE id=?", (int(status), int(order_id)))
    conn.commit(); conn.close()

# -------- Violators report --------
def top_violators(limit:int=20) -> list[dict]:
    conn=_connect()
    rows=conn.execute("SELECT vless_username, violation_count, last_violation_ts FROM device_state ORDER BY violation_count DESC LIMIT ?", (int(limit),)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# -------- Scheduled broadcasts --------
def add_scheduled_broadcast(target:str, text_html:str, run_at_iso:str) -> int:
    conn=_connect()
    now=datetime.utcnow().isoformat()
    cur=conn.execute(
        "INSERT INTO scheduled_broadcasts(target,text_html,run_at,status,created_at) VALUES(?,?,?,0,?)",
        (str(target), str(text_html), str(run_at_iso), now)
    )
    conn.commit()
    bid=int(cur.lastrowid)
    conn.close()
    return bid

def fetch_due_broadcasts(now_iso:str, limit:int=10) -> list[dict]:
    conn=_connect()
    rows=conn.execute(
        "SELECT * FROM scheduled_broadcasts WHERE status=0 AND run_at <= ? ORDER BY run_at ASC LIMIT ?",
        (str(now_iso), int(limit))
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def mark_broadcast_done(broadcast_id:int, sent_count:int):
    conn=_connect()
    conn.execute("UPDATE scheduled_broadcasts SET status=1, sent_count=? WHERE id=?", (int(sent_count), int(broadcast_id)))
    conn.commit(); conn.close()

# -------- Notice log (idempotent reminders) --------
def notice_once(key:str) -> bool:
    """Return True if key was inserted (first time), else False."""
    conn=_connect()
    try:
        conn.execute("INSERT INTO notice_log(key, created_at) VALUES(?,?)", (str(key), datetime.utcnow().isoformat()))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()

def expiring_accounts(within_days:int=7, limit:int=500) -> list[dict]:
    # expires_at stored in ISO; compare lexicographically OK
    now=datetime.utcnow()
    end=(now+timedelta(days=int(within_days))).isoformat()
    conn=_connect()
    rows=conn.execute(
        "SELECT * FROM vpn_accounts WHERE status=0 AND expires_at <= ? ORDER BY expires_at ASC LIMIT ?",
        (end, int(limit))
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_users_for_broadcast(target:str) -> list[dict]:
    target=(target or "ALL").upper()
    conn=_connect()
    if target=="ALL":
        rows=conn.execute("SELECT tg_id FROM users ORDER BY created_at DESC").fetchall()
    elif target in ("LITE","PRO"):
        rows=conn.execute(
            "SELECT DISTINCT u.tg_id FROM users u JOIN vpn_accounts a ON a.tg_id=u.tg_id "
            "WHERE a.plan_code=? AND a.status=0",
            (target,)
        ).fetchall()
    elif target=="RESELLER":
        rows=conn.execute("SELECT tg_id FROM resellers").fetchall()
    else:
        rows=conn.execute("SELECT tg_id FROM users ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def latest_account_for_user(tg_id:int) -> dict|None:
    conn=_connect()
    row=conn.execute("SELECT * FROM vpn_accounts WHERE tg_id=? ORDER BY created_at DESC LIMIT 1", (int(tg_id),)).fetchone()
    conn.close()
    return dict(row) if row else None


# -------- Message templates --------
def get_template(key:str) -> str|None:
    conn=_connect()
    row=conn.execute("SELECT text_html FROM message_templates WHERE key=?", (str(key),)).fetchone()
    conn.close()
    return row["text_html"] if row else None

def set_template(key:str, text_html:str):
    now=datetime.utcnow().isoformat()
    conn=_connect()
    conn.execute(
        "INSERT INTO message_templates(key,text_html,updated_at) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET text_html=excluded.text_html, updated_at=excluded.updated_at",
        (str(key), str(text_html), now)
    )
    conn.commit(); conn.close()

def list_active_resellers(now_iso:str|None=None, limit:int=2000) -> list[dict]:
    now_iso = now_iso or datetime.utcnow().date().isoformat()
    conn=_connect()
    rows=conn.execute(
        "SELECT * FROM resellers WHERE end_at >= ? ORDER BY tg_id DESC LIMIT ?",
        (str(now_iso), int(limit))
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# -------- Scheduled broadcasts admin helpers --------
def list_scheduled_broadcasts(status:int|None=0, limit:int=50, offset:int=0) -> list[dict]:
    conn=_connect()
    if status is None:
        rows=conn.execute("SELECT * FROM scheduled_broadcasts ORDER BY run_at ASC LIMIT ? OFFSET ?", (int(limit), int(offset))).fetchall()
    else:
        rows=conn.execute("SELECT * FROM scheduled_broadcasts WHERE status=? ORDER BY run_at ASC LIMIT ? OFFSET ?", (int(status), int(limit), int(offset))).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_scheduled_broadcast(broadcast_id:int) -> dict|None:
    conn=_connect()
    row=conn.execute("SELECT * FROM scheduled_broadcasts WHERE id=?", (int(broadcast_id),)).fetchone()
    conn.close()
    return dict(row) if row else None

def cancel_scheduled_broadcast(broadcast_id:int):
    conn=_connect()
    conn.execute("UPDATE scheduled_broadcasts SET status=2 WHERE id=?", (int(broadcast_id),))
    conn.commit(); conn.close()

def update_scheduled_broadcast_time(broadcast_id:int, run_at_iso:str):
    conn=_connect()
    conn.execute("UPDATE scheduled_broadcasts SET run_at=? WHERE id=?", (str(run_at_iso), int(broadcast_id)))
    conn.commit(); conn.close()

def pending_orders_older_than(min_age_minutes:int, limit:int=200) -> list[dict]:
    cutoff=(datetime.utcnow()-timedelta(minutes=int(min_age_minutes))).isoformat()
    conn=_connect()
    rows=conn.execute(
        "SELECT * FROM orders WHERE status=0 AND created_at <= ? AND billcode IS NOT NULL ORDER BY created_at ASC LIMIT ?",
        (cutoff, int(limit))
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_scheduled_broadcast_target(broadcast_id:int, target:str):
    conn=_connect()
    conn.execute("UPDATE scheduled_broadcasts SET target=? WHERE id=?", (str(target), int(broadcast_id)))
    conn.commit(); conn.close()

def update_scheduled_broadcast_text(broadcast_id:int, text_html:str):
    conn=_connect()
    conn.execute("UPDATE scheduled_broadcasts SET text_html=? WHERE id=?", (str(text_html), int(broadcast_id)))
    conn.commit(); conn.close()

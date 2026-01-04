from __future__ import annotations
from datetime import datetime, timedelta

PLAN_PRICE={"LITE":29.0,"PRO":49.0}
RESELLER_PRICE={"R_LITE":99.0,"R_PRO":149.0,"R_ELITE":249.0}
RESELLER_QUOTA={"R_LITE":5,"R_PRO":10,"R_ELITE":30}

def make_vless_username(tg_id:int, plan_code:str) -> str:
    return f"cfy{tg_id}_{plan_code}".lower()

def ym_now() -> str:
    return datetime.utcnow().strftime("%Y-%m")

def plan_amount(code:str)->float: return PLAN_PRICE[code]
def reseller_amount(code:str)->float: return RESELLER_PRICE[code]
def reseller_quota(code:str)->int: return RESELLER_QUOTA[code]

def reseller_period():
    start=datetime.utcnow()
    end=start+timedelta(days=365)
    return start.isoformat(), end.isoformat()


# -------- Upgrade conversion (Lite -> Pro) --------
LITE_YEAR_PRICE = 29.0
PRO_YEAR_PRICE = 49.0

def _per_day(price_year: float) -> float:
    return price_year / 365.0

def lite_to_pro_bonus_days(remaining_lite_days: int) -> int:
    """Convert remaining Lite value into bonus Pro days.
    bonus_days = floor( (remaining_lite_days * lite_day_rate) / pro_day_rate )
    """
    if remaining_lite_days <= 0:
        return 0
    lite_day = _per_day(LITE_YEAR_PRICE)
    pro_day = _per_day(PRO_YEAR_PRICE)
    bonus = int((remaining_lite_days * lite_day) // pro_day)
    return max(0, bonus)

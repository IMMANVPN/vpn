from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import httpx

@dataclass
class ToyyibPayConfig:
    secret_key: str
    category_code: str
    callback_url: str
    return_url: str

class ToyyibPayClient:
    BASE = "https://toyyibpay.com/index.php/api"
    def __init__(self, cfg: ToyyibPayConfig):
        self.cfg = cfg

    async def create_bill(self, *, bill_name:str, bill_desc:str, amount_rm:float, external_ref:str) -> str:
        amount_cent = int(round(amount_rm * 100))
        data = {
            "userSecretKey": self.cfg.secret_key,
            "categoryCode": self.cfg.category_code,
            "billName": bill_name[:30],
            "billDescription": bill_desc[:100],
            "billPriceSetting": "1",
            "billPayorInfo": "0",
            "billAmount": str(amount_cent),
            "billReturnUrl": self.cfg.return_url,
            "billCallbackUrl": self.cfg.callback_url,
            "billExternalReferenceNo": external_ref,
            "billPaymentChannel": "2",
        }
        async with httpx.AsyncClient(timeout=25) as client:
            r = await client.post(f"{self.BASE}/createBill", data=data)
            r.raise_for_status()
            j = r.json()
        billcode = j[0].get("BillCode") if isinstance(j, list) and j else None
        if not billcode:
            raise RuntimeError(f"ToyyibPay createBill failed: {j}")
        return str(billcode)

    async def get_transactions(self, billcode: str) -> list[dict]:
        async with httpx.AsyncClient(timeout=25) as client:
            r = await client.post(f"{self.BASE}/getBillTransactions", data={"billCode": billcode})
            r.raise_for_status()
            j = r.json()
        return j if isinstance(j, list) else []

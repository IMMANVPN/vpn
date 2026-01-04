from __future__ import annotations
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    BOT_TOKEN: str
    OWNER_TELEGRAM: str = "@abgdinur"

    PUBLIC_BASE_URL: str = "https://connectifyvpn.me"
    CALLBACK_TOKEN: str = Field(...)

    TOYYIBPAY_SECRET_KEY: str
    TOYYIBPAY_CATEGORY_CODE: str

    VLESS_ADDRESS: str = "104.17.147.22"
    VLESS_PORT: int = 80
    VLESS_HOST: str = "sv1.connectifyvpn.me"
    # Default ikut autoscript IMMANVPN (vless ws path biasa)
    VLESS_PATH: str = "/vlessws"

    XRAY_CONFIG_PATH: str = "/etc/xray/config.json"
    XRAY_RESTART_CMD: str = "systemctl restart xray"
    XRAY_ACCESS_LOG: str = "/var/log/xray/access.log"

    DEVICE_WINDOW_MINUTES: int = 30

    AUTO_UNSUSPEND_HOURS: int = 6

    AUTO_RELEASE_RESELLER: int = 1
    RESELLER_RELEASE_DAY: int = 1

    ADMIN_IDS: str = ""

    WEB_HOST: str = "127.0.0.1"
    WEB_PORT: int = 8080

    @property
    def admin_id_set(self) -> set[int]:
        ids=[]
        for x in (self.ADMIN_IDS or "").split(","):
            x=x.strip()
            if x:
                try: ids.append(int(x))
                except: pass
        return set(ids)

settings = Settings()

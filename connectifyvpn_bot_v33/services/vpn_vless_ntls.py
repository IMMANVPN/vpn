from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4


@dataclass
class VlessLinkConfig:
    address: str
    port: int
    host: str
    path: str


def build_vless_ws_ntls_link(uuid: str, username: str, cfg: VlessLinkConfig) -> str:
    """Build a VLESS WS Non-TLS link (standard query params).

    Nota:
    - Ini hanya bina link. Provision / insert user dilakukan oleh add_vless_user_to_xray_config.
    """
    path_enc = quote(cfg.path, safe="")
    return (
        f"vless://{uuid}@{cfg.address}:{cfg.port}"
        f"?encryption=none&flow=none&type=ws&host={cfg.host}"
        f"&headerType=none&path={path_enc}&security=none#{username}"
    )


def _validate_username(username: str) -> None:
    # IMMANVPN autoscript kebiasaannya accept: ^[a-zA-Z0-9_]+$
    # Kita longgarkan sikit tapi masih selamat.
    if not re.fullmatch(r"[a-zA-Z0-9_\-\.]{3,32}", username):
        raise ValueError("username invalid (3-32 chars a-zA-Z0-9_.-)")


def _backup_file(path: str) -> None:
    try:
        p = Path(path)
        if not p.exists():
            return
        ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        bak = p.with_suffix(p.suffix + f".bak.{ts}")
        bak.write_bytes(p.read_bytes())
    except Exception:
        # best-effort
        return


def _find_line_idx(lines: list[str], marker: str) -> int:
    """Find the first line index that ends with marker (sed-style '/MARKER$/')."""
    pat = re.compile(re.escape(marker) + r"\s*$")
    for i, ln in enumerate(lines):
        if pat.search(ln):
            return i
    return -1


def _insert_after_marker_lines(
    *,
    text: str,
    markers: list[str],
    insert_block: str,
) -> tuple[str, list[str]]:
    """Insert insert_block (multi-line str) after each marker line found.

    Returns: (new_text, used_markers)
    """
    lines = text.splitlines(True)  # keep line endings
    used: list[str] = []

    # We insert for each marker; each insertion will change indices, so do one marker at a time.
    for marker in markers:
        idx = _find_line_idx(lines, marker)
        if idx < 0:
            continue
        # Insert right after the marker line (same behavior as sed '/marker$/a\...')
        lines.insert(idx + 1, insert_block)
        used.append(marker)

    return "".join(lines), used


def _auto_markers(config_text: str) -> tuple[list[str], list[str]]:
    """Return (ws_markers, tls_markers) depending on what's present in config.

    IMMANVPN autoscript biasanya gunakan:
    - #vlessWS      (None TLS)
    - #vlessWSTLS   (TLS)
    Fallback:
    - #vless
    """
    # IMMANVPN templates usually:
    # - none-TLS marker: #vlessWS
    # - TLS marker:      #vlessWSTLS
    # Some other templates may only have a generic marker: #vless
    
    ws: list[str] = []
    tls: list[str] = []

    if "#vlessWS" in config_text:
        ws = ["#vlessWS"]
    elif "#vlessws" in config_text:
        ws = ["#vlessws"]
    elif "#vless" in config_text:
        ws = ["#vless"]

    if "#vlessWSTLS" in config_text:
        tls = ["#vlessWSTLS"]
    elif "#vlessTLS" in config_text:
        tls = ["#vlessTLS"]
    elif "#vlesstls" in config_text:
        tls = ["#vlesstls"]

    return ws, tls


def _to_exp_date(expire_date: str | None, *, days_default: int = 365) -> str:
    if expire_date:
        # accept YYYY-MM-DD only
        try:
            datetime.strptime(expire_date, "%Y-%m-%d")
            return expire_date
        except Exception as e:
            raise ValueError("expire_date must be YYYY-MM-DD") from e
    d = date.today() + timedelta(days=days_default)
    return d.isoformat()


def add_vless_user_to_xray_config(
    *,
    xray_config_path: str,
    restart_cmd: str,
    username: str,
    expire_date: str | None = None,
    also_add_tls: bool = True,
) -> str:
    """Insert a VLESS user into IMMANVPN-style Xray config.

    - Adds comment line:   #& <username> <YYYY-MM-DD>
    - Adds client line:    },{"id": "<uuid>","email": "<username>"
      (Note: no closing brace, matching IMMANVPN sed templates.)
    """
    _validate_username(username)
    uuid = str(uuid4())
    exp = _to_exp_date(expire_date)

    cfg_path = Path(xray_config_path)
    if not cfg_path.exists():
        raise FileNotFoundError(xray_config_path)

    txt = cfg_path.read_text(encoding="utf-8", errors="ignore")
    if re.search(rf"^#&\s+{re.escape(username)}\b", txt, flags=re.MULTILINE) or re.search(
        rf'"email"\s*:\s*"{re.escape(username)}"', txt
    ):
        raise RuntimeError("username already exists in xray config")

    ws_markers, tls_markers = _auto_markers(txt)
    if not ws_markers and not tls_markers:
        # For strictness, mirror original behavior
        raise RuntimeError("No suitable VLESS marker found in xray config")

    insert_block = f"#& {username} {exp}\n}},{{\"id\": \"{uuid}\",\"email\": \"{username}\"\n"

    new_txt, used = _insert_after_marker_lines(text=txt, markers=ws_markers, insert_block=insert_block)

    if also_add_tls and tls_markers:
        new_txt, used_tls = _insert_after_marker_lines(text=new_txt, markers=tls_markers, insert_block=insert_block)
        used.extend([m for m in used_tls if m not in used])

    if not used:
        raise RuntimeError("Marker present check passed but insert failed")

    _backup_file(xray_config_path)
    cfg_path.write_text(new_txt, encoding="utf-8")
    # restart
    subprocess.run(restart_cmd.split(), check=True)
    return uuid


def remove_vless_user_from_xray_config(*, xray_config_path: str, restart_cmd: str, username: str) -> None:
    """Remove a VLESS user from IMMANVPN-style Xray config.

    We mimic the autoscript deletion style:
    - delete range from '^#& <user> <exp>' until next line starting with '^},{'
    - also best-effort remove any stray '"email": "<user>"' line.
    """
    _validate_username(username)
    cfg_path = Path(xray_config_path)
    if not cfg_path.exists():
        raise FileNotFoundError(xray_config_path)

    txt = cfg_path.read_text(encoding="utf-8", errors="ignore")
    lines = txt.splitlines(True)

    out: list[str] = []
    deleting = False
    removed_any = False

    # Match any exp date (YYYY-MM-DD) because connectify stores expiry separately.
    start_re = re.compile(rf"^#&\s+{re.escape(username)}\s+\d{{4}}-\d{{2}}-\d{{2}}\s*$")
    end_re = re.compile(r"^},{")
    email_re = re.compile(rf'"email"\s*:\s*"{re.escape(username)}"')

    for ln in lines:
        if deleting:
            if end_re.search(ln):
                deleting = False
                removed_any = True
                # skip this end line too
                continue
            removed_any = True
            continue

        if start_re.search(ln):
            deleting = True
            removed_any = True
            continue

        # Extra cleanup (for config variants)
        if email_re.search(ln):
            removed_any = True
            continue

        out.append(ln)

    if not removed_any:
        raise RuntimeError("email not found in config")

    new_txt = "".join(out)
    _backup_file(xray_config_path)
    cfg_path.write_text(new_txt, encoding="utf-8")
    subprocess.run(restart_cmd.split(), check=True)


def parse_recent_ips_from_access_log(access_log_path: str, email: str, window_minutes: int) -> set[str]:
    ips: set[str] = set()
    now = datetime.utcnow()

    ts_re = re.compile(r"^(\d{4})/(\d{2})/(\d{2})\s+(\d{2}):(\d{2}):(\d{2})")
    ip_re = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")
    email_re = re.compile(rf"\b{re.escape(email)}\b")

    try:
        with open(access_log_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 524288))
            data = f.read().decode("utf-8", errors="ignore")
    except FileNotFoundError:
        return set()

    for line in data.splitlines()[::-1]:
        if not email_re.search(line):
            continue
        m = ts_re.search(line)
        if m:
            dt = datetime(
                int(m.group(1)),
                int(m.group(2)),
                int(m.group(3)),
                int(m.group(4)),
                int(m.group(5)),
                int(m.group(6)),
            )
            if now - dt > timedelta(minutes=window_minutes):
                break
        found = ip_re.findall(line)
        if found:
            ips.add(found[0])
        if len(ips) >= 5:
            break

    return ips

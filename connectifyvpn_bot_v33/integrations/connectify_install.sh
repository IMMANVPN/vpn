#!/usr/bin/env bash
#
# Installer ConnectifyVPN bot (v33) + integrasi menu IMMANVPN
#
# Apa yang script ini buat:
# 1) Salin code connectify ke /opt/connectifyvpn_bot
# 2) Setup Python venv + install requirements
# 3) Create systemd service: connectifyvpn-bot.service
# 4) (Opsyenal) Pasang wrapper `installbot` ke /usr/local/bin/installbot
#    supaya menu autoscript utama boleh ON/OFF 2 bot.
#
# Nota:
# - Script ini tidak ubah sebarang code autoscript VPN utama.
# - Kalau anda nak revert, padam /usr/local/bin/installbot (wrapper) untuk guna semula /usr/bin/installbot.
#
set -euo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Sila jalankan sebagai root." >&2
  exit 1
fi

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="/opt/connectifyvpn_bot"
VENV_DIR="${INSTALL_DIR}/venv"
SERVICE_NAME="connectifyvpn-bot.service"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}"

echo "[1/5] Salin fail ke ${INSTALL_DIR} ..."
mkdir -p "$INSTALL_DIR"

# Guna rsync kalau ada, fallback ke cp -a
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete \
    --exclude '__pycache__' --exclude '*.pyc' \
    "${SRC_DIR}/" "${INSTALL_DIR}/"
else
  rm -rf "${INSTALL_DIR:?}/"*
  cp -a "${SRC_DIR}/." "$INSTALL_DIR/"
fi

echo "[2/5] Setup virtualenv ..."
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 tak jumpa. Sila install python3 dahulu." >&2
  exit 1
fi

if [[ ! -d "$VENV_DIR" ]]; then
  python3 -m venv "$VENV_DIR"
fi

"${VENV_DIR}/bin/pip" install --upgrade pip setuptools wheel
"${VENV_DIR}/bin/pip" install -r "${INSTALL_DIR}/requirements.txt"

echo "[3/5] Sediakan .env ..."
NEW_ENV_CREATED=0
if [[ ! -f "${INSTALL_DIR}/.env" ]]; then
  cp "${INSTALL_DIR}/.env.example" "${INSTALL_DIR}/.env"
  NEW_ENV_CREATED=1
  echo "✅ .env created: ${INSTALL_DIR}/.env"
  echo "   Sila edit BOT_TOKEN, CALLBACK_TOKEN, TOYYIB_* dan setting VLESS/XRAY ikut server anda."
fi

# Auto-detect xray/v2ray (hanya jika .env baru dicipta)
if [[ "$NEW_ENV_CREATED" -eq 1 ]]; then
  if [[ -f /etc/xray/config.json ]]; then
    sed -i 's|^XRAY_CONFIG_PATH=.*$|XRAY_CONFIG_PATH=/etc/xray/config.json|g' "${INSTALL_DIR}/.env" || true
    sed -i 's|^XRAY_RESTART_CMD=.*$|XRAY_RESTART_CMD=systemctl restart xray|g' "${INSTALL_DIR}/.env" || true
  elif [[ -f /etc/v2ray/config.json ]]; then
    sed -i 's|^XRAY_CONFIG_PATH=.*$|XRAY_CONFIG_PATH=/etc/v2ray/config.json|g' "${INSTALL_DIR}/.env" || true
    sed -i 's|^XRAY_RESTART_CMD=.*$|XRAY_RESTART_CMD=systemctl restart v2ray|g' "${INSTALL_DIR}/.env" || true
  fi
fi

echo "[4/5] Create systemd service (${SERVICE_NAME}) ..."
cat > "$SERVICE_PATH" <<EOF
[Unit]
Description=ConnectifyVPN Telegram Bot (FastAPI + aiogram)
After=network.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
ExecStart=${VENV_DIR}/bin/python ${INSTALL_DIR}/app.py
Restart=always
RestartSec=3

# Bot ini perlu baca/tulis XRAY config + restart service.
User=root

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload

echo "[5/5] Pasang wrapper installbot (integrasi menu) ..."
WRAPPER_SRC="${INSTALL_DIR}/integrations/installbot"
WRAPPER_DST="/usr/local/bin/installbot"
if [[ -f "$WRAPPER_SRC" ]]; then
  install -m 0755 "$WRAPPER_SRC" "$WRAPPER_DST"
  echo "✅ Wrapper dipasang: $WRAPPER_DST"
else
  echo "⚠️  Wrapper tak jumpa: $WRAPPER_SRC" >&2
fi

echo
echo "Selesai ✅"
echo "- Untuk start bot ConnectifyVPN:  systemctl enable --now ${SERVICE_NAME}"
echo "- Untuk stop  bot ConnectifyVPN:  systemctl disable --now ${SERVICE_NAME}"
echo "- Dalam menu autoscript, pergi Bot-Panel (installbot) untuk ON/OFF kedua-dua bot."

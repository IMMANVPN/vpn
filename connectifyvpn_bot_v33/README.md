# ConnectifyVPN Store Bot v2 (VLESS NTLS + ToyyibPay Callback)
Upgrade v2 termasuk:
1) Device-limit enforcement (Lite 1 device, Pro 2 device) menggunakan *Access Log IP heuristic* + auto-suspend.
2) Reseller auto-release bulanan (auto-generate ID ikut quota dan hantar ke reseller pada awal bulan).
3) Admin panel (dashboard, orders, search, suspend/unsuspend, renew, broadcast, reseller management).
4) Hardening (idempotent callback, rate-limit callback, audit log, validate amount).

> Nota: Device-limit untuk WS/NTLS tidak 100% “lock”. Implementasi ini guna bacaan `access.log` Xray untuk kesan IP aktif.
> Anda boleh adjust `DEVICE_WINDOW_MINUTES` atau disable scan jika perlu.

## Setup
1. `cp .env.example .env` dan isi nilai
2. `pip install -r requirements.txt`
3. Run:
```bash
python app.py
```

## Endpoint callback
ToyyibPay akan POST ke:
`POST https://DOMAIN/toyyibpay/callback?token=CALLBACK_TOKEN`

## Xray requirement
- `/etc/xray/config.json` mesti ada marker `#vlessWS` (dan jika ada TLS list: `#vlessWSTLS`).
  - Fallback: bot juga boleh guna marker `#vless` jika itu sahaja yang wujud.
- access log diaktifkan (default `/var/log/xray/access.log`)


## v2.1 Updates
- Device limit: warn pada scan #2, suspend pada scan #3 (consecutive)
- Auto-unsuspend: cuba aktif semula selepas `AUTO_UNSUSPEND_HOURS` (default 6 jam) dan hantar link baru
- Upgrade prompt: butang upgrade ke Pro muncul pada warning/suspend/unsuspend

- Upgrade Lite -> Pro: bot tunjuk preview baki hari + bonus Pro days, dan callback extend Pro validity ikut bonus.


## Admin Panel (Inline Premium)
Semua fungsi admin guna inline buttons + input message (tanpa command).
Menu: Dashboard, Orders, Users/Accounts (suspend/unsuspend/renew/regen/switch/reset), Settings (window & auto-unsuspend), Broadcast.


## Sales Report + Export CSV + Reseller Panel
Admin: Sales Report (today/month + breakdown + last 14 days), Export CSV (orders/users/resellers), Reseller Panel full (list/find/add/edit/remove/credits/manual release).


## v2.5 Admin Upgrades
- Sales report toggle 7/14/30 hari.
- Export menu: orders all, paid this month, paid custom range.
- Reseller credits 12 months view.


## v2.6 Admin Upgrades
- Export Orders By Plan (paid).
- Export Orders By Month (paid, Malaysia time).
- Reseller release month picker (12 months).


## v2.7 Admin Full Pack
- Orders: filters (pending/paid/failed/refund), search by billcode/refno/TG id, order detail actions, admin mark paid + fulfill.
- Device enforcement: threshold configurable, auto-unsuspend toggle, top violators.
- Campaign: templates, scheduled broadcast, auto expiry reminder 7 days (daily 09:00 MY).


## v2.8 Premium Admin UX
- Orders: click-to-open detail (no reply needed).
- Templates: editable + saved in DB.
- Reseller: auto-release monthly (Day 1, ~00:00-00:20 MY) idempotent.


## v2.9 Upgrade Pack (Padu)
- Health: self-check report + admin rollback latest xray backup.
- Xray: auto backup before modify + rollback on failure.
- Campaign: scheduled broadcast list + view/cancel/edit time.
- Automation: auto unpaid follow-up (30m/2h/24h).


## v3.0 Premium Pack
- Health: probes /vless with latency (127.0.0.1:80 & :1010).
- Scheduled broadcasts: edit target + edit text.
- Unpaid follow-ups: customizable templates (unpaid30m/unpaid2h/unpaid24h) stored in DB.


## v3.1 Wizard + Service Actions
- Campaign: schedule wizard (no typing format). Target/date/time pickers + template or typed text + confirm.
- Health: restart services with confirm dialog (xray/nginx/haproxy).


## v3.2
- Scheduled jobs: Edit Wizard (target/date/time/text) fully inline.
- Health: Restart xray prefers settings.XRAY_RESTART_CMD.

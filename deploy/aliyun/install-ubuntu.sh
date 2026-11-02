#!/usr/bin/env bash
# Initial private installation; the application only listens on loopback.
set -euo pipefail
if [[ ${EUID} -ne 0 ]]; then
  echo '请使用 sudo bash deploy/install-ubuntu.sh 运行。' >&2
  exit 1
fi
. /etc/os-release
if [[ ${ID} != ubuntu || ${VERSION_ID} != 24.04 ]]; then
  echo '此安装程序仅用于 Ubuntu 24.04。' >&2
  exit 1
fi
bundle=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if [[ -e /opt/shiti || -e /var/lib/shiti || -e /etc/systemd/system/shiti.service ]]; then
  echo '检测到已有拾题目录或服务，已停止安装，避免覆盖学习记录。' >&2
  exit 1
fi
[[ -f "$bundle/app/server.py" && -f "$bundle/deploy/requirements.txt" ]]
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3-venv ca-certificates curl
if ! id shiti >/dev/null 2>&1; then
  useradd --system --user-group --home-dir /var/lib/shiti --shell /usr/sbin/nologin shiti
fi
install -d -m 755 /opt/shiti
install -d -m 700 -o shiti -g shiti /var/lib/shiti
cp -a "$bundle/app" /opt/shiti/app
if [[ -d "$bundle/sources" ]]; then cp -a "$bundle/sources" /opt/shiti/sources; fi
python3 -m venv /opt/shiti/venv
/opt/shiti/venv/bin/python -m pip install -r "$bundle/deploy/requirements.txt"
install -m 644 "$bundle/deploy/backup.py" /opt/shiti/backup.py
cat > /etc/systemd/system/shiti.service <<'EOF'
[Unit]
Description=Shiti private study website
After=network.target

[Service]
Type=simple
User=shiti
Group=shiti
WorkingDirectory=/opt/shiti/app
Environment=CUOTI_DATA_DIR=/var/lib/shiti
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=/opt/shiti/venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port 8765 --workers 1 --no-proxy-headers
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/var/lib/shiti

[Install]
WantedBy=multi-user.target
EOF
cat > /etc/systemd/system/shiti-backup.service <<'EOF'
[Unit]
Description=Online SQLite backup for Shiti
After=shiti.service

[Service]
Type=oneshot
User=shiti
Group=shiti
UMask=0077
ExecStart=/opt/shiti/venv/bin/python /opt/shiti/backup.py /var/lib/shiti
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/shiti
EOF
cat > /etc/systemd/system/shiti-backup.timer <<'EOF'
[Unit]
Description=Daily Shiti backup at 04:00 Beijing time

[Timer]
OnCalendar=*-*-* 04:00:00 Asia/Shanghai
Persistent=true

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now shiti.service
ready=0
for attempt in {1..30}; do
  if curl --fail --silent --output /dev/null http://127.0.0.1:8765/api/library; then
    ready=1
    break
  fi
  sleep 1
done
if [[ $ready != 1 ]]; then
  echo '服务未正常启动，请查看：sudo journalctl -u shiti -n 60 --no-pager' >&2
  exit 1
fi
systemctl enable --now shiti-backup.timer
systemctl start shiti-backup.service
echo '安装完成：服务仅监听本机 127.0.0.1:8765。请使用 SSH 隧道预览。'
echo '当前是空白学习记录；请在网页“备份与恢复”中导入你的备份。'

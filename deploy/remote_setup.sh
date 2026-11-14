#!/usr/bin/env bash
# 远端安装脚本：由 deploy.sh 上传到服务器后执行（最小侵入，DESIGN 8.9）。
# 用法: bash remote_setup.sh <DEPLOY_DIR> <APP_PORT> <JWT_SECRET> <FLASK_SECRET> [PIP_INDEX] [--update]
# 说明: JWT/FLASK 密钥是应用自身的随机凭据（非 SSH 登录密码），写入用户级 unit 文件。
set -euo pipefail

DIR="$1"; PORT="$2"; JWT="$3"; SK="$4"; IDX="${5:-}"; UPDATE="${6:-}"
VENV="$DIR/.venv"

[ -d "$VENV" ] || python3 -m venv "$VENV"
echo "installing deps..."
"$VENV/bin/pip" install -q ${IDX:+-i "$IDX"} -r "$DIR/requirements.txt"

# ── 用户级 systemd unit（不动系统目录）────────────────────────
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"
umask 077
cat > "$UNIT_DIR/vanilla-editor.service" <<EOF
[Unit]
Description=VanillaEditor
After=network.target

[Service]
WorkingDirectory=$DIR
ExecStart=$VENV/bin/gunicorn -w 2 -b 0.0.0.0:$PORT run:app
Restart=on-failure
Environment=PATH=$VENV/bin:/usr/bin:/bin
Environment=DATA_DIR=$DIR/data
Environment=PORT=$PORT
Environment=JWT_SECRET=$JWT
Environment=SECRET_KEY=$SK
Environment=VE_REQUIRE_SECRET=1

[Install]
WantedBy=default.target
EOF
umask 022

export XDG_RUNTIME_DIR="/run/user/$(id -u)"
MGR=""
if systemctl --user daemon-reload 2>/dev/null \
   && systemctl --user restart vanilla-editor 2>/dev/null \
   && systemctl --user enable vanilla-editor 2>/dev/null; then
  MGR="systemd-user"
else
  # crontab @reboot 兜底（用户自己的 crontab，不动系统目录）
  CRON_LINE="@reboot env DATA_DIR=$DIR/data PORT=$PORT JWT_SECRET=$JWT SECRET_KEY=$SK VE_REQUIRE_SECRET=1 $VENV/bin/gunicorn -w 2 -b 0.0.0.0:$PORT run:app >> $DIR/gunicorn.log 2>&1"
  ( crontab -l 2>/dev/null | grep -v vanilla-editor || true; echo "$CRON_LINE" ) | crontab -
  pkill -f "gunicorn.*:.*$PORT" 2>/dev/null || true
  sleep 1
  ( cd "$DIR" && nohup env DATA_DIR="$DIR/data" PORT=$PORT JWT_SECRET=$JWT SECRET_KEY=$SK \
      VE_REQUIRE_SECRET=1 "$VENV/bin/gunicorn" -w 2 -b "0.0.0.0:$PORT" run:app \
      >> "$DIR/gunicorn.log" 2>&1 & )
  MGR="crontab"
fi

sleep 3
CODE=$(curl -s -m 5 -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/api/public/config" || true)
echo "manager=$MGR selfcheck=$CODE dir=$DIR port=$PORT"
[ "$CODE" = "200" ] || { echo "自检失败，查看日志: $DIR/gunicorn.log 或 journalctl --user -u vanilla-editor"; exit 1; }
echo "OK: http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo '<server-ip>'):$PORT"

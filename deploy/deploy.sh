#!/usr/bin/env bash
# VanillaEditor 一键部署（最小侵入部署，DESIGN 8.9）：
#   - 不安装任何系统级包；缺依赖时探测报告并停止
#   - 不改防火墙/现有服务；全部文件只进部署目录（进程管理仅用户级 systemd 或 crontab）
#   - SSH 凭据仅经环境变量传给 remote_exec.py，不写入任何文件
#
# 用法:
#   export TARGET_HOST=<服务器IP> SSH_USER=<用户> [SSH_PASS=<密码>]   # SSH_PASS 可选，缺省走 SSH key
#   export DEPLOY_DIR=/mnt/sdcard/pro/VanillaEditor APP_PORT=58446 PIP_INDEX=<镜像可选>
#   deploy/deploy.sh            # 完整部署
#   deploy/deploy.sh --probe    # 仅只读探测
#   deploy/deploy.sh --update   # 更新代码并重启（保留 data/ 与工作区）
set -euo pipefail

TARGET_HOST="${TARGET_HOST:?请 export TARGET_HOST=<服务器IP>}"
SSH_USER="${SSH_USER:?请 export SSH_USER=<登录用户>}"
SSH_PASS="${SSH_PASS:-}"
DEPLOY_DIR="${DEPLOY_DIR:-/mnt/sdcard/pro/VanillaEditor}"
APP_PORT="${APP_PORT:-58446}"
BRANCH="${BRANCH:-develop}"
PIP_INDEX="${PIP_INDEX:-}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"

PY="${VE_DEPLOY_PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || PY="python"
"$PY" -c "import paramiko" 2>/dev/null || {
  echo "本机 python 缺少 paramiko：请先执行 pip install paramiko"; exit 1; }
export TARGET_HOST SSH_USER SSH_PASS

r() { REMOTE_CMD="$1" "$PY" "$HERE/remote_exec.py" exec; }
p() { LOCAL_PATH="$1" REMOTE_PATH="$2" "$PY" "$HERE/remote_exec.py" put; }

echo "== [1/4] 只读探测（不做任何改动）=="
r "echo '--- 系统/依赖 ---'; uname -srm; python3 --version 2>&1; git --version 2>&1; \
   python3 -m venv --help >/dev/null 2>&1 && echo 'venv: OK' || echo 'venv: MISSING(需 python3-venv)'; \
   sudo -n true 2>/dev/null && echo 'sudo: 免密可用' || echo 'sudo: 不可用(linger 跳过,自启用 crontab)'; \
   echo '--- 端口/目录 ---'; \
   (ss -tln 2>/dev/null || netstat -tln 2>/dev/null) | grep -q \":${APP_PORT} \" && echo \"port ${APP_PORT}: 已被占用!\" || echo \"port ${APP_PORT}: 空闲\"; \
   [ -d '$DEPLOY_DIR' ] && echo 'deploy dir: 已存在' || echo 'deploy dir: 不存在(将创建)'; \
   df -h '$DEPLOY_DIR' 2>/dev/null | tail -1 || df -h / | tail -1"

MODE="${1:-deploy}"
if [ "$MODE" = "--probe" ]; then echo "探测完成（仅探测模式退出）"; exit 0; fi

echo "== [2/4] 打包并上传代码 =="
gen_secret() { "$PY" -c "import secrets; print(secrets.token_hex(32))"; }
JWT_SECRET_VAL=$(gen_secret)
FLASK_SECRET_VAL=$(gen_secret)

# 打包到项目目录（Windows 下 /tmp 路径对 python 进程不可见；.gitignore 已排除）
TMP_TAR="$ROOT/_ve_deploy.tar.gz"
git -C "$ROOT" archive "$BRANCH" -o "$TMP_TAR"
r "mkdir -p '$DEPLOY_DIR/data' '$DEPLOY_DIR/workspaces' '$DEPLOY_DIR/repos'"
p "$TMP_TAR" "$DEPLOY_DIR/_ve_deploy.tar.gz"
p "$HERE/remote_setup.sh" "$DEPLOY_DIR/remote_setup.sh"
rm -f "$TMP_TAR"

echo "== [3/4] 远端解压并安装（venv + gunicorn + 用户级服务）=="
UPDATE_FLAG=""; [ "$MODE" = "--update" ] && UPDATE_FLAG="--update"
r "tar xzf '$DEPLOY_DIR/_ve_deploy.tar.gz' -C '$DEPLOY_DIR' && rm -f '$DEPLOY_DIR/_ve_deploy.tar.gz' && \
   bash '$DEPLOY_DIR/remote_setup.sh' '$DEPLOY_DIR' '$APP_PORT' '$JWT_SECRET_VAL' '$FLASK_SECRET_VAL' '${PIP_INDEX}' '$UPDATE_FLAG'"

echo "== [4/4] 完成 =="
echo "访问: http://$TARGET_HOST:$APP_PORT"
echo "后续: 浏览器打开上方地址注册账号 → 打开工作区（workspaces/ 下）→ 设置页开启远程访问"

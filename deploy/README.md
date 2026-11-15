# VanillaEditor 部署手册（最小侵入）

面向共享服务器 / ARM 设备（orange pi 等）的自用部署。设计依据：DESIGN.md 第 8 章。

## 前置条件（服务器）

| 依赖 | 要求 | 缺失时 |
|------|------|--------|
| Python | 3.10+（含 `python3-venv`） | **停止部署并报告**，由服务器管理员安装，脚本不擅自装系统包 |
| Git | 2.30+ | 同上 |
| 网络 | pip 可达 PyPI 或自配镜像 | 脚本支持 `PIP_INDEX` 指定国内镜像 |

不改动：防火墙规则、现有服务与端口、系统目录。全部项目文件只进部署目录；进程管理仅用用户级 systemd（`~/.config/systemd/user/`）或用户 crontab（`@reboot` 兜底）。

## 快速部署

本机（Windows 需先 `pip install paramiko` 到 venv）：

```bash
export TARGET_HOST=192.168.x.x          # 服务器地址
export SSH_USER=<登录用户>
export SSH_PASS=<登录密码>               # 可选；缺省走 SSH key。仅运行时使用，不写入任何文件
export DEPLOY_DIR=/mnt/sdcard/pro/VanillaEditor
export APP_PORT=58446
export PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple   # 可选

deploy/deploy.sh --probe    # 只读探测（推荐先跑）
deploy/deploy.sh            # 完整部署
deploy/deploy.sh --update   # 更新代码并重启（保留 data/ 与工作区）
```

部署脚本自动完成：创建目录 → `git archive` 打包上传 → venv + pip → 生成随机 `JWT_SECRET`/`SECRET_KEY`（应用密钥，写入用户级 unit，权限 600）→ 用户级 systemd 启动（失败自动退 crontab `@reboot` + nohup）→ **预配置远程访问**（生成 6 位访问码并打印；账号不预建，由你浏览器注册）→ 本机自检 `GET /api/public/config`。

**部署后两个关键手动步骤**（脚本会打印提示）：

1. **常驻自启**：用户级 systemd 在 SSH 会话断开后会停止服务（无 linger 时）。执行
   `sudo loginctl enable-linger <部署用户>` —— 否则每次重启/断连后需要重新 SSH 登录拉起服务
2. **防火墙放行**：若服务器启用 ufw/nftables，默认拦截新端口。执行
   `sudo ufw allow from <局域网网段> to any port 58446 proto tcp comment 'VanillaEditor'`
   （建议限定局域网来源，与既有规则风格一致）

## 目录结构（部署目录）

```
VanillaEditor/
├── .venv/            # Python 虚拟环境
├── app/ static/ run.py requirements.txt   # 代码（git archive 产出）
├── data/             # 用户数据（users.json、remote_access.json 等，首次启动自动生成）
├── workspaces/       # 写作工作区（原地模式，每目录一个 .git 仓库）
├── repos/            # 预留：bare 同步仓库
├── remote_setup.sh   # 远端安装脚本（部署后可删）
└── gunicorn.log      # crontab 兜底模式下的运行日志
```

## 数据迁移（从旧实例迁入）

1. **工作区**：旧机器工作区目录整体打包（含 `.git`，`.ve/` 会随包但首次打开时 v0.4.0 自动迁移出库），解压到部署目录 `workspaces/<名称>/`
2. **账号**（可选）：旧机器 `data/users.json` 拷到部署目录 `data/`，bcrypt 哈希可直接登录（DESIGN 8.6-1）；全新部署则跳过，浏览器注册即可
3. `remote_access.json` 不迁移——在服务器上重新开启远程访问（重新生成访问码）

## 部署后配置（浏览器 http://<服务器IP>:58446）

1. 注册你的账号（登录页"还没有账号？点击注册"）
2. 打开工作区：资源管理器 → 打开工作区 → 选择 `workspaces/<名称>`（已有 `.git` 直接复用，历史保留）
3. 设置页 → 网络和安全 → 开启远程访问（首次需先设置认证口令）→ 把生成的访问码发给手机
4. 手机/其他设备：`http://<服务器IP>:58446` + 账号 + 访问码登录

## SSH 凭据安全（约定）

- 登录密码仅经环境变量 `SSH_PASS` 传入 `remote_exec.py`（paramiko），**不写入任何脚本、配置、文档**，也不出现在命令行参数（避免进程列表泄露）
- 更安全的做法：配 SSH 公钥（`ssh-copy-id`），之后部署无需 `SSH_PASS`

## 更新与备份

- 更新：`deploy/deploy.sh --update`（git pull 等价于重新打包上传 + 重启，`data/` 与 `workspaces/` 不受影响）
- 备份：`tar czf backup_$(date +%F).tar.gz data/ workspaces/`（DESIGN 8.10）
- 日志：systemd 模式 `journalctl --user -u vanilla-editor`；crontab 模式看部署目录 `gunicorn.log`

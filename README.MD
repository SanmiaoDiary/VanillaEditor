# VanillaEditor

**一款分布式多用户离线 Markdown 编辑器，部署在自己的服务器/设备上，数据完全存储在本地。**

---

## 功能特性

- **完全离线** — 无网络时正常使用，不依赖任何云服务
- **端到端同步** — 多台 VE 设备间通过 Git 直接互相同步，各自维护完整副本，不经过第三方服务器
- **版本管理** — 每次编辑自动记录 Git 提交，随时回溯历史版本
- **原地工作区** — 直接将服务器上的授权目录作为工作区打开，编辑实时生效，不复制数据（规划中，当前为复制模式，见 UI_STATUS.md）
- **多用户权限体系** — 超级管理员 / 管理员 / 普通用户三级权限，各用户工作区相互隔离、数据私有（规划中）

> 当前实现进度与设计目标的差异见 [UI_STATUS.md](./UI_STATUS.md)。

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.10+、Flask 3.0 |
| 前端 | 原生 JS（static/index.html），hash 路由 |
| UI | Bootstrap 5.3.3 + Bootstrap Icons（本地静态） |
| 版本控制 | Git（subprocess 调用 CLI） |
| 认证 | bcrypt + JWT（30 天滑动过期） |

## 快速开始

### 环境要求

- Python 3.10+
- Git 2.30+

### 安装

```bash
git clone <repo-url>
cd VanillaEditor
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 配置

```bash
copy .env.example .env
```

编辑 `.env` 可修改端口（默认 5000）和数据目录。

### 运行

```bash
# Windows（推荐，避免 Windows Store 的 python 占位符问题）
start.bat
# 或
.venv\Scripts\python.exe run.py

# macOS / Linux
.venv/bin/python run.py

# 生产模式（Linux）
pip install gunicorn && gunicorn -w 2 -b 0.0.0.0:5000 run:app
# 生产模式（Windows）
pip install waitress && waitress-serve --host 0.0.0.0 --port 5000 run:app
```

访问：`http://localhost:5000`

---

## 项目结构

```
VanillaEditor/
├── app/                  # Flask 后端
│   ├── routes.py         # 所有 API 路由（单一入口）
│   └── git/
│       └── service.py    # Git 操作封装
├── static/               # 前端（无需构建）
│   ├── index.html        # 页面骨架
│   ├── css/app.css       # 自定义样式
│   ├── js/app.js         # 全部前端逻辑
│   └── vendor/           # Bootstrap + bootstrap-icons（本地）
├── data/                 # 运行时数据（users.json 等，已 gitignore；规划迁移 config.db）
├── start.bat             # Windows 启动脚本
├── start.ps1             # PowerShell 启动脚本
├── DESIGN.md             # 设计文档（唯一设计文档）
├── UI_STATUS.md          # UI 实现状态清单
├── CHANGELOG.md          # 版本更新日志
├── requirements.txt
└── run.py
```

## API 参考

详细 API 说明见 [DESIGN.md](./DESIGN.md) 第 6 章。

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/auth/init` | 创建账号（首次） |
| `POST` | `/api/auth/login` | 登录，返回 JWT |
| `GET/POST/DELETE` | `/api/workspaces` | 工作区 打开/列出/关闭 |
| `GET/POST` | `/api/docs` | 文档 列出/新建 |
| `DELETE` | `/api/docs/<doc_id>` | 删除文档 |
| `GET/PUT` | `/api/files/<doc_id>/<path>` | 读取/保存文件内容 |
| `POST` | `/api/commit` | 手动提交 |
| `GET` | `/api/history/<doc_id>` | 查看提交历史 |
| `POST` | `/api/sync/pull` / `/api/sync/push` | 从远端拉取 / 推送 |
| `GET/POST/DELETE` | `/api/sync/remote` | Git 远端管理 |
| `GET/POST` | `/api/git/config` | 获取/设置 Git 用户信息 |
| `GET/POST` | `/api/git/branch` | 分支列表、创建与切换 |
| `POST` | `/api/git/merge` | 合并分支 |
| `POST` | `/api/git/reset` | 回退到指定提交 |
| `GET` | `/api/access/status` | 远程访问状态 |
| `POST` | `/api/access/enable` / `disable` | 开关远程访问（开启需认证口令，见 DESIGN 4.5.1） |

## 许可

[MIT](./LICENSE)

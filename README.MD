# VanillaEditor

**一款分布式离线 Markdown 编辑器，每台设备独立运行，数据完全存储在本地。**

---

## 功能特性

- **完全离线** — 无网络时正常使用，不依赖任何云服务
- **端到端同步** — 设备间通过 Git 直接互相同步，各自维护完整副本，不经过第三方服务器
- **版本管理** — 每次编辑自动记录 Git 提交，随时回溯历史版本
- **单用户设计** — 每台设备独立运行，数据安全私有，无需注册账号

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.10+、Flask 3.0 |
| 前端 | 原生 JS（static/index.html），hash 路由 |
| UI | Bootstrap 5.3.3 + Bootstrap Icons（本地静态） |
| 版本控制 | Git（subprocess 调用 CLI） |
| 认证 | bcrypt + JWT |

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
├── data/                 # 运行时数据（users.json + 各用户仓库，已 gitignore）
├── start.bat             # Windows 启动脚本
├── start.ps1             # PowerShell 启动脚本
├── requirements.txt
└── run.py
```

## API 参考

详细 API 说明见 [DESIGN.md](./DESIGN.md)。

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/auth/init` | 创建账号 |
| `POST` | `/api/auth/login` | 登录，返回 JWT |
| `GET` | `/api/docs` | 列出文档 |
| `POST` | `/api/docs` | 新建文档/文件夹 |
| `DELETE` | `/api/docs/<doc_id>` | 删除文档 |
| `PUT` | `/api/files/<doc_id>/<path>` | 保存文件内容 |
| `GET` | `/api/files/<doc_id>/<path>` | 读取文件内容 |
| `POST` | `/api/commit` | 手动提交 |
| `GET` | `/api/history/<doc_id>` | 查看提交历史 |
| `POST` | `/api/sync/pull` | 从远端拉取 |
| `POST` | `/api/sync/push` | 推送到远端 |
| `GET/POST` | `/api/git/config` | 获取/设置 Git 用户信息 |
| `GET/POST` | `/api/git/branch` | 分支创建与切换 |
| `POST` | `/api/git/merge` | 合并分支 |
| `POST` | `/api/git/reset` | 回退到指定提交 |

## 许可

[MIT](./LICENSE)

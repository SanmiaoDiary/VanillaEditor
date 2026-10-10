# VanillaEditor 设计文档

## 1. 项目概述

VanillaEditor（香草编辑器）是一款分布式离线 Markdown 文本编辑器。每台设备运行独立的 VE 实例，提供两种数据协作方式：**远程控制**（局域网内直接访问他人电脑的编辑器界面）和**端到端同步**（设备间通过 Git 协议互相同步独立副本）。两种模式均不经过任何第三方服务器，保障数据安全。

核心特性：
- **完全离线可用** — 无网络时正常编辑
- **远程控制** — 开启后，同一局域网内手机、平板等设备通过浏览器直接访问本机 VE 界面编辑文档
- **端到端同步** — 设备间直接通过 Git 协议传输数据，各自维护独立副本
- **单用户设计** — 每台设备独立运行，数据安全私有

---

## 2. 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.10+, Flask |
| 前端 | HTML5, CSS3, Vue 3 + Bootstrap 5 |
| 编辑器 | Monaco Editor |
| 版本控制 | Git（Python `gitpython`） |
| 实时通信 | WebSocket（本地编辑器与后端通信） |
| 同步协议 | Git（push/pull/fetch） |
| 存储 | 本地文件系统（.md 文件 + .git 仓库） |

---

## 3. 架构设计

### 3.1 核心模型

VE 没有"客户端"和"服务端"之分——**每台设备运行的都是同一个 VE 实例**，既是服务提供方，也是编辑使用方。

```
┌─────────────────────────────────────────────────────┐
│                 本机 VE 实例                         │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │              Flask Server                     │   │
│  │                                              │   │
│  │  ┌──────────┐  ┌────────────────────────┐    │   │
│  │  │ REST API │  │  Git Sync Service      │    │   │
│  │  │ Auth     │  │  (push/pull/fetch)     │    │   │
│  │  └────┬─────┘  └───────────┬────────────┘    │   │
│  │       └────────────────────┼─────────────────┘   │
│  │                            ▼                     │
│  │              ┌─────────────────────┐             │
│  │              │  Local .md files    │             │
│  │              │  + .git repository  │             │
│  │              └─────────────────────┘             │
│  └──────────────────────────────────────────────────┘   │
│                           ▲                             │
│                           │ Web UI                      │
│  ┌────────────────────────┴──────────────────────────┐  │
│  │          Browser (Web GUI)                         │  │
│  │  Monaco Editor  ↔  marked.js preview               │  │
│  └──────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
                          │
              ┌───────────┼───────────┐
              │           │           │
         LAN / Direct   LAN / Direct
              │           │
   ┌──────────▼──┐  ┌────▼────────┐  ┌──▼──────────┐
   │  Device B   │  │ Device C    │  │ External Git│
   │  VE 实例    │  │ VE 实例     │  │ Remote Repo │
   └─────────────┘  └─────────────┘  └─────────────┘
```

### 3.2 两种协作模式

VE 提供两种协作方式，互不依赖：

**① 远程控制（LAN Remote Access）**

本机 VE 服务端开启后，局域网内其他设备通过浏览器访问 `http://<本机IP>:<port>`，直接操作本机上的文档。编辑发生在主机上，远程设备只是"屏幕和键盘的延伸"。

```
┌──────────────────┐         HTTP/WebSocket         ┌──────────────────┐
│     本机 VE      │ ◄──────────────────────────────► │   手机 / 平板    │
│                  │                                  │   (浏览器访问)   │
│  ┌────────────┐  │                                  └──────────────────┘
│  │ Flask API  │  │       ← 同一个数据仓库
│  │ Editor     │  │
│  └────────────┘  │
│  .git + .md files│
└──────────────────┘
```

**② 端到端同步（Peer-to-Peer Sync）**

每台设备各自拥有完整的文档副本，通过 Git push/pull 保持同步。两台设备修改各自独立的文件，不共享同一份数据。

```
┌─────────────┐         git push          ┌─────────────┐
│  Device A   │ ──────────────────────────→ │  Device B   │
│  (本地仓库) │                             │  (本地仓库) │
└──────┬──────┘                             └──────┬──────┘
       │                                           │
       │        git pull ←─────────────────────────┤
       └──────────── 各自维护独立副本 ──────────────┘
```

**选择建议：**
- 想把手机当电脑编辑器的延伸 → 用**远程控制**
- 想在两台设备各自保留完整工作副本 → 用**同步**

### 3.3 模块划分

| 模块 | 职责 |
|------|------|
| `auth` | 单用户登录（密码保护本地数据） |
| `editor` | 文档 CRUD、文件读写 |
| `git` | Git 操作封装（init/commit/pull/push/fetch/status/diff） |
| `sync` | 同步管理（远端配置、推送、拉取、冲突检测） |
| `access` | 远程控制开关、允许访问的设备列表、WebSocket 连接管理 |
| `api` | RESTful 路由，统一响应格式 |

---

## 4. 数据模型

### 4.1 配置（单用户，存于本地 JSON）

```json
{
  "username": "string",
  "password_hash": "string",
  "created_at": "ISO8601",
  "git_remotes": [
    { "name": "device-b", "url": "http://192.168.1.10:5000/git" }
  ],
  "editor_prefs": {
    "font_size": 14,
    "theme": "dark"
  }
}
```

### 4.2 文档（.md 文件，由 Git 管理）

文件内容即 Markdown 原文，Git 负责版本追踪，无需额外数据库。

---

## 5. 核心流程

### 5.1 文档编辑与版本管理

```
用户编辑 → 自动保存 → 写入 .md 文件 → git add → git commit
                                    ↓
                           生成新版本 SHA
```

- 每次保存自动生成 commit，message 格式：`update: <filename>`
- 支持查看历史版本、回滚至任意 commit
- Diff 对比通过 `git diff <sha1> <sha2>` 实现

### 5.2 端到端同步（Git 驱动）

```
┌─────────────┐          git push          ┌─────────────┐
│  Device A   │ ──────────────────────────→ │  Device B   │
│  (本地仓库) │                             │  (本地仓库) │
└──────┬──────┘                             └──────┬──────┘
       │                                           │
       │        git pull ←─────────────────────────┤
       │          (Device B 推过来的)               │
       ▼                                           ▼
  自动合并 / 冲突提示                   自动合并 / 冲突提示
```

**同步流程：**

1. 用户在设置页添加其他设备的 VE 地址作为 Git 远端
2. 点击"同步"（或自动触发）执行 `git fetch <remote>`
3. 若有新提交，自动尝试 `git merge`
4. **无冲突** → 合并成功，更新文档列表
5. **有冲突** → 进入冲突解决流程（见 5.3）

### 5.3 冲突处理

当两台设备修改了同一文件的不同部分时触发：

```
冲突发生
    │
    ├─ 方案 A：保留本地版本（丢弃远端变更）
    ├─ 方案 B：保留远端版本（丢弃本地变更）
    └─ 方案 C：手动合并（UI 展示 diff，用户逐行选择保留内容）
        │
        └─ 合并完成后 git add + git commit 解决冲突
```

冲突解决后状态回正常，继续后续同步。

---

## 6. API 设计

### 认证

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/login` | 登录，返回 JWT |
| GET | `/api/auth/me` | 当前用户信息 |

（无注册接口，首次使用时在 UI 输入密码创建管理员账号）

### 文档

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/docs` | 列出所有文档 |
| GET | `/api/docs/:id` | 获取文档内容 |
| POST | `/api/docs` | 创建新文档 |
| PUT | `/api/docs/:id` | 更新文档内容（自动 commit） |
| DELETE | `/api/docs/:id` | 删除文档 |
| GET | `/api/docs/:id/history` | 获取 Git 提交历史 |
| GET | `/api/docs/:id/compare` | 对比两个版本差异 |

### 同步

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/sync/remote` | 列出已配置的远端设备 |
| POST | `/api/sync/remote` | 添加远端设备地址 |
| DELETE | `/api/sync/remote/:name` | 删除远端设备 |
| POST | `/api/sync/pull` | 从指定远端拉取（自动合并） |
| POST | `/api/sync/push` | 推送至指定远端 |
| GET | `/api/sync/conflict` | 获取待解决的冲突详情 |
| POST | `/api/sync/resolve` | 提交冲突解决方案 |

### 远程控制

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/access/status` | 获取远程控制开关状态及当前在线连接数 |
| POST | `/api/access/enable` | 开启远程控制，生成访问密钥 |
| POST | `/api/access/disable` | 关闭远程控制 |
| GET | `/api/access/clients` | 列出当前连接的设备列表 |
| DELETE | `/api/access/clients/:id` | 踢出指定设备 |

> **安全设计**：远程控制需手动开启（默认关闭）；启用后生成一次性访问密码或 QR 码，被控端输入密码方可建立连接。连接期间全程 JWT 鉴权，关闭即断开所有连接。

---

## 7. 前端设计

### 7.1 页面结构

```
App（Vue Router）
├── /login              LoginView（单用户密码登录）
└── /editor             EditorView
    ├── 左侧 Sidebar    文档树形列表（可展开文件夹）
    ├── 中部 Editor     Monaco Editor（v-model 双向绑定）
    ├── 右侧 Preview    Markdown 实时预览（marked.js）
    └── 底部 LogBar     最近 Git 提交列表（Bootstrap Table）

额外界面
├── /sync               SyncView（设备配置、同步操作、冲突解决）
├── /access             AccessView（远程控制开关、在线设备列表、连接管理）
└── /settings           SettingsView（编辑器偏好、端口配置等）
```

### 7.2 前端技术选型

| 用途 | 库 |
|------|----|
| UI 框架 | Bootstrap 5 |
| 图标 | Bootstrap Icons |
| 状态管理 | Pinia |
| 路由 | Vue Router 4 |
| HTTP | Axios（自动携带 JWT） |
| Markdown 渲染 | marked |
| 代码编辑器 | Monaco Editor |

### 7.3 交互规范

- **自动保存**：停止输入 1.5s 防抖后调 `PUT /api/docs/:id`
- **同步按钮**：编辑器顶部常驻"同步"按钮，点击触发 `POST /api/sync/pull`
- **冲突弹窗**：检测到冲突时弹出 Modal，提供三个操作按钮（保留本地 / 保留远端 / 手动合并）
- **手动合并**：打开 diff 视图，用户逐段选择保留内容，确认后再 commit
- **远程控制开关**：AccessView 中一键开启/关闭；开启后显示本机访问地址（含内网 IP）和一次性访问密码；在线设备列表实时刷新，支持逐个踢出

---

## 8. 目录结构

```
VanillaEditor/
├── app/                      # Flask 后端
│   ├── __init__.py
│   ├── auth/
│   │   ├── routes.py
│   │   └── models.py
│   ├── editor/
│   │   ├── routes.py
│   │   └── services.py
│   ├── git/
│   │   ├── service.py        # Git 操作封装
│   │   └── repo.py           # 仓库级操作
│   ├── sync/
│   │   ├── sync_service.py   # 同步逻辑
│   │   └── conflict.py       # 冲突检测与解决
│   ├── access/
│   │   ├── routes.py         # 远程控制 API
│   │   └── manager.py        # 连接管理、密码生成、设备列表
│   └── api/
│       └── routes.py
├── frontend/                 # Vue 3 前端项目
│   ├── src/
│   │   ├── components/
│   │   ├── views/
│   │   ├── stores/
│   │   ├── router/
│   │   ├── api/
│   │   ├── App.vue
│   │   └── main.js
│   ├── public/
│   ├── index.html
│   ├── vite.config.js
│   └── package.json
├── static/                   # vite build 产物输出目录
├── config.py
├── requirements.txt
└── run.py
```

---

## 9. 安全考虑

- 密码使用 `bcrypt` 哈希存储
- JWT 过期时间 24h
- 局域网暴露时的基础防护：登录拦截 + CSRF 防护
- 路径 sanitize（防止路径穿越攻击）
- **不上传任何数据到第三方服务器**，所有数据存储在本机
- 远程控制默认关闭，需手动开启并输入访问密码才能建立连接

---

## 10. 部署方案

```bash
# 后端
pip install -r requirements.txt
python run.py

# 前端开发模式（热更新，Vite 代理到后端 API）
cd frontend
npm install
npm run dev

# 前端生产构建（产物放入 static/）
npm run build
cp -r dist/* ../static/
```

```bash
# Docker
docker build -t vanilla-editor .
docker run -d -p 5000:5000 \
  -v $(pwd)/data:/app/data \
  -e VE_PASSWORD=your_password \
  vanilla-editor
```

- 数据持久化：`data/` 目录（含 .md 文件、.git 仓库、用户配置）挂载到宿主机
- 局域网访问：确保防火墙放行对应端口，其他设备访问 `http://<本机IP>:5000`

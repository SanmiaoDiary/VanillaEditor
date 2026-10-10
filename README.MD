# VanillaEditor

**一款分布式离线 Markdown 编辑器，每台设备独立运行，提供远程控制与端到端同步两种协作方式。**

---

## 功能特性

- **完全离线** — 无网络时正常使用，不依赖任何云服务
- **远程控制** — 一键开启后，同一局域网内的手机、平板等设备通过浏览器直接访问本机 VE 界面编辑文档
- **端到端同步** — 设备间通过 Git 直接互相同步，各自维护完整副本，不经过第三方服务器
- **版本管理** — 每次编辑自动记录 Git 提交，随时回溯历史版本
- **冲突解决** — 多设备同时修改同一文件时，提供保留本地 / 保留远端 / 手动合并三种方案
- **单用户设计** — 每台设备独立运行，数据安全私有，无需注册账号

## 两种协作模式

| 模式 | 场景 | 数据流向 |
|------|------|----------|
| **远程控制** | 把手机当电脑编辑器的延伸 | 所有编辑操作发生在主机上 |
| **端到端同步** | 两台设备各自保留完整工作副本 | 通过 Git push/pull 双向同步 |

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python + Flask |
| 前端 | Vue 3 + Bootstrap 5 |
| 编辑器 | Monaco Editor |
| 版本控制 | Git（Python `gitpython`） |
| 实时通信 | WebSocket |
| 同步协议 | Git（push / pull / fetch） |

## 工作原理

### 远程控制
本机 VE 开启远程控制后，局域网内其他设备的浏览器打开 `http://<本机IP>:<port>`，输入访问密码即可连接，直接在主机上编辑文档。

```
手机/平板  ──浏览器访问──→  本机 VE  Web 界面  ──操作──→  本机 .git 仓库
```

### 端到端同步
两台设备各自添加对方的 VE 地址为 Git 远端，执行 push/pull 保持数据一致。

```
Device A  ──git push/pull──→  Device B  ──git push/pull──→  Device C
    ↑                              ↑                              ↑
  .git 仓库                      .git 仓库                      .git 仓库
```

## 快速开始

### 环境要求

- Python 3.10+
- Git 2.30+
- Node.js 18+（前端开发 & 构建）

### 安装

```bash
git clone <repo-url>
cd VanillaEditor
pip install -r requirements.txt
```

### 配置

```bash
cp .env.example .env
# 设置 VE_PASSWORD（首次登录密码）和 PORT
```

### 运行

```bash
# 前端开发模式（热更新）
cd frontend && npm install && npm run dev

# 后端（另开终端）
python run.py
```

打开浏览器访问 `http://localhost:5000`。

### 使用远程控制

1. 在 VE 中打开「远程控制」页面
2. 点击"开启"，记录显示的访问地址和一次性密码
3. 在同一局域网内的手机/平板浏览器打开该地址，输入密码即可连接

### 使用端到端同步

1. 在两台设备上分别启动 VE 并登录
2. 在 A 设备的「同步」页面输入 B 设备的地址（如 `http://192.168.1.10:5000`）
3. 双向添加后，点击「同步」即可推送和拉取数据

## 项目结构

```
VanillaEditor/
├── app/              # Flask 后端
│   ├── auth/         # 用户认证
│   ├── editor/       # 文档编辑
│   ├── git/          # Git 操作封装
│   ├── sync/         # 同步与冲突管理
│   ├── access/       # 远程控制模块
│   └── api/          # REST API
├── frontend/         # Vue 3 前端项目
│   ├── src/
│   │   ├── components/
│   │   ├── views/
│   │   ├── stores/   # Pinia 状态管理
│   │   ├── router/
│   │   └── api/      # Axios 封装
│   └── ...
├── static/           # 前端构建产物
├── config.py
├── requirements.txt
└── run.py
```

## 构建

```bash
# 后端依赖
pip install -r requirements.txt

# 前端开发模式
cd frontend && npm install && npm run dev

# 前端生产构建
npm run build

# 运行后端
cd .. && python run.py
```

## API 文档

详细 API 说明见 [DESIGN.md](./DESIGN.md) 第 6 节。

主要端点：

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/auth/login` | 登录 |
| `GET` | `/api/docs` | 列出文档 |
| `PUT` | `/api/docs/:id` | 更新文档 |
| `POST` | `/api/sync/pull` | 从远端拉取 |
| `POST` | `/api/sync/push` | 推送到远端 |
| `POST` | `/api/access/enable` | 开启远程控制 |
| `GET` | `/api/access/status` | 查询控制状态 |

## 许可

[MIT](./LICENSE)

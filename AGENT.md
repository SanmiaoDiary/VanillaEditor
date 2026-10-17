# AGENT.md — VanillaEditor 项目开发规范

## 项目概况

**VanillaEditor** 是一款分布式离线 Markdown 编辑器。每台设备独立运行，数据完全存储在本地，通过 Git 协议实现设备间端到端同步，无需任何第三方服务器。

**核心特性：**
- 完全离线可用，无网络时正常编辑
- 端到端同步：设备间通过 Git 直接互相同步，各自维护完整副本
- 版本管理：每次编辑自动记录 Git 提交，随时回溯历史版本
- 工作区支持：可将任意本地文件夹作为工作区打开，编辑时内容同步回源目录
- 单用户设计，数据安全私有

**技术栈：**
| 层 | 技术 |
|----|------|
| 后端 | Python 3.10+、Flask 3.0 |
| 前端 | 原生 JS，hash 路由，无构建步骤 |
| UI | Bootstrap 5.3.3 + Bootstrap Icons（静态本地） |
| 版本控制 | Git（subprocess 调用 CLI） |
| 认证 | bcrypt + JWT |

---

## 更新日志

### v0.1.2 — 2026-10-17

**feat:** 添加远程访问控制功能
- 设置页新增"网络与安全"分类，包含远程访问开关
- 开启后生成唯一访问码，局域网内其他设备可通过地址+访问码登录
- 支持查看本机局域网IP和访问URL
- 关闭后自动清除访问码，其他设备无法连接

**fix:** 修复Logo颜色显示问题
- 默认状态改为次要文字色，hover时变为accent颜色
- 与Bootstrap暗色主题保持一致

**fix:** 工作区按钮样式统一
- 按钮样式与旁边新建文件/文件夹按钮保持一致
- 修正按钮描述文案

---

### v0.1.1 — 2026-10-17

**feat:** 添加 Markdown 语法高亮
- 编辑器文本框内实时显示语法高亮（标题颜色、加粗、斜体、链接、代码块等）
- 采用 overlay 方案：透明 textarea + 背后 `<pre>` 高亮层，滚动自动同步
- 高亮逻辑复用内置 Markdown 解析函数，无需额外依赖

**feat:** 移动端预览切换
- 新增预览/编辑切换按钮（<768px 显示），点击可替换编辑器为预览面板或恢复编辑
- 状态持久化到 localStorage，刷新后保持上次选择

**fix:** 侧边栏 offcanvas 崩溃
- 修复移动端关闭侧边栏后再次点击按钮报错 `can't access property "backdrop"`
- 移除 Bootstrap data-bs-* 属性，改用原生事件委托控制 offcanvas 开闭

**fix:** 移动端菜单栏展开方向错误
- 将菜单 offcanvas 从 `offcanvas-end`（右侧）改为 `offcanvas-start`（左侧）
- 修复设置页 navbar 在小屏时布局异常问题

**feat:** 添加工作区功能
- 后端新增 `/api/workspaces` 系列接口：打开/关闭/扫描本地目录
- 工作区内容复制到 git 仓库管理，编辑保存时同步写回源目录
- 文件面板新增"打开工作区"按钮，支持路径输入与文件预览

**feat:** 设置页重构
- 左侧垂直菜单导航，包含：账号管理、网络与安全、版本管理与同步、关于
- 右侧内容区根据选中菜单动态切换，样式统一

**feat:** 工作区选择器重构
- 由手动输入路径改为服务器目录浏览器，显示服务器文件系统
- 支持"默认工作区"、"上级"、"下级"、"历史"四向导航
- 路径输入框与目录树双向联动

**fix:** 删除移动端侧边栏自动展开按钮 `veSidebarToggler`
- 工作区在侧边栏单独分区显示，可一键关闭

---

## 提交规范

**每次完成任何代码修改后，必须提交 commit。**

```bash
git add .
git commit -m "描述你做了什么"
```

- 提交前确保代码可以正常运行（至少不报语法错误）
- commit message 必须使用中文，简短描述变更内容
- 格式：`fix:` / `feat:` / `docs:` / `chore:` 开头（参考 Conventional Commits）
- 不在 commit 中提交 `static/`、`node_modules/`、`data/`、`__pycache__/`

---

## 项目架构

（其余内容保持不变...）

```bash
git add .
git commit -m "描述你做了什么"
```

- 提交前确保代码可以正常运行（至少不报语法错误）
- commit message 必须使用中文，简短描述变更内容
- 格式：`fix:` / `feat:` / `docs:` / `chore:` 开头（参考 Conventional Commits）
- 不在 commit 中提交 `static/`、`node_modules/`、`data/`、`__pycache__/`

---

## 项目架构

### 整体结构

```
VanillaEditor/
├── app/                # Flask 后端
│   ├── routes.py       # 所有 API 路由（单一入口，不要分散到多个文件）
│   └── git/
│       └── service.py  # Git 操作封装（list_files/read/write/commit/pull/push/log）
├── static/             # 前端（无构建，直接由 Flask 托管）
│   ├── index.html      # 页面骨架（仅结构，引入 css/js）
│   ├── css/app.css     # 全部自定义样式
│   ├── js/app.js       # 全部前端逻辑（UI 渲染 + hash 路由 + apiFetch）
│   └── vendor/         # 本地 Bootstrap 5.3.3 + bootstrap-icons 1.11.3（不依赖 CDN）
├── data/               # 运行时数据（用户数据、Git 仓库，已被 .gitignore）
├── requirements.txt    # Python 依赖
├── run.py              # 后端启动入口
└── DESIGN.md           # 详细设计文档
```

### 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.10+、Flask 3.0 |
| 前端 | 原生 JS（static/js/app.js），hash 路由，无构建步骤 |
| UI | Bootstrap 5.3.3 + Bootstrap Icons 1.11.3（本地 static/vendor/，禁止依赖 CDN） |
| 认证 | bcrypt + JWT |

---

## 开发注意事项

### 后端

1. **所有 API 路由写在 `app/routes.py` 一个文件里**，不要拆分成多个文件
2. **所有需要登录的接口必须加 `@require_auth` 装饰器**，获取用户名用 `g.username`
3. Git 操作统一用 `app/git/service.py` 里的 `GitService` 类，不要在其他地方直接调 subprocess
4. 文件路径处理必须用 `git_service._md_path()` 或 `os.path.normpath()` 防止路径穿越
5. 数据目录默认在 `data/`（相对于项目根），启动时会自动创建
6. 错误响应统一返回 JSON：`{"error": "描述"}`，正常响应返回 `{ok: True}` 或数据
7. **Windows 注意**：系统 `python` 命令可能指向 Windows Store 占位符（不真正执行 Python），请使用 `.venv\Scripts\python.exe` 或 `start.bat` 启动

### 前端

1. **无构建三文件架构**：`static/index.html`（骨架）+ `static/css/app.css`（样式）+ `static/js/app.js`（逻辑，原生 JS + 手写 hash 路由 + fetch）
2. **UI 框架**：Bootstrap 5.3.3 与 bootstrap-icons 1.11.3 已下载到 `static/vendor/` 本地引用；页面统一 `data-bs-theme="dark"`
3. **禁止 emoji**：所有图标必须用 bootstrap-icons（如 `bi-folder`、`bi-git`、`bi-gear`），不得使用 emoji 表情
4. **路由**：hash 路由，仅三个页面：`#/login`（登录/注册）、`#/editor`（编辑器主工作区）、`#/setting`（用户信息与设置）
5. **响应式**：侧边栏在 <992px 使用 Bootstrap `offcanvas-lg` 抽屉；编辑区 <768px 纵向堆叠；导航栏提供移动端折叠菜单
6. 调 API 用全局 `apiFetch()` 函数（自动携带 JWT，401 自动跳登录）
7. 修改界面：改结构在 `index.html`，改样式在 `css/app.css`，改逻辑/渲染在 `js/app.js`
8. **注意**：Windows 浏览器可能缓存静态资源，修改后需 Ctrl+Shift+R 刷新

### Git 操作（后端）

- 每次编辑文件后自动执行 `git add -A` 再 `git commit`
- commit message 格式：`update: <文件名>`
- pull/push 时使用 `git pull --no-rebase` / `git push`
- 空仓库（无提交）时 `git status` 会报错，调用前先检查 `.git` 目录是否存在
- 分支/配置/合并/回退：`/api/git/config`、`/api/git/branches`、`/api/git/branch`、`/api/git/merge`、`/api/git/reset`（实现在 `GitService` 的 config/branches/checkout/merge/reset_hard 方法）
- 新仓库 init 时自动写入默认 `user.name`/`user.email`（用户名 + `@vanilla.local`），避免首次提交失败

---

## 常见任务速查

### 添加新 API 接口

1. 在 `app/routes.py` 的对应区块添加路由
2. 在 `static/js/app.js` 中用 `apiFetch()` 调用

### 添加新前端页面

在 `static/js/app.js` 中编写渲染函数，并用 `Router.register('#/xxx', ...)` 注册路由（注意路由命名规范：`#/login`、`#/editor`、`#/setting`）。

### 修改样式

---

## 启动命令

```bash
# Windows（推荐，避免系统 python 指向 Windows Store 占位符）
start.bat
# 或直接使用虚拟环境 Python
.venv\Scripts\python.exe run.py

# macOS / Linux
.venv/bin/python run.py
```

访问：`http://localhost:5000`（生产模式）或局域网内其他设备访问 `http://<本机IP>:5000`

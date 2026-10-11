# AGENT.md — VanillaEditor 项目开发规范

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
python run.py
```

访问：`http://localhost:5000`（生产模式）或局域网内其他设备访问 `http://<本机IP>:5000`

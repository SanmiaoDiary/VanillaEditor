# AGENT.md — VanillaEditor 项目开发规范

## 提交规范

**每次完成任何代码修改后，必须提交 commit。**

```bash
git add .
git commit -m "描述你做了什么"
```

- 提交前确保代码可以正常运行（至少不报语法错误）
- commit message 用中文，简短描述变更内容
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
├── frontend/           # Vue 3 + Vite 前端
│   ├── src/
│   │   ├── components/ # 通用组件（ActivityBar/Sidebar/GitPanel/EditorPane/PreviewPane/StatusBar/Toast）
│   │   ├── views/      # 页面组件（Login/Layout/Settings/Sync）
│   │   ├── stores/     # Pinia store（auth.js/editor.js）
│   │   ├── router/     # Vue Router 配置
│   │   ├── api/        # Axios 封装（自动携带 JWT）
│   │   ├── App.vue
│   │   └── main.js
│   ├── index.html
│   ├── vite.config.js
│   ├── package.json
│   └── ...
├── static/             # 前端构建产物（npm run build 后生成，已被 .gitignore）
├── data/               # 运行时数据（用户数据、Git 仓库，已被 .gitignore）
├── requirements.txt    # Python 依赖
├── run.py              # 后端启动入口
└── DESIGN.md           # 详细设计文档
```

### 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.10+、Flask 3.0 |
| 前端 | Vue 3 + Vite 5 |
| UI | Bootstrap 5 + Bootstrap Icons |
| 状态管理 | Pinia |
| 路由 | Vue Router 4 |
| HTTP | Axios |
| Markdown | marked |
| Git | gitpython |
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

1. **单文件架构**：前端全部代码在 `static/index.html`，通过 CDN 加载 Vue 3、Vue Router、Pinia、axios、marked，无构建步骤
2. **无需 npm/vite**：没有 Node.js 依赖，不需要 `npm install` 或 `npm run build`
3. 调用 API 用全局 `api` 对象（已封装 axios + JWT 自动注入）
4. 修改界面直接在 `static/index.html` 里改对应组件的代码
5. **注意**：Windows 浏览器可能缓存 HTML，修改后需 Ctrl+Shift+R 刷新

### Git 操作（后端）

- 每次编辑文件后自动执行 `git add -A` 再 `git commit`
- commit message 格式：`update: <文件名>`
- pull/push 时使用 `git pull --no-rebase` / `git push`
- 空仓库（无提交）时 `git status` 会报错，调用前先检查 `.git` 目录是否存在

---

## 常见任务速查

### 添加新 API 接口

1. 在 `app/routes.py` 的对应区块添加路由
2. 在 `frontend/src/api/` 添加封装函数（可选）
3. 在前端组件中调用

### 添加新前端页面

直接在 `static/index.html` 的脚本中定义新组件并注册到 router。

### 修改样式

---

## 启动命令

```bash
python run.py
```

访问：`http://localhost:5000`（生产模式）或局域网内其他设备访问 `http://<本机IP>:5000`

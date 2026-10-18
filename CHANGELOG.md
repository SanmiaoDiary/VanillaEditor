# Changelog

All notable changes to VanillaEditor will be documented in this file.

---

## [Unreleased]

### Fixed
- **光标对齐**：修复高亮层与编辑区字体/行高不一致导致的光标偏移问题，统一显式设置 `font-family`、`line-height`、`letter-spacing`、`tab-size`
- **回车键失效**：移除 contenteditable 方案，改回 textarea + 高亮覆盖层，解决空行后 Enter 键无法继续创建新行的问题
- **中文输入法（IME）冲突**：通过 `compositionstart`/`compositionend` 事件检测组合状态，避免输入拼音时被高亮重渲打断
- **工作区按钮样式**：修复 `me-1` 间距缺失问题，图标改为有效的 `bi-folder-symlink`
- **预览面板默认折叠**：电脑端预览面板默认隐藏，工具栏新增切换按钮，按图标可展开/收起
- **预览面板空间保持**：移除 `.ve-preview:empty { display: none }`，空内容时面板仍保留 100px 高度不塌陷

### Added
- **行号显示**：编辑器左侧新增 44px 行号栏，与编辑区同步滚动
- **Markdown 语法高亮**：行首 `#` / `>` / `-` / `*` / 数字`.` 等标记以蓝色高亮，行内 `**粗体**`、`*斜体*`、`` `代码` ``、链接等保持原有着色
- **标签页**：支持多文件同时打开，每个文件独立标签，支持关闭和切换，未保存状态点同步显示
- **移动端预览切换**：移动端新增编辑/预览切换按钮，localStorage 持久化状态
- **远程仓库连接**：项目已连接 `git@github.com:SanmiaoDiary/VanillaEditor.git`

### Changed
- 编辑器结构从 contenteditable div 改为 textarea + `<pre>` 高亮覆盖层
- 预览面板从固定展示改为可折叠，桌面端默认折叠

---

## [v0.1.0] - Previous
- 初始版本发布

"""AI 工具执行层：MCP 服务器与内置 AI 助手共用的工具集（DESIGN 4.10）。

两个入口（POST /api/mcp、POST /api/ai/chat）都最终落到 execute_tool()，
能力一份、安全边界一份：
- 路径经 normpath + realpath 前缀校验，防穿越与符号链接逃逸（对齐 DESIGN 9.1 规则 4）
- 一律拒绝访问 .git 目录内部
- 数据按 username 隔离，仅能操作该用户注册/打开的工作区
"""

import json
import os

_SEARCH_SKIP_DIRS = {".git", ".ve", "__pycache__", "node_modules", ".venv", "venv", ".idea", ".vscode"}
_SEARCH_MAX_FILE = 1024 * 1024  # 1MB：跳过大文件
_SEARCH_MAX_HITS = 50


class ToolError(Exception):
    """工具执行失败。调用方将其转为 isError 结果返回给 AI（不是协议错误）。"""


# ── 工具 JSON Schema（OpenAI function 格式；MCP tools/list 复用其 parameters） ──

def _fn(name, description, props, required):
    return {"type": "function", "function": {
        "name": name,
        "description": description,
        "parameters": {"type": "object", "properties": props, "required": required},
    }}

DOC_ID_PROP = {"doc_id": {"type": "string", "description": "工作区 id（来自 ve_list_workspaces）"}}

TOOLS_SCHEMA = [
    _fn("ve_list_workspaces",
        "列出当前用户的全部写作工作区（id、名称、源目录、可用性）。后续所有工具都需要 doc_id，来自这里的 id。",
        {}, []),
    _fn("ve_list_files",
        "列出工作区内的文件（相对路径、名称；排除 .git）。",
        {**DOC_ID_PROP, "subpath": {"type": "string", "description": "可选，仅列出该子目录下的文件"}}, ["doc_id"]),
    _fn("ve_read_file",
        "读取工作区内一个文本文件的完整内容（UTF-8）。",
        {**DOC_ID_PROP, "path": {"type": "string", "description": "工作区内的相对路径，如 novel/chapter1.md"}}, ["doc_id", "path"]),
    _fn("ve_write_file",
        "写入（创建或覆盖）工作区内的一个文本文件。携带 commit_message 时立即 git 提交（提交信息自动加 ai: 前缀），否则保留未提交状态。",
        {**DOC_ID_PROP,
         "path": {"type": "string", "description": "工作区内相对路径"},
         "content": {"type": "string", "description": "完整文件内容（整体覆盖写入）"},
         "commit_message": {"type": "string", "description": "可选；提供则写后立即提交"}}, ["doc_id", "path", "content"]),
    _fn("ve_delete_file",
        "删除工作区内一个文件（不支持删除目录）。携带 commit_message 时立即提交删除。",
        {**DOC_ID_PROP,
         "path": {"type": "string", "description": "工作区内相对路径"},
         "commit_message": {"type": "string", "description": "可选；提供则删除后立即提交"}}, ["doc_id", "path"]),
    _fn("ve_rename_file",
        "重命名或移动工作区内的一个文件（目标父目录不存在时自动创建）。携带 commit_message 时立即提交。",
        {**DOC_ID_PROP,
         "path": {"type": "string", "description": "原相对路径"},
         "new_path": {"type": "string", "description": "新相对路径"},
         "commit_message": {"type": "string", "description": "可选；提供则重命名后立即提交"}}, ["doc_id", "path", "new_path"]),
    _fn("ve_search_in_files",
        "在工作区全部文本文件中做全文子串搜索，返回 文件:行号:行内容 列表（上限 50 条）。",
        {**DOC_ID_PROP, "query": {"type": "string", "description": "搜索的文本（区分大小写）"}}, ["doc_id", "query"]),
    _fn("ve_commit",
        "提交工作区当前全部变更（git add -A + commit）。",
        {**DOC_ID_PROP, "message": {"type": "string", "description": "提交信息"}}, ["doc_id", "message"]),
    _fn("ve_history",
        "查看工作区提交历史（sha、message、author、date），按时间倒序。",
        {**DOC_ID_PROP, "count": {"type": "integer", "description": "条数，默认 20，上限 100"}}, ["doc_id"]),
    _fn("ve_diff",
        "查看工作区当前未提交变更的 git diff（相对 HEAD）。提交前先用它确认改动范围。",
        {**DOC_ID_PROP}, ["doc_id"]),
    _fn("ve_restore",
        "【危险】将工作区强制回退到指定提交（git reset --hard）：丢弃全部未提交变更，并丢弃该提交之后的提交历史。仅在用户明确要求回退时使用。",
        {**DOC_ID_PROP, "sha": {"type": "string", "description": "目标提交的 sha（来自 ve_history）"}}, ["doc_id", "sha"]),
    _fn("ve_branch",
        "分支操作：action=list（默认）列出分支；action=create 创建并切换到新分支 name；action=switch 切换分支 name。",
        {**DOC_ID_PROP,
         "action": {"type": "string", "enum": ["list", "create", "switch"], "description": "默认 list"},
         "name": {"type": "string", "description": "create/switch 时的分支名"}}, ["doc_id"]),
    _fn("ve_sync",
        "与远端同步：direction=pull 拉取，direction=push 推送（upstream 回退策略同 VE 同步面板）。",
        {**DOC_ID_PROP, "direction": {"type": "string", "enum": ["pull", "push"]}}, ["doc_id", "direction"]),
    _fn("ve_sync_status",
        "查看工作区同步状态：当前分支与跟踪远端、ahead/behind、冲突文件、未提交变更、远端列表。",
        {**DOC_ID_PROP}, ["doc_id"]),
]


# ── 路径安全 ────────────────────────────────────────────────────

def _resolve_in_repo(username, doc_id, rel_path, git_service, data_dir):
    """校验并解析工作区内路径，返回 (repo_path, 绝对路径)。非法即抛 ToolError。"""
    rel_path = (rel_path or "").replace("\\", "/").strip("/")
    repo_path = git_service._repo_path(username, doc_id)
    if not os.path.isdir(repo_path):
        raise ToolError(f"工作区不存在或不可用: {doc_id}")
    repo_real = os.path.realpath(repo_path)
    # docs 回退模式：仓库必须位于 data/<username>/ 内（注册表 source_path 本身来自用户主动打开，视为可信）
    if not git_service.load_registry(username).get(doc_id):
        user_base = os.path.realpath(os.path.join(data_dir, username))
        if not (repo_real == user_base or repo_real.startswith(user_base + os.sep)):
            raise ToolError("非法工作区")
    target = os.path.normpath(os.path.join(repo_path, rel_path))
    target_real = os.path.realpath(target)
    if target_real != repo_real and not target_real.startswith(repo_real + os.sep):
        raise ToolError("路径越界：目标不在工作区内")
    rel = os.path.relpath(target_real, repo_real)
    if ".git" in rel.split(os.sep):
        raise ToolError("禁止访问 .git 目录")
    return repo_path, target


def _tool_workspaces(username, args, git_service, data_dir):
    reg = git_service.load_registry(username)
    out = []
    for doc_id, entry in sorted(reg.items()):
        src = entry.get("source_path", "")
        out.append({
            "doc_id": doc_id,
            "name": entry.get("name", doc_id),
            "source_path": src,
            "available": os.path.isdir(src),
        })
    return out


def _tool_list_files(username, args, git_service, data_dir):
    doc_id = args.get("doc_id", "")
    sub = (args.get("subpath") or "").replace("\\", "/").strip("/")
    repo_path, base = _resolve_in_repo(username, doc_id, sub, git_service, data_dir)
    files = git_service.list_files(username, doc_id)
    prefix = sub + "/" if sub else ""
    out = []
    for f in files:
        p = f["path"].replace(os.sep, "/")
        if prefix and not p.startswith(prefix):
            continue
        out.append({"path": p, "dir": f.get("dir", "")})
    return out


def _tool_read_file(username, args, git_service, data_dir):
    doc_id, path = args.get("doc_id", ""), args.get("path", "")
    _, target = _resolve_in_repo(username, doc_id, path, git_service, data_dir)
    if not os.path.isfile(target):
        raise ToolError(f"文件不存在: {path}")
    with open(target, encoding="utf-8", errors="replace") as f:
        content = f.read()
    if len(content) > 200_000:
        content = content[:200_000] + "\n…（内容过长，已截断到 20 万字符）"
    return {"path": path.replace("\\", "/"), "content": content}


def _maybe_commit(username, doc_id, message, git_service):
    """commit_message 提供时立即提交（ai: 前缀，DESIGN 4.10.2）。返回 sha 或 None。"""
    if not message:
        return None
    ok, sha = git_service.commit(username, doc_id, f"ai: {message}")
    if not ok:
        raise ToolError(f"提交失败: {sha}")
    return sha


def _tool_write_file(username, args, git_service, data_dir):
    doc_id, path = args.get("doc_id", ""), args.get("path", "")
    content = args.get("content")
    if content is None:
        raise ToolError("缺少 content")
    repo_path, target = _resolve_in_repo(username, doc_id, path, git_service, data_dir)
    os.makedirs(os.path.dirname(target) or repo_path, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        f.write(content)
    sha = _maybe_commit(username, doc_id, args.get("commit_message"), git_service)
    out = {"ok": True, "path": path.replace("\\", "/"), "bytes": len(content.encode("utf-8"))}
    if sha:
        out["commit"] = sha
    return out


def _tool_delete_file(username, args, git_service, data_dir):
    doc_id, path = args.get("doc_id", ""), args.get("path", "")
    _, target = _resolve_in_repo(username, doc_id, path, git_service, data_dir)
    if not os.path.isfile(target):
        raise ToolError(f"文件不存在: {path}")
    os.remove(target)
    sha = _maybe_commit(username, doc_id, args.get("commit_message"), git_service)
    out = {"ok": True, "path": path.replace("\\", "/")}
    if sha:
        out["commit"] = sha
    return out


def _tool_rename_file(username, args, git_service, data_dir):
    doc_id = args.get("doc_id", "")
    src, dst = args.get("path", ""), args.get("new_path", "")
    _, src_abs = _resolve_in_repo(username, doc_id, src, git_service, data_dir)
    _, dst_abs = _resolve_in_repo(username, doc_id, dst, git_service, data_dir)
    if not os.path.isfile(src_abs):
        raise ToolError(f"文件不存在: {src}")
    if os.path.exists(dst_abs):
        raise ToolError(f"目标已存在: {dst}")
    os.makedirs(os.path.dirname(dst_abs), exist_ok=True)
    os.rename(src_abs, dst_abs)
    sha = _maybe_commit(username, doc_id, args.get("commit_message"), git_service)
    out = {"ok": True, "path": src.replace("\\", "/"), "new_path": dst.replace("\\", "/")}
    if sha:
        out["commit"] = sha
    return out


def _tool_search(username, args, git_service, data_dir):
    doc_id, query = args.get("doc_id", ""), args.get("query", "")
    if not query:
        raise ToolError("缺少 query")
    repo_path, _ = _resolve_in_repo(username, doc_id, "", git_service, data_dir)
    hits = []
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in _SEARCH_SKIP_DIRS]
        for fn in files:
            if len(hits) >= _SEARCH_MAX_HITS:
                break
            fp = os.path.join(root, fn)
            try:
                if os.path.getsize(fp) > _SEARCH_MAX_FILE:
                    continue
                with open(fp, encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        if query in line:
                            rel = os.path.relpath(fp, repo_path).replace(os.sep, "/")
                            hits.append({"path": rel, "line": i, "text": line.strip()[:200]})
                            if len(hits) >= _SEARCH_MAX_HITS:
                                break
            except OSError:
                continue
    return {"hits": hits, "truncated": len(hits) >= _SEARCH_MAX_HITS}


def _tool_commit(username, args, git_service, data_dir):
    doc_id, message = args.get("doc_id", ""), args.get("message", "")
    if not message:
        raise ToolError("缺少 message")
    ok, sha = git_service.commit(username, doc_id, message)
    if not ok:
        raise ToolError(f"提交失败: {sha}")
    return {"commit": sha}


def _tool_history(username, args, git_service, data_dir):
    doc_id = args.get("doc_id", "")
    count = args.get("count") or 20
    try:
        count = max(1, min(100, int(count)))
    except (TypeError, ValueError):
        count = 20
    return {"commits": git_service.log(username, doc_id, count)}


def _tool_diff(username, args, git_service, data_dir):
    doc_id = args.get("doc_id", "")
    repo_path = git_service._repo_path(username, doc_id)
    if not os.path.isdir(repo_path):
        raise ToolError(f"工作区不存在: {doc_id}")
    out = git_service.diff_worktree(username, doc_id)
    if len(out) > 100_000:
        out = out[:100_000] + "\n…（diff 过长，已截断）"
    return {"diff": out}


def _tool_restore(username, args, git_service, data_dir):
    doc_id, sha = args.get("doc_id", ""), args.get("sha", "")
    ok, err = git_service.reset_hard(username, doc_id, sha)
    if not ok:
        raise ToolError(f"回退失败: {err}")
    return {"ok": True, "restored_to": sha}


def _tool_branch(username, args, git_service, data_dir):
    doc_id = args.get("doc_id", "")
    action = args.get("action") or "list"
    if action == "list":
        return {"branches": git_service.branches(username, doc_id)}
    name = args.get("name", "").strip()
    if not name:
        raise ToolError("缺少 name")
    ok, err = git_service.checkout(username, doc_id, name, create=(action == "create"))
    if not ok:
        raise ToolError(f"分支操作失败: {err}")
    return {"ok": True, "action": action, "branch": name}


def _tool_sync(username, args, git_service, data_dir):
    doc_id = args.get("doc_id", "")
    direction = args.get("direction", "")
    if direction == "pull":
        ok, err = git_service.pull(username, doc_id)
    elif direction == "push":
        ok, err = git_service.push(username, doc_id)
    else:
        raise ToolError("direction 必须是 pull 或 push")
    if not ok:
        raise ToolError(f"{'拉取' if direction == 'pull' else '推送'}失败: {err}")
    tracking = git_service.remote_tracking(username, doc_id)
    return {"ok": True, "direction": direction, "tracking": tracking}


def _tool_sync_status(username, args, git_service, data_dir):
    doc_id = args.get("doc_id", "")
    return {
        "tracking": git_service.remote_tracking(username, doc_id),
        "remotes": git_service.remote_list(username, doc_id),
        "conflicts": git_service.unmerged_files(username, doc_id),
        "uncommitted": git_service.has_uncommitted(username, doc_id),
    }


_TOOLS = {
    "ve_list_workspaces": _tool_workspaces,
    "ve_list_files": _tool_list_files,
    "ve_read_file": _tool_read_file,
    "ve_write_file": _tool_write_file,
    "ve_delete_file": _tool_delete_file,
    "ve_rename_file": _tool_rename_file,
    "ve_search_in_files": _tool_search,
    "ve_commit": _tool_commit,
    "ve_history": _tool_history,
    "ve_diff": _tool_diff,
    "ve_restore": _tool_restore,
    "ve_branch": _tool_branch,
    "ve_sync": _tool_sync,
    "ve_sync_status": _tool_sync_status,
}


def execute_tool(username, name, args, git_service, data_dir):
    """统一工具入口。成功返回可 JSON 序列化的 dict；失败抛 ToolError。"""
    fn = _TOOLS.get(name)
    if fn is None:
        raise ToolError(f"未知工具: {name}")
    if not isinstance(args, dict):
        raise ToolError("参数必须是对象")
    return fn(username, args, git_service, data_dir)


def openai_tools():
    """OpenAI /chat/completions 的 tools 参数（DESIGN 4.10.4）。"""
    return TOOLS_SCHEMA


def mcp_tools():
    """MCP tools/list 的 tools 数组（DESIGN 4.10.3）：
    由同一份 schema 转换，name/description/inputSchema。"""
    out = []
    for t in TOOLS_SCHEMA:
        f = t["function"]
        out.append({
            "name": f["name"],
            "description": f["description"],
            "inputSchema": f["parameters"],
        })
    return out

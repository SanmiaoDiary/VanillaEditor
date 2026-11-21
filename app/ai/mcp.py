"""MCP Streamable HTTP 协议处理（DESIGN 4.10.3，ADR-005 手写 JSON-RPC 2.0）。

支持 initialize / notifications/initialized / ping / tools/list / tools/call。
无状态实现：initialize 下发 Mcp-Session-Id 响应头但不强制校验后续请求；
响应为 application/json（规范允许非流式 JSON），notification 返回 HTTP 202。
"""

import json
import uuid

MCP_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")
SERVER_NAME = "vanillaeditor"

_JSONRPC_PARSE_ERROR = -32700
_JSONRPC_METHOD_NOT_FOUND = -32601
_JSONRPC_INVALID_PARAMS = -32602

_SYSTEM_INSTRUCTIONS = (
    "VanillaEditor (VE) 是自托管的 Markdown 编辑器，这里是它的 MCP 服务器。"
    "通过工具可以对用户工作区进行读写文件、全文搜索、Git 提交/历史/分支、"
    "pull/push 同步等操作。先用 ve_list_workspaces 获取 doc_id。"
    "ve_restore 会丢弃历史与未提交变更，仅在用户明确要求回退时使用。"
)


def _resp(rpc_id, result):
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def _err(rpc_id, code, message):
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}


def handle_mcp_request(username, body, tool_executor, server_version):
    """处理一条 JSON-RPC 2.0 消息（DESIGN 4.10.3）。

    tool_executor: callable(name, args) -> dict，由路由层绑定用户后传入，
    失败抛 ToolError。
    返回 (响应 dict | None, session_id)。None 表示 notification（HTTP 202 空 body）。
    """
    session_id = uuid.uuid4().hex
    if not isinstance(body, dict):
        return _err(None, _JSONRPC_PARSE_ERROR, "Parse error"), None
    method = body.get("method")
    rpc_id = body.get("id")
    params = body.get("params") or {}

    # JSON-RPC notification（无 id）必须不返回响应体
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None, (session_id if method == "notifications/initialized" else None)

    try:
        if method == "initialize":
            requested = params.get("protocolVersion", "")
            version = requested if requested in MCP_PROTOCOL_VERSIONS else MCP_PROTOCOL_VERSIONS[-1]
            return _resp(rpc_id, {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": server_version},
                "instructions": _SYSTEM_INSTRUCTIONS,
            }), session_id

        if method == "ping":
            return _resp(rpc_id, {}), session_id

        if method == "tools/list":
            from app.ai.tools import mcp_tools
            return _resp(rpc_id, {"tools": mcp_tools()}), session_id

        if method == "tools/call":
            name = params.get("name", "")
            arguments = params.get("arguments") or {}
            from app.ai.tools import ToolError
            try:
                result = tool_executor(name, arguments)
                text = json.dumps(result, ensure_ascii=False, indent=1)
                error = False
            except ToolError as e:
                text = str(e)
                error = True
            except Exception as e:  # noqa: BLE001 工具内部错误一律以 isError 结果返回（DESIGN 4.10.3）
                text = f"工具内部错误: {e}"
                error = True
            return _resp(rpc_id, {
                "content": [{"type": "text", "text": text}],
                "isError": error,
            }), session_id

        if method.startswith("notifications/"):
            return None, None
        return _err(rpc_id, _JSONRPC_METHOD_NOT_FOUND, f"Method not found: {method}"), session_id
    except Exception as e:  # noqa: BLE001 协议兜底
        return _err(rpc_id, _JSONRPC_INVALID_PARAMS, f"Invalid request: {e}"), session_id

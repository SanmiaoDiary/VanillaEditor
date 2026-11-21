"""OpenAI 兼容 API 客户端（DESIGN 4.10.4）。

标准库 urllib 实现，零新依赖（ADR-005 同源决策：最小侵入部署）。
仅实现 /chat/completions（非流式）——内置助手的工具循环在后端完成，
一次请求返回最终结果。
"""

import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit


class AIProviderError(Exception):
    """AI API 调用失败（网络/HTTP/响应格式）。"""


def _payload(cfg, messages, tools=None, max_tokens=None):
    body = {
        "model": cfg.get("model", ""),
        "messages": messages,
        "temperature": float(cfg.get("temperature", 0.7)),
    }
    if tools:
        body["tools"] = tools
    if max_tokens:
        body["max_tokens"] = max_tokens
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


def _post(cfg, payload, timeout):
    req = urllib.request.Request(
        cfg["base_url"].rstrip("/") + "/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + (cfg.get("api_key") or ""),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        raise AIProviderError(f"API 返回 HTTP {e.code}: {detail or e.reason}") from e
    except urllib.error.URLError as e:
        raise AIProviderError(f"无法连接 AI API: {e.reason}") from e
    except (ValueError, KeyError) as e:
        raise AIProviderError(f"API 响应格式异常: {e}") from e
    try:
        return data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as e:
        raise AIProviderError(f"API 响应缺少 choices/message: {data}") from e


def validate_cfg(cfg):
    """校验配置完整性，缺项抛 AIProviderError。"""
    for field in ("base_url", "api_key", "model"):
        if not cfg.get(field):
            raise AIProviderError(f"AI API 未配置完整（缺少 {field}），请在设置页填写")


def chat_completion(cfg, messages, tools=None, timeout=90):
    """调用 /chat/completions，返回 assistant message dict（可能含 tool_calls）。"""
    return _post(cfg, _payload(cfg, messages, tools), timeout)


def test_connection(cfg, timeout=20):
    """最小请求测试连通性。成功返回 {model, provider}；失败抛 AIProviderError。"""
    validate_cfg(cfg)
    messages = [{"role": "user", "content": "连接测试，请回复 OK"}]
    _post(cfg, _payload(cfg, messages, max_tokens=10), timeout)
    host = urlsplit(cfg["base_url"]).hostname or ""
    return {"model": cfg.get("model", ""), "provider": host}

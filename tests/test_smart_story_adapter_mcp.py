from __future__ import annotations

import httpx
import pytest

from tools.smart_story_adapter.config import AdapterError
from tools.smart_story_adapter.mcp import McpClient


def test_mcp_client_posts_tool_call_with_bearer_token() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "structuredContent": {"accepted": True, "agent_run_id": 10}
                },
            },
        )

    client = McpClient(
        endpoint="https://api.example.com/mcp/ai-agent",
        token="mcp-secret",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = client.call_tool("report_run_progress", {"agent_project_id": 20, "status": "running"})

    assert result["accepted"] is True
    assert captured[0].headers["Authorization"] == "Bearer mcp-secret"
    body = __import__("json").loads(captured[0].content)
    assert body["method"] == "tools/call"
    assert body["params"]["name"] == "report_run_progress"
    assert body["params"]["arguments"]["status"] == "running"


def test_mcp_client_raises_adapter_error_on_network_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    client = McpClient(
        endpoint="https://api.example.com/mcp/ai-agent",
        token="mcp-secret",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(AdapterError, match="MCP call report_run_progress failed due to network error: Connection refused"):
        client.call_tool("report_run_progress", {"agent_project_id": 20, "status": "running"})


def test_mcp_client_raises_adapter_error_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    client = McpClient(
        endpoint="https://api.example.com/mcp/ai-agent",
        token="mcp-secret",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(AdapterError, match="MCP call report_run_progress failed with HTTP 500"):
        client.call_tool("report_run_progress", {"agent_project_id": 20, "status": "running"})


def test_mcp_client_raises_adapter_error_on_invalid_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>Not JSON</html>")

    client = McpClient(
        endpoint="https://api.example.com/mcp/ai-agent",
        token="mcp-secret",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(AdapterError, match="MCP call report_run_progress failed: Invalid JSON response"):
        client.call_tool("report_run_progress", {"agent_project_id": 20, "status": "running"})


def test_mcp_client_raises_adapter_error_on_jsonrpc_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32600, "message": "Invalid Request"}
            },
        )

    client = McpClient(
        endpoint="https://api.example.com/mcp/ai-agent",
        token="mcp-secret",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(AdapterError, match="MCP call report_run_progress failed:"):
        client.call_tool("report_run_progress", {"agent_project_id": 20, "status": "running"})


def test_mcp_client_raises_adapter_error_on_non_dict_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["not", "a", "dict"])

    client = McpClient(
        endpoint="https://api.example.com/mcp/ai-agent",
        token="mcp-secret",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(AdapterError, match="MCP call report_run_progress failed: Invalid JSON response format"):
        client.call_tool("report_run_progress", {"agent_project_id": 20, "status": "running"})


def test_mcp_client_extracts_jsonrpc_error_on_http_500() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32603, "message": "Internal error"}
            },
        )

    client = McpClient(
        endpoint="https://api.example.com/mcp/ai-agent",
        token="mcp-secret",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(AdapterError, match="MCP call report_run_progress failed: {'code': -32603, 'message': 'Internal error'}"):
        client.call_tool("report_run_progress", {"agent_project_id": 20, "status": "running"})

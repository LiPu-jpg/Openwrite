from __future__ import annotations

import json
from threading import Thread
from types import SimpleNamespace
from urllib.request import ProxyHandler, Request, build_opener

from tools.init_project import init_project
from tools.llm.client import LLMClient, LLMConfig, Message
from tools.mutation_summary import build_mutation_summary
from tools.operation_trace import (
    OperationTraceStore,
    capture_operation_trace,
    summarize_context_packet,
)
from tools.studio import create_server


class _TraceBackend:
    def token_counter(self, *, messages, tools=None, **kwargs):
        return sum(len(str(item.get("content") or "")) for item in messages)

    def completion(self, **kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="模型输出中的秘密正文",
                        reasoning_content="不应保留的推理",
                    ),
                    finish_reason="stop",
                )
            ],
            usage={"prompt_tokens": 8, "completion_tokens": 5, "total_tokens": 13},
            model=kwargs["model"],
        )


def test_trace_store_links_model_tool_and_domain_without_raw_sensitive_content(tmp_path):
    packet = {
        "chapter_id": "ch_001",
        "context_manifest": {
            "strategy": "hierarchical-provenance-v1",
            "packet_revision": "packet-a",
            "source_revision": "source-a",
            "estimated_tokens": 120,
            "request_budget": {"input_budget_tokens": 4096},
            "items": [
                {"sources": [{"path": "src/outline.md", "exists": True, "revision": "outline-a"}]}
            ],
        },
    }
    with capture_operation_trace() as collector:
        response = LLMClient(
            LLMConfig(model="test-model", api_key="provider-secret"),
            client=_TraceBackend(),
        ).chat([Message("system", "系统秘密提示"), Message("user", "作者秘密提示")])
    assert response.content == "模型输出中的秘密正文"

    mutation = build_mutation_summary(
        operation="manuscript.update",
        entity_kind="manuscript",
        entity_id="ch_001",
        path="data/manuscript/ch_001.md",
        before="旧秘密正文",
        after="新秘密正文",
        source_revision="old-rev",
        result_revision="new-rev",
        flatten=False,
    )
    store = OperationTraceStore(tmp_path)
    reference = store.record(
        route="/api/document",
        request_id="req_trace",
        payload={
            "path": "data/manuscript/ch_001.md",
            "content": "请求中的秘密正文",
            "api_key": "credential-secret",
        },
        response={"mutation_summary": mutation},
        request_context={
            "session_id": "ses_1",
            "tool_call_id": "call_1",
            "root_call_id": "root_1",
            "tool_name": "novel_doc_write",
        },
        context=summarize_context_packet(packet),
        model_calls=collector.model_calls,
    )

    trace_path = tmp_path / reference["path"]
    serialized = trace_path.read_text(encoding="utf-8")
    for secret in (
        "provider-secret",
        "credential-secret",
        "系统秘密提示",
        "作者秘密提示",
        "模型输出中的秘密正文",
        "不应保留的推理",
        "请求中的秘密正文",
        "旧秘密正文",
        "新秘密正文",
    ):
        assert secret not in serialized

    record = json.loads(serialized)
    assert record["request"]["tool_call_id"] == "call_1"
    assert record["request"]["arguments"]["values"]["api_key"] == {
        "storage": "omitted",
        "present": True,
    }
    assert record["context"]["packet_revision"] == "packet-a"
    assert record["context"]["sources"] == [
        {"path": "src/outline.md", "exists": True, "revision": "outline-a"}
    ]
    assert record["model_calls"][0]["response"]["usage"]["total_tokens"] == 13
    assert record["domain_change"]["items"][0]["field"] == "value"
    assert record["privacy"] == {
        "raw_prompt_stored": False,
        "raw_context_stored": False,
        "raw_model_response_stored": False,
        "raw_chain_of_thought_stored": False,
        "raw_credentials_stored": False,
        "raw_mutation_values_stored": False,
    }
    assert record["retention"] == {
        "scope": "novel_project",
        "max_age_days": 30,
        "max_records": 100,
    }
    assert store.list(1)[0]["trace_id"] == reference["trace_id"]


def test_http_write_trace_links_dsh_call_context_packet_model_and_committed_chapter(tmp_path):
    init_project(tmp_path, "demo", "Trace 小说")

    def writer(root, args):
        from tools.cli import _save_chapter

        generated = LLMClient(
            LLMConfig(model="trace-model"), client=_TraceBackend()
        ).chat([Message("user", "写作时的私密指令")], operation="chapter_write")
        path = _save_chapter(
            root,
            "demo",
            args["chapter_id"],
            "第一章",
            generated.content,
        )
        return {
            "ok": True,
            "chapter_id": args["chapter_id"],
            "title": "第一章",
            "word_count": len(generated.content),
            "draft_path": str(path),
            "usage": generated.usage,
        }

    server = create_server(tmp_path, port=0, writer_executor=writer)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        request = Request(
            f"{base}/api/write",
            method="POST",
            data=json.dumps(
                {"chapter_id": "ch_001", "target_words": 200, "guidance": "不要泄露的作者指令"}
            ).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-OpenWrite-Studio": "1",
                "X-OpenWrite-Workspace-Root": str(tmp_path),
                "X-OpenWrite-Session-Id": "ses_write",
                "X-OpenWrite-Tool-Call-Id": "call_write",
                "X-OpenWrite-Root-Call-Id": "root_write",
                "X-OpenWrite-Tool-Name": "novel_write_chapter",
            },
        )
        with build_opener(ProxyHandler({})).open(request) as response:
            written = json.loads(response.read())
        reference = written["operation_trace"]
        assert reference["model_call_count"] == 1
        trace_file = tmp_path / "data" / "novels" / "demo" / reference["path"]
        raw = trace_file.read_text(encoding="utf-8")
        assert "写作时的私密指令" not in raw
        assert "不要泄露的作者指令" not in raw
        assert "模型输出中的秘密正文" not in raw
        trace = json.loads(raw)
        assert trace["request"]["tool_call_id"] == "call_write"
        assert trace["request"]["tool_name"] == "novel_write_chapter"
        assert trace["context"]["chapter_id"] == "ch_001"
        assert trace["context"]["packet_revision"]
        assert trace["model_calls"][0]["operation"] == "chapter_write"
        assert trace["domain_change"]["operation"] == "manuscript.create"
        assert trace["domain_change"]["execution_status"] == "committed"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

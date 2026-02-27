"""Phase 7B Web 应用测试 — FastAPI 页面路由 + REST API。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pathlib import Path

from tools.web import create_app


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    """创建测试用 FastAPI 客户端（使用临时项目目录）。"""
    # 初始化最小项目结构
    novel_id = "test_novel"
    base = tmp_path / "data" / "novels" / novel_id
    for sub in [
        "outline/chapters",
        "characters/cards",
        "characters/profiles",
        "characters/timeline/logs",
        "foreshadowing/logs",
        "world",
        "style",
        "manuscript",
    ]:
        (base / sub).mkdir(parents=True, exist_ok=True)

    app = create_app(project_dir=tmp_path, novel_id=novel_id)
    return TestClient(app)


# ══════════════════════════════════════════════════════════════════════
# 1. 页面路由测试
# ══════════════════════════════════════════════════════════════════════


class TestPageRoutes:
    """所有页面应返回 200 + HTML。"""

    def test_dashboard(self, client: TestClient):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "项目概览" in resp.text

    def test_timeline(self, client: TestClient):
        resp = client.get("/timeline")
        assert resp.status_code == 200
        assert "叙事时间线" in resp.text

    def test_world(self, client: TestClient):
        resp = client.get("/world")
        assert resp.status_code == 200
        assert "世界观图谱" in resp.text

    def test_characters(self, client: TestClient):
        resp = client.get("/characters")
        assert resp.status_code == 200
        assert "人物档案" in resp.text

    def test_foreshadowing(self, client: TestClient):
        resp = client.get("/foreshadowing")
        assert resp.status_code == 200
        assert "伏笔" in resp.text

    def test_style(self, client: TestClient):
        resp = client.get("/style")
        assert resp.status_code == 200
        assert "风格系统" in resp.text

    def test_editor(self, client: TestClient):
        resp = client.get("/editor")
        assert resp.status_code == 200
        assert "编辑器" in resp.text

    def test_static_css(self, client: TestClient):
        resp = client.get("/static/css/main.css")
        assert resp.status_code == 200
        assert "sidebar" in resp.text


# ══════════════════════════════════════════════════════════════════════
# 2. REST API 测试
# ══════════════════════════════════════════════════════════════════════


class TestRestAPI:
    """REST API 端点测试。"""

    def test_api_stats(self, client: TestClient):
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "novel_id" in data
        assert "entities" in data
        assert "characters" in data

    def test_api_world_entities_empty(self, client: TestClient):
        resp = client.get("/api/world/entities")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_api_world_relations_empty(self, client: TestClient):
        resp = client.get("/api/world/relations")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_api_world_check(self, client: TestClient):
        resp = client.get("/api/world/check")
        assert resp.status_code == 200
        data = resp.json()
        assert "is_valid" in data
        assert data["is_valid"] is True

    def test_api_characters_empty(self, client: TestClient):
        resp = client.get("/api/characters")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_api_character_not_found(self, client: TestClient):
        resp = client.get("/api/characters/不存在的人")
        assert resp.status_code == 404

    def test_api_foreshadowing_empty(self, client: TestClient):
        resp = client.get("/api/foreshadowing")
        assert resp.status_code == 200
        data = resp.json()
        assert "nodes" in data
        assert data["nodes"] == []

    def test_api_foreshadowing_stats(self, client: TestClient):
        resp = client.get("/api/foreshadowing/statistics")
        assert resp.status_code == 200

    def test_api_docs(self, client: TestClient):
        resp = client.get("/api/docs")
        assert resp.status_code == 200

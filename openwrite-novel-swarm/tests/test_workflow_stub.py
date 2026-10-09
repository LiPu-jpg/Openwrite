"""Stub-based harness test for openwrite-novel-swarm/scripts/workflow.py.

注入 fake swarmflow 模块，用预设的 LLM 响应端到端驱动 run()，
覆盖：全通过、修订回炉、HITL 门、仅评审模式、回炉耗尽五种场景。
运行：python3 tests/test_workflow_stub.py
"""
import asyncio
import importlib.util
import json
import sys
import types

SKILL_DIR = "/Users/jiaoziang/openjiu/openwrite-novel-swarm"
WORKFLOW_PATH = SKILL_DIR + "/scripts/workflow.py"

CHAPTER = "第1章 测试章节正文。" * 120  # >500 chars


# ---------------------------------------------------------------------------
# Fake swarmflow runtime
# ---------------------------------------------------------------------------

class FakeSwarmflow(types.ModuleType):
    def __init__(self, responder):
        super().__init__("swarmflow")
        self.responder = responder
        self.phases = []
        self.logs = []
        self.calls = []

    def phase(self, title):
        self.phases.append(title)

    def log(self, message):
        self.logs.append(str(message))

    async def agent(self, prompt, label=None, phase=None, schema=None):
        self.calls.append({"label": label, "phase": phase})
        return self.responder(label=label, prompt=prompt, schema=schema)

    async def parallel(self, thunks):
        results = []
        for t in thunks:
            results.append(await t())
        return results


def load_workflow(responder):
    fake = FakeSwarmflow(responder)
    sys.modules["swarmflow"] = fake
    spec = importlib.util.spec_from_file_location("openwrite_workflow_under_test", WORKFLOW_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, fake


# ---------------------------------------------------------------------------
# Responder factories
# ---------------------------------------------------------------------------

def ok_planner(**_):
    return json.dumps({
        "verdict": "READY-FOR-GATE", "characters": 3, "chapter_count": 5,
        "promises_registered": True, "asset_pack": "资产包内容", "notes": "ok",
    })


def ok_writer(**_):
    return json.dumps({
        "verdict": "DELIVERED", "conflicts": 0,
        "chapter_text": CHAPTER, "state_updates": "truth:...",
    })


def review_pass(label, **_):
    scores = {
        "reviewer-canon": {"coherence": 8, "canon": 8},
        "reviewer-drama": {"plot": 8, "pacing": 7},
        "reviewer-prose": {"character": 8, "style": 8},
    }
    return json.dumps({"verdict": "PASS", "blockers": 0,
                       "domain_scores": scores[label], "findings": "", "summary": "ok"})


def review_fail_drama_once():
    state = {"n": 0}

    def responder(label, **_):
        if label == "reviewer-drama" and state["n"] == 0:
            state["n"] += 1
            return json.dumps({"verdict": "NEEDS-REVISION", "blockers": 1,
                               "domain_scores": {"plot": 4, "pacing": 6},
                               "findings": "核心承诺未兑现", "summary": "plot weak"})
        return review_pass(label)

    return responder


def review_always_fail(label, **_):
    scores = {
        "reviewer-canon": {"coherence": 8, "canon": 8},
        "reviewer-drama": {"plot": 3, "pacing": 6},
        "reviewer-prose": {"character": 8, "style": 8},
    }
    return json.dumps({"verdict": "NEEDS-REVISION", "blockers": 1,
                       "domain_scores": scores[label], "findings": "f", "summary": "bad"})


def ok_revision(**_):
    return json.dumps({"verdict": "APPLIED", "applied": 2, "hard_blocks": 0,
                       "diff_summary": "两处修订"})


def chain(*responders):
    def combined(**kwargs):
        for r in responders:
            out = r(**kwargs)
            if out is not None:
                return out
        return None
    return combined


def by_label(mapping, default=None):
    def responder(label, **kwargs):
        fn = mapping.get(label, default)
        return fn(label=label, **kwargs) if fn else None
    return responder


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

PASS_COUNT = [0]
FAIL_COUNT = [0]


def check(name, cond, detail=""):
    if cond:
        PASS_COUNT[0] += 1
        print("PASS  " + name)
    else:
        FAIL_COUNT[0] += 1
        print("FAIL  " + name + ("  -- " + detail if detail else ""))


async def scenario_happy():
    wf, fake = load_workflow(by_label({
        "goethe-planner": ok_planner,
        "dante-writer": ok_writer,
        "reviewer-canon": review_pass,
        "reviewer-drama": review_pass,
        "reviewer-prose": review_pass,
    }))
    result = await wf.run(json.dumps({"author_intent": "一部短篇悬疑小说"}))
    check("happy: delivered", result["status"] == "delivered", result["status"])
    check("happy: 6 domains scored", len(result["domain_scores"]) == 6)
    check("happy: no rework", result["revision_history"] == [])
    check("happy: phase order", fake.phases == ["规划资产包", "章节写作", "六域并行评审",
                                                "聚合判定", "修订与复评", "交付结算"],
          str(fake.phases))
    labels = [c["label"] for c in fake.calls]
    check("happy: agents dispatched once each",
          labels.count("goethe-planner") == 1 and labels.count("dante-writer") == 1
          and labels.count("reviewer-canon") == 1 and labels.count("reviewer-drama") == 1
          and labels.count("reviewer-prose") == 1 and "revision-forge" not in labels,
          str(labels))


async def scenario_rework():
    wf, fake = load_workflow(by_label({
        "goethe-planner": ok_planner,
        "dante-writer": ok_writer,
        "reviewer-canon": review_pass,
        "reviewer-drama": review_fail_drama_once(),
        "reviewer-prose": review_pass,
        "revision-forge": ok_revision,
    }))
    result = await wf.run(json.dumps({"author_intent": "悬疑"}))
    check("rework: delivered after 1 round", result["status"] == "delivered", result["status"])
    check("rework: 1 revision round", len(result["revision_history"]) == 1)
    labels = [c["label"] for c in fake.calls]
    check("rework: revision-forge ran once", labels.count("revision-forge") == 1, str(labels))
    check("rework: drama re-reviewed once",
          [c["label"] for c in fake.calls].count("reviewer-drama") == 2, str(labels))
    check("rework: canon/prose not re-dispatched",
          labels.count("reviewer-canon") == 1 and labels.count("reviewer-prose") == 1)


async def scenario_gate():
    wf, fake = load_workflow(by_label({"goethe-planner": ok_planner}))
    result = await wf.run(json.dumps({"author_intent": "悬疑", "outline_approved": False}))
    check("gate: awaiting OUTLINE-FINAL",
          result["status"] == "awaiting_gate" and result["gate"] == "OUTLINE-FINAL")
    check("gate: writer not dispatched", all(c["label"] != "dante-writer" for c in fake.calls))


async def scenario_review_only():
    def responder(label, **_):
        return review_pass(label)

    wf, fake = load_workflow(responder)
    result = await wf.run(json.dumps({"chapter_text": CHAPTER}))
    check("review-only: delivered", result["status"] == "delivered", result["status"])
    check("review-only: planner/writer skipped",
          all(c["label"] not in ("goethe-planner", "dante-writer") for c in fake.calls),
          str([c["label"] for c in fake.calls]))


async def scenario_exhausted():
    wf, fake = load_workflow(by_label({
        "goethe-planner": ok_planner,
        "dante-writer": ok_writer,
        "reviewer-canon": review_pass,
        "reviewer-drama": review_always_fail,
        "reviewer-prose": review_pass,
        "revision-forge": ok_revision,
    }))
    result = await wf.run(json.dumps({"author_intent": "悬疑", "max_rework_rounds": 2}))
    check("exhausted: delivered-with-blockers",
          result["status"] == "delivered-with-blockers", result["status"])
    check("exhausted: 2 rounds max", len(result["revision_history"]) == 2)
    check("exhausted: blocker flag present",
          any("DELIVERED-WITH-BLOCKERS" in f for f in result["flags"]))


async def scenario_planner_retry():
    state = {"n": 0}

    def flaky_planner(**_):
        state["n"] += 1
        if state["n"] == 1:
            return json.dumps({"verdict": "NEEDS-MORE-WORK", "characters": 0,
                               "chapter_count": 0, "promises_registered": False,
                               "asset_pack": "", "notes": "draft"})
        return ok_planner()

    wf, fake = load_workflow(by_label({
        "goethe-planner": flaky_planner,
        "dante-writer": ok_writer,
        "reviewer-canon": review_pass,
        "reviewer-drama": review_pass,
        "reviewer-prose": review_pass,
    }))
    result = await wf.run(json.dumps({"author_intent": "悬疑"}))
    check("retry: planner retried then delivered", result["status"] == "delivered",
          result.get("status"))


async def main():
    await scenario_happy()
    await scenario_rework()
    await scenario_gate()
    await scenario_review_only()
    await scenario_exhausted()
    await scenario_planner_retry()
    print("---")
    print("passed=%d failed=%d" % (PASS_COUNT[0], FAIL_COUNT[0]))
    sys.exit(1 if FAIL_COUNT[0] else 0)


if __name__ == "__main__":
    asyncio.run(main())

"""Real-model smoke test for openwrite-novel-swarm/scripts/workflow.py.

注入"真实模型版" swarmflow 模块：agent() 直接调用 OpenAI 兼容接口（默认 DeepSeek），
其余与桩件测试同构。覆盖一次完整单章流水线：规划 → 写作 → 三评审并行 → 聚合 →
（如需）修订复评 → 交付结算。

运行（需环境变量 API_BASE / API_KEY / MODEL_NAME）：
    export API_BASE=https://api.deepseek.com API_KEY=sk-... MODEL_NAME=deepseek-chat
    python tests/smoke_real_model.py
产物：tests/smoke_real_output.json（含各角色原始输出与用量统计）
"""
import asyncio
import importlib.util
import json
import os
import sys
import time
import types

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW_PATH = os.path.join(SKILL_DIR, "scripts", "workflow.py")

API_BASE = os.environ["API_BASE"].rstrip("/")
API_KEY = os.environ["API_KEY"]
MODEL = os.environ.get("MODEL_NAME", "deepseek-chat")

USAGE = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "seconds": 0.0}


# ---------------------------------------------------------------------------
# Real-model swarmflow runtime
# ---------------------------------------------------------------------------

class RealSwarmflow(types.ModuleType):
    def __init__(self):
        super().__init__("swarmflow")
        try:
            from openai import AsyncOpenAI
        except ImportError:
            print("FATAL: 需要 openai 包（venv-swarm 已装）")
            raise
        self.client = AsyncOpenAI(base_url=API_BASE, api_key=API_KEY, timeout=300)
        self.phases = []
        self.logs = []

    def phase(self, title):
        self.phases.append(title)
        print(f"\n=== PHASE: {title} ===", flush=True)

    def log(self, message):
        self.logs.append(str(message))
        print(f"  [log] {message}", flush=True)

    async def agent(self, prompt, label=None, phase=None, schema=None):
        USAGE["calls"] += 1
        t0 = time.time()
        print(f"  -> {label} ...", end="", flush=True)
        resp = await self.client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=4000,
        )
        el = time.time() - t0
        USAGE["seconds"] += el
        u = resp.usage
        USAGE["prompt_tokens"] += u.prompt_tokens
        USAGE["completion_tokens"] += u.completion_tokens
        text = resp.choices[0].message.content or ""
        print(f" {el:.1f}s, {u.completion_tokens} tok out", flush=True)
        return text

    async def parallel(self, thunks):
        return list(await asyncio.gather(*[t() for t in thunks]))


def load_workflow():
    fake = RealSwarmflow()
    sys.modules["swarmflow"] = fake
    spec = importlib.util.spec_from_file_location("openwrite_workflow_real_smoke", WORKFLOW_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, fake


async def main():
    workflow, rt = load_workflow()
    args = {
        "author_intent": (
            "微型悬疑短篇《夜班便利店》，共 3 章：深夜店员小周发现冰柜里"
            "多出一具'尸体'，报警后尸体却消失；第 2 章追查监控发现'尸体'"
            "每晚同一时间出现；第 3 章反转——那是隔壁剧本杀店的直播道具，"
            "但小周在道具手里发现了真人的求救纸条，开放式收尾。"
        ),
        "genre_constraints": "现代都市悬疑短篇；每章 600-1000 字；单主角视角",
        "existing_assets": "",
        "outline_approved": True,
        "revision_approved": True,
        "max_rework_rounds": 2,
    }
    result = await workflow.run(args)

    out_path = os.path.join(SKILL_DIR, "tests", "smoke_real_output.json")
    payload = {
        "model": MODEL,
        "args": args,
        "result": result,
        "runtime": {"phases": rt.phases, "logs": rt.logs},
        "usage": USAGE,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("\n===== RESULT =====")
    print("status:", result.get("status"))
    for k in ("failed_at", "gate", "verdict", "judgement", "domain_scores", "rounds"):
        if k in result:
            print(f"{k}: {result[k]}")
    print("usage:", json.dumps(USAGE))
    print("output:", out_path)


if __name__ == "__main__":
    asyncio.run(main())

"""Calls GLM for routing measurements; never executes selected tools."""
import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path
from cloud.agent.client import GLMAgent

CASES = [
    ("你叫什么名字？", "respond_text"),
    ("为什么天空是蓝色的？简单说一下。", "respond_text"),
    ("帮我查一下深圳今天的天气。", "get_weather"),
    ("看看我手里拿的是什么。", "request_vision"),
    ("帮我播放周杰伦的晴天。", "play_music"),
    ("请去厨房。", "navigate_to"),
]

async def benchmark(runs=3, quick=False):
    agent = GLMAgent(Path(__file__).resolve().parents[1] / "configs/agent.yaml")
    agent.client = agent.client.with_options(max_retries=0, timeout=25)
    results = []
    try:
        for run in range(runs):
            for query, expected in (CASES[:1] if quick else CASES):
                modes = ("tool", "json") if run % 2 == 0 else ("json", "tool")
                for mode in modes:
                    agent.route_protocol = mode
                    started = time.monotonic()
                    row = {"run": run + 1, "protocol": mode, "query": query, "expected": expected}
                    try:
                        route = await agent._route(query, [], "uncertain")
                        row.update(action=route["action"], correct=route["action"] == expected)
                    except Exception as exc:
                        row.update(error=type(exc).__name__, correct=False)
                    row["seconds"] = round(time.monotonic() - started, 4)
                    results.append(row)
                    print(json.dumps(row, ensure_ascii=False), flush=True)
    finally:
        await agent.client.close()
    for mode in ("tool", "json"):
        rows = [r for r in results if r["protocol"] == mode]
        print(json.dumps({"protocol": mode, "samples": len(rows),
                          "correct": sum(r["correct"] for r in rows),
                          "median_seconds": statistics.median(r["seconds"] for r in rows)},
                         ensure_ascii=False), flush=True)
    return results

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.runs <= 10:
        parser.error("--runs must be between 1 and 10")
    asyncio.run(benchmark(args.runs, args.quick))

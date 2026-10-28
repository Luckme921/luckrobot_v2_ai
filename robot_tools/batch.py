"""Bounded tool plans: independent resources run concurrently, shared ones in order."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
import json
import re

from robot_tools.catalog import LOCAL_SCHEMAS, TOOL_SCHEMAS
from robot_tools.registry import validate

REMOTE_SCHEMAS = {t["function"]["name"]: t["function"]["parameters"]
                  for t in TOOL_SCHEMAS
                  if t["function"]["name"] in {"get_weather", "web_search", "navigate_to", "navigation_control"}}
BATCH_SCHEMAS = {**LOCAL_SCHEMAS, **REMOTE_SCHEMAS}


def needs_semantic_route(text):
    # Only bypass local shortcuts; the model still decides whether/how to act.
    domains = (
        r"导航|建图|底盘|探索|地图",
        r"风扇|灯光|灯效|呼吸灯|彩虹灯",
        r"音乐|歌曲|播放|放一首|想听|换歌|暂停",
        r"音量|大声|小声",
        r"天气|气温|下雨",
        r"搜索|查一下|查一查|摄像头|看看",
    )
    count = sum(bool(re.search(pattern, text)) for pattern in domains)
    return count >= 2 or (count >= 1 and bool(re.search(r"并且|同时|顺便|然后|再把|以及|还要|并把", text)))


def validate_plan(requests):
    if not isinstance(requests, list) or not 1 <= len(requests) <= 4:
        raise ValueError("tool plan must contain one to four actions")
    seen = set()
    music_count = 0
    navigation_count = 0
    for request in requests:
        if not isinstance(request, dict) or set(request) != {"name", "arguments"}:
            raise ValueError("invalid tool plan entry")
        name = request["name"]
        if not isinstance(name, str) or name not in BATCH_SCHEMAS:
            raise ValueError("unknown batch tool")
        validate(request["arguments"], BATCH_SCHEMAS[name])
        arguments = request["arguments"]
        if name == "fan_light_control":
            if arguments["action"] == "set_speed" and "percent" not in arguments:
                raise ValueError("fan speed requires percent")
            if arguments["action"] == "set_light":
                mode = arguments.get("mode")
                if mode not in {"static", "breath", "rainbow"}:
                    raise ValueError("light requires mode")
                rgb = [key in arguments for key in ("red", "green", "blue")]
                if (mode == "rainbow" and any(rgb)) or (mode != "rainbow" and not all(rgb)):
                    raise ValueError("invalid light RGB")
        if name == "volume_control" and arguments["action"] == "set" and "percent" not in arguments:
            raise ValueError("volume set requires percent")
        fingerprint = json.dumps(request, sort_keys=True, ensure_ascii=False)
        if fingerprint in seen:
            raise ValueError("duplicate tool action")
        seen.add(fingerprint)
        music_count += name.startswith("music_")
        navigation_count += name in {"navigation_control", "navigate_to"}
    if navigation_count > 1:
        raise ValueError("navigation mode changes require separate confirmed turns")
    if music_count > 1:
        raise ValueError("dependent/conflicting music actions need separate turns")


def execute_plan(requests, execute, cancellation=None):
    """Validate every action before starting; failures do not hide other results."""
    validate_plan(requests)
    groups = {}
    for index, request in enumerate(requests):
        name = request["name"]
        resource = "audio" if name.startswith("music_") or name == "volume_control" else name
        groups.setdefault(resource, []).append((index, request))
    results = [None] * len(requests)

    def run(items):
        for index, request in items:
            if cancellation is not None and cancellation.event.is_set():
                results[index] = {"tool": request["name"], "ok": False, "executed": False,
                                  "status": "cancelled", "message": "该操作尚未执行，已被打断。"}
                continue
            print("[TOOL_REQUEST] source=model_batch name=" + request["name"] +
                  " arguments=" + json.dumps(request["arguments"], ensure_ascii=False), flush=True)
            try:
                result = execute(request["name"], request["arguments"])
            except Exception as exc:
                print(f"[TOOL_BATCH] failed={type(exc).__name__} tool={request['name']}", flush=True)
                result = {"ok": False, "executed": False, "status": "error",
                          "message": "这个操作未完成，请稍后再试。"}
            results[index] = {"tool": request["name"], **result}
    with ThreadPoolExecutor(max_workers=min(4, len(groups)), thread_name_prefix="tool-plan") as pool:
        futures = [pool.submit(copy_context().run, run, items) for items in groups.values()]
        for future in futures:
            future.result()
    return results


def result_message(result):
    if result.get("message"):
        return str(result["message"])
    name = result.get("tool")
    if name == "get_weather" and result.get("ok"):
        current = result.get("current", {})
        daily = result.get("daily", {})
        text = f"{result.get('location', '当地')}当前气温{current.get('temperature_2m', '未知')}度。"
        for i, day in enumerate(daily.get("time", [])):
            low = daily.get("temperature_2m_min", [])
            high = daily.get("temperature_2m_max", [])
            if i < len(low) and i < len(high):
                text += f"{day}最低{low[i]}度，最高{high[i]}度。"
        return text
    if name == "web_search" and result.get("ok"):
        titles = [str(x.get("title", "")) for x in result.get("results", [])[:3]]
        return "搜索结果：" + "；".join(x for x in titles if x) if any(titles) else "没有找到相关搜索结果。"
    if name == "navigate_to":
        return "当前接口不支持前往语义地点，未移动机器人。"
    return "这个操作未完成，请稍后再试。"

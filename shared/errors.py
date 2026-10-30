"""Safe diagnostic fields: never log provider messages, request bodies or secrets."""
import json
import re
from shared.timing import trace_id


def error_info(exc):
    original = exc
    chain, visited = [], set()
    while exc is not None and id(exc) not in visited:
        visited.add(id(exc))
        chain.append(exc)
        exc = getattr(exc, "__cause__", None)
    exc = next((item for item in chain if hasattr(item, "body") or
                hasattr(item, "status_code") and type(item).__name__ != "HTTPException"), chain[-1])
    body = getattr(exc, "body", None)
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        body = body["error"]
    code = str(body.get("code", "")) if isinstance(body, dict) else ""
    # SDK streaming errors sometimes store code on the exception itself.
    code = code or str(getattr(exc, "code", "") or "")
    status = getattr(exc, "status_code", None)
    raw = (type(exc).__name__ + " " + code + " " + str(exc)).lower()
    if any(x in raw for x in ("insufficient_quota", "arrearage", "1113", "余额不足", "quota_exhausted")):
        reason = "quota_exhausted"
    elif any(x in raw for x in ("data_inspection", "datainspection", "content_filter", "inappropriate", "sensitive_content")):
        reason = "content_rejected"
    elif status == 429 or "ratelimit" in raw or "throttling" in raw:
        reason = "rate_limited"
    elif status in (401, 403) or "authentication" in raw:
        reason = "authentication"
    elif "timeout" in raw or "timed out" in raw:
        reason = "timeout"
    elif "connection" in raw or "urlerror" in raw or "ssl" in raw:
        reason = "network"
    elif status == 400:
        reason = "invalid_request"
    elif isinstance(exc, ValueError) or "empty content" in raw or "empty reply" in raw:
        reason = "invalid_response"
    else:
        reason = "unavailable"
    detail = getattr(original, "detail", None)
    if isinstance(detail, dict) and detail.get("reason") in ERROR_MESSAGES:
        reason = detail["reason"]
    elif "1113" in str(detail) or "余额不足" in str(detail):
        reason = "quota_exhausted"
    clean = lambda s: str(s)[:100] if re.fullmatch(r"[a-zA-Z0-9_.:-]{1,100}", str(s or "")) else ""
    return {"reason": reason, "type": type(exc).__name__,
            "status": status if type(status) is int else None,
            "code": clean(code), "request_id": clean(getattr(exc, "request_id", ""))}


ERROR_MESSAGES = {
    "quota_exhausted": "大模型账户余额不足或没有可用资源包，请检查后再试。",
    "rate_limited": "模型服务当前请求较多，请稍后再试。",
    "authentication": "模型接口认证或访问权限异常，请检查配置。",
    "timeout": "模型服务响应超时了，请稍后再试。",
    "network": "连接模型服务失败了，请检查网络后再试。",
    "content_rejected": "模型服务未接受这次对话内容，暂时无法回答。",
    "invalid_request": "模型接口拒绝了请求参数，需要检查配置。",
    "invalid_response": "模型返回的内容不完整，请再试一次。",
    "unavailable": "刚才处理请求失败了，请稍后再试。",
}


def log_error(exc, stage):
    info = error_info(exc)
    print("[AGENT_ERROR] " + json.dumps(
        {"trace_id": trace_id.get(), "stage": stage, **info}, ensure_ascii=False), flush=True)
    return info

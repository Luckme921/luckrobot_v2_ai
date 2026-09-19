"""Navigation adapter. Replace this mock with a high-level ROS2 action only."""
def navigate_to(arguments):
    location = str(arguments.get("location", "")).strip()
    if not location:
        return {"ok": False, "tool": "navigate_to", "status": "rejected",
                "executed": False, "reason": "missing_location"}
    return {"ok": True, "tool": "navigate_to", "status": "mock_accepted",
            "executed": False, "location": location, "backend": "mock",
            "message": f"已收到前往{location}的导航请求。当前仅完成 Tool Router 模拟调用，ROS2 导航执行尚未连接。"}

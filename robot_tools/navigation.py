"""Model tools only request approved modes; motion confirmation belongs to local UI."""
from edge.navigation import bridge
from edge.navigation.state import TOOL_COMMANDS


def navigate_to(arguments):
    return {"ok": False, "tool": "navigate_to", "status": "unsupported", "executed": False,
            "message": "当前已接入 ROS 建图与模式控制，但尚未启用 Nav2 目标阶段和语义地点配置，不能前往该地点。"}


def navigation_control(arguments):
    command = arguments.get("command")
    if command not in TOOL_COMMANDS:
        return {"ok": False, "tool": "navigation_control", "executed": False,
                "message": "此操作未提供给语音工具。"}
    if command == "status":
        status = bridge.status()
        system = status.get("system", {})
        message = (f"小脑软件状态：{system.get('state', '未知')}；"
                   f"底盘状态：{status.get('state', '未知')}。")
        if not system.get("fresh"):
            message += "监督状态已过期或通信尚未建立。"
        elif not status.get("fresh"):
            message += "底盘管理器尚未就绪；软件启动不代表定位完成。"
        if status.get("reason"):
            message += f"原因：{status['reason']}。"
        return {"tool": "navigation_control", "ok": bool(system.get("fresh")),
                "executed": False, "navigation": status, "message": message}
    return {"tool": "navigation_control", **bridge.request(command)}

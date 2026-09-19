"""Volume tool: the LLM and local command parser use this same function."""
from edge.audio.volume import VolumeCommand, volume_reply

def volume_control(controller, action, percent=None):
    if action == "set" and percent is None:
        return {"ok": False, "status": "rejected", "executed": False,
                "message": "请告诉我要把音量调到百分之几。"}
    command = VolumeCommand(action, percent)
    value = controller.execute(command)
    return {"ok": True, "status": "success", "executed": True,
            "percent": value, "message": volume_reply(command, value)}

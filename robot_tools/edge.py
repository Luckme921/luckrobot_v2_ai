"""Assemble device tools with injected hardware controllers."""
from functools import partial
from robot_tools.catalog import LOCAL_SCHEMAS
from robot_tools.registry import ToolRegistry
from robot_tools.volume import volume_control
from robot_tools.fan_light import fan_light_control

def build_edge_tools(volume, music, fan_light=None):
    registry = ToolRegistry()
    registry.register("volume_control", LOCAL_SCHEMAS["volume_control"], partial(volume_control, volume))
    registry.register("music_search", LOCAL_SCHEMAS["music_search"], music.search)
    registry.register("music_select", LOCAL_SCHEMAS["music_select"], music.select)
    registry.register("music_control", LOCAL_SCHEMAS["music_control"], music.control)
    if fan_light is not None:
        registry.register("fan_light_control", LOCAL_SCHEMAS["fan_light_control"],
                          partial(fan_light_control, fan_light))
    return registry

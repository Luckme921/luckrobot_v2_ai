"""Named colors from the checked-in 天天配色网 Chinese color table."""

from functools import lru_cache
import json
from pathlib import Path


COLOR_ALIASES = {'绿色': '绿', '紫色': '紫', '白色': '白', '黑色': '黒'}


@lru_cache(maxsize=1)
def color_table():
    path = Path(__file__).with_name('chinese_colors.json')
    rows = json.loads(path.read_text(encoding='utf-8'))['colors']
    return {row['name']: row['hex'] for row in rows}


def color_rgb(name):
    value = color_table().get(COLOR_ALIASES.get(name, name))
    if value is None:
        raise ValueError(f'未知颜色名：{name}')
    value = value.lstrip('#')
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def has_color(name):
    return COLOR_ALIASES.get(name, name) in color_table()

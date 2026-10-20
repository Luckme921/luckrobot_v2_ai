"""Named colors from the checked-in 天天配色网 Chinese color table."""

from functools import lru_cache
import json
from pathlib import Path


COLOR_ALIASES = {'绿色': '绿', '紫色': '紫', '白色': '白', '黑色': '黒'}


@lru_cache(maxsize=1)
def color_table():
    path = Path(__file__).with_name('chinese_colors.json')
    rows = json.loads(path.read_text(encoding='utf-8'))['colors']
    table = {}
    for row in rows:
        table.setdefault(row['name'], []).append(row['hex'])
    return table


def color_rgb(name):
    values = color_table().get(COLOR_ALIASES.get(name, name))
    if not values:
        raise ValueError(f'未知颜色名：{name}')
    distinct = sorted(set(values))
    if len(distinct) != 1:
        raise ValueError(f'{name}有多个色值：{", ".join(distinct)}；请指定 RGB 数值')
    value = distinct[0].lstrip('#')
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def is_unambiguous_color(name):
    values = color_table().get(COLOR_ALIASES.get(name, name), ())
    return len(set(values)) == 1

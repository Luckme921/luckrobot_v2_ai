"""Best-effort read-only navigation speech; never controls motion."""
import json
import math
import time
from collections import deque
from edge.navigation.bridge import RUNTIME

EVENT = RUNTIME / 'feedback-event.json'
TEXTS = {
 'OBSTACLE_LIMITING': '检测到碰撞风险，正在限制运动。',
 'LOCAL_PATH_BLOCKED': '暂时没有安全的通行轨迹，请留意周围环境。',
 'PLANNING_FAILED': '暂时无法规划到目标的路线。',
 'GOAL_OUTSIDE_MAP': '目标点在当前地图范围之外。',
 'MOTION_NOT_FOLLOWING': '运动反馈未跟上指令，正在等待重新规划。',
 'TF_UNAVAILABLE': '定位转换暂时不可用。',
 'TF_STALE': '定位转换数据已过期。',
 'DATA_TIME_INVALID': '导航数据时间异常。',
 'STOP_REASON_UNKNOWN': '机器人暂时未移动，具体原因尚未确认。',
 'MOTION_RESUMED': '机器人已恢复运动。',
 'GOAL_SUCCEEDED': '已到达目标。',
 'GOAL_CANCELED': '导航任务已取消。',
 'GOAL_ABORTED': '本次导航未能完成，请检查最新故障信息。',
}

class FeedbackSpeech:
    def __init__(self):
        self.seen = deque(maxlen=256)
        self.last = -math.inf
        self.poll_at = 0

    def take(self, ready=True):
        now = time.monotonic()
        if now < self.poll_at:
            return None
        self.poll_at = now + .5
        try:
            item = json.loads(EVENT.read_text(encoding='utf-8'))
            age = time.time() - float(item['observed_unix'])
            ttl = min(10., float(item['ttl_sec']))
            ident = item['event_id']
            code = item['code']
            if item.get('schema') != 1 or not isinstance(ident, str) or code not in TEXTS:
                return None
            if not math.isfinite(age) or not 0 <= age <= ttl or ident in self.seen:
                return None
            if not ready or now - self.last < 8:
                return None
            self.seen.append(ident)
            self.last = now
            return TEXTS[code]
        except (OSError, ValueError, KeyError, TypeError):
            return None

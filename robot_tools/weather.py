"""Open-Meteo weather with explicit location disambiguation and bounded GET retries."""
import json
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from robot_tools.registry import validate
from shared.timing import measure, trace_id


def _get(url, params):
    stage = "geocoding" if "geocoding-api." in url else "forecast"
    req = Request(url + "?" + urlencode(params), headers={"User-Agent": "LuckRobot/1.0"})
    for attempt in range(1, 3):
        started = time.monotonic()
        try:
            with urlopen(req, timeout=5) as response:
                raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise ValueError("Weather response too large")
            data = json.loads(raw)
            if not isinstance(data, dict) or data.get("error"):
                raise ValueError("Weather provider returned invalid data")
            print(f"[WEATHER_HTTP] trace_id={trace_id.get()} stage={stage} "
                  f"attempt={attempt} seconds={time.monotonic()-started:.3f} status=ok", flush=True)
            return data
        except (OSError, ValueError) as exc:
            status = getattr(exc, "code", None)
            transient = (isinstance(exc, (TimeoutError, socket.timeout, URLError))
                         and not isinstance(exc, HTTPError)) or (
                             isinstance(exc, HTTPError) and status in {429, 502, 503, 504})
            print(f"[WEATHER_HTTP] trace_id={trace_id.get()} stage={stage} attempt={attempt} "
                  f"seconds={time.monotonic()-started:.3f} status=error "
                  f"type={type(exc).__name__} http_status={status}", flush=True)
            if attempt == 2 or not transient:
                raise
            time.sleep(0.2)


def _region_key(text):
    return str(text or "").replace("省", "").replace("市", "").strip()


def get_weather(city, days=1, region=""):
    from robot_tools.catalog import WEATHER_SCHEMA
    try:
        validate({"city": city, "days": days, "region": region}, WEATHER_SCHEMA)
    except ValueError:
        return {"ok": False, "tool": "get_weather", "executed": False,
                "status": "rejected", "message": "请提供城市和一到七天的预报范围。"}
    city, region = city.strip(), region.strip()
    if not city:
        return {"ok": False, "tool": "get_weather", "executed": False,
                "status": "needs_input", "message": "你想查询哪个城市的天气？"}
    stage = "geocoding"
    try:
        with measure("weather_geocoding"):
            places = _get("https://geocoding-api.open-meteo.com/v1/search",
                          {"name": city.removesuffix("市"), "count": 10,
                           "language": "zh", "format": "json"}).get("results", [])
        if not isinstance(places, list) or any(not isinstance(p, dict) for p in places):
            raise ValueError("Invalid geocoding result")
        if region:
            places = [p for p in places if any(
                _region_key(region) == _region_key(p.get(key))
                for key in ("admin1", "admin2", "country"))]
        if not places:
            return {"ok": False, "tool": "get_weather", "executed": True,
                    "status": "not_found", "stage": stage,
                    "message": "没有找到这个城市，请提供城市及所在省份或国家。"}
        exact = [p for p in places if p["name"].removesuffix("市") == city.removesuffix("市")]
        choices = exact or places
        if len(choices) > 1:
            return {"ok": False, "tool": "get_weather", "executed": True,
                    "status": "needs_input", "stage": stage,
                    "message": "找到了多个地点，请补充省份或国家。",
                    "locations": [{k: p.get(k) for k in ("name", "admin1", "country")} for p in choices]}
        place = choices[0]
        stage = "forecast"
        with measure("weather_forecast"):
            data = _get("https://api.open-meteo.com/v1/forecast", {
                "latitude": place["latitude"], "longitude": place["longitude"],
                "current": "temperature_2m,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
                "timezone": "auto", "forecast_days": days})
        if not isinstance(data.get("current"), dict) or not isinstance(data.get("daily"), dict):
            raise ValueError("Incomplete weather response")
        return {"ok": True, "tool": "get_weather", "executed": True, "status": "success",
                "source": "Open-Meteo", "location": place["name"],
                "region": place.get("admin1"), "country": place.get("country"),
                "timezone": data.get("timezone"), "current": data.get("current"),
                "current_units": data.get("current_units"), "daily": data.get("daily"),
                "daily_units": data.get("daily_units")}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        timeout = isinstance(exc, (TimeoutError, socket.timeout)) or (
            isinstance(exc, URLError) and isinstance(exc.reason, (TimeoutError, socket.timeout)))
        reason = "timeout" if timeout else "http_error" if isinstance(exc, HTTPError) else (
            "network" if isinstance(exc, OSError) else "invalid_response")
        print(f"[WEATHER_ERROR] trace_id={trace_id.get()} stage={stage} "
              f"type={type(exc).__name__} reason={reason}", flush=True)
        return {"ok": False, "tool": "get_weather", "executed": True,
                "status": "error", "stage": stage, "reason": reason,
                "message": "天气服务连接超时，我现在无法确认天气。" if timeout else
                           "天气服务暂时不可用，我现在无法确认天气。"}

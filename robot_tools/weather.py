"""Open-Meteo geocoding + forecast. No guessed weather on failure."""
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from robot_tools.registry import validate
# Schema is kept here too via lazy import to avoid catalog import cycles.

def _get(url, params):
    req = Request(url + "?" + urlencode(params), headers={"User-Agent": "LuckRobot/1.0"})
    with urlopen(req, timeout=7) as response:
        raw = response.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError("Weather response too large")
    return json.loads(raw)

def get_weather(city, days=1):
    from robot_tools.catalog import WEATHER_SCHEMA
    try:
        validate({"city": city, "days": days}, WEATHER_SCHEMA)
    except ValueError:
        return {"ok": False, "tool": "get_weather", "executed": False,
                "status": "rejected", "message": "请提供城市和一到七天的预报范围。"}
    city = city.strip()
    if not city:
        return {"ok": False, "tool": "get_weather", "executed": False,
                "status": "needs_input", "message": "你想查询哪个城市的天气？"}
    try:
        places = _get("https://geocoding-api.open-meteo.com/v1/search",
                      {"name": city, "count": 3, "language": "zh", "format": "json"}).get("results", [])
        if not places:
            return {"ok": False, "tool": "get_weather", "executed": True,
                    "status": "not_found", "message": "没有找到这个城市，请提供更完整的地名。"}
        # Do not silently guess between equally named places.
        exact = [p for p in places if p["name"].rstrip("市") == city.rstrip("市")]
        choices = exact or places
        if len(choices) > 1:
            return {"ok": False, "tool": "get_weather", "executed": True,
                    "status": "needs_input", "message": "找到了多个地点，请补充省份或国家。",
                    "locations": [{k: p.get(k) for k in ("name", "admin1", "country")} for p in choices]}
        place = choices[0]
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
    except (OSError, ValueError, KeyError, TypeError):
        return {"ok": False, "tool": "get_weather", "executed": True,
                "status": "error", "message": "天气服务暂时不可用，我现在无法确认天气。"}

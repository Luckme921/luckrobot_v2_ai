import json
import unittest
from urllib.error import HTTPError, URLError
from unittest.mock import Mock, patch
from robot_tools.weather import _get, get_weather


class WeatherDiagnosticsTests(unittest.TestCase):
    def test_explicit_region_filters_homonyms(self):
        places = {"results": [
            {"name": "深圳", "admin1": "广东", "latitude": 22, "longitude": 114},
            {"name": "深圳", "admin1": "福建省", "latitude": 25, "longitude": 118}]}
        forecast = {"current": {"temperature_2m": 26}, "daily": {}}
        with patch("robot_tools.weather._get", side_effect=[places, forecast]) as get:
            answer = get_weather("深圳市", region="广东省")
            self.assertTrue(answer["ok"])
            self.assertEqual(get.call_args_list[0].args[1]["name"], "深圳")
            self.assertEqual(get.call_args_list[1].args[1]["latitude"], 22)

    def test_timeout_retains_failed_stage(self):
        with patch("robot_tools.weather._get", side_effect=TimeoutError()):
            answer = get_weather("广州")
        self.assertEqual(answer["stage"], "geocoding")
        self.assertEqual(answer["reason"], "timeout")

    def test_forecast_failure_is_not_reported_as_geocoding(self):
        places = {"results": [{"name": "广州", "latitude": 23, "longitude": 113}]}
        with patch("robot_tools.weather._get", side_effect=[places, ValueError()]):
            answer = get_weather("广州")
        self.assertEqual(answer["stage"], "forecast")

    def test_get_retries_transport_once_but_not_bad_request(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{"results":[]}'
        with patch("robot_tools.weather.urlopen", side_effect=[URLError("down"), response]) as get, patch("robot_tools.weather.time.sleep"):
            self.assertEqual(_get("https://geocoding-api.open-meteo.com/v1/search", {}), {"results": []})
            self.assertEqual(get.call_count, 2)
        bad = HTTPError("url", 400, "bad", {}, None)
        with patch("robot_tools.weather.urlopen", side_effect=bad) as get:
            with self.assertRaises(HTTPError):
                _get("https://geocoding-api.open-meteo.com/v1/search", {})
            self.assertEqual(get.call_count, 1)

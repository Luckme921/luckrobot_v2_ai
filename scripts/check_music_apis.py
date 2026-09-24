"""Probe public music endpoints referenced by wangye.html without playing audio."""
from __future__ import annotations

import argparse
import json
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def request_json(base, parameters, timeout):
    url = base + ("&" if "?" in base else "?") + urlencode(parameters)
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "LuckRobot-API-Check/1.0"})
    started = time.monotonic()
    with urlopen(request, timeout=timeout) as response:
        body = response.read(1_000_001)
        status = response.status
    if len(body) > 1_000_000:
        raise ValueError("response_too_large")
    return json.loads(body), status, time.monotonic() - started


def run_check(name, action):
    started = time.monotonic()
    try:
        details = action()
        return {"name": name, "reachable": True, "seconds": round(time.monotonic() - started, 3), **details}
    except Exception as exc:
        return {"name": name, "reachable": False, "seconds": round(time.monotonic() - started, 3),
                "error": type(exc).__name__, "message": str(exc)[:160]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?", default="周杰伦")
    parser.add_argument("--timeout", type=float, default=12.0)
    args = parser.parse_args()
    query, timeout = args.query, max(1.0, min(args.timeout, 30.0))

    def migu():
        base = "https://api.xcvts.cn/api/music/migu"
        data, status, elapsed = request_json(
            base, {"gm": query, "n": "", "num": 2, "type": "json"}, timeout)
        rows = data.get("data") if isinstance(data, dict) else None
        if data.get("code") != 200 or not isinstance(rows, list):
            raise ValueError("invalid_search_schema")
        playable = False
        if rows:
            detail, _, _ = request_json(
                base, {"gm": query, "n": rows[0].get("n", 1), "num": 2, "type": "json"}, timeout)
            playable = isinstance(detail, dict) and str(detail.get("music_url", "")).startswith("http")
        return {"http_status": status, "search_seconds": round(elapsed, 3),
                "candidates": len(rows), "detail_playable": playable}

    def netease():
        search, status, elapsed = request_json(
            "https://api.vkeys.cn/v2/music/netease",
            {"word": query, "page": 1, "num": 2}, timeout)
        rows = search.get("data") if isinstance(search, dict) else None
        if search.get("code") != 200 or not isinstance(rows, list):
            raise ValueError("invalid_search_schema")
        playable = lyric_ok = False
        if rows:
            song_id = rows[0].get("id")
            detail, _, _ = request_json(
                "https://api.qijieya.cn/meting/", {"type": "song", "id": song_id}, timeout)
            playable = isinstance(detail, list) and bool(detail) and str(detail[0].get("url", "")).startswith("http")
            lyric, _, _ = request_json(
                "https://api.vkeys.cn/v2/music/netease/lyric", {"id": song_id}, timeout)
            lyric_ok = isinstance(lyric, dict) and lyric.get("code") == 200
        return {"http_status": status, "search_seconds": round(elapsed, 3),
                "candidates": len(rows), "detail_playable": playable, "lyric_ok": lyric_ok}

    def qq():
        base = "https://tang.api.s01s.cn/music_open_api.php"
        search, status, elapsed = request_json(base, {"msg": query, "type": "json"}, timeout)
        rows = search.get("data") if isinstance(search, dict) else search
        if not isinstance(rows, list):
            raise ValueError("invalid_search_schema")
        playable = False
        if rows:
            mid = rows[0].get("song_mid")
            detail, _, _ = request_json(base, {"msg": query, "type": "json", "mid": mid}, timeout)
            playable = isinstance(detail, dict) and any(
                str(detail.get(key, "")).startswith("http") for key in
                ("song_play_url_standard", "song_play_url_hq", "song_play_url", "song_play_url_sq"))
        return {"http_status": status, "search_seconds": round(elapsed, 3),
                "candidates": len(rows), "detail_playable": playable}

    def kuwo():
        base = "https://kw-api.cenguigui.cn/"
        search, status, elapsed = request_json(
            base, {"name": query, "page": 1, "limit": 2}, timeout)
        rows = search.get("data") if isinstance(search, dict) else None
        if search.get("code") != 200 or not isinstance(rows, list):
            raise ValueError("invalid_search_schema")
        playable = False
        if rows:
            detail, _, _ = request_json(
                base, {"id": rows[0].get("rid"), "type": "song", "level": "zp", "format": "json"}, timeout)
            payload = detail.get("data") if isinstance(detail, dict) else None
            playable = isinstance(payload, dict) and str(payload.get("url", "")).startswith("http")
        return {"http_status": status, "search_seconds": round(elapsed, 3),
                "candidates": len(rows), "detail_playable": playable}

    report = {
        "query": query,
        "checked_at_epoch": int(time.time()),
        "results": [
            run_check("migu_xcvts", migu),
            run_check("netease_vkeys_qijieya", netease),
            run_check("qq_tang", qq),
            run_check("kuwo_cenguigui", kuwo),
        ],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all(item["reachable"] for item in report["results"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

from functools import wraps

import hashlib
import json
import os
from difflib import SequenceMatcher
from pathlib import Path
import re
import subprocess
import threading
import time
from urllib.parse import quote

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    InvalidSessionIdException,
    NoSuchElementException,
    NoSuchWindowException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from urllib3.exceptions import MaxRetryError, ProtocolError

from edge.audio.device_resolver.pulse import (
    resolve_speaker,
)


class QQMusicError(RuntimeError):
    pass


class QQMusicAuthRequired(QQMusicError):
    """The QQ web player is signed out."""


class QQMusicAmbiguousError(
    QQMusicError
):
    def __init__(
        self,
        query: str,
        candidates: list[str],
    ) -> None:
        self.query = str(query)
        self.candidates = tuple(
            candidates
        )

        super().__init__(
            "QQ Music search is ambiguous: "
            f"query={self.query!r}, "
            f"candidates={self.candidates!r}"
        )


def _driver_locked(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        if method.__name__ in {"search_candidates", "play"} and getattr(self, "_auth_in_progress", False):
            raise QQMusicAuthRequired("QQ 音乐正在等待扫码登录")
        with self._driver_lock:
            try:
                return method(self, *args, **kwargs)
            except (
                InvalidSessionIdException,
                NoSuchWindowException,
                MaxRetryError,
                ProtocolError,
            ) as exc:
                # A desktop-session transition or Firefox crash can leave a
                # live geckodriver object pointing at a dead browser. Search
                # and play can safely start a fresh browser once; transport
                # controls cannot restore their previous playback state.
                self.close()
                if method.__name__ not in {"search_candidates", "play"}:
                    raise QQMusicError(
                        "QQ Music browser session ended; retry the request"
                    ) from exc
                print(
                    f"[MUSIC] QQ_SESSION_RESTART action={method.__name__}",
                    flush=True,
                )
                try:
                    return method(self, *args, **kwargs)
                except (
                    InvalidSessionIdException,
                    NoSuchWindowException,
                    MaxRetryError,
                    ProtocolError,
                ) as retry_exc:
                    self.close()
                    raise QQMusicError(
                        "QQ Music browser session could not be restored"
                    ) from retry_exc

    return wrapped


class QQMusicController:
    HOME_URL = "https://y.qq.com/"

    SEARCH_URL = (
        "https://y.qq.com/n/ryqq/search"
        "?t=song&w={query}"
    )

    PLAYER_PATH = "/player"

    MIN_MATCH_SCORE = 6.0
    AMBIGUITY_MARGIN = 1.0

    def __init__(
        self,
        *,
        profile_path: str | Path,
        firefox_binary: str = "/usr/bin/firefox",
        geckodriver_path: str = (
            "/usr/local/bin/geckodriver"
        ),
        headless: bool = True,
        timeout_seconds: float = 30.0,
        speaker_match_any: (
            list[str] | None
        ) = None,
    ) -> None:
        self.profile_path = Path(
            profile_path
        ).resolve()

        self.firefox_binary = str(
            firefox_binary
        )

        self.geckodriver_path = str(
            geckodriver_path
        )

        self.headless = bool(
            headless
        )

        self.timeout_seconds = float(
            timeout_seconds
        )

        self.speaker_match_any = list(
            speaker_match_any
            or []
        )

        self._driver = None
        self._search_handle = None
        self._driver_lock = (
            threading.RLock()
        )
        self._auth_in_progress = False

    @property
    def running(self) -> bool:
        return self._driver is not None

    def start(self) -> None:
        with self._driver_lock:
            if self._driver is not None:
                return

            if not self.profile_path.exists():
                raise QQMusicError(
                    "QQ Music Firefox profile "
                    f"does not exist: "
                    f"{self.profile_path}"
                )

            options = Options()

            options.binary_location = (
                self.firefox_binary
            )

            if self.headless:
                options.add_argument(
                    "-headless"
                )

            # Options.profile clones the directory into /tmp. Authentication
            # cookies would then disappear when that WebDriver session ends.
            options.add_argument("-profile")
            options.add_argument(str(self.profile_path))

            options.page_load_strategy = (
                "eager"
            )

            options.set_preference(
                "media.autoplay.default",
                0,
            )

            try:
                service = Service(
                    executable_path=(
                        self.geckodriver_path
                    )
                )

                self._driver = (
                    webdriver.Firefox(
                        service=service,
                        options=options,
                    )
                )

            except WebDriverException as exc:
                self._driver = None

                raise QQMusicError(
                    "Failed to start Firefox "
                    f"WebDriver: {exc}"
                ) from exc

            self._search_handle = (
                self._driver
                .current_window_handle
            )

    def close(self) -> None:
        with self._driver_lock:
            driver = self._driver

            self._driver = None
            self._search_handle = None

            if driver is None:
                return

            try:
                driver.quit()
            except (WebDriverException, MaxRetryError, ProtocolError, OSError):
                pass

    def prewarm(self) -> str:
        # Prewarm means:
        # - geckodriver ready
        # - Firefox ready
        # - profile loaded (authentication is not checked here)
        #
        # Do NOT navigate the QQ Music homepage
        # here. The homepage can occasionally
        # keep WebDriver waiting for a very long
        # time. The first music request will
        # navigate directly to its search URL.
        self.start()

        if self._driver is None:
            raise QQMusicError(
                "Firefox WebDriver "
                "did not start"
            )

        return "webdriver-ready"

    def _require_driver(self):
        if self._driver is None:
            self.start()

        if self._driver is None:
            raise QQMusicError(
                "Firefox WebDriver "
                "is unavailable"
            )

        return self._driver

    def _wait(self) -> WebDriverWait:
        return WebDriverWait(
            self._require_driver(),
            self.timeout_seconds,
        )

    def _ensure_search_window(self) -> None:
        driver = self._require_driver()

        handles = driver.window_handles

        if (
            self._search_handle
            in handles
        ):
            driver.switch_to.window(
                self._search_handle
            )
            return

        for handle in handles:
            driver.switch_to.window(handle)

            if self.PLAYER_PATH not in (
                driver.current_url
            ):
                self._search_handle = handle
                return

        driver.switch_to.new_window(
            "tab"
        )

        self._search_handle = (
            driver.current_window_handle
        )

    @staticmethod
    def _normalize_search_text(
        value: str,
    ) -> str:
        value = str(value).lower()

        # “的”通常只是中文口语里的连接词，
        # 对歌曲搜索匹配没有区分意义。
        value = value.replace(
            "的",
            "",
        )

        return re.sub(
            r"[\W_]+",
            "",
            value,
            flags=re.UNICODE,
        )

    @classmethod
    def _search_result_score(
        cls,
        query: str,
        title: str,
        row_text: str,
    ) -> float:
        query_text = str(
            query
        ).strip()

        query_norm = (
            cls._normalize_search_text(
                query_text
            )
        )

        title_norm = (
            cls._normalize_search_text(
                title
            )
        )

        row_norm = (
            cls._normalize_search_text(
                row_text
            )
        )

        raw_terms = [
            term
            for term in re.split(
                r"[\s的,/，、]+",
                query_text,
            )
            if term
        ]

        terms = [
            cls._normalize_search_text(
                term
            )
            for term in raw_terms
        ]

        terms = [
            term
            for term in terms
            if term
        ]

        score = 0.0

        # Preserve meaningful repeated words
        # in real song titles, e.g.
        # "斑马，斑马".
        #
        # If the complete normalized title
        # occurs inside the normalized query,
        # strongly prefer that candidate.
        if (
            title_norm
            and title_norm in query_norm
        ):
            score += 12.0

        for term in terms:
            if term == title_norm:
                score += 12.0

            elif term in title_norm:
                score += 8.0

            elif term in row_norm:
                score += 4.0

            else:
                # ASR 常见同音字错误例如
                # “安河桥” -> “安和桥”。
                ratio = SequenceMatcher(
                    None,
                    term,
                    title_norm,
                ).ratio()

                if ratio >= 0.60:
                    score += (
                        ratio * 6.0
                    )

        version_markers = (
            "live",
            "现场",
            "翻唱",
            "cover",
            "remix",
            "dj",
            "伴奏",
            "纯音乐",
            "独唱版",
            "女声",
            "男声",
            "加速",
            "慢速",
        )

        title_lower = str(
            title
        ).lower()

        for marker in version_markers:
            marker_norm = (
                cls._normalize_search_text(
                    marker
                )
            )

            if (
                marker.lower()
                in title_lower
                and marker_norm
                not in query_norm
            ):
                score -= 6.0

        # 用户没有指定特殊版本时，
        # 给简单原版标题一个小幅优先级。
        if not any(
            marker.lower()
            in title_lower
            for marker in version_markers
        ):
            score += 2.0

        # 多歌手合作版略微降权。
        # 如果用户明确搜索多个歌手，
        # 其他匹配分仍然可以覆盖此惩罚。
        if (
            "/"
            in row_text
            or "／"
            in row_text
        ):
            score -= 1.5

        return score

    def _song_row(
        self,
        link,
    ):
        try:
            return link.find_element(
                By.XPATH,
                (
                    "./ancestor::div["
                    "contains("
                    "concat(' ',"
                    "normalize-space(@class),"
                    "' '),"
                    "' songlist__item '"
                    ")"
                    "][1]"
                ),
            )
        except NoSuchElementException as exc:
            raise QQMusicError(
                "QQ Music search result "
                "row was not found"
            ) from exc

    @classmethod
    def _unmatched_query_terms(
        cls,
        query: str,
        title: str,
        row_text: str,
    ) -> list[str]:
        title_norm = (
            cls._normalize_search_text(
                title
            )
        )

        row_norm = (
            cls._normalize_search_text(
                row_text
            )
        )

        terms = [
            cls._normalize_search_text(
                term
            )
            for term in re.split(
                r"[\s的,/，、]+",
                str(query),
            )
            if term.strip()
        ]

        missing = []

        for term in terms:
            if not term:
                continue

            if (
                term in title_norm
                or term in row_norm
            ):
                continue

            # Allow common ASR homophone /
            # minor title differences such as
            # 安河桥 -> 安和桥.
            title_ratio = (
                SequenceMatcher(
                    None,
                    term,
                    title_norm,
                )
                .ratio()
            )

            if title_ratio >= 0.60:
                continue

            missing.append(
                term
            )

        return missing

    @classmethod
    def _selection_is_ambiguous(
        cls,
        query: str,
        candidates,
    ) -> bool:
        if len(candidates) < 2:
            return False

        top = candidates[0]
        second = candidates[1]

        top_score = float(top[0])
        second_score = float(
            second[0]
        )

        if (
            top_score - second_score
            > cls.AMBIGUITY_MARGIN
        ):
            return False

        query_terms = [
            cls._normalize_search_text(
                term
            )
            for term in re.split(
                r"[\s的,/，、]+",
                str(query),
            )
            if term.strip()
        ]

        query_terms = list(
            dict.fromkeys(
                term
                for term in query_terms
                if term
            )
        )

        top_title = (
            cls._normalize_search_text(
                top[1]
            )
        )

        second_title = (
            cls._normalize_search_text(
                second[1]
            )
        )

        # Only a song title was supplied and
        # several results are effectively tied:
        # do not guess the artist/version.
        if len(query_terms) <= 1:
            return True

        # Different titles/versions with
        # effectively identical confidence
        # are also unsafe to auto-select.
        return (
            top_title
            != second_title
        )

    def _find_song_by_mid(
        self,
        mid: str,
    ):
        driver = self._require_driver()

        mid = str(mid).strip()

        if not mid:
            return False

        links = driver.find_elements(
            By.CSS_SELECTOR,
            (
                "a[href*='/songDetail/"
                f"{mid}']"
            ),
        )

        for link in links:
            try:
                title = (
                    link.text
                    or link.get_attribute(
                        "title"
                    )
                    or ""
                ).strip()

                if (
                    link.is_displayed()
                    and title
                ):
                    print(
                        "[MUSIC] PERSONAL_SELECTED "
                        f"mid={mid} "
                        f"title={title!r}",
                        flush=True,
                    )

                    return link

            except WebDriverException:
                continue

        return False

    def _find_best_song(
        self,
        query: str,
    ):
        driver = self._require_driver()

        links = driver.find_elements(
            By.CSS_SELECTOR,
            "a[href*='/songDetail/']",
        )

        candidates = []

        for link in links:
            try:
                title = (
                    link.text.strip()
                )

                if (
                    not link.is_displayed()
                    or not title
                ):
                    continue

                row = self._song_row(
                    link
                )

                row_text = (
                    row.text.strip()
                )

                score = (
                    self
                    ._search_result_score(
                        query,
                        title,
                        row_text,
                    )
                )

                candidates.append(
                    (
                        score,
                        title,
                        row_text,
                        link,
                    )
                )

            except (
                WebDriverException,
                QQMusicError,
            ):
                continue

        if not candidates:
            return False

        candidates.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        for rank, item in enumerate(
            candidates[:3],
            start=1,
        ):
            print(
                "[MUSIC] SEARCH_CANDIDATE "
                f"rank={rank} "
                f"title={item[1]!r} "
                f"score={item[0]:.2f}",
                flush=True,
            )

        query_parts = [
            part
            for part in re.split(
                r"[\s的,/，、]+",
                str(query),
            )
            if part.strip()
        ]

        # A multi-part Cloud query normally means
        # song + artist/version information.
        # Do not silently discard those qualifiers.
        if len(query_parts) >= 2:
            fully_matched = [
                item
                for item in candidates
                if not (
                    self
                    ._unmatched_query_terms(
                        query,
                        item[1],
                        item[2],
                    )
                )
            ]

            if fully_matched:
                candidates = (
                    fully_matched
                )

                candidates.sort(
                    key=lambda item: item[0],
                    reverse=True,
                )

            else:
                best = candidates[0]

                missing = (
                    self
                    ._unmatched_query_terms(
                        query,
                        best[1],
                        best[2],
                    )
                )

                raise QQMusicError(
                    "No QQ Music result "
                    "matched all requested "
                    "song/artist terms: "
                    f"query={query!r}, "
                    f"missing={missing!r}, "
                    f"best={best[1]!r}"
                )

        score, title, row_text, link = (
            candidates[0]
        )

        if (
            score
            < self.MIN_MATCH_SCORE
        ):
            raise QQMusicError(
                "No sufficiently confident "
                "QQ Music result: "
                f"query={query!r}, "
                f"best={title!r}, "
                f"score={score:.2f}"
            )

        if self._selection_is_ambiguous(
            query,
            candidates,
        ):
            raise QQMusicAmbiguousError(
                query,
                [
                    item[1]
                    for item
                    in candidates[:3]
                ],
            )

        print(
            "[MUSIC] SEARCH_SELECTED "
            f"title={title!r} "
            f"score={score:.2f}",
            flush=True,
        )

        return link

    def _switch_to_player(
        self,
    ) -> None:
        driver = self._require_driver()

        def find_player(_):
            for handle in reversed(
                driver.window_handles
            ):
                driver.switch_to.window(
                    handle
                )

                if self.PLAYER_PATH in (
                    driver.current_url
                ):
                    return handle

            return False

        try:
            handle = (
                self._wait()
                .until(find_player)
            )
        except TimeoutException as exc:
            raise QQMusicError(
                "QQ Music player window "
                "did not appear"
            ) from exc

        driver.switch_to.window(
            handle
        )

    @_driver_locked
    def current_track(
        self,
    ) -> str:
        self._switch_to_player()

        driver = self._require_driver()

        try:
            element = (
                self._wait()
                .until(
                    lambda d:
                    d.find_element(
                        By.CSS_SELECTOR,
                        ".player_music__info",
                    )
                )
            )
        except TimeoutException as exc:
            raise QQMusicError(
                "Current track information "
                "is unavailable"
            ) from exc

        return element.text.strip()

    @_driver_locked
    def current_track_snapshot(self, cover_path: Path) -> tuple[str, str]:
        """Read the playing track and cache QQ's displayed album image."""
        track = self.current_track()
        driver = self._require_driver()
        try:
            image = driver.find_element(By.CSS_SELECTOR, ".song_info__pic")
            source = image.get_attribute("src") or ""
            if not source or not image.is_displayed():
                return track, ""
            if source == getattr(self, "_cover_source", "") and cover_path.is_file():
                return track, self._cover_revision
            png = image.screenshot_as_png
            if not png.startswith(b"\x89PNG\r\n\x1a\n") or len(png) > 2_000_000:
                return track, ""
            revision = hashlib.sha256(png).hexdigest()[:16]
            cover_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = cover_path.with_suffix(".tmp")
            temporary.write_bytes(png)
            os.replace(temporary, cover_path)
            self._cover_source = source
            self._cover_revision = revision
            return track, revision
        except (NoSuchElementException, WebDriverException, OSError):
            return track, ""

    def _play_button(self):
        self._switch_to_player()

        try:
            return (
                self._require_driver()
                .find_element(
                    By.CSS_SELECTOR,
                    ".btn_big_play",
                )
            )
        except NoSuchElementException as exc:
            raise QQMusicError(
                "QQ Music play/pause "
                "control was not found"
            ) from exc

    @staticmethod
    def _is_playing(
        button,
    ) -> bool:
        classes = (
            button.get_attribute(
                "class"
            )
            or ""
        )

        return (
            "btn_big_play--pause"
            in classes.split()
        )

    def _firefox_sink_inputs(
        self,
    ) -> list[str]:
        try:
            result = subprocess.run(
                [
                    "pactl",
                    "-f",
                    "json",
                    "list",
                    "sink-inputs",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=3,
            )

            data = json.loads(
                result.stdout
            )
        except (
            subprocess.CalledProcessError,
            json.JSONDecodeError,
            subprocess.TimeoutExpired,
        ) as exc:
            raise QQMusicError(
                "Failed to inspect "
                "PulseAudio sink inputs"
            ) from exc

        if not isinstance(
            data,
            list,
        ):
            return []

        indices = []

        for item in data:
            properties = item.get(
                "properties",
                {},
            )

            searchable = json.dumps(
                properties,
                ensure_ascii=False,
            ).lower()

            if "firefox" not in searchable:
                continue

            index = item.get(
                "index"
            )

            if index is not None:
                indices.append(
                    str(index)
                )

        return indices

    def route_audio(
        self,
        *,
        wait_seconds: float = 5.0,
    ) -> str | None:
        if not self.speaker_match_any:
            return None

        try:
            sink = resolve_speaker(
                self.speaker_match_any
            )

            subprocess.run(
                [
                    "pactl",
                    "set-default-sink",
                    sink,
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=3,
            )
        except (
            subprocess.CalledProcessError,
            RuntimeError,
            subprocess.TimeoutExpired,
        ) as exc:
            raise QQMusicError(
                "Failed to select "
                "music output sink"
            ) from exc

        deadline = (
            time.monotonic()
            + max(
                0.0,
                float(wait_seconds),
            )
        )

        while True:
            indices = (
                self
                ._firefox_sink_inputs()
            )

            if indices:
                moved = False
                for index in indices:
                    try:
                        subprocess.run(
                            [
                                "pactl",
                                "move-sink-input",
                                index,
                                sink,
                            ],
                            check=True,
                            capture_output=True,
                            text=True,
                            timeout=3,
                        )
                        moved = True
                    except (
                        subprocess
                        .CalledProcessError,
                        subprocess.TimeoutExpired,
                    ) as exc:
                        print(f"[MUSIC] ROUTE_RETRY sink_input={index} "
                              f"error={type(exc).__name__} "
                              f"reason={str(exc)[:120]!r}", flush=True)

                if moved:
                    return sink

            if (
                time.monotonic()
                >= deadline
            ):
                if indices:
                    raise QQMusicError("Firefox audio routing did not settle")
                return sink

            time.sleep(0.25)

    @_driver_locked
    def search_candidates(self, query: str, limit: int = 3) -> list[dict]:
        """Collect selectable song IDs without starting playback."""
        if self._auth_in_progress:
            raise QQMusicAuthRequired("QQ 音乐正在等待扫码登录")
        driver = self._require_driver()
        self._ensure_search_window()
        driver.get(self.SEARCH_URL.format(query=quote(query)))
        def collect(_):
            results, seen = [], set()
            for link in driver.find_elements(By.CSS_SELECTOR, "a[href*='/songDetail/']"):
                try:
                    title = link.text.strip()
                    href = link.get_attribute("href") or ""
                    mid = href.split("/songDetail/", 1)[-1].split("?")[0].strip("/")
                    if not title or not link.is_displayed() or not mid or mid in seen:
                        continue
                    try:
                        row = link.find_element(
                            By.XPATH,
                            "./ancestor::*[contains(@class,'songlist__item')][1]",
                        )
                        artist_cells = row.find_elements(By.CSS_SELECTOR, ".songlist__artist")
                        artist_text = artist_cells[0].text.strip() if artist_cells else ""
                    except WebDriverException:
                        artist_text = ""
                    artists = [name.strip() for name in re.split(r"[/、\n]+", artist_text)
                               if name.strip()]
                    seen.add(mid)
                    results.append({"id": mid, "title": title, "artists": artists,
                                    "backend": "qqmusic", "query": query})
                    if len(results) >= limit:
                        break
                except WebDriverException:
                    continue
            return results or False
        try:
            return self._wait().until(collect)
        except TimeoutException:
            if self._login_link_visible(driver):
                raise QQMusicAuthRequired("QQ 音乐登录已失效，请在屏幕上扫码登录")
            return []

    @staticmethod
    def _login_link_visible(driver) -> bool:
        return any(node.is_displayed() and node.text.strip() == "登录"
                   for node in driver.find_elements(By.CSS_SELECTOR, "a.top_login__link"))

    @classmethod
    def _logged_in_page(cls, driver) -> bool:
        if cls._login_link_visible(driver):
            return False
        return any(node.is_displayed() for node in driver.find_elements(
            By.CSS_SELECTOR, "img.top_login__cover"))

    def account_info(self, avatar_path: Path | None = None) -> dict:
        """Read the account shown by QQ's own page, without exposing cookies."""
        with self._driver_lock:
            driver = self._require_driver()
            self._ensure_search_window()
            driver.get(self.SEARCH_URL.format(query="music"))
            opened_at = time.monotonic()
            state = WebDriverWait(driver, self.timeout_seconds).until(
                lambda d: "ready" if self._logged_in_page(d) else
                "required" if time.monotonic() - opened_at >= 4
                and self._login_link_visible(d) else False)
            if state != "ready":
                return {"state": "required", "nickname": "", "avatar": False}
            avatar = driver.find_element(By.CSS_SELECTOR, "img.top_login__cover")
            nickname = driver.execute_script("""
                const image = arguments[0];
                const link = image.closest('a');
                const candidates = [image.alt, image.title,
                    link && link.title, link && link.getAttribute('aria-label'),
                    link && link.querySelector('.top_login__nick')?.textContent];
                return candidates.map(v => (v || '').trim()).find(Boolean) || '';
            """, avatar)
            saved_avatar = False
            if avatar_path is not None:
                try:
                    avatar_path.parent.mkdir(parents=True, exist_ok=True)
                    avatar.screenshot(str(avatar_path))
                    saved_avatar = avatar_path.is_file()
                except (WebDriverException, OSError):
                    avatar_path.unlink(missing_ok=True)
            if not nickname:
                try:
                    driver.get("https://y.qq.com/n/ryqq/profile")
                    name_node = WebDriverWait(driver, self.timeout_seconds).until(
                        lambda d: next((node for node in d.find_elements(
                            By.CSS_SELECTOR, ".profile__name")
                            if node.text.strip()), False))
                    nickname = name_node.text.strip()
                except (TimeoutException, WebDriverException):
                    pass
            return {"state": "ready", "nickname": str(nickname or "")[:80],
                    "avatar": saved_avatar}

    def logout_account(self) -> None:
        """Discard only cookies from this project's dedicated Firefox profile."""
        with self._driver_lock:
            self.close()
            for name in ("cookies.sqlite", "cookies.sqlite-wal", "cookies.sqlite-shm"):
                (self.profile_path / name).unlink(missing_ok=True)

    @staticmethod
    def _click_browser_at(driver, x: float, y: float) -> None:
        """Click the visible element, descending into QQ's login iframes."""
        driver.switch_to.default_content()
        width, height = driver.execute_script("return [window.innerWidth, window.innerHeight]")
        px = max(1, min(int(width) - 1, round(x * width)))
        py = max(1, min(int(height) - 1, round(y * height)))
        try:
            for _ in range(4):
                target, left, top = driver.execute_script("""
                    const x = arguments[0], y = arguments[1];
                    const target = document.elementFromPoint(x, y);
                    if (!target) return [null, 0, 0];
                    const rect = target.getBoundingClientRect();
                    return [target, rect.left, rect.top];
                """, px, py)
                if target is None:
                    return
                if target.tag_name.lower() != "iframe":
                    target.click()
                    return
                driver.switch_to.frame(target)
                px -= round(left)
                py -= round(top)
        finally:
            driver.switch_to.default_content()

    @staticmethod
    def _login_qr_png(driver) -> bytes | None:
        """Capture QQ's QR at its native pixels for a sharp Qt enlargement."""
        driver.switch_to.default_content()
        try:
            outer = driver.find_elements(By.CSS_SELECTOR, "iframe.login-box-bd__ifr_qq")
            if not outer or not outer[0].is_displayed():
                return None
            driver.switch_to.frame(outer[0])
            inner = driver.find_elements(By.CSS_SELECTOR, "#ptlogin_iframe")
            if not inner:
                return None
            driver.switch_to.frame(inner[0])
            qr = driver.find_elements(By.CSS_SELECTOR, "#qrlogin_img")
            return qr[0].screenshot_as_png if qr and qr[0].is_displayed() else None
        except WebDriverException:
            return None
        finally:
            driver.switch_to.default_content()

    def authenticate_with_browser(self, browser_path: Path, publish,
                                  get_click, get_cancel,
                                  qr_path: Path | None = None) -> bool:
        """Mirror the real QQ login page for the Qt touchscreen."""
        with self._driver_lock:
            self._auth_in_progress = True
        last_click = str(get_click().get("id", ""))
        last_cancel = str(get_cancel().get("id", ""))
        stage = "search_page"
        try:
            with self._driver_lock:
                driver = self._require_driver()
                self._ensure_search_window()
                driver.set_window_size(1280, 720)
                driver.get(self.SEARCH_URL.format(query="music"))
                opened_at = time.monotonic()
                state = WebDriverWait(driver, self.timeout_seconds).until(
                    lambda d: "ready" if self._logged_in_page(d) else
                    "login" if time.monotonic() - opened_at >= 4
                    and self._login_link_visible(d) else False)
                if state == "ready":
                    publish("ready")
                    return True
                stage = "open_login"
                modal_open = any(node.is_displayed() for node in driver.find_elements(
                    By.CSS_SELECTOR, "iframe.login-box-bd__ifr_qq"))
                if not modal_open:
                    driver.find_element(By.CSS_SELECTOR, "a.top_login__link").click()

            deadline = time.monotonic() + 240
            published = False
            qr_revision = 0
            previous_qr = None
            while time.monotonic() < deadline:
                if str(get_cancel().get("id", "")) != last_cancel:
                    publish("required")
                    return False
                click = get_click()
                with self._driver_lock:
                    if self._logged_in_page(driver):
                        publish("ready")
                        return True
                    if str(click.get("id", "")) not in {"", last_click}:
                        last_click = str(click["id"])
                        try:
                            self._click_browser_at(driver, float(click["x"]), float(click["y"]))
                        except (WebDriverException, ValueError, TypeError) as exc:
                            print(f"[MUSIC] QQ_BROWSER_CLICK_ERROR type={type(exc).__name__}", flush=True)
                    if not driver.current_url.startswith("https://y.qq.com/"):
                        driver.get(self.SEARCH_URL.format(query="music"))
                    browser_path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = browser_path.with_name("." + browser_path.name + ".tmp")
                    temporary.write_bytes(driver.get_screenshot_as_png())
                    os.replace(temporary, browser_path)
                    qr_png = self._login_qr_png(driver) if qr_path is not None else None
                    qr_changed = qr_png != previous_qr
                    if qr_changed and qr_path is not None:
                        if qr_png:
                            qr_path.parent.mkdir(parents=True, exist_ok=True)
                            temporary_qr = qr_path.with_name("." + qr_path.name + ".tmp")
                            temporary_qr.write_bytes(qr_png)
                            os.replace(temporary_qr, qr_path)
                        else:
                            qr_path.unlink(missing_ok=True)
                        previous_qr = qr_png
                        qr_revision += 1
                    if not published or qr_changed:
                        publish("browser", qr_available=bool(qr_png), qr_revision=qr_revision)
                        published = True
                time.sleep(0.75)
            publish("error", detail="登录网页已超时，请重新打开 QQ 音乐登录")
            return False
        except TimeoutException as exc:
            raise QQMusicError(f"QQ 音乐网页加载超时（{stage}），请重试") from exc
        finally:
            browser_path.unlink(missing_ok=True)
            if qr_path is not None:
                qr_path.unlink(missing_ok=True)
            with self._driver_lock:
                self._auth_in_progress = False

    def authenticate_with_qr(self, qr_path: Path, publish) -> bool:
        """Show the web login QR; use the existing browser/profile only."""
        with self._driver_lock:
            self._auth_in_progress = True
        stage = "search_page"
        try:
            with self._driver_lock:
                driver = self._require_driver()
                self._ensure_search_window()
                driver.get(self.SEARCH_URL.format(query="music"))
                opened_at = time.monotonic()
                page_state = WebDriverWait(driver, self.timeout_seconds).until(
                    lambda d: "ready" if self._logged_in_page(d) else
                    "login" if time.monotonic() - opened_at >= 4
                    and self._login_link_visible(d) else False)
                if page_state == "ready":
                    publish("ready")
                    return True
                stage = "open_login"
                driver.find_element(By.CSS_SELECTOR, "a.top_login__link").click()
                wait = WebDriverWait(driver, self.timeout_seconds)
                opened = wait.until(lambda d: "ready" if self._logged_in_page(d) else
                                    "iframe" if d.find_elements(By.CSS_SELECTOR,
                                                               "iframe.login-box-bd__ifr_qq") else False)
                if opened == "ready":
                    publish("ready")
                    return True
                driver.switch_to.frame(driver.find_element(By.CSS_SELECTOR, "iframe.login-box-bd__ifr_qq"))
                stage = "qq_login_frame"
                wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, "#ptlogin_iframe"))
                driver.switch_to.frame(driver.find_element(By.CSS_SELECTOR, "#ptlogin_iframe"))
                stage = "qr_image"
                qr = wait.until(lambda d: d.find_element(By.CSS_SELECTOR, "#qrlogin_img"))
                wait.until(lambda d: qr.is_displayed() and qr.get_attribute("src"))
                qr_path.parent.mkdir(parents=True, exist_ok=True)
                qr.screenshot(str(qr_path))
                driver.switch_to.default_content()
                publish("qr")
            deadline = time.monotonic() + 150
            while time.monotonic() < deadline:
                time.sleep(1)
                with self._driver_lock:
                    if not self._login_link_visible(driver):
                        qr_path.unlink(missing_ok=True)
                        publish("ready")
                        return True
            qr_path.unlink(missing_ok=True)
            publish("error", detail="二维码已过期，请重新点击登录")
            return False
        except TimeoutException as exc:
            raise QQMusicError(f"QQ 音乐网页加载超时（{stage}），请重试") from exc
        finally:
            with self._driver_lock:
                if self._driver is not None:
                    try:
                        self._driver.switch_to.default_content()
                    except WebDriverException:
                        pass
                self._auth_in_progress = False

    @_driver_locked
    def play(
        self,
        query: str,
        *,
        preferred_mid: str | None = None,
        strict_mid: bool = False,
    ) -> str:
        query = str(
            query
        ).strip()

        if self._auth_in_progress:
            raise QQMusicAuthRequired("QQ 音乐正在等待扫码登录")

        if not query:
            raise QQMusicError(
                "Music query is empty"
            )

        play_t0 = time.monotonic()

        driver = self._require_driver()
        # QQ can leave an earlier player tab active when a new search opens
        # another one. Silence all existing player tabs before replacing it.
        self.stop()

        driver_done = (
            time.monotonic()
        )

        self._ensure_search_window()

        window_done = (
            time.monotonic()
        )

        url = self.SEARCH_URL.format(
            query=quote(query)
        )

        driver.get(url)

        navigate_done = (
            time.monotonic()
        )

        try:
            if preferred_mid:
                # Personal-library MID is the first
                # choice, but QQ search occasionally
                # does not expose that exact MID in
                # its rendered result list.
                exact_deadline = (
                    time.monotonic()
                    + 3.0
                )

                song = False

                while (
                    time.monotonic()
                    < exact_deadline
                ):
                    song = (
                        self
                        ._find_song_by_mid(
                            preferred_mid
                        )
                    )

                    if song:
                        break

                    time.sleep(0.20)

                if not song:
                    if strict_mid:
                        raise QQMusicError("Selected song is no longer present; search again")
                    print(
                        "[MUSIC] "
                        "PERSONAL_MID_MISS "
                        f"mid={preferred_mid} "
                        "fallback="
                        "qualified_search",
                        flush=True,
                    )

                    song = (
                        self._wait()
                        .until(
                            lambda d:
                            self
                            ._find_best_song(
                                query
                            )
                        )
                    )

            else:
                song = (
                    self._wait()
                    .until(
                        lambda d:
                        self
                        ._find_best_song(
                            query
                        )
                    )
                )

        except TimeoutException as exc:
            raise QQMusicError(
                "QQ Music returned "
                "no playable search result"
            ) from exc

        search_done = (
            time.monotonic()
        )

        row = self._song_row(
            song
        )

        try:
            # A result can be below the visible viewport in kiosk mode.
            # Pointer movement can then fail before the click is attempted.
            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center',inline:'nearest'});"
                "arguments[0].dispatchEvent(new MouseEvent('mouseover',{bubbles:true}));",
                row,
            )

            play_button = (
                row.find_element(
                    By.CSS_SELECTOR,
                    ".list_menu__play",
                )
            )

            driver.execute_script(
                "arguments[0].click();",
                play_button,
            )

        except WebDriverException as exc:
            raise QQMusicError(
                "Failed to click "
                "QQ Music search result"
            ) from exc

        click_done = (
            time.monotonic()
        )

        self._switch_to_player()

        player_done = (
            time.monotonic()
        )

        self.route_audio()

        audio_done = (
            time.monotonic()
        )

        track = self.current_track()

        track_done = (
            time.monotonic()
        )

        print(
            "[MUSIC] PLAY_TIMING "
            f"driver="
            f"{driver_done - play_t0:.3f}s "
            f"window="
            f"{window_done - driver_done:.3f}s "
            f"navigate="
            f"{navigate_done - window_done:.3f}s "
            f"search="
            f"{search_done - navigate_done:.3f}s "
            f"click="
            f"{click_done - search_done:.3f}s "
            f"player="
            f"{player_done - click_done:.3f}s "
            f"audio="
            f"{audio_done - player_done:.3f}s "
            f"metadata="
            f"{track_done - audio_done:.3f}s "
            f"total="
            f"{track_done - play_t0:.3f}s",
            flush=True,
        )

        if not track:
            raise QQMusicError(
                "QQ Music started playback "
                "without track metadata"
            )

        return track

    @_driver_locked
    def pause(
        self,
    ) -> str:
        button = self._play_button()

        if self._is_playing(
            button
        ):
            self._require_driver().execute_script(
                "arguments[0].click();",
                button,
            )

            try:
                self._wait().until(
                    lambda d:
                    not self._is_playing(
                        d.find_element(
                            By.CSS_SELECTOR,
                            ".btn_big_play",
                        )
                    )
                )
            except TimeoutException as exc:
                raise QQMusicError(
                    "QQ Music did not pause"
                ) from exc

        return self.current_track()

    @_driver_locked
    def resume(
        self,
    ) -> str:
        button = self._play_button()

        if not self._is_playing(
            button
        ):
            self._require_driver().execute_script(
                "arguments[0].click();",
                button,
            )

            try:
                self._wait().until(
                    lambda d:
                    self._is_playing(
                        d.find_element(
                            By.CSS_SELECTOR,
                            ".btn_big_play",
                        )
                    )
                )
            except TimeoutException as exc:
                raise QQMusicError(
                    "QQ Music did not resume"
                ) from exc

        self.route_audio()

        return self.current_track()

    @_driver_locked
    def next(
        self,
    ) -> str:
        old_track = (
            self.current_track()
        )

        driver = self._require_driver()

        try:
            button = driver.find_element(
                By.CSS_SELECTOR,
                ".btn_big_next",
            )

            driver.execute_script(
                "arguments[0].click();",
                button,
            )

            new_track = (
                self._wait()
                .until(
                    lambda d: (
                        d.find_element(
                            By.CSS_SELECTOR,
                            ".player_music__info",
                        )
                        .text
                        .strip()
                    )
                    if (
                        d.find_element(
                            By.CSS_SELECTOR,
                            ".player_music__info",
                        )
                        .text
                        .strip()
                        != old_track
                    )
                    else False
                )
            )

        except (
            NoSuchElementException,
            TimeoutException,
        ) as exc:
            raise QQMusicError(
                "QQ Music could not "
                "switch to next track"
            ) from exc

        self.route_audio()

        return str(
            new_track
        ).strip()

    @_driver_locked
    def previous(
        self,
    ) -> str:
        self._switch_to_player()

        driver = self._require_driver()

        try:
            button = driver.find_element(
                By.CSS_SELECTOR,
                ".btn_big_prev",
            )

            driver.execute_script(
                "arguments[0].click();",
                button,
            )
        except NoSuchElementException as exc:
            raise QQMusicError(
                "QQ Music previous-track "
                "control was not found"
            ) from exc

        time.sleep(0.5)

        self.route_audio()

        return self.current_track()

    @_driver_locked
    def stop(
        self,
    ) -> str:
        # QQ Music Web has no stop control. Pause every player tab: the page
        # may open a new tab while an older one continues to play.
        driver = self._require_driver()
        paused = 0
        for handle in list(driver.window_handles):
            try:
                driver.switch_to.window(handle)
                if self.PLAYER_PATH not in driver.current_url:
                    continue
                button = driver.find_element(By.CSS_SELECTOR, ".btn_big_play")
                if self._is_playing(button):
                    driver.execute_script("arguments[0].click();", button)
                    paused += 1
                driver.execute_script(
                    "document.querySelectorAll('audio, video').forEach(m => m.pause());"
                )
            except (NoSuchWindowException, NoSuchElementException):
                continue
        if paused:
            print(f"[MUSIC] PLAYER_STOPPED tabs={paused}", flush=True)
        return ""

    def __enter__(
        self,
    ) -> "QQMusicController":
        self.start()
        return self

    def __exit__(
        self,
        exc_type,
        exc,
        traceback,
    ) -> None:
        self.close()

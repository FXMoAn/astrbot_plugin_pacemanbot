import asyncio
import copy
import math
import time
from collections import OrderedDict, deque
from datetime import datetime
from datetime import timezone as datetime_timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote, urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from astrbot.api import logger

PACEMAN_BASE_URL = "https://paceman.gg/stats/api"
RANKED_BASE_URL = "https://api.mcsrranked.com"
API_ENDPOINTS = {
    "paceman": {
        "session_stats": "/getSessionStats/",
        "nph_stats": "/getNPH/",
        "session_nethers": "/getSessionNethers/",
        "nickname": "/getNickAlways/",
        "latest_completion": "/getLatestCompletion/",
        "pbs": "/getPBs/",
    },
    "ranked": {
        "user_stats": "/users/{username}",
        "leaderboard": "/leaderboard",
        "matches": "/users/{username}/matches",
    },
}
API_MESSAGES = {
    "not_found": "没有找到该玩家或对应的数据。",
    "invalid_request": "查询参数有误，请检查用户名、赛季和查询范围。",
    "rate_limited": "查询过于频繁，请稍后重试。",
    "timeout": "查询超时，请稍后重试。",
    "network": "暂时无法连接数据服务，请稍后重试。",
    "unavailable": "数据服务暂时不可用，请稍后重试。",
    "bad_response": "数据服务返回的内容有误，请稍后重试。",
}


class ApiError(Exception):
    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ):
        self.code = code
        self.message = message or API_MESSAGES.get(code, API_MESSAGES["unavailable"])
        self.status_code = status_code
        self.retry_after = retry_after
        super().__init__(self.message)


class ApiClient:
    """Plugin-owned HTTP pool, bounded cache and shared in-flight requests."""

    CACHE_LIMIT = 256
    PENDING_LIMIT = 256
    RANKED_REQUEST_LIMIT = 500
    RANKED_WINDOW = 600.0
    ASSET_SIZE_LIMIT = 8 * 1024 * 1024

    def __init__(
        self,
        request_timeout: float = 10,
        request_concurrency: int = 6,
        user_cache_ttl: float = 20,
        leaderboard_cache_ttl: float = 60,
    ):
        self.request_timeout = max(1.0, float(request_timeout))
        self.user_cache_ttl = max(0.0, float(user_cache_ttl))
        self.leaderboard_cache_ttl = max(0.0, float(leaderboard_cache_ttl))
        concurrency = max(1, int(request_concurrency))
        self._semaphore = asyncio.Semaphore(concurrency)
        self._client = httpx.AsyncClient(
            timeout=self.request_timeout,
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=concurrency, max_keepalive_connections=concurrency
            ),
            headers={"User-Agent": "astrbot-pacemanbot"},
        )
        self._cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._inflight: dict[str, asyncio.Task] = {}
        self._ranked_requests: deque[float] = deque()
        self._cooldowns: dict[str, float] = {}
        self._closed = False
        self._close_task: asyncio.Task | None = None

    async def fetch(
        self,
        api_type: str,
        endpoint_type: str,
        username: str = "",
        params: dict | None = None,
    ) -> Any:
        """Return data without Ranked's status/data envelope.

        latest_completion returns a dict or None. pbs and matches return lists;
        the other current endpoints return dictionaries.
        """
        self._ensure_open()
        url = self._build_url(api_type, endpoint_type, username, params)
        key = f"json:{url}"
        cached = self._cache.get(key)
        if cached is not None:
            if cached[0] > time.monotonic():
                self._cache.move_to_end(key)
                return copy.deepcopy(cached[1])
            self._cache.pop(key, None)
        return copy.deepcopy(
            await self._coalesced(
                key, lambda: self._fetch_uncached(api_type, endpoint_type, url, key)
            )
        )

    async def get_bytes(self, url: str, timeout: float | None = None) -> bytes:
        """Download skin bytes through the shared connection/concurrency pool."""
        self._ensure_open()
        address = urlsplit(url)
        if address.scheme not in {"http", "https"} or not address.hostname:
            raise ApiError("invalid_request", "图片地址有误。")
        scope = f"asset:{address.hostname}"
        return await self._coalesced(
            f"bytes:{url}:{timeout}", lambda: self._download_bytes(url, scope, timeout)
        )

    async def aclose(self):
        if self._close_task is None:
            self._closed = True
            self._close_task = asyncio.create_task(self._close())
        # Cleanup continues if an unloading caller itself is cancelled.
        await asyncio.shield(self._close_task)

    async def _close(self):
        tasks = list(self._inflight.values())
        for task in tasks:
            task.cancel()
        try:
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            try:
                await self._client.aclose()
            finally:
                self._cache.clear()
                self._inflight.clear()
                self._cooldowns.clear()
                self._ranked_requests.clear()

    def _ensure_open(self):
        if self._closed:
            raise ApiError("unavailable", "插件正在停止，请稍后重试。")

    async def _coalesced(self, key: str, factory):
        task = self._inflight.get(key)
        if task is None:
            if len(self._inflight) >= self.PENDING_LIMIT:
                raise ApiError("unavailable", "等待查询的请求较多，请稍后重试。")
            task = asyncio.create_task(factory())
            self._inflight[key] = task
            task.add_done_callback(
                lambda completed: self._finish_request(key, completed)
            )
        # One cancelled command must not cancel another command's shared query.
        return await asyncio.shield(task)

    def _finish_request(self, key: str, task: asyncio.Task):
        if self._inflight.get(key) is task:
            self._inflight.pop(key, None)
        if not task.cancelled():
            # Retrieve exceptions when every waiting command was cancelled.
            task.exception()

    def _build_url(self, api_type, endpoint_type, username, params):
        if (
            api_type not in API_ENDPOINTS
            or endpoint_type not in API_ENDPOINTS[api_type]
        ):
            raise ApiError("invalid_request", "不支持该数据查询。")
        username = str(username or "").strip()
        if len(username) > 64:
            raise ApiError("invalid_request", "用户名过长，请检查输入。")
        query: dict[str, Any] = {}
        if api_type == "paceman":
            base_url = PACEMAN_BASE_URL
            if endpoint_type == "nickname":
                query["uuid"] = username
            elif endpoint_type == "pbs":
                if username:
                    query["names"] = username
            else:
                query["name"] = username
                if endpoint_type in {"session_stats", "nph_stats", "session_nethers"}:
                    query.update(hours=24, hoursBetween=24)
        else:
            base_url = RANKED_BASE_URL
            if endpoint_type == "matches":
                query.update(count=5, type=2, sort="newest", excludedecay=True)
        query.update(
            {key: value for key, value in (params or {}).items() if value is not None}
        )
        if api_type == "paceman" and endpoint_type == "pbs":
            if query.get("uuids"):
                try:
                    query["uuids"] = ",".join(
                        str(UUID(value.strip()))
                        for value in str(query["uuids"]).split(",")
                    )
                except (ValueError, AttributeError) as error:
                    raise ApiError("invalid_request", "玩家 UUID 有误。") from error
                query.pop("names", None)
            if not query.get("names") and not query.get("uuids"):
                raise ApiError("invalid_request", "查询 PB 需要提供用户名或 UUID。")
        elif api_type == "paceman":
            if not query.get("uuid" if endpoint_type == "nickname" else "name"):
                raise ApiError("invalid_request", "请提供用户名或 UUID。")
        elif endpoint_type in {"user_stats", "matches"} and not username:
            raise ApiError("invalid_request", "请提供用户名或 UUID。")
        path = API_ENDPOINTS[api_type][endpoint_type].format(
            username=quote(username, safe="")
        )
        normalized = {
            key: "true" if value is True else "false" if value is False else str(value)
            for key, value in sorted(query.items())
        }
        return str(httpx.URL(f"{base_url}{path}", params=normalized))

    async def _fetch_uncached(self, api_type, endpoint_type, url, key):
        scope = "ranked" if api_type == "ranked" else f"paceman:{endpoint_type}"
        response = await self._request(url, api_type, scope)
        try:
            payload = response.json()
        except (ValueError, UnicodeError) as error:
            raise ApiError("bad_response") from error
        try:
            data = self._normalize(api_type, endpoint_type, payload)
        except ApiError as error:
            if error.code == "rate_limited":
                self._cooldowns[scope] = time.monotonic() + 60
            raise
        ttl = (
            self.leaderboard_cache_ttl
            if endpoint_type == "leaderboard"
            else self.user_cache_ttl
        )
        if ttl > 0 and not self._closed:
            now = time.monotonic()
            for old_key, (expires, _) in list(self._cache.items()):
                if expires <= now:
                    self._cache.pop(old_key, None)
            self._cache[key] = (now + ttl, data)
            self._cache.move_to_end(key)
            while len(self._cache) > self.CACHE_LIMIT:
                self._cache.popitem(last=False)
        return data

    @staticmethod
    def _normalize(api_type, endpoint_type, payload):
        if api_type == "ranked":
            if not isinstance(payload, dict) or payload.get("status") not in (
                "success",
                "error",
            ):
                raise ApiError("bad_response")
            if payload["status"] == "error":
                raise ApiClient._body_error(payload.get("data"))
            if "data" not in payload:
                raise ApiError("bad_response")
            payload = payload["data"]
        elif isinstance(payload, dict) and "error" in payload:
            raise ApiClient._body_error(payload["error"])
        if endpoint_type == "latest_completion":
            if payload is None or payload == []:
                return None
            if isinstance(payload, list):
                if len(payload) != 1:
                    raise ApiError("bad_response")
                payload = payload[0]
            if not isinstance(payload, dict) or payload.get("finish") is None:
                raise ApiError("bad_response")
        elif endpoint_type in {"pbs", "matches"}:
            if not isinstance(payload, list) or any(
                not isinstance(item, dict) for item in payload
            ):
                raise ApiError("bad_response")
        elif not isinstance(payload, dict):
            raise ApiError("bad_response")
        elif endpoint_type == "session_stats" and not isinstance(
            payload.get("nether"), dict
        ):
            raise ApiError("bad_response")
        elif endpoint_type == "session_nethers" and not payload.get("uuid"):
            raise ApiError("bad_response")
        elif endpoint_type == "nickname" and not isinstance(payload.get("name"), str):
            raise ApiError("bad_response")
        elif endpoint_type == "user_stats" and not (
            isinstance(payload.get("nickname"), str)
            and isinstance(payload.get("uuid"), str)
        ):
            raise ApiError("bad_response")
        elif endpoint_type == "leaderboard" and not isinstance(
            payload.get("users"), list
        ):
            raise ApiError("bad_response")
        return payload

    @staticmethod
    def _body_error(value):
        if isinstance(value, dict) and any(key in value for key in ("query", "params", "body")):
            return ApiError("invalid_request")
        text = str(value or "").lower()
        if "unknown user" in text or "not found" in text or "does not exist" in text:
            return ApiError("not_found")
        if "too many" in text or "rate limit" in text:
            return ApiError("rate_limited")
        if "invalid" in text or "parameter" in text or "wrong" in text:
            return ApiError("invalid_request")
        return ApiError("unavailable")

    def _admit_request(self, api_type, scope):
        self._ensure_open()
        now = time.monotonic()
        cooldown = self._cooldowns.get(scope, 0) - now
        if cooldown > 0:
            raise ApiError("rate_limited", retry_after=cooldown)
        self._cooldowns.pop(scope, None)
        if api_type == "ranked":
            while (
                self._ranked_requests
                and self._ranked_requests[0] <= now - self.RANKED_WINDOW
            ):
                self._ranked_requests.popleft()
            if len(self._ranked_requests) >= self.RANKED_REQUEST_LIMIT:
                raise ApiError(
                    "rate_limited",
                    retry_after=self._ranked_requests[0] + self.RANKED_WINDOW - now,
                )
            self._ranked_requests.append(now)

    async def _request(self, url, api_type, scope, timeout=None):
        for attempt in range(2):
            try:
                async with self._semaphore:
                    self._admit_request(api_type, scope)
                    response = await self._client.get(
                        url,
                        timeout=self.request_timeout if timeout is None else timeout,
                    )
                self._check_status(response, api_type, scope)
                return response
            except httpx.TimeoutException as error:
                api_error, source = ApiError("timeout"), error
            except httpx.HTTPError as error:
                api_error, source = ApiError("network"), error
            except ApiError as error:
                if error.code not in {"timeout", "network", "unavailable"}:
                    raise
                api_error, source = error, error
            logger.warning(
                f"{api_type} 查询失败: {api_error.code} (第 {attempt + 1} 次)"
            )
            if attempt == 1:
                if api_error is source:
                    raise api_error
                raise api_error from source
            await asyncio.sleep(0.25)

    def _check_status(self, response, api_type, scope):
        status = response.status_code
        if 200 <= status < 300:
            return
        if status == 429:
            delay = self._retry_after(response.headers.get("Retry-After"))
            self._cooldowns[scope] = max(
                self._cooldowns.get(scope, 0), time.monotonic() + delay
            )
            raise ApiError("rate_limited", status_code=status, retry_after=delay)
        if status == 404 or (api_type == "ranked" and status == 400):
            code = "not_found"
            if api_type == "ranked":
                try:
                    body_error = self._body_error(response.json().get("data"))
                    if body_error.code == "invalid_request":
                        code = "invalid_request"
                except (ValueError, AttributeError):
                    pass
        elif status == 408:
            code = "timeout"
        elif status in {400, 401, 422}:
            code = "invalid_request"
        else:
            code = "unavailable"
        raise ApiError(code, status_code=status)

    @staticmethod
    def _retry_after(value):
        if value:
            try:
                delay = float(value)
                if math.isfinite(delay):
                    return max(1.0, delay)
            except ValueError:
                try:
                    date = parsedate_to_datetime(value)
                    if date.tzinfo is None:
                        date = date.replace(tzinfo=datetime_timezone.utc)
                    return max(1.0, date.timestamp() - time.time())
                except (TypeError, ValueError, OverflowError):
                    pass
        return 60.0

    async def _download_bytes(self, url, scope, timeout):
        for attempt in range(2):
            try:
                async with self._semaphore:
                    self._admit_request("asset", scope)
                    async with self._client.stream(
                        "GET",
                        url,
                        timeout=self.request_timeout if timeout is None else timeout,
                    ) as response:
                        self._check_status(response, "asset", scope)
                        chunks = []
                        size = 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > self.ASSET_SIZE_LIMIT:
                                raise ApiError(
                                    "bad_response", "皮肤图片过大，暂时无法获取。"
                                )
                            chunks.append(chunk)
                        return b"".join(chunks)
            except httpx.TimeoutException as error:
                api_error, source = ApiError("timeout"), error
            except httpx.HTTPError as error:
                api_error, source = ApiError("network"), error
            except ApiError as error:
                if error.code not in {"timeout", "network", "unavailable"}:
                    raise
                api_error, source = error, error
            if attempt == 1:
                if api_error is source:
                    raise api_error
                raise api_error from source
            await asyncio.sleep(0.25)


def get_time(milliseconds):
    """Return total minutes and seconds, without wrapping after one day."""
    seconds = max(0, int(float(milliseconds) / 1000))
    return divmod(seconds, 60)


def format_time(milliseconds: int | float | None) -> str:
    if milliseconds is None or isinstance(milliseconds, bool):
        return "—"
    try:
        number = float(milliseconds)
        if not math.isfinite(number) or number < 0:
            return "—"
        minutes, seconds = get_time(number)
        return f"{minutes}:{seconds:02d}"
    except (TypeError, ValueError, OverflowError):
        return "—"


def to_local_time(
    timestamp, timezone: str = "Asia/Shanghai", *, milliseconds: bool = False
):
    """Epoch seconds by default; opt in to millisecond dates for newer APIs."""
    if timestamp is None or isinstance(timestamp, bool):
        return "—"
    try:
        seconds = float(timestamp) / (1000 if milliseconds else 1)
        return datetime.fromtimestamp(seconds, tz=ZoneInfo(timezone)).strftime(
            "%Y-%m-%d"
        )
    except (TypeError, ValueError, OverflowError, OSError, ZoneInfoNotFoundError):
        return "—"

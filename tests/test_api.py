"""Offline API regressions: python -m unittest discover -s tests -p 'test_api.py'."""

import asyncio
import json
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import _bootstrap  # noqa: F401
import httpx
from pacemanbot_test.utils import ApiClient, ApiError, format_time, to_local_time

UUID_HEX = "f2e05ad464b54d288fa18da14e9a2786"
UUID_DASHED = "f2e05ad4-64b5-4d28-8fa1-8da14e9a2786"
COMPLETION = {
    "id": 2584391,
    "nether": 118899,
    "bastion": None,
    "fortress": 280508,
    "finish": 555739,
    "obtainObsidian": None,
}


class CountingTransport(httpx.MockTransport):
    def __init__(self, handler):
        super().__init__(handler)
        self.close_count = 0

    async def aclose(self):
        self.close_count += 1
        await super().aclose()


class ApiClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clients = []

    async def asyncTearDown(self):
        await asyncio.gather(*(client.aclose() for client in self.clients))

    async def make_client(self, handler, **options):
        client = ApiClient(**options)
        await client._client.aclose()
        transport = CountingTransport(handler)
        client._client = httpx.AsyncClient(transport=transport)
        self.clients.append(client)
        return client, transport

    async def test_identical_concurrent_queries_share_one_request(self):
        entered, release = asyncio.Event(), asyncio.Event()
        calls = 0

        async def handle(request):
            nonlocal calls
            calls += 1
            entered.set()
            await release.wait()
            return httpx.Response(200, json=[COMPLETION])

        client, _ = await self.make_client(handle)
        queries = [asyncio.create_task(client.fetch("paceman", "latest_completion", "LEC666888"))
                   for _ in range(8)]
        await asyncio.wait_for(entered.wait(), 1)
        release.set()
        results = await asyncio.gather(*queries)
        self.assertEqual(calls, 1)
        self.assertTrue(all(item == COMPLETION for item in results))
        results[0]["finish"] = 0
        self.assertEqual(results[1]["finish"], COMPLETION["finish"])

    async def test_cached_payload_isolated_and_expires(self):
        calls = 0

        def handle(request):
            nonlocal calls
            calls += 1
            return httpx.Response(200, json=[COMPLETION])

        client, _ = await self.make_client(handle, user_cache_ttl=0.05)
        first = await client.fetch("paceman", "latest_completion", "LEC666888")
        first["finish"] = 0
        cached = await client.fetch("paceman", "latest_completion", "LEC666888")
        self.assertEqual(cached["finish"], COMPLETION["finish"])
        self.assertEqual(calls, 1)
        await asyncio.sleep(0.06)
        await client.fetch("paceman", "latest_completion", "LEC666888")
        self.assertEqual(calls, 2)

    async def test_cache_has_a_size_bound(self):
        calls = 0

        def handle(request):
            nonlocal calls
            calls += 1
            return httpx.Response(200, json=[COMPLETION])

        client, _ = await self.make_client(handle)
        client.CACHE_LIMIT = 2
        for name in ("one", "two", "three"):
            await client.fetch("paceman", "latest_completion", name)
        self.assertEqual(len(client._cache), 2)
        await client.fetch("paceman", "latest_completion", "one")
        self.assertEqual(calls, 4)

    async def test_cancelled_waiter_does_not_cancel_shared_query(self):
        entered, release = asyncio.Event(), asyncio.Event()
        calls = 0

        async def handle(request):
            nonlocal calls
            calls += 1
            entered.set()
            await release.wait()
            return httpx.Response(200, json=[COMPLETION])

        client, _ = await self.make_client(handle)
        cancelled = asyncio.create_task(client.fetch("paceman", "latest_completion", "LEC666888"))
        remaining = asyncio.create_task(client.fetch("paceman", "latest_completion", "LEC666888"))
        await asyncio.wait_for(entered.wait(), 1)
        cancelled.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await cancelled
        release.set()
        self.assertEqual(await asyncio.wait_for(remaining, 1), COMPLETION)
        self.assertEqual(calls, 1)

    async def test_concurrency_limit_applies_to_distinct_requests(self):
        entered, release = asyncio.Event(), asyncio.Event()
        active = peak = 0

        async def handle(request):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            if active == 2:
                entered.set()
            await release.wait()
            active -= 1
            return httpx.Response(200, json=[COMPLETION])

        client, _ = await self.make_client(handle, request_concurrency=2)
        tasks = [asyncio.create_task(client.fetch("paceman", "latest_completion", str(index)))
                 for index in range(6)]
        await asyncio.wait_for(entered.wait(), 1)
        self.assertEqual(active, 2)
        release.set()
        await asyncio.gather(*tasks)
        self.assertEqual(peak, 2)

    async def test_ranked_429_cools_all_ranked_endpoints_without_retry(self):
        calls = 0

        def handle(request):
            nonlocal calls
            calls += 1
            return httpx.Response(429, headers={"Retry-After": "120"},
                                  json={"status": "error", "data": "Too many requests"})

        client, _ = await self.make_client(handle)
        for endpoint in ("user_stats", "matches", "leaderboard"):
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(ApiError) as raised:
                    await client.fetch("ranked", endpoint, "LEC666888")
                self.assertEqual(raised.exception.code, "rate_limited")
                self.assertGreater(raised.exception.retry_after, 110)
        self.assertEqual(calls, 1)
        self.assertFalse(client._cache)

    async def test_paceman_cooldown_is_per_route(self):
        calls = []

        def handle(request):
            calls.append(request.url.path)
            if request.url.path.endswith("/getLatestCompletion/"):
                return httpx.Response(429, headers={"Retry-After": "60"},
                                      json={"error": "Too many requests"})
            return httpx.Response(200, json={"rnph": 0, "count": 0})

        client, _ = await self.make_client(handle)
        for name in ("one", "two"):
            with self.assertRaises(ApiError) as raised:
                await client.fetch("paceman", "latest_completion", name)
            self.assertEqual(raised.exception.code, "rate_limited")
        self.assertEqual(await client.fetch("paceman", "nph_stats", "LEC666888"),
                         {"rnph": 0, "count": 0})
        self.assertEqual(len(calls), 2)

    async def test_retry_after_http_date(self):
        expiry = datetime.now(timezone.utc) + timedelta(seconds=90)
        client, _ = await self.make_client(lambda request: httpx.Response(
            429, headers={"Retry-After": format_datetime(expiry, usegmt=True)}, json={"error": "busy"}
        ))
        with self.assertRaises(ApiError) as raised:
            await client.fetch("paceman", "latest_completion", "LEC666888")
        self.assertEqual(raised.exception.code, "rate_limited")
        self.assertGreater(raised.exception.retry_after, 85)
        self.assertLessEqual(raised.exception.retry_after, 90)

    async def test_200_error_envelope_is_not_cached(self):
        calls = 0

        def handle(request):
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(200, json={"status": "error", "data": "User not found"})
            return httpx.Response(200, json={"status": "success", "data": {
                "uuid": UUID_HEX, "nickname": "LEC666888"}})

        client, _ = await self.make_client(handle)
        with self.assertRaises(ApiError) as raised:
            await client.fetch("ranked", "user_stats", "LEC666888")
        self.assertEqual(raised.exception.code, "not_found")
        self.assertEqual((await client.fetch("ranked", "user_stats", "LEC666888"))["uuid"], UUID_HEX)
        self.assertEqual(calls, 2)

    async def test_ranked_400_query_validation_is_not_player_not_found(self):
        client, _ = await self.make_client(lambda request: httpx.Response(400, json={
            "status": "error", "data": {"query": {"season": ["Too small: expected number to be >=1"]}}
        }))
        with self.assertRaises(ApiError) as raised:
            await client.fetch("ranked", "user_stats", "LEC666888", params={"season": 0})
        self.assertEqual(raised.exception.code, "invalid_request")

    async def test_ranked_400_missing_user_remains_not_found(self):
        client, _ = await self.make_client(lambda request: httpx.Response(400, json={
            "status": "error", "data": "User not found"
        }))
        with self.assertRaises(ApiError) as raised:
            await client.fetch("ranked", "user_stats", "missing")
        self.assertEqual(raised.exception.code, "not_found")

    async def test_200_rate_limit_envelope_also_cools_down(self):
        calls = 0

        def handle(request):
            nonlocal calls
            calls += 1
            return httpx.Response(200, json={"status": "error", "data": "Rate limit exceeded"})

        client, _ = await self.make_client(handle)
        for name in ("one", "two"):
            with self.assertRaises(ApiError) as raised:
                await client.fetch("ranked", "user_stats", name)
            self.assertEqual(raised.exception.code, "rate_limited")
        self.assertEqual(calls, 1)

    async def test_transient_5xx_retries_once_then_succeeds(self):
        calls = 0

        def handle(request):
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(503, json={"error": "busy"})
            return httpx.Response(200, json=[COMPLETION])

        client, _ = await self.make_client(handle)
        self.assertEqual(await client.fetch("paceman", "latest_completion", "LEC666888"), COMPLETION)
        self.assertEqual(calls, 2)

    async def test_permanent_5xx_stops_after_two_attempts(self):
        calls = 0

        def handle(request):
            nonlocal calls
            calls += 1
            return httpx.Response(500, text="internal error")

        client, _ = await self.make_client(handle)
        with self.assertRaises(ApiError) as raised:
            await client.fetch("paceman", "latest_completion", "LEC666888")
        self.assertEqual(raised.exception.code, "unavailable")
        self.assertEqual(calls, 2)
        self.assertFalse(client._cache)

    async def test_bad_json_is_reported_as_bad_response(self):
        client, _ = await self.make_client(lambda request: httpx.Response(200, text="<html>error</html>"))
        with self.assertRaises(ApiError) as raised:
            await client.fetch("paceman", "latest_completion", "LEC666888")
        self.assertEqual(raised.exception.code, "bad_response")

    async def test_malformed_status_is_reported_as_bad_response(self):
        for status in ([], {}, None):
            with self.subTest(status=status):
                client, _ = await self.make_client(lambda request, value=status: httpx.Response(
                    200, json={"status": value, "data": {}}
                ))
                with self.assertRaises(ApiError) as raised:
                    await client.fetch("ranked", "user_stats", "LEC666888")
                self.assertEqual(raised.exception.code, "bad_response")

    async def test_latest_completion_accepts_object_array_and_empty(self):
        for payload, expected in [(COMPLETION, COMPLETION), ([COMPLETION], COMPLETION),
                                  ([], None), (None, None)]:
            with self.subTest(payload=payload):
                client, _ = await self.make_client(
                    lambda request, value=payload: httpx.Response(200, content=json.dumps(value))
                )
                self.assertEqual(await client.fetch("paceman", "latest_completion", "LEC666888"), expected)

    async def test_noncompletion_is_not_treated_as_latest_completion(self):
        client, _ = await self.make_client(lambda request: httpx.Response(200, json={"finish": None}))
        with self.assertRaises(ApiError) as raised:
            await client.fetch("paceman", "latest_completion", "LEC666888")
        self.assertEqual(raised.exception.code, "bad_response")

    async def test_pbs_query_formats_uuid_with_hyphens(self):
        requests = []

        def handle(request):
            requests.append(request)
            return httpx.Response(200, json=[{"uuid": UUID_DASHED, "finish": 509383}])

        client, _ = await self.make_client(handle)
        result = await client.fetch("paceman", "pbs", params={"uuids": UUID_HEX})
        self.assertEqual(result[0]["finish"], 509383)
        self.assertEqual(requests[0].url.path, "/stats/api/getPBs/")
        self.assertEqual(requests[0].url.params["uuids"], UUID_DASHED)
        self.assertNotIn("names", requests[0].url.params)
        with self.assertRaises(ApiError) as raised:
            await client.fetch("paceman", "pbs", params={"uuids": "not-a-uuid"})
        self.assertEqual(raised.exception.code, "invalid_request")
        self.assertEqual(len(requests), 1)

    async def test_matches_use_ranked_type_and_exclude_decay_and_allow_season(self):
        requests = []

        def handle(request):
            requests.append(request)
            return httpx.Response(200, json={"status": "success", "data": []})

        client, _ = await self.make_client(handle)
        self.assertEqual(await client.fetch("ranked", "matches", UUID_HEX), [])
        defaults = requests[0].url.params
        self.assertEqual(requests[0].url.path, f"/users/{UUID_HEX}/matches")
        self.assertEqual(defaults["type"], "2")
        self.assertEqual(defaults["sort"], "newest")
        self.assertEqual(defaults["excludedecay"], "true")
        self.assertEqual(defaults["count"], "5")
        await client.fetch("ranked", "matches", UUID_HEX, params={"season": 11, "count": 10})
        self.assertEqual(requests[1].url.params["season"], "11")
        self.assertEqual(requests[1].url.params["count"], "10")

    async def test_ranked_request_budget_blocks_without_sending(self):
        calls = 0

        def handle(request):
            nonlocal calls
            calls += 1
            return httpx.Response(200, json={"status": "success", "data": []})

        client, _ = await self.make_client(handle)
        client.RANKED_REQUEST_LIMIT = 2
        await client.fetch("ranked", "matches", "one")
        await client.fetch("ranked", "matches", "two")
        with self.assertRaises(ApiError) as raised:
            await client.fetch("ranked", "matches", "three")
        self.assertEqual(raised.exception.code, "rate_limited")
        self.assertGreater(raised.exception.retry_after, 590)
        self.assertEqual(calls, 2)

    async def test_shared_client_downloads_skin_and_honors_timeout(self):
        requests = []

        def handle(request):
            requests.append(request)
            return httpx.Response(200, content=b"image-bytes")

        client, _ = await self.make_client(handle)
        self.assertEqual(await client.get_bytes("https://render.crafty.gg/skin", timeout=3), b"image-bytes")
        self.assertEqual(requests[0].extensions["timeout"]["read"], 3)
        self.assertFalse(client._cache)

    async def test_oversized_skin_fails_without_caching(self):
        client, _ = await self.make_client(lambda request: httpx.Response(200, content=b"12345"))
        client.ASSET_SIZE_LIMIT = 4
        with self.assertRaises(ApiError) as raised:
            await client.get_bytes("https://render.crafty.gg/skin")
        self.assertEqual(raised.exception.code, "bad_response")
        self.assertFalse(client._cache)

    async def test_concurrent_close_cancels_pending_query_and_closes_once(self):
        entered = asyncio.Event()

        async def handle(request):
            entered.set()
            await asyncio.Event().wait()

        client, transport = await self.make_client(handle)
        query = asyncio.create_task(client.fetch("paceman", "latest_completion", "LEC666888"))
        await asyncio.wait_for(entered.wait(), 1)
        await asyncio.gather(client.aclose(), client.aclose())
        with self.assertRaises(asyncio.CancelledError):
            await query
        self.assertEqual(transport.close_count, 1)
        self.assertTrue(client._client.is_closed)
        self.assertFalse(client._inflight)
        with self.assertRaises(ApiError) as raised:
            await client.fetch("paceman", "latest_completion", "LEC666888")
        self.assertEqual(raised.exception.code, "unavailable")

    async def test_cancelled_close_waiter_does_not_abort_cleanup(self):
        entered, release = asyncio.Event(), asyncio.Event()
        client, transport = await self.make_client(lambda request: httpx.Response(200, json=[]))
        original_close = client._client.aclose

        async def delayed_close():
            entered.set()
            await release.wait()
            await original_close()

        client._client.aclose = delayed_close
        closing = asyncio.create_task(client.aclose())
        await asyncio.wait_for(entered.wait(), 1)
        closing.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await closing
        release.set()
        await asyncio.wait_for(client.aclose(), 1)
        self.assertTrue(client._client.is_closed)
        self.assertEqual(transport.close_count, 1)


class TimeFormattingTests(unittest.TestCase):
    def test_nullable_duration_and_long_duration(self):
        for value in (None, float("nan"), -1, True):
            self.assertEqual(format_time(value), "—")
        self.assertEqual(format_time(555739), "9:15")
        self.assertEqual(format_time(90000000), "1500:00")

    def test_explicit_timezone_and_millisecond_timestamp(self):
        self.assertEqual(to_local_time(57600), "1970-01-02")
        self.assertEqual(to_local_time(57600, "UTC"), "1970-01-01")
        self.assertEqual(to_local_time(57600000, milliseconds=True), "1970-01-02")
        self.assertEqual(to_local_time(None), "—")


if __name__ == "__main__":
    unittest.main()

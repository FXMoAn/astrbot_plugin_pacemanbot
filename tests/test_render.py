import asyncio
import hashlib
import io
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import _bootstrap  # noqa: F401
from pacemanbot_test import paceman as render
from PIL import Image


def png(color="white", size=(1280, 720)):
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG")
    return output.getvalue()


def sample_stats():
    return render.UserSessionStats(
        nether={"count": 24, "avg": "3:15"},
        bastion={"count": 99, "avg": "9:59"},
        fortress={"count": 98, "avg": "9:58"},
        first_structure={"count": 13, "avg": "4:35"},
        second_structure={"count": 7, "avg": "7:01"},
        first_portal=None,
        finish={"count": 2, "avg": "14:53"},
        truncated=True,
        future_field="ignored",
    )


class FakeAPI:
    def __init__(self):
        self.calls = 0
        self.fail = False

    async def get_bytes(self, url, timeout=None):
        self.calls += 1
        await asyncio.sleep(0.02)
        if self.fail:
            raise RuntimeError("Skin service unavailable")
        return png("blue", (20, 40))


class FakeStar:
    def __init__(self, directory):
        self.directory = directory
        self.calls = 0
        self.payloads = []
        self.failures = []
        self.content = None
        self.delay = 0

    async def html_render(self, tmpl, data, return_url=False, options=None):
        self.calls += 1
        call_number = self.calls
        self.payloads.append(data)
        await asyncio.sleep(self.delay)
        if self.failures:
            raise self.failures.pop(0)
        target = self.directory / f"render-{call_number}.png"
        content = self.content or png("red" if data["uname"] == "red" else "green")
        target.write_bytes(content)
        return str(target)


class RenderDataTests(unittest.TestCase):
    def test_null_segments_and_extra_api_fields_are_tolerated(self):
        stats = sample_stats()
        self.assertIsNone(stats.first_portal.count)
        self.assertIsNone(stats.end.avg)
        self.assertTrue(stats.truncated)
        run = render.RunStats(time=1790740000, first_portal=None, future_field=1)
        data = render.run_template_data(run, "Asia/Shanghai")
        self.assertEqual(data["times"]["first_portal"], "—")
        self.assertEqual(data["update_time"], "2026-09-30")

    def test_missing_nph_and_truncated_statistics_are_visible(self):
        data = render.session_template_data(sample_stats(), None, hours=48)
        self.assertEqual(data["hours"], 48)
        self.assertEqual(data["summary"]["rnph"], "—")
        self.assertTrue(data["nph_missing"])
        self.assertIn("不完整", data["notice"])
        self.assertIn("暂不可用", data["notice"])
        self.assertEqual(data["stats"]["bastion"], {"count": "13", "avg": "4:35"})
        self.assertEqual(data["stats"]["fortress"], {"count": "7", "avg": "7:01"})

    def test_small_valid_image_is_accepted_but_cropped_or_corrupt_image_is_not(self):
        complete = png(size=(640, 360))
        self.assertLess(len(complete), 4096)
        self.assertEqual(render.validate_image(complete, card=True), complete)
        with self.assertRaises(ValueError):
            render.validate_image(png(size=(1280, 600)), card=True)
        with self.assertRaises(Exception):
            render.validate_image(complete[:32], card=True)
        with self.assertRaises(ValueError):
            render.validate_image(b"<!doctype html>", card=True)


class RenderServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.api = FakeAPI()
        self.star = FakeStar(self.directory)
        self.services = []

    def service(self, **config):
        service = render.RenderService(self.star, self.api, self.directory, config)
        self.services.append(service)
        return service

    async def asyncTearDown(self):
        for service in self.services:
            await service.aclose()
        self.temporary.cleanup()

    async def test_concurrent_users_receive_separate_bytes_and_share_skin_request(self):
        service = self.service(render_concurrency=2)
        red, green = await asyncio.gather(
            service.session_image("red", sample_stats(), skin_id="same", hours=48),
            service.session_image("green", sample_stats(), skin_id="same", hours=48),
        )
        self.assertIsInstance(red, bytes)
        self.assertIsInstance(green, bytes)
        with Image.open(io.BytesIO(red)) as image:
            self.assertEqual(image.getpixel((0, 0)), (255, 0, 0))
        with Image.open(io.BytesIO(green)) as image:
            self.assertEqual(image.getpixel((0, 0)), (0, 128, 0))
        self.assertEqual(self.api.calls, 1)
        for payload in self.star.payloads:
            self.assertEqual(payload["stats"]["bastion"]["count"], "13")
            self.assertEqual(payload["stats"]["fortress"]["count"], "7")
            self.assertEqual(payload["hours"], 48)

    async def test_skin_cache_expires_is_bounded_and_preserves_stale_skin_on_failure(
        self,
    ):
        service = self.service(skin_cache_ttl=60, skin_cache_max_files=2)
        await service.session_image("red", sample_stats(), skin_id="first")
        await service.session_image("red", sample_stats(), skin_id="first")
        self.assertEqual(self.api.calls, 1)
        key = hashlib.sha256(b"first").hexdigest()
        cached = service.skin_dir / f"{key}.png"
        previous = cached.read_bytes()
        os.utime(cached, (0, 0))
        self.api.fail = True
        await service.session_image("red", sample_stats(), skin_id="first")
        self.assertEqual(self.api.calls, 2)
        self.assertEqual(cached.read_bytes(), previous)
        self.assertNotEqual(self.star.payloads[-1]["skin_uri"], "")
        self.api.fail = False
        await service.session_image("red", sample_stats(), skin_id="second")
        await service.session_image("red", sample_stats(), skin_id="third")
        self.assertEqual(len(list(service.skin_dir.glob("*.png"))), 2)
        self.assertFalse(list(service.skin_dir.glob("*.tmp")))

    async def test_only_temporary_html_failures_are_retried(self):
        service = self.service(render_attempts=2)
        self.star.failures = [RuntimeError("HTTP 503")]
        self.assertTrue(await service.session_image("red", sample_stats()))
        self.assertEqual(self.star.calls, 2)
        self.star.content = b"<!doctype html>"
        self.star.calls = 0
        self.assertTrue(await service.session_image("red", sample_stats()))
        self.assertEqual(self.star.calls, 1)
        self.star.content = None
        self.star.calls = 0
        self.star.failures = [RuntimeError("HTTP 503")]
        limited = self.service(render_attempts=1)
        self.assertTrue(await limited.session_image("red", sample_stats()))
        self.assertEqual(self.star.calls, 1)

    async def test_html_budget_falls_back_to_pil(self):
        service = self.service(render_timeout=1)
        self.star.delay = 3
        start = time.monotonic()
        image = await service.session_image("red", sample_stats())
        self.assertLess(time.monotonic() - start, 2)
        self.assertIsInstance(image, bytes)
        with Image.open(io.BytesIO(image)) as decoded:
            self.assertEqual(decoded.size, (1280, 720))
        self.assertEqual(self.star.calls, 1)

    async def test_pil_does_not_block_event_loop_and_failure_returns_text_signal(self):
        service = self.service(image_mode="pil")
        original = render._pil_image
        ticks = 0
        ticks_during_pil = []

        def slow_pil(*args, **kwargs):
            time.sleep(0.15)
            ticks_during_pil.append(ticks)
            return original(*args, **kwargs)

        async def heartbeat():
            nonlocal ticks
            for _ in range(10):
                await asyncio.sleep(0.01)
                ticks += 1

        with patch.object(render, "_pil_image", slow_pil):
            await asyncio.gather(
                service.session_image("red", sample_stats()), heartbeat()
            )
        self.assertEqual(ticks, 10)
        self.assertGreaterEqual(ticks_during_pil[0], 5)
        with patch.object(
            render, "_pil_image", side_effect=RuntimeError("PIL unavailable")
        ):
            self.assertIsNone(await service.session_image("red", sample_stats()))
        self.assertEqual(self.star.calls, 0)

    async def test_text_mode_makes_no_skin_or_render_requests(self):
        service = self.service(image_mode="text")
        self.assertIsNone(await service.session_image("red", sample_stats()))
        self.assertEqual(self.api.calls, 0)
        self.assertEqual(self.star.calls, 0)


if __name__ == "__main__":
    unittest.main()

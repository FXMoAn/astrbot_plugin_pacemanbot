import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import _bootstrap  # noqa: F401
from pacemanbot_test.main import PaceManPlugin
from pacemanbot_test.storage import BindingStore
from pacemanbot_test.utils import ApiError

from astrbot.core.star.filter.command import CommandFilter

UUID = "f2e05ad464b54d288fa18da14e9a2786"


class Event:
    def __init__(
        self, message="", sender="local-test-user", platform="qq-main", kind="aiocqhttp"
    ):
        self.message, self.sender, self.platform, self.kind = (
            message,
            sender,
            platform,
            kind,
        )
        self.is_at_or_wake_command = True
        self.extra = {}

    def get_sender_id(self):
        return self.sender

    def get_platform_id(self):
        return self.platform

    def get_platform_name(self):
        return self.kind

    def get_message_str(self):
        return self.message

    def set_extra(self, key, value):
        self.extra[key] = value

    def plain_result(self, text):
        return SimpleNamespace(text=text, chain=None)

    def chain_result(self, chain):
        return SimpleNamespace(text=None, chain=chain)


class MemoryKV:
    def __init__(self):
        self.values = {}

    async def get_kv_data(self, key, default):
        return copy.deepcopy(self.values.get(key, default))

    async def put_kv_data(self, key, value):
        self.values[key] = copy.deepcopy(value)

    async def delete_kv_data(self, key):
        self.values.pop(key, None)


class API:
    def __init__(self):
        self.calls = []
        self.failures = {}
        self.nickname = "LEC666888"

    async def fetch(self, provider, endpoint, username="", params=None):
        self.calls.append((provider, endpoint, username, params))
        failure = self.failures.get((provider, endpoint))
        if failure:
            raise failure
        if endpoint == "user_stats":
            return {
                "nickname": self.nickname,
                "uuid": UUID,
                "eloRate": 1700,
                "eloRank": 200,
                "statistics": {
                    "season": {
                        "playedMatches": {"ranked": 3},
                        "bestTime": {"ranked": None},
                        "completions": {"ranked": 0},
                        "wins": {"ranked": 1},
                    }
                },
            }
        if endpoint == "session_nethers":
            return {"uuid": UUID, "count": 0, "avg": "0:00"}
        if endpoint == "nickname":
            return {"name": self.nickname}
        if endpoint == "session_stats":
            return {
                "nether": {"count": 4, "avg": "0:30"},
                "first_structure": {"count": 3, "avg": "1:20"},
                "second_structure": {"count": 2, "avg": "2:30"},
                "bastion": {"count": 99, "avg": "9:99"},
                "truncated": True,
            }
        if endpoint == "nph_stats":
            return {"rnph": 1.0, "totalResets": 99}
        if endpoint == "latest_completion":
            return {"id": 1, "finish": 509383, "bastion": None, "time": 1778597391}
        if endpoint == "pbs":
            return [
                {"uuid": UUID, "finish": 509383, "pb": "8:29", "timestamp": 1778597391}
            ]
        if endpoint == "leaderboard":
            return {
                "season": {"number": 12},
                "users": [
                    {
                        "uuid": str(i),
                        "nickname": f"Player{i}",
                        "seasonResult": {"eloRate": 2200 - i, "eloRank": i + 1},
                    }
                    for i in range(25)
                ],
            }
        if endpoint == "matches":
            return []
        raise AssertionError(endpoint)

    async def aclose(self):
        pass


class Renderer:
    async def session_image(self, *args, **kwargs):
        return None

    async def run_image(self, *args, **kwargs):
        return None

    async def aclose(self):
        pass


class CommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.plugin = PaceManPlugin(SimpleNamespace(), {"image_mode": "text"})
        await self.plugin.api.aclose()
        self.plugin.api = API()
        self.plugin.renderer = Renderer()
        self.kv = MemoryKV()
        self.plugin.get_kv_data = self.kv.get_kv_data
        self.plugin.put_kv_data = self.kv.put_kv_data
        self.plugin.delete_kv_data = self.kv.delete_kv_data
        self.event = Event()
        await self.plugin.initialize()

    async def asyncTearDown(self):
        await self.plugin.terminate()

    async def command(self, name, *args):
        return [
            result async for result in getattr(self.plugin, name)(self.event, *args)
        ]

    async def test_register_either_provider_and_uuid(self):
        self.plugin.api.failures[("ranked", "user_stats")] = ApiError("not_found")
        result = (await self.command("register", "twitch_alias"))[0]
        self.assertIn("LEC666888", result.text)
        binding = await self.plugin.bindings.get(self.event)
        self.assertEqual(binding["uuid"], UUID)
        self.assertEqual(binding["source"], "paceman")

    async def test_register_failure_does_not_erase_existing_binding(self):
        await self.command("register", "LEC666888")
        self.plugin.api.failures = {
            ("ranked", "user_stats"): ApiError("rate_limited"),
            ("paceman", "session_nethers"): ApiError("not_found"),
        }
        text = (await self.command("register", "new_player"))[0].text
        self.assertIn("频繁", text)
        self.assertEqual(
            (await self.plugin.bindings.get(self.event))["username"], "LEC666888"
        )

    async def test_nph_failure_keeps_session_and_requested_mapping(self):
        self.plugin.api.failures[("paceman", "nph_stats")] = ApiError("timeout")
        text = (await self.command("paceman", "LEC666888", "48"))[0].text
        self.assertIn("最近48小时", text)
        self.assertIn("猪堡数量：3", text)
        self.assertIn("下要数量：2", text)
        self.assertNotIn("猪堡数量：99", text)
        self.assertIn("暂不可用", text)
        self.assertIn("部分数据", text)
        session = next(
            call for call in self.plugin.api.calls if call[1] == "session_stats"
        )
        self.assertEqual(session[3], {"hours": 48, "hoursBetween": 48})

    async def test_latest_completion_missing_splits_and_pb_uuid(self):
        run = (await self.command("run", "LEC666888"))[0].text
        self.assertIn("猪堡：—", run)
        self.assertIn("完成：8:29", run)
        self.assertNotIn("recent_runs", [call[1] for call in self.plugin.api.calls])
        pb = (await self.command("pb", "LEC666888"))[0].text
        self.assertIn("PB：8:29", pb)
        self.assertIn("日期：2026-05-", pb)
        self.assertEqual(self.plugin.api.calls[-1][3], {"uuids": UUID})

    async def test_all_commands_and_help_have_new_usage(self):
        await self.command("register", "LEC666888")
        rank = (await self.command("rank"))[0].text
        self.assertIn("已参加排位", rank)
        recent = (await self.command("recent", "3"))[0].text
        self.assertIn("暂无", recent)
        calls = [call for call in self.plugin.api.calls if call[1] == "matches"]
        self.assertEqual(calls[-1][3]["type"], 2)
        self.assertEqual(calls[-1][3]["excludedecay"], "true")
        board = (await self.command("ldb", "cn", "2", "11"))[0].text
        self.assertIn("第 2/2 页", board)
        self.assertIn("21. Player20", board)
        self.assertEqual(self.plugin.api.calls[-1][3], {"country": "cn", "season": 11})
        help_text = (await self.command("bothelp"))[0].text
        for command in ["/pb", "/recent", "/ldb cn 2", "/rank", "1–168"]:
            self.assertIn(command, help_text)

    async def test_actual_astrbot_argument_parser(self):
        await self.command("register", "LEC666888")
        for command, message in [
            ("paceman", "paceman 48"),
            ("rank", "rank 0"),
            ("recent", "recent 3"),
            ("ldb", "ldb cn 2 11"),
        ]:
            metadata = SimpleNamespace(handler=getattr(PaceManPlugin, command))
            command_filter = CommandFilter(command, handler_md=metadata)
            event = Event(message)
            self.assertTrue(command_filter.filter(event, {}))
            results = [
                result
                async for result in getattr(self.plugin, command)(
                    event, **event.extra["parsed_params"]
                )
            ]
            self.assertNotIn("失败", results[0].text)
        invalid = (await self.command("paceman", "LEC666888", "0"))[0].text
        self.assertIn("1–168", invalid)

    async def test_unregistered_user_and_saved_name_refresh(self):
        text = (await self.command("rank"))[0].text
        self.assertIn("/register", text)
        await self.command("register", "LEC666888")
        self.plugin.api.nickname = "RenamedPlayer"
        await self.command("paceman")
        self.assertEqual(
            (await self.plugin.bindings.get(self.event))["username"], "RenamedPlayer"
        )

    async def test_current_season_alias_is_not_sent_to_api(self):
        await self.command("register", "LEC666888")
        result = (await self.command("rank", "0"))[0]
        self.assertIn("本赛季", result.text)
        self.assertIsNone(self.plugin.api.calls[-1][3])
        await self.command("ldb", "cn", "1", "0")
        self.assertEqual(self.plugin.api.calls[-1][3], {"country": "cn"})


class StorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.kv = MemoryKV()
        self.legacy = self.path / "astrbot-pacemanbot.json"
        self.store = BindingStore(self.kv, self.path / "plugin", self.legacy)

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def test_legacy_backup_and_platform_scope(self):
        payload = {"42": {"username": "LEC666888", "gg_count": 10}}
        self.legacy.write_text(json.dumps(payload), encoding="utf-8")
        await self.store.initialize()
        unrelated = Event(sender="42", platform="discord", kind="discord")
        self.assertIsNone(await self.store.get(unrelated))
        qq = Event(sender="42")
        binding = await self.store.get(qq)
        self.assertEqual(binding["username"], "LEC666888")
        self.assertEqual(json.loads(self.legacy.read_text()), payload)
        self.assertEqual(
            (self.path / "plugin" / "legacy-bindings-backup.json").read_bytes(),
            self.legacy.read_bytes(),
        )
        other_instance = Event(sender="42", platform="qq-other")
        self.assertIsNone(await self.store.get(other_instance))
        await self.store.put(other_instance, {"username": "Other", "uuid": None})
        self.assertEqual((await self.store.get(qq))["username"], "LEC666888")
        self.assertEqual((await self.store.get(other_instance))["username"], "Other")

    async def test_corrupt_legacy_does_not_break_new_bindings(self):
        self.legacy.write_text("{broken", encoding="utf-8")
        await self.store.initialize()
        await self.store.put(Event(), {"username": "LEC666888", "uuid": UUID})
        self.assertEqual((await self.store.get(Event()))["uuid"], UUID)
        self.assertEqual(
            (self.path / "plugin" / "legacy-bindings-backup.json").read_text(),
            "{broken",
        )

    async def test_simultaneous_bindings_do_not_overwrite_other_users(self):
        await asyncio.gather(
            *[
                self.store.put(Event(sender=str(i)), {"username": f"User{i}"})
                for i in range(20)
            ]
        )
        bindings = await asyncio.gather(
            *[self.store.get(Event(sender=str(i))) for i in range(20)]
        )
        self.assertEqual(
            [value["username"] for value in bindings], [f"User{i}" for i in range(20)]
        )


if __name__ == "__main__":
    unittest.main()

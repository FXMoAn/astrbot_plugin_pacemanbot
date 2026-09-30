import copy
import unittest

import _bootstrap  # noqa: F401
from pacemanbot_test.ranked import (
    RankedDataError,
    format_leaderboard,
    format_rank,
    format_recent,
)

PLAYER_UUID = "f2e05ad464b54d288fa18da14e9a2786"
OPPONENT_UUID = "94915bf21f3940acaf74693750a265cf"


def player_profile():
    return {
        "uuid": PLAYER_UUID,
        "nickname": "Runner",
        "eloRate": 1739,
        "eloRank": 176,
        "statistics": {
            "season": {
                "playedMatches": {"ranked": 10},
                "completions": {"ranked": 4},
                "bestTime": {"ranked": 456856},
                "completionTime": {"ranked": 2400000},
                "wins": {"ranked": 6},
                "forfeits": {"ranked": 2},
            }
        },
        "seasonResult": {"last": {"eloRate": 1798, "eloRank": 294}},
    }


def match_record(**overrides):
    record = {
        "id": 12345,
        "type": 2,
        "date": 1790696601,
        "players": [
            {"uuid": OPPONENT_UUID, "nickname": "Other"},
            {"uuid": PLAYER_UUID, "nickname": "Runner"},
        ],
        "result": {"uuid": PLAYER_UUID, "time": 436119},
        "changes": [
            {"uuid": OPPONENT_UUID, "change": -20, "eloRate": 1752},
            {"uuid": PLAYER_UUID, "change": 20, "eloRate": 1719},
        ],
        "forfeited": False,
        "decayed": False,
    }
    record.update(overrides)
    return record


class RankedProfileTests(unittest.TestCase):
    def setUp(self):
        self.profile = player_profile()

    def test_no_pb_with_played_matches_does_not_claim_inactivity(self):
        stats = self.profile["statistics"]["season"]
        stats["bestTime"]["ranked"] = None
        stats["completions"]["ranked"] = 0
        stats["completionTime"]["ranked"] = None
        result = format_rank(self.profile)
        self.assertIn("已参加排位，暂无完成记录", result)
        self.assertNotIn("未参加排位", result)
        self.assertIn("赛季胜率：60.00%", result)
        self.assertIn("平均完成时间：暂无完成记录", result)

    def test_zero_denominators_are_displayed_without_division(self):
        stats = self.profile["statistics"]["season"]
        for name in ("playedMatches", "completions", "completionTime", "wins", "forfeits"):
            stats[name]["ranked"] = 0
        stats["bestTime"]["ranked"] = None
        self.profile["eloRate"] = None
        self.profile["eloRank"] = None
        result = format_rank(self.profile)
        self.assertIn("本赛季未参加排位", result)
        self.assertIn("赛季胜率：暂无数据", result)
        self.assertIn("赛季弃权率：暂无数据", result)
        self.assertNotIn("None", result)

    def test_placement_rating_null_is_shown_as_placement(self):
        self.profile["eloRate"] = None
        self.profile["eloRank"] = None
        result = format_rank(self.profile)
        self.assertIn("Elo：定级中", result)
        self.assertIn("全球排名：定级中", result)

    def test_null_statistics_are_distinct_from_zero_matches(self):
        stats = self.profile["statistics"]["season"]
        for item in stats.values():
            item["ranked"] = None
        result = format_rank(self.profile)
        self.assertIn("赛季场次暂无数据", result)
        self.assertNotIn("未参加排位", result)
        self.assertIn("赛季胜率：暂无数据", result)

    def test_historical_rating_uses_season_last(self):
        result = format_rank(self.profile, season=10)
        self.assertIn("第10赛季", result)
        self.assertIn("Elo：1798", result)
        self.assertIn("全球排名：294", result)
        self.assertNotIn("Elo：1739", result)

    def test_current_season_uses_top_level_rating(self):
        result = format_rank(self.profile)
        self.assertIn("Elo：1739", result)
        self.assertIn("全球排名：176", result)
        self.assertEqual(format_rank(self.profile, season=0), result)

    def test_missing_pb_does_not_erase_known_completions(self):
        self.profile["statistics"]["season"]["bestTime"]["ranked"] = None
        result = format_rank(self.profile)
        self.assertIn("完成次数：4", result)
        self.assertIn("赛季 PB：暂无时间数据", result)
        self.assertNotIn("暂无完成记录", result)

    def test_malformed_statistics_raise_a_display_error(self):
        self.profile["statistics"]["season"]["wins"]["ranked"] = "invalid"
        with self.assertRaises(RankedDataError):
            format_rank(self.profile)


class RankedLeaderboardTests(unittest.TestCase):
    def setUp(self):
        self.board = {
            "season": {"number": 12},
            "users": [
                {
                    "nickname": f"P{position}",
                    "country": "cn",
                    "seasonResult": {"eloRate": 2000 - position, "eloRank": 100 + position},
                }
                for position in range(23)
            ],
        }

    def test_china_second_page_preserves_board_and_global_positions(self):
        result = format_leaderboard(self.board, country="cn", page=2)
        self.assertIn("中国榜单（第 2/2 页）", result)
        self.assertIn("21. P20", result)
        self.assertIn("全球 #120", result)
        self.assertIn("23. P22", result)
        self.assertNotIn("20. P19", result)
        self.assertIn("country=cn", result)

    def test_global_page_uses_configured_page_size(self):
        result = format_leaderboard(self.board, page=1, page_size=5)
        self.assertIn("全球榜单（第 1/5 页）", result)
        self.assertIn("5. P4", result)
        self.assertNotIn("6. P5", result)
        self.assertNotIn("country=cn", result)

    def test_out_of_range_page_is_a_useful_message(self):
        result = format_leaderboard(self.board, page=3)
        self.assertIn("共有 2 页", result)
        self.assertIn("1–2", result)

    def test_empty_board_is_not_a_format_error(self):
        self.assertIn("暂无玩家数据", format_leaderboard({"users": []}))

    def test_missing_users_is_a_format_error(self):
        with self.assertRaises(RankedDataError):
            format_leaderboard({"season": {"number": 12}})


class RankedRecentTests(unittest.TestCase):
    def setUp(self):
        self.profile = player_profile()

    def test_win_matches_player_uuid_and_shows_before_and_after_elo(self):
        result = format_recent([match_record()], self.profile)
        self.assertIn("| 胜 | 对手 Other", result)
        self.assertIn("Elo +20（1719 → 1739）", result)
        self.assertIn("比赛用时 7分16秒", result)
        self.assertIn("09-29 23:43", result)

    def test_loss_and_forfeit_do_not_claim_player_completion(self):
        record = match_record(result={"uuid": OPPONENT_UUID, "time": 436119}, forfeited=True)
        record["changes"][1] = {"uuid": PLAYER_UUID, "change": -20, "eloRate": 1759}
        result = format_recent([record], self.profile)
        self.assertIn("负，弃权结束", result)
        self.assertIn("Elo -20（1759 → 1739）", result)
        self.assertIn("比赛用时", result)
        self.assertNotIn("个人完成", result)

    def test_draw_and_nullable_placement_changes(self):
        record = match_record(result={"uuid": None, "time": 300000})
        record["changes"][1] = {"uuid": PLAYER_UUID, "change": None, "eloRate": None}
        result = format_recent([record], self.profile)
        self.assertIn("| 平局 |", result)
        self.assertIn("定级赛，暂无 Elo 变化", result)

    def test_decay_casual_and_unrelated_games_are_filtered(self):
        unrelated = match_record(id=3, players=[{"uuid": OPPONENT_UUID, "nickname": "Other"}])
        records = [match_record(id=1, decayed=True), match_record(id=2, type=1), unrelated]
        self.assertIn("暂无近期排位", format_recent(records, self.profile))

    def test_empty_matches_are_a_valid_empty_result(self):
        self.assertIn("暂无近期排位", format_recent([], self.profile))

    def test_nullable_elo_without_pre_match_rating_still_shows_change(self):
        record = match_record()
        record["changes"][1] = {"uuid": PLAYER_UUID, "change": 20, "eloRate": None}
        result = format_recent([record], self.profile)
        self.assertIn("Elo +20", result)
        self.assertNotIn("None", result)

    def test_hyphenated_uuid_identifies_the_same_player(self):
        self.profile["uuid"] = "f2e05ad4-64b5-4d28-8fa1-8da14e9a2786"
        result = format_recent([match_record()], self.profile)
        self.assertIn("| 胜 |", result)
        self.assertIn("Elo +20", result)

    def test_limit_counts_only_real_ranked_games(self):
        records = [match_record(id=1, decayed=True), match_record(id=2), match_record(id=3)]
        result = format_recent(records, self.profile, limit=1)
        self.assertIn("最近 1 场", result)
        self.assertIn("#2", result)
        self.assertNotIn("#3", result)

    def test_malformed_required_result_or_changes_raise(self):
        for field in ("result", "changes"):
            with self.subTest(field=field), self.assertRaises(RankedDataError):
                record = copy.deepcopy(match_record())
                record[field] = None
                format_recent([record], self.profile)


if __name__ == "__main__":
    unittest.main()

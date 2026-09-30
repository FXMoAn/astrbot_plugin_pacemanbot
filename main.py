import asyncio
import re
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image, Plain
from astrbot.api.star import Context, Star, register
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .paceman import RenderService, RunStats, UserSessionStats
from .ranked import RankedDataError, format_leaderboard, format_rank, format_recent
from .storage import BindingStore, normalize_uuid
from .utils import ApiClient, ApiError, format_time, to_local_time

DEFAULT_CONFIG = {
    "request_timeout": 10,
    "request_concurrency": 6,
    "user_cache_ttl": 20,
    "leaderboard_cache_ttl": 60,
    "render_concurrency": 2,
    "render_timeout": 12,
    "render_attempts": 2,
    "skin_timeout": 3,
    "skin_cache_ttl": 86400,
    "skin_cache_max_files": 200,
    "leaderboard_page_size": 20,
    "paceman_hours": 24,
    "timezone": "Asia/Shanghai",
    "image_mode": "auto",
}


class UserInputError(ValueError):
    pass


def _integer(value, minimum: int, maximum: int, label: str) -> int:
    try:
        if isinstance(value, bool) or not re.fullmatch(r"\d+", str(value)):
            raise ValueError
        number = int(value)
    except (ValueError, TypeError):
        raise UserInputError(f"{label}必须是 {minimum}–{maximum} 的整数。") from None
    if not minimum <= number <= maximum:
        raise UserInputError(f"{label}必须是 {minimum}–{maximum} 的整数。")
    return number


def _config(config) -> dict:
    values = dict(DEFAULT_CONFIG)
    if config:
        for key in values:
            values[key] = config.get(key, values[key])
    limits = {
        "request_timeout": (1, 60),
        "request_concurrency": (1, 20),
        "user_cache_ttl": (0, 3600),
        "leaderboard_cache_ttl": (0, 3600),
        "render_concurrency": (1, 8),
        "render_timeout": (1, 60),
        "render_attempts": (1, 2),
        "skin_timeout": (1, 20),
        "skin_cache_ttl": (0, 2592000),
        "skin_cache_max_files": (1, 2000),
        "leaderboard_page_size": (1, 50),
        "paceman_hours": (1, 168),
    }
    for key, (minimum, maximum) in limits.items():
        try:
            values[key] = _integer(values[key], minimum, maximum, key)
        except UserInputError:
            logger.warning("Invalid PaceMan config %s; using default.", key)
            values[key] = DEFAULT_CONFIG[key]
    try:
        ZoneInfo(str(values["timezone"]))
    except (ValueError, KeyError, TypeError):
        values["timezone"] = DEFAULT_CONFIG["timezone"]
    if values["image_mode"] not in {"auto", "pil", "text"}:
        values["image_mode"] = "auto"
    return values


@register("pacemanbot", "Mo_An", "查询 PaceMan 和 MCSR Ranked 速通数据", "1.6.0")
class PaceManPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = _config(config)
        data_root = Path(get_astrbot_data_path())
        self.data_dir = data_root / "plugin_data" / "pacemanbot"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.api = ApiClient(
            request_timeout=self.config["request_timeout"],
            request_concurrency=self.config["request_concurrency"],
            user_cache_ttl=self.config["user_cache_ttl"],
            leaderboard_cache_ttl=self.config["leaderboard_cache_ttl"],
        )
        self.bindings = BindingStore(
            self, self.data_dir, data_root / "astrbot-pacemanbot.json"
        )
        self.renderer = RenderService(self, self.api, self.data_dir, self.config)

    async def initialize(self):
        await self.bindings.initialize()

    async def terminate(self):
        try:
            await self.renderer.aclose()
        finally:
            await self.api.aclose()

    @filter.command("bothelp", alias={"pmhelp"})
    async def bothelp(self, event: AstrMessageEvent):
        """查看 PaceMan／Ranked 命令、参数和示例；也可使用 /pmhelp。"""
        yield event.plain_result(
            "PaceMan / MCSR Ranked 帮助\n"
            "/register 用户名：绑定玩家，PaceMan 或 Ranked 能查到即可\n"
            f"/paceman [用户名] [小时]：统计速通数据，默认{self.config['paceman_hours']}小时，范围1–168\n"
            "/run [用户名]：查询最近一次完成的速通，缺失分段显示 —\n"
            "/pb [用户名]：查询 PaceMan 个人最好成绩\n"
            "/rank [用户名] [赛季]：查询排位成绩，省略赛季或填0查当前赛季\n"
            "/recent [用户名] [条数]：最近排位比赛，默认5场，范围1–10\n"
            f"/ldb [cn] [页码] [赛季]：全球／中国榜单，每页{self.config['leaderboard_page_size']}名，默认第1页和当前赛季\n"
            "省略用户名使用已绑定玩家；仅填数字时表示小时／赛季／条数。\n"
            "示例：/paceman LEC666888 48；/rank LEC666888 11；/recent 5\n"
            "榜单示例：/ldb 2；/ldb cn 2；/ldb cn 1 11\n"
            "中国榜按玩家资料 country=cn 筛选；榜单序号与全球排名分别显示。\n"
            "统计图片保留第一／第二结构对应猪堡／下要的显示口径。\n"
            "数据有短期缓存；RNPH 来自追踪器统计，数据缺失会注明。\n"
            "项目：https://github.com/FXMoAn/astrbot_plugin_pacemanbot"
        )

    async def _identity(self, name: str) -> dict:
        name = str(name).strip()
        if not name or not (
            re.fullmatch(r"[A-Za-z0-9_]{1,32}", name) or normalize_uuid(name)
        ):
            raise UserInputError("请输入有效的游戏名、Twitch 名或玩家 UUID。")
        ranked, paceman = await asyncio.gather(
            self.api.fetch("ranked", "user_stats", name),
            self.api.fetch("paceman", "session_nethers", name),
            return_exceptions=True,
        )
        ranked_uuid = (
            normalize_uuid(ranked.get("uuid")) if isinstance(ranked, dict) else None
        )
        paceman_uuid = (
            normalize_uuid(paceman.get("uuid")) if isinstance(paceman, dict) else None
        )
        if ranked_uuid and paceman_uuid and ranked_uuid != paceman_uuid:
            raise UserInputError("该名称在两个平台对应不同玩家，请改用游戏名或 UUID。")
        player_uuid = ranked_uuid or paceman_uuid
        if not player_uuid:
            failures = [
                item for item in (ranked, paceman) if isinstance(item, ApiError)
            ]
            for failure in failures:
                if failure.code != "not_found":
                    raise failure
            if any(not isinstance(item, ApiError) for item in (ranked, paceman)):
                raise RankedDataError("Player response has no valid UUID")
            raise UserInputError("PaceMan 和 MCSR Ranked 均未找到该玩家。")
        canonical_name = ranked.get("nickname") if isinstance(ranked, dict) else None
        if not canonical_name:
            nickname = await self.api.fetch("paceman", "nickname", player_uuid)
            canonical_name = (
                nickname.get("name") if isinstance(nickname, dict) else None
            )
        if not isinstance(canonical_name, str) or not re.fullmatch(
            r"[A-Za-z0-9_]{1,16}", canonical_name
        ):
            raise RankedDataError("Could not resolve canonical Minecraft nickname")
        source = "ranked" if ranked_uuid else "paceman"
        if ranked_uuid and paceman_uuid:
            source = "paceman+ranked"
        return {"username": canonical_name, "uuid": player_uuid, "source": source}

    async def _player(self, event, name: str = "") -> dict:
        if name:
            return await self._identity(name)
        binding = await self.bindings.get(event)
        if not binding:
            raise UserInputError(
                "请先使用 /register 用户名 绑定玩家，或在命令后填写用户名。"
            )
        if not normalize_uuid(binding.get("uuid")):
            binding = await self._identity(binding["username"])
            await self.bindings.put(event, binding)
        else:
            try:
                nickname = await self.api.fetch("paceman", "nickname", binding["uuid"])
                canonical_name = nickname.get("name")
                if (
                    isinstance(canonical_name, str)
                    and re.fullmatch(r"[A-Za-z0-9_]{1,16}", canonical_name)
                    and canonical_name != binding["username"]
                ):
                    binding = dict(binding, username=canonical_name)
                    await self.bindings.put(event, binding)
            except ApiError:
                logger.info("Player name refresh unavailable; using stored nickname.")
        return binding

    @staticmethod
    def _optional_number(name, value, default, minimum, maximum, label):
        name = str(name or "").strip()
        if not value and name.isdecimal():
            name, value = "", name
        number = (
            default if value in (None, "") else _integer(value, minimum, maximum, label)
        )
        return name, number

    @staticmethod
    def _error(error: Exception) -> str:
        if isinstance(error, (UserInputError, ApiError)):
            return str(error)
        if isinstance(error, (ValidationError, RankedDataError)):
            logger.exception("PaceMan/Ranked response format error.")
            return "数据格式暂时无法识别，请稍后重试。"
        logger.exception("PaceMan command failed.")
        return "查询暂时失败，请稍后重试。"

    @filter.command("register")
    async def register(self, event: AstrMessageEvent, username: str = ""):
        """/register 用户名：通过 PaceMan 或 Ranked 校验，保存玩家 UUID 与游戏名。"""
        try:
            if not username:
                raise UserInputError("用法：/register 用户名")
            binding = await self._identity(username)
            await self.bindings.put(event, binding)
            yield event.plain_result(f"绑定成功，当前游戏名：{binding['username']}")
        except Exception as error:
            yield event.plain_result(self._error(error))

    @filter.command("paceman")
    async def paceman(self, event: AstrMessageEvent, name: str = "", hours: str = ""):
        """/paceman [用户名] [小时]：查询1–168小时统计，默认24小时。"""
        try:
            name, hours = self._optional_number(
                name, hours, self.config["paceman_hours"], 1, 168, "小时数"
            )
            player = await self._player(event, name)
            params = {"hours": hours, "hoursBetween": hours}
            session, nph = await asyncio.gather(
                self.api.fetch(
                    "paceman", "session_stats", player["username"], params=params
                ),
                self.api.fetch(
                    "paceman", "nph_stats", player["username"], params=params
                ),
                return_exceptions=True,
            )
            if isinstance(session, BaseException):
                raise session
            if isinstance(nph, BaseException):
                logger.warning("Optional PaceMan NPH query failed: %s", nph)
                nph = None
            data = UserSessionStats.model_validate(session)
            text = self._session_text(player["username"], data, nph, hours)
            image = await self.renderer.session_image(
                player["username"], data, nph, skin_id=player["uuid"], hours=hours
            )
            yield (
                event.chain_result([Image.fromBytes(image)])
                if image
                else event.plain_result(text)
            )
        except Exception as error:
            yield event.plain_result(self._error(error))

    @staticmethod
    def _session_text(username, data, nph, hours):
        lines = [f"{username} 最近{hours}小时 PaceMan 数据"]
        for label, field in (
            ("下界", "nether"),
            ("猪堡", "first_structure"),
            ("下要", "second_structure"),
            ("盲传", "first_portal"),
            ("要塞", "stronghold"),
            ("末地", "end"),
            ("完成", "finish"),
        ):
            stats = getattr(data, field)
            lines.append(
                f"{label}数量：{stats.count if stats.count is not None else '—'}，平均时间：{stats.avg or '—'}"
            )
        if nph is None:
            lines.append("RNPH：暂不可用")
        else:
            lines.append(
                f"RNPH：{nph.get('rnph') if nph.get('rnph') is not None else '—'}"
            )
            lines.append(
                f"追踪器累计刷种数：{nph.get('totalResets') if nph.get('totalResets') is not None else '—'}"
            )
        if data.truncated or (nph and nph.get("truncated")):
            lines.append("记录较多，统计包含最近部分数据。")
        return "\n".join(lines)

    @filter.command("run")
    async def run(self, event: AstrMessageEvent, name: str = ""):
        """/run [用户名]：查询 PaceMan 最近一次完成记录，省略用户名查本人。"""
        try:
            player = await self._player(event, name)
            payload = await self.api.fetch(
                "paceman", "latest_completion", player["username"]
            )
            if not payload:
                yield event.plain_result(f"{player['username']} 暂无完成的速通记录。")
                return
            data = RunStats.model_validate(payload)
            text = self._run_text(player["username"], data)
            image = await self.renderer.run_image(
                player["username"], data, skin_id=player["uuid"]
            )
            yield (
                event.chain_result(
                    [
                        Plain(f"{player['username']} 的最近一次完成记录"),
                        Image.fromBytes(image),
                    ]
                )
                if image
                else event.plain_result(text)
            )
        except Exception as error:
            yield event.plain_result(self._error(error))

    def _run_text(self, username, data):
        stamp = data.updatedTime or data.time
        lines = [
            f"{username} 的最近一次完成记录",
            f"日期：{to_local_time(stamp, self.config['timezone']) if stamp else '—'}",
        ]
        for label, field in (
            ("下界", "nether"),
            ("猪堡", "bastion"),
            ("下要", "fortress"),
            ("盲传", "first_portal"),
            ("要塞", "stronghold"),
            ("末地", "end"),
            ("完成", "finish"),
        ):
            lines.append(f"{label}：{format_time(getattr(data, field))}")
        return "\n".join(lines)

    @filter.command("rank")
    async def rank(self, event: AstrMessageEvent, name: str = "", season: str = ""):
        """/rank [用户名] [赛季]：查询排位数据；赛季0或省略表示当前赛季。"""
        try:
            name, season = self._optional_number(name, season, None, 0, 10000, "赛季")
            season = season or None
            player = await self._player(event, name)
            profile = await self.api.fetch(
                "ranked",
                "user_stats",
                player["uuid"],
                params={"season": season} if season is not None else None,
            )
            yield event.plain_result(format_rank(profile, season=season))
        except Exception as error:
            yield event.plain_result(self._error(error))

    @filter.command("ldb")
    async def ldb(
        self,
        event: AstrMessageEvent,
        region: str = "",
        page: str = "",
        season: str = "",
    ):
        """/ldb [cn] [页码] [赛季]：分页查询全球／中国排位榜单。"""
        try:
            country = "cn" if str(region).lower() == "cn" else None
            if country:
                page_value, season_value = page or "1", season
            else:
                if season:
                    raise UserInputError(
                        "用法：/ldb [cn] [页码] [赛季]，例如 /ldb cn 2 11"
                    )
                page_value, season_value = region or "1", page
            page_number = _integer(page_value, 1, 10000, "页码")
            season_number = (
                _integer(season_value, 0, 10000, "赛季") if season_value else None
            )
            params = {}
            if country:
                params["country"] = country
            if season_number:
                params["season"] = season_number
            payload = await self.api.fetch("ranked", "leaderboard", params=params)
            yield event.plain_result(
                format_leaderboard(
                    payload,
                    country=country,
                    page=page_number,
                    page_size=self.config["leaderboard_page_size"],
                )
            )
        except Exception as error:
            yield event.plain_result(self._error(error))

    @filter.command("recent")
    async def recent(self, event: AstrMessageEvent, name: str = "", count: str = ""):
        """/recent [用户名] [条数]：查询最近1–10场排位，排除分数衰减记录。"""
        try:
            name, count = self._optional_number(name, count, 5, 1, 10, "条数")
            player = await self._player(event, name)
            profile, matches = await asyncio.gather(
                self.api.fetch("ranked", "user_stats", player["uuid"]),
                self.api.fetch(
                    "ranked",
                    "matches",
                    player["uuid"],
                    params={
                        "count": count,
                        "type": 2,
                        "sort": "newest",
                        "excludedecay": "true",
                    },
                ),
            )
            yield event.plain_result(
                format_recent(
                    matches, profile, limit=count, timezone=self.config["timezone"]
                )
            )
        except Exception as error:
            yield event.plain_result(self._error(error))

    @filter.command("pb")
    async def pb(self, event: AstrMessageEvent, name: str = ""):
        """/pb [用户名]：查询 PaceMan 个人最好成绩，省略用户名查本人。"""
        try:
            player = await self._player(event, name)
            records = await self.api.fetch(
                "paceman", "pbs", params={"uuids": player["uuid"]}
            )
            if not records:
                yield event.plain_result(
                    f"{player['username']} 暂无 PaceMan 个人最好成绩记录。"
                )
                return
            yield event.plain_result(self._pb_text(player["username"], records))
        except Exception as error:
            yield event.plain_result(self._error(error))

    def _pb_text(self, username: str, records: list) -> str:
        lines = [f"{username} 的 PaceMan 个人最好成绩"]
        for record in records:
            if not isinstance(record, dict):
                raise RankedDataError("Invalid PaceMan PB record")
            duration = record.get("finish")
            if not isinstance(duration, (int, float)) or duration <= 0:
                raise RankedDataError("PaceMan PB record has no valid completion time")
            lines.append(f"PB：{format_time(duration)}")
            stamp = (
                record.get("timestamp")
                or record.get("updatedTime")
                or record.get("realUpdated")
            )
            if stamp:
                lines.append(f"日期：{to_local_time(stamp, self.config['timezone'])}")
        return "\n".join(lines)

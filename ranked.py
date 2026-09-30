"""Validated Ranked data and formatting, independent of network and AstrBot."""

from datetime import datetime
from math import ceil
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class RankedDataError(ValueError):
    """The API returned data that cannot be safely displayed."""


class RankedModel(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class RankedStat(RankedModel):
    ranked: int | None = None
    casual: int | None = None


class RankedSeasonStatistics(RankedModel):
    bestTime: RankedStat = Field(default_factory=RankedStat)
    playedMatches: RankedStat = Field(default_factory=RankedStat)
    wins: RankedStat = Field(default_factory=RankedStat)
    loses: RankedStat = Field(default_factory=RankedStat)
    forfeits: RankedStat = Field(default_factory=RankedStat)
    completions: RankedStat = Field(default_factory=RankedStat)
    completionTime: RankedStat = Field(default_factory=RankedStat)


class RankedStatistics(RankedModel):
    season: RankedSeasonStatistics = Field(default_factory=RankedSeasonStatistics)
    total: RankedSeasonStatistics = Field(default_factory=RankedSeasonStatistics)


class RankedStanding(RankedModel):
    eloRate: int | None = None
    eloRank: int | None = None


class RankedSeasonResult(RankedModel):
    last: RankedStanding | None = None
    highest: int | None = None
    lowest: int | None = None


class RankedUser(RankedModel):
    uuid: str = ""
    nickname: str = Field(min_length=1)
    eloRate: int | None = None
    eloRank: int | None = None
    country: str | None = None


class RankedProfile(RankedUser):
    statistics: RankedStatistics = Field(default_factory=RankedStatistics)
    seasonResult: RankedSeasonResult | None = None


class RankedLeaderboardUser(RankedUser):
    seasonResult: RankedStanding | None = None


class RankedLeaderboardSeason(RankedModel):
    number: int | None = None
    startsAt: int | None = None
    endsAt: int | None = None


class RankedLeaderboard(RankedModel):
    season: RankedLeaderboardSeason = Field(default_factory=RankedLeaderboardSeason)
    users: list[RankedLeaderboardUser]


class RankedMatchResult(RankedModel):
    uuid: str | None = None
    time: int | None = None


class RankedEloChange(RankedModel):
    uuid: str
    change: int | None = None
    eloRate: int | None = None


class RankedMatch(RankedModel):
    id: int
    type: int
    season: int | None = None
    date: int | None = None
    players: list[RankedUser]
    result: RankedMatchResult
    changes: list[RankedEloChange] = Field(default_factory=list)
    forfeited: bool = False
    decayed: bool = False


def _parse(model, data):
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise RankedDataError("Ranked 数据格式异常，请稍后重试。") from exc


def _uuid_key(value: str | None) -> str:
    return (value or "").replace("-", "").lower()


def _time_text(milliseconds: int | float | None) -> str:
    if milliseconds is None or milliseconds < 0:
        return "暂无完成记录"
    minutes, seconds = divmod(int(milliseconds) // 1000, 60)
    return f"{minutes}分{seconds:02d}秒"


def _rate_text(numerator: int | None, denominator: int | None) -> str:
    if numerator is None or denominator is None or denominator <= 0:
        return "暂无数据"
    return f"{numerator / denominator * 100:.2f}%"


def format_rank(profile: dict, season: int | None = None) -> str:
    """Format an unpacked /users response without treating a missing PB as inactivity."""
    if season == 0:
        season = None
    user = _parse(RankedProfile, profile)
    stats = user.statistics.season
    played = stats.playedMatches.ranked
    completions = stats.completions.ranked
    standing = user.seasonResult.last if user.seasonResult else None
    # A historical user's top-level rating still describes their current profile.
    # Historical ratings must come from the selected season's last standing.
    if season is not None:
        elo = standing.eloRate if standing else None
        rank = standing.eloRank if standing else None
    else:
        elo = user.eloRate
        rank = user.eloRank
    title = f"第{season}赛季" if season is not None else "本赛季"
    lines = [f"{user.nickname} 的 MCSR Ranked {title}数据"]
    if played == 0:
        lines.append("本赛季未参加排位。" if season is None else "该赛季未参加排位。")
    elif played is None:
        lines.append("赛季场次暂无数据。")
    elif completions == 0:
        lines.append("已参加排位，暂无完成记录。")
    elif completions is None and stats.bestTime.ranked is None:
        lines.append("已参加排位，暂无完成时间数据。")

    if elo is None:
        elo_text = (
            "暂无成绩" if played == 0 else ("暂无数据" if played is None else "定级中")
        )
    else:
        elo_text = str(elo)
    rank_text = (
        str(rank)
        if rank is not None
        else (
            "定级中"
            if elo is None and played is not None and played > 0
            else "暂无排名"
        )
    )
    average = None
    if (
        completions is not None
        and completions > 0
        and stats.completionTime.ranked is not None
    ):
        average = stats.completionTime.ranked / completions
    best_text = _time_text(stats.bestTime.ranked)
    average_text = _time_text(average)
    if completions is not None and completions > 0:
        if stats.bestTime.ranked is None:
            best_text = "暂无时间数据"
        if average is None:
            average_text = "暂无时间数据"
    lines.extend(
        [
            f"Elo：{elo_text}",
            f"全球排名：{rank_text}",
            f"排位场次：{played if played is not None else '暂无数据'}",
            f"完成次数：{completions if completions is not None else '暂无数据'}",
            f"赛季 PB：{best_text}",
            f"赛季胜率：{_rate_text(stats.wins.ranked, played)}",
            f"赛季弃权率：{_rate_text(stats.forfeits.ranked, played)}",
            f"平均完成时间：{average_text}",
        ]
    )
    return "\n".join(lines)


def format_leaderboard(
    payload: dict, country: str | None = None, page: int = 1, page_size: int = 20
) -> str:
    """Paginate the server-filtered board; page is never sent to the Ranked API."""
    board = _parse(RankedLeaderboard, payload)
    if page < 1 or page_size < 1:
        raise RankedDataError("页码和每页条数必须大于 0。")
    region = "中国" if country and country.lower() == "cn" else "全球"
    season = (
        f"第{board.season.number}赛季"
        if board.season.number is not None
        else "当前赛季"
    )
    if not board.users:
        return f"MCSR Ranked {season}{region}榜单暂无玩家数据。"
    pages = ceil(len(board.users) / page_size)
    if page > pages:
        return f"当前{region}榜单共有 {pages} 页，请输入 1–{pages} 页。"
    start = (page - 1) * page_size
    lines = [f"MCSR Ranked {season}{region}榜单（第 {page}/{pages} 页）"]
    for position, user in enumerate(
        board.users[start : start + page_size], start=start + 1
    ):
        standing = user.seasonResult
        elo = standing.eloRate if standing else None
        global_rank = standing.eloRank if standing else None
        rating = f"{elo} Elo" if elo is not None else "定级中"
        ranking = f"全球 #{global_rank}" if global_rank is not None else "暂无全球排名"
        lines.append(f"{position}. {user.nickname} — {rating}（{ranking}）")
    if country:
        lines.append("中国榜单按 Ranked 资料中的 country=cn 筛选。")
    return "\n".join(lines)


def format_recent(
    matches: list, profile: dict, limit: int = 5, timezone: str = "Asia/Shanghai"
) -> str:
    """Format recent real ranked games, including draws and placement matches."""
    user = _parse(RankedUser, profile)
    if not user.uuid:
        raise RankedDataError("玩家资料缺少 UUID，无法识别最近比赛。")
    if not isinstance(matches, list):
        raise RankedDataError("Ranked 比赛数据格式异常，请稍后重试。")
    if not 1 <= limit <= 10:
        raise RankedDataError("最近比赛条数须为 1–10。")
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise RankedDataError("最近比赛的时区设置无效。") from exc
    own_uuid = _uuid_key(user.uuid)
    records = []
    for item in matches:
        match = _parse(RankedMatch, item)
        if match.type != 2 or match.decayed:
            continue
        if not any(_uuid_key(player.uuid) == own_uuid for player in match.players):
            continue
        records.append(match)
        if len(records) >= limit:
            break
    if not records:
        return f"{user.nickname} 暂无近期排位比赛记录。"
    lines = [f"{user.nickname} 最近 {len(records)} 场排位比赛（{timezone}）"]
    for position, match in enumerate(records, start=1):
        opponents = [
            player.nickname
            for player in match.players
            if _uuid_key(player.uuid) != own_uuid
        ]
        opponent = "、".join(opponents) or "未知对手"
        winner_uuid = _uuid_key(match.result.uuid)
        outcome = (
            "平局" if not winner_uuid else ("胜" if winner_uuid == own_uuid else "负")
        )
        note = "，弃权结束" if match.forfeited else ""
        change = next(
            (item for item in match.changes if _uuid_key(item.uuid) == own_uuid), None
        )
        if change is None:
            elo_text = "Elo 变化暂无数据"
        elif change.change is None:
            elo_text = "定级赛，暂无 Elo 变化"
        elif change.eloRate is None:
            elo_text = f"Elo {change.change:+d}"
        else:
            after = change.eloRate + change.change
            elo_text = f"Elo {change.change:+d}（{change.eloRate} → {after}）"
        if match.date is None:
            date_text = "时间未知"
        else:
            try:
                date_text = datetime.fromtimestamp(match.date, tz=zone).strftime(
                    "%m-%d %H:%M"
                )
            except (ValueError, OverflowError, OSError) as exc:
                raise RankedDataError("Ranked 比赛时间格式异常。") from exc
        duration = (
            _time_text(match.result.time)
            if match.result.time is not None
            else "暂无用时数据"
        )
        lines.append(f"{position}. {date_text} | {outcome}{note} | 对手 {opponent}")
        lines.append(f"   比赛用时 {duration} | {elo_text} | #{match.id}")
    return "\n".join(lines)

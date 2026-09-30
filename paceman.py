import asyncio
import base64
import hashlib
import io
import math
import os
import tempfile
import time
from collections.abc import Mapping
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from PIL import Image, ImageDraw, ImageFont, ImageOps
from pydantic import BaseModel, ConfigDict, Field, field_validator

from astrbot.api import logger

from .constant import ASSETS_DIR, CARD_SIZE, DEFAULT_TEMPLATE, get_template_path


class StructureStats(BaseModel):
    model_config = ConfigDict(extra="ignore")
    count: int | None = None
    avg: str | None = None


class UserSessionStats(BaseModel):
    model_config = ConfigDict(extra="ignore")
    nether: StructureStats = Field(default_factory=StructureStats)
    bastion: StructureStats = Field(default_factory=StructureStats)
    fortress: StructureStats = Field(default_factory=StructureStats)
    first_structure: StructureStats = Field(default_factory=StructureStats)
    second_structure: StructureStats = Field(default_factory=StructureStats)
    first_portal: StructureStats = Field(default_factory=StructureStats)
    stronghold: StructureStats = Field(default_factory=StructureStats)
    end: StructureStats = Field(default_factory=StructureStats)
    finish: StructureStats = Field(default_factory=StructureStats)
    truncated: bool = False

    @field_validator(
        "nether",
        "bastion",
        "fortress",
        "first_structure",
        "second_structure",
        "first_portal",
        "stronghold",
        "end",
        "finish",
        mode="before",
    )
    @classmethod
    def empty_segment(cls, value: Any) -> Any:
        return {} if value is None else value

    @field_validator("truncated", mode="before")
    @classmethod
    def empty_truncated(cls, value: Any) -> Any:
        return False if value is None else value


class RunStats(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int | None = None
    nether: int | None = None
    bastion: int | None = None
    fortress: int | None = None
    first_portal: int | None = None
    stronghold: int | None = None
    end: int | None = None
    finish: int | None = None
    lootBastion: int | None = None
    obtainObsidian: int | None = None
    obtainCryingObsidian: int | None = None
    obtainRod: int | None = None
    time: int | None = None
    updatedTime: int | None = None
    realUpdated: int | None = None


SEGMENTS = (
    "nether",
    "bastion",
    "fortress",
    "first_portal",
    "stronghold",
    "end",
    "finish",
)
MAX_IMAGE_BYTES = 8 * 1024 * 1024


@lru_cache(maxsize=4)
def load_template(template_name: str) -> str:
    return get_template_path(template_name).read_text(encoding="utf-8")


@lru_cache(maxsize=16)
def asset_data_uri(filename: str, mime_type: str) -> str:
    return bytes_data_uri((ASSETS_DIR / filename).read_bytes(), mime_type)


def bytes_data_uri(content: bytes, mime_type: str) -> str:
    return f"data:{mime_type};base64,{base64.b64encode(content).decode('ascii')}"


def image_mime_type(content: bytes) -> str | None:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def validate_image(content: bytes, *, card: bool = False) -> bytes:
    if not content or len(content) > MAX_IMAGE_BYTES or not image_mime_type(content):
        raise ValueError("图片格式或大小无效")
    with Image.open(io.BytesIO(content)) as image:
        width, height = image.size
        if not (1 <= width <= 4096 and 1 <= height <= 4096):
            raise ValueError("图片尺寸无效")
        if card and (
            width < CARD_SIZE[0] // 2
            or height < CARD_SIZE[1] // 2
            or abs(width / height - CARD_SIZE[0] / CARD_SIZE[1]) > 0.05
        ):
            raise ValueError("渲染图片未包含完整卡片")
        image.verify()
    with Image.open(io.BytesIO(content)) as image:
        image.load()
    return content


@lru_cache(maxsize=16)
def _asset_image(filename: str) -> Image.Image:
    with Image.open(ASSETS_DIR / filename) as image:
        return image.convert("RGBA")


@lru_cache(maxsize=8)
def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(ASSETS_DIR / "1_Minecraft-Regular.otf"), size)


def _display(value: Any, *, precision: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{precision}f}" if math.isfinite(value) else "—"
    return str(value)


def _format_time(milliseconds: int | None) -> str:
    if milliseconds is None or milliseconds < 0:
        return "—"
    minutes, seconds = divmod(milliseconds // 1000, 60)
    return f"{minutes}:{seconds:02d}"


def _format_date(timestamp: int | None, timezone: str) -> str:
    if timestamp is None:
        return "未知日期"
    try:
        return datetime.fromtimestamp(timestamp, ZoneInfo(timezone)).strftime(
            "%Y-%m-%d"
        )
    except (ValueError, OverflowError, OSError):
        return "未知日期"


def common_template_data(uname: str) -> dict[str, Any]:
    return {
        "uname": uname,
        "font_uri": asset_data_uri("1_Minecraft-Regular.otf", "font/otf"),
        "background_uri": asset_data_uri("background.webp", "image/webp"),
        "skin_uri": "",
        "icons": {key: asset_data_uri(f"{key}.webp", "image/webp") for key in SEGMENTS},
    }


def session_template_data(
    data: UserSessionStats, nph_stats: Mapping | None, hours: int = 24
) -> dict[str, Any]:
    # Keep the user's first/second structure convention in every renderer.
    stages = {
        "nether": data.nether,
        "bastion": data.first_structure,
        "fortress": data.second_structure,
        "first_portal": data.first_portal,
        "stronghold": data.stronghold,
        "end": data.end,
        "finish": data.finish,
    }
    nph = nph_stats if isinstance(nph_stats, Mapping) else {}
    warnings = []
    if data.truncated or nph.get("truncated"):
        warnings.append("记录较多，统计数据可能不完整")
    if not any(
        nph.get(key) is not None for key in ("rnph", "rpe", "resets", "totalResets")
    ):
        warnings.append("NPH 数据暂不可用，— 表示缺失")
    return {
        "hours": hours,
        "title": f"最近{hours}小时统计",
        "stats": {
            key: {"count": _display(stage.count), "avg": _display(stage.avg)}
            for key, stage in stages.items()
        },
        "summary": {
            "rnph": _display(nph.get("rnph")),
            "rpe": _display(nph.get("rpe")),
            "resets": _display(nph.get("resets")),
            "total_resets": _display(nph.get("totalResets")),
        },
        "notice": " · ".join(warnings),
        "truncated": data.truncated or bool(nph.get("truncated")),
        "nph_missing": not nph
        or all(
            nph.get(key) is None for key in ("rnph", "rpe", "resets", "totalResets")
        ),
    }


def run_template_data(run: RunStats, timezone: str) -> dict[str, Any]:
    return {
        "times": {key: _format_time(getattr(run, key)) for key in SEGMENTS},
        "update_time": _format_date(run.updatedTime or run.time, timezone),
    }


def _pil_image(
    uname: str, card_data: dict[str, Any], skin: bytes | None, *, session: bool
) -> bytes:
    background = _asset_image("background.webp").resize(CARD_SIZE)
    background.alpha_composite(Image.new("RGBA", CARD_SIZE, (0, 0, 0, 88)))
    draw = ImageDraw.Draw(background)
    for index, key in enumerate(SEGMENTS):
        y = 62 + index * 72
        icon = _asset_image(f"{key}.webp").resize((52, 52))
        background.alpha_composite(icon, (106, y))
        if session:
            stage = card_data["stats"][key]
            text = f"{stage['count']} {stage['avg']}"
        else:
            text = card_data["times"][key]
        draw.text((184, y + 2), text, fill="white", font=_font(48))

    display_name = uname
    while draw.textlength(display_name, font=_font(36)) > 330 and len(display_name) > 1:
        display_name = display_name[:-2] + "…"
    draw.text((1030, 50), display_name, fill="white", font=_font(36), anchor="mt")
    if session:
        draw.text(
            (1030, 90),
            f"Last {card_data['hours']} hours",
            fill="white",
            font=_font(18),
            anchor="mt",
        )
    if skin:
        with Image.open(io.BytesIO(skin)) as image:
            rendered_skin = ImageOps.contain(image.convert("RGBA"), (280, 440))
            background.alpha_composite(
                rendered_skin, (1030 - rendered_skin.width // 2, 124)
            )

    if session:
        draw.rectangle((62, 586, 1218, 690), fill=(10, 12, 16, 180))
        labels = (
            ("RNPH", "rnph"),
            ("RPE", "rpe"),
            (f"{card_data['hours']}h resets", "resets"),
            ("Tracker total", "total_resets"),
        )
        for index, (label, key) in enumerate(labels):
            x = 88 + index * 287
            draw.text((x, 598), label, fill="white", font=_font(18))
            value = card_data["summary"][key]
            value_size = 36 if len(value) <= 10 else 24
            draw.text((x, 630), value, fill="white", font=_font(value_size))
        notices = []
        if card_data["truncated"]:
            notices.append("PARTIAL DATA")
        if card_data["nph_missing"]:
            notices.append("NPH UNAVAILABLE")
        if notices:
            draw.text(
                (640, 699),
                " / ".join(notices),
                fill="#fff0b0",
                font=_font(14),
                anchor="mt",
            )
    else:
        # The bitmap fallback uses Latin labels when a CJK system font is unavailable.
        date = card_data["update_time"]
        draw.text(
            (640, 658),
            date if date != "未知日期" else "Unknown date",
            fill="white",
            font=_font(26),
            anchor="mt",
        )
    output = io.BytesIO()
    background.convert("RGB").save(output, format="PNG")
    return output.getvalue()


class Paceman:
    def __init__(
        self,
        uname: str,
        data: UserSessionStats,
        nph_stats: Mapping | None = None,
        hours: int = 24,
    ):
        self.uname = uname
        self.data = data
        self.nph_stats = nph_stats
        self.hours = hours

    def generate_image(self, skin: bytes | None = None) -> bytes:
        return _pil_image(
            self.uname,
            session_template_data(self.data, self.nph_stats, self.hours),
            skin,
            session=True,
        )


class Run:
    def __init__(self, run: RunStats, uname: str, timezone: str = "Asia/Shanghai"):
        self.run = run
        self.uname = uname
        self.timezone = timezone

    def generate_image(self, skin: bytes | None = None) -> bytes:
        return _pil_image(
            self.uname, run_template_data(self.run, self.timezone), skin, session=False
        )


def _number(
    config: Mapping, key: str, default: float, minimum: float, maximum: float
) -> float:
    try:
        value = float(config.get(key, default))
        return min(maximum, max(minimum, value)) if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def _temporary_render_error(error: Exception) -> bool:
    if isinstance(
        error,
        (
            httpx.TimeoutException,
            httpx.NetworkError,
            TimeoutError,
            asyncio.TimeoutError,
        ),
    ):
        return True
    message = str(error).lower()
    return any(
        token in message
        for token in (
            "timed out",
            "timeout",
            "connection",
            "http 429",
            "http 502",
            "http 503",
            "http 504",
        )
    )


class RenderService:
    def __init__(self, star: Any, api_client: Any, data_dir: Path, config: Mapping):
        self.star = star
        self.api = api_client
        self.skin_dir = Path(data_dir) / "skins"
        self.timeout = _number(config, "render_timeout", 12, 1, 60)
        self.attempts = int(_number(config, "render_attempts", 2, 1, 2))
        self.skin_timeout = _number(config, "skin_timeout", 3, 0.1, 20)
        self.skin_ttl = _number(config, "skin_cache_ttl", 86400, 0, 2592000)
        self.skin_max_files = int(_number(config, "skin_cache_max_files", 200, 1, 2000))
        self.semaphore = asyncio.Semaphore(
            int(_number(config, "render_concurrency", 2, 1, 8))
        )
        self.image_mode = str(config.get("image_mode", "auto"))
        self.timezone = str(config.get("timezone", "Asia/Shanghai"))
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            self.timezone = "Asia/Shanghai"
        self._skin_tasks: dict[str, asyncio.Task] = {}
        self._image_tasks: set[asyncio.Task] = set()
        self._closed = False

    async def session_image(
        self,
        uname: str,
        data: UserSessionStats,
        nph_stats: Mapping | None = None,
        skin_id: str | None = None,
        *,
        hours: int = 24,
    ) -> bytes | None:
        return await self._image(
            uname,
            session_template_data(data, nph_stats, hours),
            DEFAULT_TEMPLATE,
            skin_id,
        )

    async def run_image(
        self, uname: str, run: RunStats, skin_id: str | None = None
    ) -> bytes | None:
        return await self._image(
            uname, run_template_data(run, self.timezone), "run", skin_id
        )

    async def _image(
        self,
        uname: str,
        card_data: dict[str, Any],
        template_name: str,
        skin_id: str | None,
    ) -> bytes | None:
        if self._closed or self.image_mode == "text":
            return None
        request = asyncio.current_task()
        if request is not None:
            self._image_tasks.add(request)
        acquired = False
        state = {"skin": None}
        started = asyncio.get_running_loop().time()
        try:
            await asyncio.wait_for(self.semaphore.acquire(), timeout=self.timeout)
            acquired = True
            try:
                remaining = max(
                    0.001, self.timeout - (asyncio.get_running_loop().time() - started)
                )
                output = await asyncio.wait_for(
                    self._prepare_image(
                        uname, card_data, template_name, skin_id, state
                    ),
                    timeout=remaining,
                )
                if output is not None:
                    return output
            except (TimeoutError, asyncio.TimeoutError):
                logger.info("图片渲染超过时间预算，使用本地绘图")
            except Exception:
                logger.exception("HTML 图片渲染失败，使用本地绘图")
            try:
                return await asyncio.to_thread(
                    _pil_image,
                    uname,
                    card_data,
                    state["skin"],
                    session=template_name == DEFAULT_TEMPLATE,
                )
            except Exception:
                logger.exception("本地图片渲染失败，使用文字回复")
                return None
        except (TimeoutError, asyncio.TimeoutError):
            logger.info("图片渲染队列繁忙，使用文字回复")
            return None
        finally:
            if acquired:
                self.semaphore.release()
            if request is not None:
                self._image_tasks.discard(request)

    async def _prepare_image(self, uname, card_data, template_name, skin_id, state):
        state["skin"] = await self._skin(skin_id or uname)
        if self.image_mode == "pil":
            return None
        template_data = await asyncio.to_thread(common_template_data, uname)
        template_data.update(card_data)
        if state["skin"]:
            template_data["skin_uri"] = bytes_data_uri(
                state["skin"], image_mime_type(state["skin"])
            )
        return await self._html(template_name, template_data)

    async def _html(self, template_name: str, data: dict[str, Any]) -> bytes | None:
        template = await asyncio.to_thread(load_template, template_name)
        for attempt in range(self.attempts):
            try:
                output = await self.star.html_render(
                    tmpl=template,
                    data=data,
                    return_url=False,
                    options={
                        "full_page": True,
                        "type": "png",
                        "scale": "css",
                        "clip": {
                            "x": 0,
                            "y": 0,
                            "width": CARD_SIZE[0],
                            "height": CARD_SIZE[1],
                        },
                    },
                )
                if not output:
                    return None
                return await asyncio.to_thread(self._read_render_output, Path(output))
            except Exception as error:
                if attempt + 1 >= self.attempts or not _temporary_render_error(error):
                    logger.warning(f"HTML 图片渲染失败: {error}")
                    return None
                await asyncio.sleep(0.3 * (attempt + 1))
        return None

    @staticmethod
    def _read_render_output(path: Path) -> bytes:
        with path.open("rb") as source:
            content = source.read(MAX_IMAGE_BYTES + 1)
        return validate_image(content, card=True)

    async def _skin(self, identity: str) -> bytes | None:
        key = hashlib.sha256(identity.lower().encode("utf-8")).hexdigest()
        task = self._skin_tasks.get(key)
        if task is None:
            task = asyncio.create_task(self._load_skin(key, identity))
            self._skin_tasks[key] = task
            task.add_done_callback(
                lambda finished: self._finish_skin_task(key, finished)
            )
        return await asyncio.shield(task)

    def _finish_skin_task(self, key: str, task: asyncio.Task) -> None:
        if self._skin_tasks.get(key) is task:
            self._skin_tasks.pop(key, None)

    async def _load_skin(self, key: str, identity: str) -> bytes | None:
        path = self.skin_dir / f"{key}.png"
        cached, fresh = await asyncio.to_thread(self._cached_skin, path)
        if fresh:
            return cached
        try:
            content = await asyncio.wait_for(
                self.api.get_bytes(
                    f"https://render.crafty.gg/3d/full/{quote(identity, safe='')}",
                    timeout=self.skin_timeout,
                ),
                timeout=self.skin_timeout,
            )
            await asyncio.to_thread(validate_image, content)
            await asyncio.to_thread(self._save_skin, path, content)
            return content
        except Exception as error:
            logger.info(f"皮肤暂不可用，使用缓存或无皮肤卡片: {error}")
            return cached

    def _cached_skin(self, path: Path) -> tuple[bytes | None, bool]:
        try:
            modified = path.stat().st_mtime
            with path.open("rb") as source:
                content = validate_image(source.read(MAX_IMAGE_BYTES + 1))
            return content, time.time() - modified < self.skin_ttl
        except (OSError, ValueError, SyntaxError):
            return None, False

    def _save_skin(self, path: Path, content: bytes) -> None:
        self.skin_dir.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            dir=self.skin_dir, prefix="skin-", suffix=".tmp"
        )
        try:
            with os.fdopen(descriptor, "wb") as destination:
                destination.write(content)
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        files = []
        for cached in self.skin_dir.glob("*.png"):
            try:
                files.append((cached.stat().st_mtime, cached))
            except FileNotFoundError:
                continue
        for _, cached in sorted(files)[: max(0, len(files) - self.skin_max_files)]:
            cached.unlink(missing_ok=True)

    async def aclose(self) -> None:
        self._closed = True
        current = asyncio.current_task()
        tasks = (self._image_tasks | set(self._skin_tasks.values())) - {current}
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._skin_tasks.clear()

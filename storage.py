"""Player bindings stored in AstrBot's plugin KV namespace."""

import asyncio
import json
from pathlib import Path
from urllib.parse import quote
from uuid import UUID, uuid4

from astrbot.api import logger


def normalize_uuid(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return UUID(str(value)).hex
    except (ValueError, TypeError, AttributeError):
        return None


class BindingStore:
    def __init__(self, star, data_dir: Path, legacy_file: Path):
        self.star = star
        self.data_dir = data_dir
        self.legacy_file = legacy_file
        self._lock = asyncio.Lock()
        self._initialized = False

    @staticmethod
    def _key(event) -> str:
        getter = getattr(event, "get_platform_id", None)
        platform_id = getter() if callable(getter) else event.get_platform_name()
        if not platform_id:
            platform_id = event.get_platform_name()
        return f"binding:v2:{quote(str(platform_id), safe='')}:{quote(str(event.get_sender_id()), safe='')}"

    async def initialize(self):
        async with self._lock:
            if self._initialized:
                return
            if await self.star.get_kv_data("bindings:legacy_migrated", False):
                self._initialized = True
                return
            if self.legacy_file.exists():
                try:
                    content = await asyncio.to_thread(self.legacy_file.read_bytes)
                    await asyncio.to_thread(self._backup, content)
                    records = json.loads(content)
                    if not isinstance(records, dict):
                        raise ValueError("Legacy binding data is not an object")
                except (OSError, ValueError, UnicodeError):
                    logger.exception(
                        "Could not migrate legacy PaceMan bindings; backup retained."
                    )
                    self._initialized = True
                    return
                count = 0
                for user_id, record in records.items():
                    if not isinstance(record, dict):
                        continue
                    username = record.get("username")
                    if not isinstance(username, str) or not username.strip():
                        continue
                    key = f"binding:legacy:{quote(str(user_id), safe='')}"
                    if await self.star.get_kv_data(key, None) is None:
                        await self.star.put_kv_data(
                            key,
                            {
                                "username": username.strip(),
                                "uuid": normalize_uuid(record.get("uuid")),
                                "source": "legacy",
                            },
                        )
                    count += 1
                logger.info(
                    "Migrated %s legacy PaceMan bindings into plugin KV.", count
                )
            await self.star.put_kv_data("bindings:legacy_migrated", True)
            self._initialized = True

    def _backup(self, content: bytes):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        target = self.data_dir / "legacy-bindings-backup.json"
        if target.exists():
            return
        temporary = target.with_suffix(f".{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(content)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)

    async def get(self, event) -> dict | None:
        await self.initialize()
        async with self._lock:
            binding = await self.star.get_kv_data(self._key(event), None)
            if isinstance(binding, dict) and binding.get("username"):
                return binding
            # Historical bindings use QQ account IDs, rather than session/group IDs.
            if event.get_platform_name().lower() not in {
                "aiocqhttp",
                "qq_official",
                "qqofficial",
                "qq",
            }:
                return None
            legacy_key = f"binding:legacy:{quote(str(event.get_sender_id()), safe='')}"
            legacy = await self.star.get_kv_data(legacy_key, None)
            if isinstance(legacy, dict) and legacy.get("username"):
                await self.star.put_kv_data(self._key(event), legacy)
                await self.star.delete_kv_data(legacy_key)
                return legacy
            return None

    async def put(self, event, binding: dict):
        await self.initialize()
        async with self._lock:
            await self.star.put_kv_data(self._key(event), binding)

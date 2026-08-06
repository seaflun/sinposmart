# -*- coding: utf-8 -*-
"""Read-only version check for the SinpoSmart public package."""

from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


VERSION_PATTERN = re.compile(r"^\d{4}\.\d{2}\.\d{2}\.\d{4}$")
DEFAULT_VERSION_URL = (
    "https://github.com/seaflun/sinposmart/releases/latest/download/"
    "sinposmart-version.txt"
)


class UpdateCheckError(RuntimeError):
    """Safe version-check failure suitable for operator display."""


@dataclass(frozen=True)
class VersionInfo:
    current_version: str
    latest_version: str
    update_available: bool


def fetch_text(url: str, timeout_seconds: int) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "SinpoSmart-Updater"})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        payload = response.read()
    return payload.decode("utf-8-sig").strip()


def version_key(version: str) -> tuple[int, int, int, int]:
    if not VERSION_PATTERN.fullmatch(str(version or "").strip()):
        raise UpdateCheckError(f"版本格式錯誤：{version or '-'}")
    return tuple(int(part) for part in version.split("."))


class UpdateRepository:
    def __init__(
        self,
        version_path: Path,
        *,
        remote_version_url: str = DEFAULT_VERSION_URL,
        text_fetcher: Callable[[str, int], str] = fetch_text,
        timeout_seconds: int = 10,
    ) -> None:
        self.version_path = Path(version_path)
        self.remote_version_url = remote_version_url
        self.text_fetcher = text_fetcher
        self.timeout_seconds = max(1, int(timeout_seconds))

    def current_version(self) -> str:
        try:
            version = self.version_path.read_text(encoding="utf-8-sig").strip()
        except OSError as exc:
            raise UpdateCheckError("無法讀取目前版本。") from exc
        version_key(version)
        return version

    def check(self) -> VersionInfo:
        current = self.current_version()
        try:
            latest = self.text_fetcher(self.remote_version_url, self.timeout_seconds).strip()
        except Exception as exc:
            raise UpdateCheckError("無法連線檢查更新，請稍後重試。") from exc
        current_key = version_key(current)
        latest_key = version_key(latest)
        return VersionInfo(current, latest, latest_key > current_key)

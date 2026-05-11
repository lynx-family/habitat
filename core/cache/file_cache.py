import shutil
from pathlib import Path
from typing import Callable, Optional, Union

from core.cache.config import CacheConfig


class FileCache:
    def __init__(
        self,
        config: CacheConfig,
        *,
        cache_path_handler: Callable[[str], Path],
    ) -> None:
        self.config = config

        self.cache_path_handler = cache_path_handler

    def path(self, key: str) -> Path:
        return self.config.base / self.cache_path_handler(key)

    def write(self, key: str, value: Path) -> None:
        if not self.config.on or self.config.read_only:
            return

        cache_path = self.path(key)
        if cache_path.exists():
            return

        # Copy the file to cache path
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        shutil.copy2(value, cache_path)

    def write_content(self, key: str, value: Union[bytes, str]) -> None:
        if not self.config.on or self.config.read_only:
            return

        cache_path = self.path(key)
        if not cache_path.exists():
            cache_path.parent.mkdir(parents=True, exist_ok=True)

        mode = "w"
        if isinstance(value, bytes):
            mode = "wb"
        with open(cache_path, mode) as f:
            f.write(value)

    def lookup(self, key: str) -> Optional[Path]:
        if not self.config.on:
            return None

        return self.path(key) if self.path(key).exists() else None

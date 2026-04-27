from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Union

from core.settings import GLOBAL_CACHE_DIR


# Write file stamp to global cache only for convenience. Make sure to add --force when executing sync command in CI
# so that no content will be written into global cache.
@dataclass
class FileStamp:
    type: str
    name: Union[str, Path]
    target_dir: Union[str, Path]

    global_cache_dir: ClassVar[Path] = Path(GLOBAL_CACHE_DIR)
    fast_digest: str = None
    full_digest: str = None
    extra: dict = None
    version: ClassVar[int] = 1

    @property
    def stamp_path(self) -> Path:
        buf = bytearray()
        buf.extend((self.type + str(self.name) + str(self.target_dir)).encode("utf-8"))
        buf.extend(json.dumps(self.extra, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        hasher = hashlib.sha256()
        hasher.update(buf)
        return self.global_cache_dir / f"stamps-v{self.version}" / f"{hasher.hexdigest()}.stamp"

    def exists(self) -> bool:
        return self.stamp_path.exists()

    def write(self, fast_digest: str, full_digest: str):
        self.stamp_path.parent.mkdir(parents=True, exist_ok=True)
        obj = {
            "version": self.version,
            "type": self.type,
            "name": str(self.name),
            "target_dir": str(self.target_dir),
            "fast_digest": fast_digest,
            "full_digest": full_digest,
            "extra": self.extra,
        }
        with open(self.stamp_path, "w") as f:
            f.write(json.dumps(obj, indent=2))

    def read(self) -> dict:
        if not self.stamp_path.exists():
            return {}

        with open(self.stamp_path) as f:
            content = f.read()

        return json.loads(content)

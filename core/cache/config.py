from dataclasses import dataclass
from pathlib import Path


@dataclass
class CacheConfig:
    base: Path
    on: bool = True
    read_only: bool = False

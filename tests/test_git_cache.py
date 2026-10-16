import asyncio
import subprocess
from unittest.mock import AsyncMock, MagicMock

from core.cache.git_cache import GitCacheInfo, GitCacheTarget
from core.fetchers.git_fetcher import GitFetcher


def git_error():
    return subprocess.CalledProcessError(1, "git fetch", output=b"fetch failed")


def test_git_fetcher_falls_back_when_cache_update_fails():
    source_target = GitCacheTarget("https://example.com/repo.git", "main")
    cache = MagicMock()
    cache.read = AsyncMock(return_value=GitCacheInfo(hit=False, target=source_target))
    cache.write = AsyncMock(side_effect=git_error())

    fetcher = GitFetcher(MagicMock())
    fetcher.cache = cache

    info = asyncio.run(fetcher.try_fetch_in_cache(source_target.url, source_target.refspec))

    assert info == GitCacheInfo(hit=False, target=source_target)

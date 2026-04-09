import logging
import subprocess
from pathlib import Path
from typing import Callable, NamedTuple, Optional

from core.cache.config import CacheConfig
from core.utils import is_bare_git_repo, rmtree, run_git_command

CACHE_RETRY_TIMES = 2


class GitCacheTarget(NamedTuple):
    url: str
    refspec: str


class GitCacheInfo(NamedTuple):
    hit: Optional[bool]
    target: Optional[GitCacheTarget]


class GitCache:
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

    @staticmethod
    def cached_refspec(refspec: str) -> str:
        # if a git dependency is fetched by branch or tag
        if ":" in refspec:
            # in this case, the local cache repo was used as a remote.
            # the (<remote ref>:<local repo ref>) refspec format should be adapted with the cache process.
            # 1. the "<remote ref>" should be like "refs/remotes/origin/main" since the local cache repo will
            #  be used as "remote",
            # 2. the "<local repo ref>" should be like "refs/remotes/origin/main" as well. because the checkout
            #  args for branch is set to "-B <branch> refs/remotes/origin/main".
            _, cached_ref = refspec.split(":", 1)
            return f"{cached_ref}:{cached_ref.lstrip('+')}"
        return refspec

    async def write(self, key: str, refspec: str) -> GitCacheTarget:
        if not self.config.on or self.config.read_only:
            return GitCacheTarget(key, refspec)

        url = key
        repo_cache_dir = self.path(url)
        had_cache_repo = is_bare_git_repo(repo_cache_dir)

        if not had_cache_repo:
            repo_cache_dir.mkdir(parents=True, exist_ok=True)
            cmd = f"git init --bare {repo_cache_dir}"
            await run_git_command(
                cmd, shell=True, cwd=repo_cache_dir, stderr=subprocess.STDOUT
            )
            cmd = f"git config remote.origin.url {url}"
            await run_git_command(
                cmd, shell=True, cwd=repo_cache_dir, stderr=subprocess.STDOUT
            )
            logging.debug(f"create a bare repo in {repo_cache_dir}")

        logging.debug(f"update repo {url} and its refspec {refspec} cache in {repo_cache_dir}")
        fetch_args = ["--force", "--progress", "--update-head-ok", "--no-recurse-submodules"]
        cmd = f"git fetch {' '.join(fetch_args)} -- {url} {refspec}"

        remained_chances = CACHE_RETRY_TIMES
        while True:
            remained_chances -= 1
            try:
                await run_git_command(
                    cmd, shell=True, cwd=repo_cache_dir, stderr=subprocess.STDOUT
                )
            except subprocess.CalledProcessError:
                if remained_chances > 0:
                    logging.warning(f"not a valid cache, removing {repo_cache_dir}")
                    # TODO: windows permission
                    rmtree(repo_cache_dir, ignore_errors=True)
                else:
                    raise
            else:
                break

        return GitCacheTarget(repo_cache_dir, self.cached_refspec(refspec))

    async def read(self, key: GitCacheTarget) -> GitCacheInfo:
        # cache disabled, return directly with the original url and refspec.
        if not self.config.on:
            return GitCacheInfo(hit=False, target=key)

        repo_cache_dir = self.path(key.url)
        had_cache_repo = is_bare_git_repo(repo_cache_dir)

        # cache repo not initialized, return directly with the original url and refspec.
        if not had_cache_repo:
            logging.debug(f"cache repo {repo_cache_dir} does not exist")
            return GitCacheInfo(
                hit=False,
                target=key,
            )

        cmd = f"git cat-file -t {key.refspec.rsplit()[-1]}"
        try:
            await run_git_command(
                cmd,
                shell=True,
                cwd=repo_cache_dir,
                stderr=subprocess.STDOUT,
                suppress_error_log=True,
            )
        except subprocess.CalledProcessError:
            # cache repo initialized, but the content is not yet updated.
            logging.debug(f"cache repo {repo_cache_dir}({key.url}) has no cache of refspec {key.refspec}")
            return GitCacheInfo(hit=False, target=key)

        # cache hit with the url and refspec, use repo_cache_dir as url and use the cached refspec.
        logging.debug(f"cache hit with {key.url} and its refspec {key.refspec}")
        return GitCacheInfo(
            hit=True,
            target=GitCacheTarget(
                url=repo_cache_dir,
                refspec=self.cached_refspec(key.refspec),
            ),
        )

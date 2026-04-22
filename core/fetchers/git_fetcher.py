# Copyright 2024 The Lynx Authors. All rights reserved.
# Licensed under the Apache License Version 2.0 that can be found in the
# LICENSE file in the root directory of this source tree.

import hashlib
import logging
import os
import re
import shlex
import subprocess
import sys
import time
from glob import glob
from pathlib import Path

from core.cache.config import CacheConfig
from core.cache.git_cache import GitCache, GitCacheInfo, GitCacheTarget
from core.exceptions import GitException, HabitatException
from core.fetchers.fetcher import Fetcher
from core.observe import observer
from core.settings import DEBUG, DEFAULT_GIT_EMAIL, DEFAULT_GIT_USER
from core.trace import get_global_tracer
from core.utils import (convert_git_url_to_http, create_temp_dir, get_full_commit_id, is_git_repo_valid, is_git_root,
                        is_subdir, move, rmtree, run_git_command)


def cache_path(url: str) -> Path:
    repo_name = re.split(r"/|:", url)[-1]
    return Path(repo_name) / hashlib.md5(url.encode()).hexdigest()


# Check if the git index is clean for "git am". If not, try to call "git am --abort" to reset.
async def abort_unfinished_git_am(cwd: str):
    # Get the rebase-apply path of the current git repository.
    check_command = "git rev-parse --git-path rebase-apply"
    try:
        output = await run_git_command(shlex.split(check_command), cwd=cwd)
        rebase_apply = output.strip()
    except subprocess.CalledProcessError as e:
        raise GitException(
            "failed to get the path of rebase-apply",
            cause=e,
            hint=f"check if path {cwd} is a valid git repository",
            context={
                "command": check_command,
                "working-directory": cwd
            }
        )

    # Abort git am to guarantee idempotency.
    if (Path(cwd) / Path(rebase_apply)).exists():
        abort_command = "git am --abort"
        try:
            await run_git_command(shlex.split(abort_command), cwd=cwd, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            raise GitException(
                "failed to clean git index by aborting git am",
                cause=e,
                hint=f"check if there are other unfinished git operations in {cwd}",
                context={
                    "command": abort_command,
                    "working-directory": cwd,
                    "stdout": e.output.decode().strip()
                }
            )


async def apply_patches(patch_path: str, cwd: str):
    expanded_patch_paths = list(glob(patch_path))
    expanded_patch_paths.sort()

    if not expanded_patch_paths:
        raise HabitatException(
            "failed to match valid patch paths.",
            hint=f"check if patches {patch_path} exist"
        )

    user_args = ["-c", f"user.name={DEFAULT_GIT_USER}", "-c", f"user.email={DEFAULT_GIT_EMAIL}"]
    command = ["git", *user_args, "am", *expanded_patch_paths]
    await abort_unfinished_git_am(cwd)
    try:
        await run_git_command(command, cwd=cwd, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        raise GitException(
            "Failed to apply patches.",
            cause=e,
            hint=f"Check if patches have conflict with code. Or remove {cwd} then retry.",
            context={
                "command": shlex.join(command),
                "working-directory": cwd,
                "stderr": e.stderr.decode()
            }
        )


class GitFetcher(Fetcher):
    # TODO: find a better name
    async def try_fetch_in_cache(self, url: str, refspec: str) -> GitCacheInfo:
        default_target = GitCacheTarget(url, refspec)

        info = await self.cache.read(default_target)
        if info.hit:
            return info

        target = await self.cache.write(url, refspec)
        return GitCacheInfo(hit=info.hit, target=target)

    async def fetch(self, root_dir, options, *args, **kwargs):
        tracer = get_global_tracer()
        async_id = None
        if tracer:
            async_id = tracer.async_begin(
                f"git_fetch_{self.component.name}",
                category="git_fetcher",
                args={
                    "source": self.component.url,
                    "target_dir": self.component.target_dir,
                    "revision": getattr(
                        self.component,
                        "commit",
                        getattr(
                            self.component,
                            "branch",
                            getattr(self.component, "tag", "HEAD"),
                        ),
                    ),
                },
            )

        url = self.component.url
        target_dir = self.component.target_dir

        self.cache = GitCache(
            CacheConfig(
                base=Path(options.cache_dir) / "git",
                on=not options.disable_cache,
                read_only=options.read_only_cache
            ),
            cache_path_handler=cache_path
        )

        if options.git_auth:
            url = convert_git_url_to_http(url, options.git_auth)

        logging.info(
            f"Fetch git repository {url if DEBUG else self.component.url} to {target_dir}"
        )

        try:
            new_init = False
            if not options.clean and (not options.raw or self.component.is_root):
                source_dir = target_dir
            else:
                source_dir = create_temp_dir(
                    root_dir=root_dir,
                    name=f'GIT-FETCHER-{self.component.name.replace("/", "_")}',
                )

            source_dir = os.path.abspath(source_dir)

            if not is_git_root(source_dir):
                cmd = f"git init {source_dir}"
                await run_git_command(cmd, shell=True, stderr=subprocess.STDOUT)
                new_init = True
            elif not is_git_repo_valid(source_dir):
                # Check if alternates is set to the right path, since the global cache might be cleaned.
                # If the alternates are not available, the git repository need to be re-created to avoid losing objects.
                rmtree(source_dir)
                cmd = f"git init {source_dir}"
                await run_git_command(cmd, shell=True, stderr=subprocess.STDOUT)
                new_init = True

            remote = await run_git_command(
                "git remote", shell=True, cwd=source_dir, stderr=subprocess.STDOUT
            )
            remote = remote.strip()
            if not remote:
                cmd = "git config remote.origin.url " + url
                await run_git_command(
                    cmd, shell=True, cwd=source_dir, stderr=subprocess.STDOUT
                )
                remote = "origin"

            # if a repository was fetched before git lfs install,
            # files tracked by lfs will be replaced by file pointer
            if getattr(self.component, "enable_lfs", None):
                try:
                    await run_git_command(
                        "git lfs install",
                        shell=True,
                        cwd=source_dir,
                        stderr=subprocess.STDOUT,
                        suppress_error_log=True,
                    )
                except subprocess.CalledProcessError as e:
                    logging.warning(
                        f"{e.output.decode()} This may caused by: "
                        f"1. git lfs not installed. 2. a git lfs install command is already running."
                    )

            if options.force and not new_init:
                if options.raw:
                    # check and clean existing paths if user intends to
                    if hasattr(self.component, "paths"):
                        paths_to_fetch = self.component.paths
                    else:
                        paths_to_fetch = [target_dir]

                    for p in paths_to_fetch:
                        if os.path.exists(p) and (options.clean or options.force):
                            logging.warning(
                                f"remove existing target directory {target_dir}"
                            )
                            rmtree(p)
                        else:
                            raise HabitatException(
                                f'directory {target_dir} exist, try use "-f/--force" flag or remove it manually'
                            )
                else:
                    cmd = "git clean -fd && git reset --hard"
                    await run_git_command(
                        cmd, shell=True, cwd=source_dir, stderr=subprocess.STDOUT
                    )

            logging.debug(
                f"Fetch git repository {url if DEBUG else self.component.url} in {source_dir}"
            )
            # fix reserved name in file path causing the checkout command complain "error: invalid path..." on windows
            if sys.platform == "win32":
                cmd = "git config core.protectNTFS false"
                await run_git_command(
                    cmd, shell=True, cwd=source_dir, stderr=subprocess.STDOUT
                )

            # Enable sparse checkouts
            if hasattr(self.component, "paths"):
                cmd = f'git sparse-checkout set {" ".join(self.component.paths)}'
            else:
                # Repopulate the working directory with all files, disabling sparse checkouts.
                cmd = "git sparse-checkout disable"
            try:
                await run_git_command(
                    cmd, shell=True, cwd=source_dir, stderr=subprocess.STDOUT
                )
            except subprocess.CalledProcessError:
                # Since sparse checkout is not supported by old version of git, just give a warning here.
                logging.warning(f"sparse checkout is not supported, skip cmd {cmd}")

            if hasattr(self.component, "commit"):
                commit = self.component.commit
                ref_spec = (
                    commit if len(commit) == 40 else get_full_commit_id(commit, url)
                )
                checkout_args = "FETCH_HEAD"
            elif hasattr(self.component, "branch"):
                # the refspec below is for fetching ref from remote to `source_dir`,
                # it should be like "+refs/heads/main:refs/remotes/origin/main" (<remote ref>:<local repo ref>)
                ref_spec = f"+refs/heads/{self.component.branch}:refs/remotes/{remote}/{self.component.branch}"
                # checkout refs in `source_dir`, it should be like "refs/remotes/origin/main"
                checkout_args = f"-B {self.component.branch} refs/remotes/{remote}/{self.component.branch}"
            elif hasattr(self.component, "tag"):
                ref_spec = (
                    f"+refs/tags/{self.component.tag}:refs/tag/{self.component.tag}"
                )
                checkout_args = self.component.tag
            elif new_init:
                remote = "origin"
                cmd = f"git remote show {remote}"
                output = await run_git_command(
                    cmd,
                    shell=True,
                    cwd=source_dir,
                    stderr=subprocess.STDOUT,
                    env={"LANG": "en_US.UTF-8"},
                )
                res = re.search(r"HEAD branch: (\S+)", output)
                if not res:
                    raise HabitatException(
                        f"HEAD branch of remote repository {remote} not found"
                    )
                branch_name = res[1]
                ref_spec = (
                    f"+refs/heads/{branch_name}:refs/remotes/{remote}/{branch_name}"
                )
                checkout_args = f"-B {branch_name} refs/remotes/{remote}/{branch_name}"
            else:
                cmd = "git status -uno"
                output = await run_git_command(
                    cmd, shell=True, cwd=target_dir, stderr=subprocess.STDOUT
                )
                if output.startswith("HEAD detached at"):
                    # HEAD is detached, do nothing
                    return [target_dir]
                elif output.startswith("On branch"):
                    branch_name = output.split()[2]
                else:
                    raise HabitatException(output)
                ref_spec = (
                    f"+refs/heads/{branch_name}:refs/remotes/{remote}/{branch_name}"
                )
                checkout_args = f"-B {branch_name} refs/remotes/{remote}/{branch_name}"

            fetch_all = self.component.fetch_mode == "all"
            if self.component.is_root or fetch_all:
                ref_spec = "'+refs/heads/*:refs/remotes/origin/*'"
                depth_arg = ""
            else:
                depth_arg = "--depth=1 --no-tags" if options.no_history else ""

            checkout_ref_spec = ref_spec
            cache_info = GitCacheInfo(hit=None, target=GitCacheTarget(url, checkout_ref_spec))

            t0_ns = time.perf_counter_ns()
            cache_info = await self.try_fetch_in_cache(url, checkout_ref_spec)
            url = cache_info.target.url
            checkout_ref_spec = cache_info.target.refspec

            if self.cache.config.on:
                observer.record_cache_access("git", hit=bool(cache_info.hit))

            fetch_args = ["--force", "--progress", "--update-head-ok", "--no-recurse-submodules"]
            cmd = f"git fetch {depth_arg} {' '.join(fetch_args)} -- {url} {checkout_ref_spec}"
            await run_git_command(
                cmd, shell=True, cwd=source_dir, retry=1, stderr=subprocess.STDOUT
            )
            duration_ms = int((time.perf_counter_ns() - t0_ns) / 1_000_000)
            if not bool(cache_info.hit):
                observer.record_download_task(
                    duration_ms,
                    {
                        "durationMs": duration_ms,
                        "kind": "git",
                        "url": self.component.url,
                        "objectKey": checkout_ref_spec
                    }
                )

            if options.raw and not os.path.exists(target_dir):
                os.mkdir(target_dir)
            if options.raw:
                if not os.path.exists(target_dir):
                    os.mkdir(target_dir)
                cmd = f"git --work-tree={target_dir} checkout FETCH_HEAD -- ."
            else:
                cmd = f"git checkout {checkout_args}"

            # If specify enable_lfs to false explicitly, set an extra env when running checkout command
            checkout_env = os.environ.copy()
            if getattr(self.component, "enable_lfs", None) is False:
                checkout_env["GIT_LFS_SKIP_SMUDGE"] = "1"

            try:
                await run_git_command(
                    cmd, shell=True, cwd=source_dir, stderr=subprocess.STDOUT, env=checkout_env
                )
            except subprocess.CalledProcessError:
                logging.warning(
                    f"A checkout for {target_dir} has failed. This might caused by that "
                    f"the target directory for {url} is occupied by another git repository. A clean"
                    " fetch is on the run."
                )
                if not is_subdir(root_dir, source_dir):
                    rmtree(source_dir)
                    await self.fetch(root_dir, options, *args, **kwargs)
                else:
                    raise HabitatException(
                        f"{root_dir} is a sub directory of {source_dir}. Please check the conflict manually."
                    )

            if getattr(self.component, "enable_lfs", None):
                try:
                    await run_git_command(
                        "git lfs pull",
                        shell=True,
                        cwd=source_dir,
                        stderr=subprocess.STDOUT,
                    )
                except subprocess.CalledProcessError as e:
                    raise HabitatException(
                        f"{e} This may caused by not installing git lfs"
                    )

            patch_path = getattr(self.component, "patches", None)
            if not patch_path:
                pass
            elif isinstance(patch_path, str):
                await apply_patches(patch_path, source_dir)
            elif isinstance(patch_path, list):
                for p in patch_path:
                    await apply_patches(p, source_dir)

            target_dir = os.path.abspath(target_dir)
            if target_dir != source_dir and not options.raw:
                move(source_dir, target_dir)
            elif target_dir != source_dir:
                rmtree(source_dir, ignore_errors=True)

        except Exception as e:
            if tracer and async_id:
                tracer.async_instant(
                    async_id,
                    f"git_fetch_{self.component.name}_error",
                    category="git_fetcher",
                    args={"error": str(e)},
                )
            raise
        finally:
            if tracer and async_id:
                tracer.async_end(async_id)

        return [target_dir]

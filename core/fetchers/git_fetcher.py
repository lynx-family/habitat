# Copyright 2024 The Lynx Authors. All rights reserved.
# Licensed under the Apache License Version 2.0 that can be found in the
# LICENSE file in the root directory of this source tree.

import hashlib
import logging
import os
import re
import subprocess
import sys
from glob import glob

from core.exceptions import HabitatException
from core.fetchers.fetcher import Fetcher
from core.settings import DEBUG
from core.trace import get_global_tracer
from core.utils import (async_check_output, convert_git_url_to_http, create_temp_dir, get_full_commit_id,
                        is_bare_git_repo, is_git_repo_valid, is_git_root, is_git_user_set, move, rmtree)


async def fetch_in_cache_if_needed(url, ref_spec, global_cache_dir, fetch_all=False):
    repo_name = re.split(r"/|:", url)[-1]
    repo_cache_dir = os.path.join(
        global_cache_dir, repo_name, hashlib.md5(url.encode()).hexdigest()
    )
    if not os.path.exists(repo_cache_dir):
        os.makedirs(repo_cache_dir)

    need_fetch = False
    if not is_bare_git_repo(repo_cache_dir):
        cmd = f"git init --bare {repo_cache_dir}"
        await run_git_command(
            cmd, shell=True, cwd=global_cache_dir, stderr=subprocess.STDOUT
        )
        cmd = "git config remote.origin.url " + url
        await run_git_command(
            cmd, shell=True, cwd=repo_cache_dir, stderr=subprocess.STDOUT
        )
        need_fetch = True
    elif fetch_all:
        need_fetch = True
    else:
        cmd = f"git cat-file -t {ref_spec.rsplit()[-1]}"
        try:
            await run_git_command(
                cmd,
                shell=True,
                cwd=repo_cache_dir,
                stderr=subprocess.STDOUT,
                suppress_error_log=True,
            )
        except subprocess.CalledProcessError:
            need_fetch = True

    if need_fetch:
        logging.debug(f"update git cache in {repo_cache_dir}")
        cmd = f"git fetch --force --progress --update-head-ok -- {url} {ref_spec}"
        try:
            await run_git_command(
                cmd, shell=True, cwd=repo_cache_dir, stderr=subprocess.STDOUT
            )
        except subprocess.CalledProcessError:
            logging.warning(f"not a valid cache, removing {repo_cache_dir}")
            # TODO: windows permission
            rmtree(repo_cache_dir, ignore_errors=True)
            await run_git_command(
                cmd, shell=True, cwd=repo_cache_dir, stderr=subprocess.STDOUT
            )
    return repo_cache_dir


async def run_git_command(cmd: str, *args, **kwargs):
    suppress_error_log = kwargs.get("suppress_error_log", False)
    if suppress_error_log:
        kwargs.pop("suppress_error_log")
    try:
        output = await async_check_output(cmd, *args, **kwargs)
    except subprocess.CalledProcessError as e:
        if not suppress_error_log:
            logging.error(
                f"running command {cmd} in {kwargs.get('cwd') if kwargs.get('cwd') else os.getcwd()}, "
                f"original output:{os.linesep}{e.output.decode()}"
            )
        raise e
    return output.decode()


async def apply_patches(patch_path: str, cwd: str):
    expanded_patch_paths = list(glob(patch_path))
    expanded_patch_paths.sort()

    if not expanded_patch_paths:
        raise HabitatException("failed to match valid patch paths.")

    apply = "apply"
    if await is_git_user_set():
        apply = "am"
    try:
        await async_check_output(
            ["git", apply] + expanded_patch_paths, cwd=cwd, stderr=subprocess.STDOUT
        )
    except subprocess.CalledProcessError as e:
        raise HabitatException(
            f"{e.output.decode()}. This might caused by conflicts between patches and code."
        )


class GitFetcher(Fetcher):

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
                ref_spec = f"+refs/heads/{self.component.branch}:refs/remotes/{remote}/{self.component.branch}"
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

            if not options.disable_cache:
                global_cache_dir = os.path.expanduser(
                    os.path.join(options.cache_dir, "git")
                )
                global_cache_dir = os.path.realpath(
                    os.path.expandvars(global_cache_dir)
                )
                repo_cache_dir = await fetch_in_cache_if_needed(
                    url, ref_spec, global_cache_dir, fetch_all=fetch_all
                )
                url = repo_cache_dir

            cmd = f"git fetch {depth_arg} --force --progress --update-head-ok -- {url} {ref_spec}"
            await run_git_command(
                cmd, shell=True, cwd=source_dir, retry=1, stderr=subprocess.STDOUT
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
            checkout_env = None
            if getattr(self.component, "enable_lfs", None) is False:
                checkout_env = {"GIT_LFS_SKIP_SMUDGE": "1"}

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
                rmtree(source_dir)
                await self.fetch(root_dir, options, *args, **kwargs)

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

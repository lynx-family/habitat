# Copyright 2024 The Lynx Authors. All rights reserved.
# Licensed under the Apache License Version 2.0 that can be found in the
# LICENSE file in the root directory of this source tree.

import hashlib
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from core import __version__, components
from core.common.error_code import ERROR_INCOMPATIBLE_VERSION
from core.components.dependency_group import DependencyGroup
from core.exceptions import HabitatException
from core.fetchers.git_fetcher import GitFetcher
from core.settings import DEFAULT_CONFIG_FILE_NAME, DEFAULT_DEPS_CACHE_FILE_NAME, ENTRIES_CACHE_TAG_PREFIX
from core.trace import get_global_tracer
from core.utils import check_call, eval_deps, find_classes, get_head_commit_id, is_git_sha


def store_entries_cache_to_git(entries_cache: dict, root_dir=None):
    root_dir = root_dir or os.getcwd()
    head_commit_id = get_head_commit_id(cwd=root_dir)
    temp_file = os.path.join(
        root_dir, f"{DEFAULT_DEPS_CACHE_FILE_NAME}_{head_commit_id}"
    )
    with open(temp_file, "w") as f:
        logging.debug(f"writing deps cache: {entries_cache}")
        json.dump(entries_cache, f)

    sha = (
        subprocess.check_output(["git", "hash-object", "-w", temp_file], cwd=root_dir)
        .decode()
        .strip()
    )
    check_call(
        ["git", "tag", "-f", f"{ENTRIES_CACHE_TAG_PREFIX}_{head_commit_id}", sha],
        cwd=root_dir,
    )
    os.remove(temp_file)


def load_entries_cache_from_git(root_dir=None):
    try:
        deps_cache = (
            subprocess.check_output(
                [
                    "git",
                    "cat-file",
                    "-p",
                    f"{ENTRIES_CACHE_TAG_PREFIX}_{get_head_commit_id(cwd=root_dir)}",
                ],
                cwd=root_dir or os.getcwd(),
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
        deps_cache = json.loads(deps_cache)
        return deps_cache
    except subprocess.CalledProcessError:
        return None


def load_solutions(
    root_dir, solution_file, ignore_non_existing=False, enable_version_checking=True
):
    env = {}
    if hasattr(solution_file, "read"):
        exec(solution_file.read(), env)
    else:
        if not os.path.exists(solution_file):
            if ignore_non_existing:
                return []
            raise HabitatException(
                f"File {DEFAULT_CONFIG_FILE_NAME} not found in directory {root_dir}"
            )
        with open(solution_file, "r") as f:
            exec(f.read(), env)

    if "habitat_version" in env and env["habitat_version"] != __version__.__version__:
        logging.warning(
            f"current version({__version__.__version__}) is not compatible with the configuration"
            f'({env["habitat_version"]}) in {solution_file}'
        )
        sys.stderr.write(f'expected version: {env["habitat_version"]}\n')
        if enable_version_checking:
            sys.exit(ERROR_INCOMPATIBLE_VERSION)
        logging.warning("habitat compatible check is disabled")

    if "solutions" not in env:
        logging.error(f"Can not find any solutions in file {solution_file}")
        return []

    solutions = []
    for solution_config in env["solutions"]:
        solution = Solution(
            Path(root_dir) / Path(solution_config["name"]), solution_config
        )
        solutions.append(solution)

    return solutions


def load_mapping_file(mapping_file_path):
    env = {}
    if not os.path.exists(mapping_file_path):
        return None
    with open(mapping_file_path, "r") as f:
        exec(f.read(), env)

    return env.get("mappings")


def apply_mapping(dep, mappings: dict):
    for attr, mp in mappings.get(dep.type, {}).items():
        original_attr = getattr(dep, attr)
        if original_attr in mp:
            dep.set_attr(attr, mp[original_attr], override=True)
            dep.set_attr(f"original_{attr}", original_attr)
            logging.info(
                f"replace ({dep.name})'s [{attr}] {original_attr} with {mp[original_attr]}"
            )


def merge_dict(base, new):
    merged_dict = {}
    for key in set(base.keys()) | set(new.keys()):
        if key == "condition":
            merged_dict[key] = base.get(key) or new.get(key)
        else:
            merged_dict[key] = base.get(key) if key not in new else new[key]
    return merged_dict


def merge_deps(base, new):
    if not base:
        return new
    if not new:
        return base

    merged_deps = {}
    for key in set(base.keys()) | set(new.keys()):
        if base.get(key) and new.get(key):
            merged_deps[key] = merge_dict(base[key], new[key])
        else:
            merged_deps[key] = base.get(key) if key not in new else new[key]
    return merged_deps


class Solution(DependencyGroup):
    type = "solution"
    defined_fields = {
        "name": {"type": str},
        "url": {
            "type": str,
            "validator": lambda val, component: val.startswith(
                ("git", "http", "https", "file")
            ),
        },
        "branch": {"type": str, "optional": True},
        "commit": {"type": str, "optional": True},
        "deps_file": {"default": "DEPS"},
        "targets": {"type": list, "optional": True},
        "target_deps_files": {"type": dict, "optional": True},
        "mapping_file": {
            "type": str,
            "optional": True,
        },
    }
    source_attributes = ["url"]
    source_stamp_attributes = ["branch", "commit"]

    def __init__(self, *args, **kwargs):
        super(Solution, self).__init__(*args, **kwargs)
        self.fetcher = GitFetcher(self)

    async def fetch_deps_only(
        self, root_dir, options, existing_sources=None, existing_targets=None
    ):
        # Since we skip fetch method, the on_fetched method should be called explicitly
        self.on_fetched(root_dir, options)

        await self.fetch_children(root_dir, options, existing_sources, existing_targets)
        self.on_children_fetched(root_dir, options)

    def on_fetched(self, root_dir, options):
        super(Solution, self).on_fetched(root_dir, options)
        if options.all:
            targets = getattr(self, "targets", [])
        else:
            targets = options.target.split(",") if options.target else [None]
        self.load_deps(root_dir, targets, options.target_only)

    def instantiate_deps(self, root_dir: str, deps: dict, mappings: dict = None):
        """parse the config dict and instantiate it into a corresponding component."""
        mapping_file_rel_path = getattr(self, "mapping_file", None)
        mapping_file_abs_path = (
            os.path.join(root_dir, mapping_file_rel_path)
            if mapping_file_rel_path
            else None
        )
        _mappings = {}
        # prioritize using mappings defined in .habitat file.
        if mappings:
            _mappings = mappings
        elif mapping_file_rel_path is None:
            pass
        elif not os.path.exists(mapping_file_abs_path):
            raise HabitatException(f"expect mapping file in {mapping_file_abs_path}")
        else:
            _mappings = load_mapping_file(mapping_file_abs_path)

        dependency_classes = find_classes(
            components, lambda c: getattr(c, "is_component", False)
        )
        for name, config in deps.items():
            if "type" not in config:
                raise HabitatException(
                    f"dependency must has a type, got config {config}"
                )
            dep_type = config.get("type")
            try:
                dep = next(c for c in dependency_classes if c.type == dep_type)(
                    Path(self.target_dir) / Path(name), {"name": name, **config}, self
                )

                if _mappings:
                    apply_mapping(dep, _mappings)

            except StopIteration:
                raise HabitatException(
                    f"invalid dependency type {dep_type} in config {config}"
                )
            else:
                dep.set_attr(
                    "local_source_stamps", self.local_source_stamps, override=True
                )
                self.add_child(dep)

    def load_deps(self, root_dir, targets=None, target_only=False):
        targets = targets or []
        deps_file_path = os.path.join(self.target_dir, self.deps_file)
        if not os.path.exists(deps_file_path):
            logging.warning(f"deps file {deps_file_path} not found, skip sync deps")
            return

        deps_cache = load_entries_cache_from_git(root_dir) or {}
        # check hash
        md5_hash = hashlib.md5(repr(deps_cache.get("entries", "")).encode()).hexdigest()
        if md5_hash != deps_cache.get("hash"):
            logging.debug("deps cache is broken, try a complete synchronization")
            logging.debug(f"deps cache: {deps_cache}")
            self.set_attr("local_source_stamps", {}, override=True)
        else:
            self.set_attr("local_source_stamps", deps_cache["entries"], override=True)

        deps = {}
        # if target is specified and --target-only is set, skip base deps.
        skip_base_deps = target_only and not targets == [None]
        for target in targets:
            deps = (
                merge_deps(deps, eval_deps(deps_file_path, target, root_dir))
                if not skip_base_deps
                else {}
            )
            if (
                hasattr(self, "target_deps_files")
                and target
                and self.target_deps_files.get(target)
            ):
                target_deps_file = os.path.join(
                    self.target_dir,
                    self.target_deps_files.get(target, "DEPS." + target),
                )
                deps = merge_deps(deps, eval_deps(target_deps_file, target, root_dir))

        mappings = load_mapping_file(os.path.join(root_dir, DEFAULT_CONFIG_FILE_NAME))
        self.instantiate_deps(root_dir, deps, mappings)

        deps_cache["entries"] = {}
        for dep in self.children:
            if not dep.condition:
                continue
            deps_cache["entries"][dep.name] = dep.source_stamp

        # update entries cache
        deps_cache["hash"] = hashlib.md5(
            repr(deps_cache["entries"]).encode()
        ).hexdigest()
        store_entries_cache_to_git(deps_cache, root_dir=root_dir)

    def up_to_date(self):
        return is_git_sha(getattr(self, "commit", "")) and super().up_to_date()

    async def fetch(
        self, root_dir, options, existing_sources=None, existing_targets=None
    ):
        tracer = get_global_tracer()
        async_id = None
        if tracer:
            async_id = tracer.async_begin(
                f"solution_fetch_{self.name}",
                category="solution",
                args={"solution_name": self.name, "root_dir": str(root_dir)},
            )

        if self.parent:
            root_dir = self.target_dir
        try:
            await super(Solution, self).fetch(
                root_dir,
                options,
                existing_sources=existing_sources,
                existing_targets=existing_targets,
            )
            if tracer:
                tracer.async_instant(
                    async_id,
                    f"solution_fetch_{self.name}_children_complete",
                    category="solution",
                )
        except Exception as e:
            if tracer and async_id:
                tracer.async_instant(
                    async_id,
                    f"solution_fetch_{self.name}_error",
                    category="solution",
                    args={"error": str(e)},
                )
            raise
        finally:
            if tracer and async_id:
                tracer.async_end(async_id)

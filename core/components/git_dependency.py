# Copyright 2024 The Lynx Authors. All rights reserved.
# Licensed under the Apache License Version 2.0 that can be found in the
# LICENSE file in the root directory of this source tree.

import logging
from pathlib import Path
from typing import Union

from core.components.component import Component
from core.fetchers.git_fetcher import GitFetcher
from core.utils import get_patch_series, is_git_sha, is_git_url, is_repo_patched, is_repo_unchanged


class GitDependency(Component):
    type = "git"
    defined_fields = {
        "url": {
            "type": str,
            "validator": lambda val, component: is_git_url(val),
        },
        "branch": {"type": str, "optional": True},
        "commit": {
            "type": str,
            "validator": lambda val, component: is_git_sha(val),
            "optional": True,
        },
        "tag": {"type": str, "optional": True},
        "enable_lfs": {
            "type": bool,
            "optional": True,
            "default": None,
        },
        "patches": {
            "type": Union[str, list],
            "validator": lambda val, component: isinstance(val, (str, list)),
            "optional": True,
        },
    }
    source_attributes = ["url"]
    source_stamp_attributes = ["branch", "commit", "tag"]

    def __init__(self, *args, **kwargs):
        super(GitDependency, self).__init__(*args, **kwargs)
        self.fetcher = GitFetcher(self)

    def up_to_date(self):
        target_dir = Path(self.target_dir)
        if not target_dir.exists():
            return False

        target_commit = getattr(self, "commit", None)
        if not target_commit:
            return False

        patches = getattr(self, "patches", None)
        if not patches:
            should_skip = is_repo_unchanged(target_commit, target_dir)
        elif isinstance(patches, str):
            patch_series = get_patch_series(patches)
            should_skip = is_repo_patched(target_commit, patch_series, target_dir)
        elif isinstance(patches, list):
            patch_series = []
            for p in patches:
                patch_series.extend(get_patch_series(p))
            should_skip = is_repo_patched(target_commit, patch_series, target_dir)

        if should_skip:
            logging.info(f"Skip {self.name} because it is already up to date")
        return should_skip

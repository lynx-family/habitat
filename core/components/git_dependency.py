# Copyright 2024 The Lynx Authors. All rights reserved.
# Licensed under the Apache License Version 2.0 that can be found in the
# LICENSE file in the root directory of this source tree.

from typing import Union

from core.components.component import Component
from core.fetchers.git_fetcher import GitFetcher
from core.utils import is_git_sha, is_git_url


class GitDependency(Component):
    type = 'git'
    defined_fields = {
        "url": {
            "type": str,
            "validator": lambda val, component: is_git_url(val),
        },
        "branch": {
            "type": str,
            "optional": True
        },
        "commit": {
            "type": str,
            "validator": lambda val, component: is_git_sha(val),
            "optional": True
        },
        "tag": {
            "type": str,
            "optional": True
        },
        "enable_lfs": {
            "type": bool,
            "optional": True,
            "default": False,
        },
        "patches": {
            "type": Union[str, list],
            "optional": True,
        }
    }
    source_attributes = ['url']
    source_stamp_attributes = ['branch', 'commit', 'tag']

    def __init__(self, *args, **kwargs):
        super(GitDependency, self).__init__(*args, **kwargs)
        self.fetcher = GitFetcher(self)

    def up_to_date(self):
        return is_git_sha(getattr(self, 'commit', '')) and super().up_to_date()

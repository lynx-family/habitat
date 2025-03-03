# Copyright 2024 The Lynx Authors. All rights reserved.
# Licensed under the Apache License Version 2.0 that can be found in the
# LICENSE file in the root directory of this source tree.

import logging
import os
import subprocess

from core.commands.command import Command
from core.exceptions import HabitatException
from core.settings import ENTRIES_CACHE_TAG_PREFIX, GLOBAL_CACHE_DIR
from core.utils import check_call, clean_temp_dirs, get_head_commit_id, git_root_dir, is_git_repo, rmtree


def clean_global_cache(_):
    for subdir in ['git', 'objects']:
        rmtree(os.path.join(GLOBAL_CACHE_DIR, subdir))


def clean_deps(root_dir):
    if not root_dir:
        raise HabitatException('not in a git repository and the root directory is not specified')

    head_commit_id = get_head_commit_id(cwd=root_dir)
    tag_name = f'{ENTRIES_CACHE_TAG_PREFIX}_{head_commit_id}'
    try:
        check_call(['git', 'tag', '-v', ], cwd=root_dir)
    except subprocess.SubprocessError:
        logging.warning('no deps cache found')
    else:
        check_call(['git', 'tag', '-d', tag_name], cwd=root_dir)


class Clean(Command):
    name = 'clean'
    help = 'Clean cache file or downloaded dependencies'
    args = [
        {
            'flags': ['-a', '--all'],
            'action': 'store_true',
            'help': 'Clean all artifacts fetched by habitat, including local cache and global cache',
            'default': False
        },
        {
            'flags': ['-d', '--deps-cache'],
            'action': 'store_true',
            'help': 'Clean local cache',
            'default': False
        },
        {
            'flags': ['-c', '--global-cache'],
            'action': 'store_true',
            'help': 'Clean local cache',
            'default': False
        },
        {
            'flags': ['root'],
            'help': 'Source root of the codebase, default to the root of current git repository if not set',
            'nargs': '?',
            'default': None
        }
    ]

    def __init__(self):
        self.actions = []

    async def run(self, options, *args, **kwargs):
        if options.root:
            root_dir = os.path.abspath(options.root)
        elif is_git_repo(os.getcwd()):
            root_dir = git_root_dir()
        else:
            root_dir = os.getcwd()

        self.actions.append(clean_temp_dirs)

        if options.deps_cache or options.all:
            self.actions.append(clean_deps)

        if options.global_cache or options.all:
            self.actions.append(clean_global_cache)

        for action in self.actions:
            action(root_dir)

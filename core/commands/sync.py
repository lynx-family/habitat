# Copyright 2024 The Lynx Authors. All rights reserved.
# Licensed under the Apache License Version 2.0 that can be found in the
# LICENSE file in the root directory of this source tree.

import logging
import os

from core.commands.command import Command
from core.components.solution import load_solutions
from core.settings import COMPATIBLE_CHECK, DEFAULT_CONFIG_FILE_NAME, GLOBAL_CACHE_DIR
from core.utils import git_root_dir, ignore_paths_in_git


class Sync(Command):
    name = 'sync'
    help = 'Sync dependencies'
    args = [
        {
            'flags': ['--no-history'],
            'help': 'Sync git dependencies with history (only works for git dependencies), default to False',
            'action': 'store_true',
            'default': False
        },
        {
            'flags': ['--raw'],
            'help': 'Only checkout source tree and don\'t keep git repository',
            'action': 'store_true',
            'default': False
        },
        {
            'flags': ['-f', '--force'],
            'help': 'Force to override existing files',
            'action': 'store_true',
            'default': True
        },
        {
            'flags': ['--clean'],
            'help': 'Force to clean existing directories',
            'action': 'store_true',
            'default': False
        },
        {
            'flags': ['--target'],
            'help': 'Target to fetch all dependencies for, this argument can be accessed '
                    'as a global variable in deps file',
            'default': None
        },
        {
            'flags': ['--git-auth'],
            'help': 'Set username and token for git. Habitat will translate ssh protocol to http and add the username '
                    'and token to the url',
            'default': None
        },
        {
            'flags': ['--compatible'],
            'help': 'Do not raise exception if there\'s no configure file found',
            'action': 'store_true',
            'default': False
        },
        {
            'flags': ['--main'],
            'help': 'Sync the main repository along with dependencies if set, default False',
            'action': 'store_true',
            'default': False
        },
        {
            'flags': ['--disable-ignore'],
            'help': 'Disable ignoring target directories of deps in git repository (only works for the deps which '
                    'have no "ignore_in_git" flag set to False in their deps configuration',
            'action': 'store_true',
            'default': False
        },
        {
            'flags': ['--disable-cache'],
            'help': 'Do not use global cache',
            'action': 'store_true',
            'default': False
        },
        {
            'flags': ['--cache-dir'],
            'help': 'Global cache directory, default is $HOME/.habitat_cache',
            'default': GLOBAL_CACHE_DIR
        },
        {
            'flags': ['root'],
            'help': 'Source root of the codebase, default to the root of current git repository if not set',
            'nargs': '?',
            'default': None
        },
        {
            'flags': ['--strict'],
            'help': 'When there is a dependencies conflict, stop syncing in strict mode, '
                    'or try resolving conflict automatically in non-strict mode, default False',
            'action': 'store_true',
            'default': False
        },
        {
            'flags': ['-a', '--all'],
            'help': 'Sync all dependencies for all targets.',
            'action': 'store_true',
            'default': False
        },
        {
            'flags': ['--target-only'],
            'help': 'Sync target dependencies only.',
            'action': 'store_true',
            'default': False
        }
    ]

    async def run(self, options, *args, **kwargs):
        root_dir = os.path.abspath(options.root or git_root_dir())
        solution_file = os.path.join(root_dir, DEFAULT_CONFIG_FILE_NAME)
        solutions = load_solutions(
            root_dir, solution_file, ignore_non_existing=options.compatible, enable_version_checking=COMPATIBLE_CHECK
        )

        for solution in solutions:
            if options.main:
                await solution.fetch(root_dir, options, {})
            else:
                await solution.fetch_deps_only(root_dir, options, {}, existing_targets={root_dir: solution})

            for dep in solution.list_deps():
                if not dep.condition:
                    continue
                if not options.disable_ignore and dep.ignore_in_git and dep.parent:
                    ignore_paths_in_git(dep.parent.target_dir, [dep.target_dir], ignore_errors=True)

            tree_str = solution.get_pretty_dependency_tree()
            logging.info(f'Dependencies for {solution.target_dir} are ready')
            logging.debug(f'Dependency tree:\n{tree_str}')

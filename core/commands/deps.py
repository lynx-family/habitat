# Copyright 2024 The Lynx Authors. All rights reserved.
# Licensed under the Apache License Version 2.0 that can be found in the
# LICENSE file in the root directory of this source tree.

import os
import string

from core.commands.command import Command
from core.components.solution import load_solutions
from core.settings import COMPATIBLE_CHECK, DEFAULT_CONFIG_FILE_NAME
from core.utils import git_root_dir


class PartialFormatter(string.Formatter):
    def __init__(self, missing='~'):
        self.missing = missing

    def get_field(self, field_name, args, kwargs):
        # Handle a key not found
        try:
            val = super().get_field(field_name, args, kwargs)
        except (KeyError, AttributeError):
            val = self.missing, field_name
        return val


class Deps(Command):
    name = 'deps'
    help = 'List or manage dependencies'
    args = [
        {
            'flags': ['-r', '--raw'],
            'help': 'print dependencies raw info',
            'action': 'store_true',
            'default': False
        },
        {
            'flags': ['--source-stamp'],
            'help': 'only print source stamp',
            'action': 'store_true',
            'default': False
        },
        {
            'flags': ['--format'],
            'help': 'format print',
            'default': None
        },
        {
            'flags': ['--target'],
            'help': 'Target to list all dependencies for, this argument can be accessed '
                    'as a global variable in deps file',
            'default': None
        },
        {
            'flags': ['--type'],
            'help': 'filter by type, only works with --source-stamp or --format',
            'default': None
        },
        {
            'flags': ['--name'],
            'help': 'filter by name, only works with --source-stamp or --format',
            'default': None
        },
        {
            'flags': ['root'],
            'help': 'Source root of the codebase, default to the root of current git repository if not set',
            'nargs': '?',
            'default': None
        },
        {
            'flags': ['--ignore-condition'],
            'help': 'Ignore condition and list all deps',
            'action': 'store_true',
            'default': False
        }
    ]

    async def run(self, options, *args, **kwargs):
        root_dir = os.path.abspath(options.root or git_root_dir())
        solution_file = os.path.join(root_dir, DEFAULT_CONFIG_FILE_NAME)
        solutions = load_solutions(
            root_dir, solution_file, ignore_non_existing=False, enable_version_checking=COMPATIBLE_CHECK
        )

        for solution in solutions:
            targets = options.target.split(',') if options.target else [None]
            solution.load_deps(root_dir, targets)

            deps = solution.list_deps()
            if options.name:
                deps = [dep for dep in deps if options.name == dep.name]
            if options.type:
                deps = [dep for dep in deps if options.type == dep.type]
            if not options.ignore_condition:
                deps = [dep for dep in deps if dep.condition]

            if options.raw:
                for dep in deps:
                    print(dep)
            elif options.source_stamp:
                for dep in deps:
                    print(dep.source_stamp)
            elif options.format:
                for dep in deps:
                    formatter = PartialFormatter()
                    format_string = options.format
                    print(formatter.format(
                        format_string,
                        **dep.attributes
                    ))
            else:
                tree_str = solution.get_pretty_dependency_tree()
                print(f'Dependency tree:\n{tree_str}')

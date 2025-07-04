# Copyright 2024 The Lynx Authors. All rights reserved.
# Licensed under the Apache License Version 2.0 that can be found in the
# LICENSE file in the root directory of this source tree.

import logging
import os

from core.commands.command import Command
from core.exceptions import HabitatException
from core.settings import DEFAULT_CONFIG_FILE_NAME
from core.utils import is_git_url

SOLUTION_CONFIG_TEMPLATE = {"name": ".", "deps_file": "DEPS"}


def is_dir(path):
    if os.path.exists(path) and not os.path.isdir(path):
        raise ValueError
    return path


def _is_git_url(url):
    if not is_git_url(url):
        raise ValueError
    return url


class Config(Command):
    name = "config"
    help = "Create a new config in directory"
    args = [
        {"flags": ["--name"], "help": "override default name", "default": "."},
        {
            "flags": ["url"],
            "help": "Source root of the codebase, default to the root of current git repository if not set",
            "type": _is_git_url,
        },
        {
            "flags": ["-b", "--branch"],
            "help": "Specify branch to checkout",
            "default": None,
        },
        {
            "flags": ["dir"],
            "help": "Target directory",
            "nargs": "?",
            "type": is_dir,
            "default": ".",
        },
    ]

    async def run(self, options, *args, **kwargs):
        config_file_path = os.path.join(
            os.path.abspath(options.dir), DEFAULT_CONFIG_FILE_NAME
        )
        if os.path.exists(config_file_path):
            raise HabitatException(f"config file exists in {options.dir}")

        if not os.path.exists(options.dir):
            os.mkdir(options.dir)

        logging.info(f"write new configuration to {config_file_path}")
        solution_config = {**SOLUTION_CONFIG_TEMPLATE, "url": options.url}
        if options.name:
            solution_config["name"] = options.name
        if options.branch:
            solution_config["branch"] = options.branch
        with open(config_file_path, "w+") as f:
            f.write(f"solutions = {str([solution_config])}")

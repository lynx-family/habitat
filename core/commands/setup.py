# Copyright 2024 The Lynx Authors. All rights reserved.
# Licensed under the Apache License Version 2.0 that can be found in the
# LICENSE file in the root directory of this source tree.

import re

from core.commands.command import Command
from core.common.key_value_storage import KeyValueStorage
from core.exceptions import HabitatException
from core.settings import USER_CONFIG_STORAGE_PATH


class Setup(Command):
    name = "setup"
    help = "Setup global configurations for habitat."
    args = [
        {
            "flags": ["-l", "--list"],
            "action": "store_true",
            "help": "List all user configurations",
            "default": False,
        },
        {
            "flags": ["configs"],
            "help": "The expression to set the value of certain configuration,"
            ' which should be in format of "aaa=bbb,ccc,ddd"',
            "nargs": "?",
            "default": None,
        },
    ]
    configs = []

    async def run(self, options, *args, **kwargs):
        storage = KeyValueStorage(USER_CONFIG_STORAGE_PATH)

        if options.list:
            print("Current configs:")
            for key, value in storage.data.items():
                print(f"  {key}: {value}")
            return

        if options.configs:
            for expr in options.configs.split(","):
                matches = re.match(r"^(\S+)=(.*)$", expr.strip())
                if not matches:
                    raise HabitatException(f"Invalid expression {expr}")
                key, value = tuple(
                    s.encode("ascii", "ignore").decode() for s in matches.groups()
                )
                storage.set(key, value)
            return

        inputs = {}
        for config in self.configs:
            prompt = config["help"]
            if "choices" in config:
                prompt += f', choices are: {", ".join(config["choices"])}'
            if "default" in config:
                prompt += f' (default: {config["default"]})'
            prompt += ":"
            print(prompt)
            inputs[config["name"]] = input() or config.get("default")

            if "choices" in config and inputs[config["name"]] not in config["choices"]:
                raise HabitatException("Invalid input")

        for key, value in inputs.items():
            storage.set(key, value)

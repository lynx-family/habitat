# Copyright 2024 The Lynx Authors. All rights reserved.
# Licensed under the Apache License Version 2.0 that can be found in the
# LICENSE file in the root directory of this source tree.

from abc import ABC, abstractmethod


class Command(ABC):

    name = None
    help = None
    args = []
    subcommands = []

    async def run_command(self, options):
        await self.run(options)

    @abstractmethod
    async def run(self, options, *args, **kwargs):
        raise NotImplementedError

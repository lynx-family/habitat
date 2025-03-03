# Copyright 2024 The Lynx Authors. All rights reserved.
# Licensed under the Apache License Version 2.0 that can be found in the
# LICENSE file in the root directory of this source tree.

import logging
import os
import subprocess
from typing import Callable, Iterable

from core.components.component import Component
from core.exceptions import HabitatException
from core.utils import async_check_output


class ActionDependency(Component):
    type = 'action'
    defined_fields = {
        'commands': {
            'validator': lambda val, config: isinstance(val, Iterable) or isinstance(val, str),
            'default': []
        },
        'function': {
            'validator': lambda val, config: isinstance(val, Callable) or val is None,
            'default': None
        },
        'cwd': {
            'optional': True
        }
    }
    source_attributes = []
    source_stamp_attributes = []

    @property
    def source_stamp(self):
        return "(action)"

    async def fetch(self, root_dir, options, existing_sources=None, existing_targets=None):
        logging.info(f'Run action {self.name}')
        commands = self.commands
        env = getattr(self, 'env', {})
        cwd = getattr(self, 'cwd', None)
        cwd = os.path.join(root_dir, cwd) if cwd else root_dir

        if self.function:
            saved_dir = os.getcwd()
            os.chdir(cwd)
            self.function()
            os.chdir(saved_dir)

        try:
            for command in commands:
                logging.info(f'Run command {command} in path {cwd}')
                await async_check_output(
                    command,
                    shell=isinstance(command, str), stderr=subprocess.STDOUT, cwd=cwd, env={**os.environ.copy(), **env}
                )
            self.on_fetched(root_dir, options)
        except subprocess.CalledProcessError as e:
            logging.error(f'a command has failed recently, original output:\n{e.output.decode()}')
            raise HabitatException(f'failed to run action {commands} in {self.target_dir}') from e
        except Exception as e:
            raise HabitatException(f'failed to run action {commands} in {self.target_dir}') from e
        finally:
            if hasattr(self, 'parent') and self.parent:
                self.parent.produce_event(self.name)

    def up_to_date(self):
        # action should never be cached
        return False

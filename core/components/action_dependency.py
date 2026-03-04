# Copyright 2024 The Lynx Authors. All rights reserved.
# Licensed under the Apache License Version 2.0 that can be found in the
# LICENSE file in the root directory of this source tree.

import logging
import os
import shlex
import subprocess
import time
from contextlib import nullcontext
from typing import Callable, Iterable

from core.components.component import Component
from core.exceptions import HabitatException
from core.observe import observer
from core.utils import async_check_output


_DOWNLOAD_TOOLS = {"pnpm"}


def _command_tokens(cmd) -> list:
    if cmd is None:
        return []
    if isinstance(cmd, (list, tuple)):
        return [str(x) for x in cmd]
    if isinstance(cmd, str):
        try:
            return [str(x) for x in shlex.split(cmd)]
        except Exception:
            return []
    return []


def _download_tool_for_command(cmd) -> str:
    tokens = _command_tokens(cmd)
    if not tokens:
        return ""
    prog = os.path.basename(tokens[0])
    return prog if prog in _DOWNLOAD_TOOLS else ""


def _safe_command_for_profile(tool: str, cmd) -> str:
    if not tool:
        return ""

    tokens = _command_tokens(cmd)
    if len(tokens) >= 2 and not str(tokens[1]).startswith("-"):
        return f"{tool} {tokens[1]}"
    return tool


class ActionDependency(Component):
    type = "action"
    defined_fields = {
        "commands": {
            "validator": lambda val, config: isinstance(val, Iterable)
            or isinstance(val, str),
            "default": [],
        },
        "function": {
            "validator": lambda val, config: isinstance(val, Callable) or val is None,
            "default": None,
        },
        "output": {
            "validator": lambda val, config: isinstance(val, bool),
            "default": False,
        },
        "cwd": {"optional": True},
    }
    source_attributes = []
    source_stamp_attributes = []

    @property
    def source_stamp(self):
        return "(action)"

    async def fetch(
        self, root_dir, options, existing_sources=None, existing_targets=None
    ):
        logging.info(f"Run action {self.name}")
        dep_name = getattr(self, "name", "unknown")
        span_start_ns = time.perf_counter_ns()

        commands = self.commands
        env = getattr(self, "env", {})
        cwd = getattr(self, "cwd", None)
        cwd = os.path.join(root_dir, cwd) if cwd else root_dir

        if self.function:
            saved_dir = os.getcwd()
            os.chdir(cwd)
            self.function()
            os.chdir(saved_dir)

        ctx = observer.dependency_context(
            getattr(self, "name", "unknown"), getattr(self, "type", "unknown")
        )


        try:
            action_outputs = []

            with ctx:
                for command in commands:
                    tool = _download_tool_for_command(command)
                    safe_cmd = _safe_command_for_profile(tool, command)
                    t0_ns = time.perf_counter_ns()

                    output = await async_check_output(
                        command,
                        shell=isinstance(command, str),
                        stderr=subprocess.STDOUT,
                        cwd=cwd,
                        env={**os.environ.copy(), **env},
                    )
                    if tool:
                        duration_ms = int((time.perf_counter_ns() - t0_ns) / 1_000_000)
                        observer.record_download_task(
                            duration_ms,
                            {
                                "durationMs": duration_ms,
                                "kind": "tool",
                                "tool": tool,
                                "command": safe_cmd,
                                "bytes": 0,
                            },
                        )

                    logging.info(f"Run command {command} in path {cwd}")
                    if self.output:
                        action_outputs.extend(output.decode().splitlines())

            if self.output:
                logging.info(f"┌──── {self.name}")
                for output in action_outputs:
                    logging.info(f"│ {output}")
                logging.info("└────")

            self.on_fetched(root_dir, options)
        except subprocess.CalledProcessError as e:
            logging.error(f"command {command} fails, original output:")
            logging.error(f'  --> {e.output.decode().strip()}')
            raise HabitatException(
                f"failed to run action {commands} in {self.target_dir}"
            ) from e
        except Exception as e:
            raise HabitatException(
                f"failed to run action {commands} in {self.target_dir}"
            ) from e
        finally:
            duration_ms = int((time.perf_counter_ns() - span_start_ns) / 1_000_000)
            observer.record_dependency_span(duration_ms, dep_name=dep_name)

            if hasattr(self, "parent") and self.parent:
                self.parent.produce_event(self.name)

    def up_to_date(self):
        # action should never be cached
        return False
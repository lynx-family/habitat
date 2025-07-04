# Copyright 2024 The Lynx Authors. All rights reserved.
# Licensed under the Apache License Version 2.0 that can be found in the
# LICENSE file in the root directory of this source tree.

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.components.component import Component


class Fetcher(ABC):
    defined_fields = {"type": {"type": str}, "condition": {"default": True}}

    def __init__(self, component: "Component"):
        self._component = component

    @property
    def component(self) -> "Component":
        return self._component

    @abstractmethod
    async def fetch(self, root_dir, options):
        raise NotImplementedError

# Copyright 2024 The Lynx Authors. All rights reserved.
# Licensed under the Apache License Version 2.0 that can be found in the
# LICENSE file in the root directory of this source tree.

import json
from typing import Optional


class HabitatException(Exception):
    """Base exception in habitat"""

    def __init__(
        self,
        message: str,
        *,
        cause: Optional[Exception] = None,
        hint: Optional[str] = None,
        context: Optional[dict] = None,
    ):
        self.message = message
        self.cause = cause
        self.hint = hint
        self.context = context

    def __str__(self) -> str:
        e = {"message": self.message}

        if self.cause:
            e["cause"] = str(self.cause)

        if self.hint:
            e["hint"] = self.hint

        if self.context:
            e["context"] = self.context

        return json.dumps(e, indent=2, ensure_ascii=False)

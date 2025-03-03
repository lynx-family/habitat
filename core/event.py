# Copyright 2024 The Lynx Authors. All rights reserved.
# Licensed under the Apache License Version 2.0 that can be found in the
# LICENSE file in the root directory of this source tree.

import asyncio


class Event(asyncio.Event):

    def __init__(self, name):
        super(Event, self).__init__()
        self._name = name

    def __str__(self):
        return "event: " + self._name

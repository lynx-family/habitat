# Copyright 2024 The Lynx Authors. All rights reserved.
# Licensed under the Apache License Version 2.0 that can be found in the
# LICENSE file in the root directory of this source tree.

import logging

from core.fetchers.fetcher import Fetcher


class DummyFetcher(Fetcher):

    async def fetch(self, *args, **kwargs):
        logging.warning(f"unsupported dependency config {self.component}, skip")
        return []

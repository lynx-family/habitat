# Copyright 2024 The Lynx Authors. All rights reserved.
# Licensed under the Apache License Version 2.0 that can be found in the
# LICENSE file in the root directory of this source tree.

from core.components.component import Component
from core.fetchers.http_fetcher import HttpFetcher
from core.utils import is_http_url


class HttpDependency(Component):
    type = "http"
    defined_fields = {
        "url": {"type": str, "validator": lambda value, component: is_http_url(value)},
        "sha256": {"type": str, "optional": True},
        "decompress": {"type": bool, "optional": True, "default": True},
        "paths": {"type": list, "optional": True, "default": []},
        "http_headers": {"type": dict, "optional": True, "default": {}},
    }
    source_attributes = ["url"]
    source_stamp_attributes = ["url"]

    def __init__(self, *args, **kwargs):
        super(HttpDependency, self).__init__(*args, **kwargs)
        self.fetcher = HttpFetcher(self)

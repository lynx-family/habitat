# Copyright 2024 The Lynx Authors. All rights reserved.
# Licensed under the Apache License Version 2.0 that can be found in the
# LICENSE file in the root directory of this source tree.

import os
import shutil

from core.exceptions import HabitatException
from core.settings import GLOBAL_CACHE_DIR


class CacheMixin:
    """
    TODO(zouzhecheng):
    1. cache expiration
    2. cache existence
    """
    cache_dir = os.path.join(GLOBAL_CACHE_DIR, 'objects')

    def get_from_cache(self, key):
        if self.cache_dir is None:
            return
        cache_path = os.path.join(self.cache_dir, key)
        return cache_path if os.path.exists(cache_path) else None

    def put_to_cache(self, key, path=None, content: bytes = None):
        if self.cache_dir is None:
            return
        cache_path = os.path.join(self.cache_dir, key)
        if not os.path.exists(cache_path):
            d = os.path.dirname(cache_path)
            if not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
            if path:
                shutil.copy2(path, cache_path)
            elif content:
                with open(cache_path, 'wb') as f:
                    f.write(content)
            else:
                raise HabitatException('either "path" or "content" is required')

# Copyright 2024 The Lynx Authors. All rights reserved.
# Licensed under the Apache License Version 2.0 that can be found in the
# LICENSE file in the root directory of this source tree.

import os
import tempfile

DEBUG = os.environ.get("HABITAT_DEBUG", None) == 'true'
COMPATIBLE_CHECK = os.environ.get("HABITAT_COMPATIBLE_CHECK", None) != 'false'

DEFAULT_CONFIG_FILE_NAME = '.habitat'
DEFAULT_DEPS_CACHE_FILE_NAME = '.habitat_entries'

GLOBAL_CACHE_DIR = os.path.join(os.environ.get("HOME", tempfile.gettempdir()), '.habitat_cache')
USER_CONFIG_STORAGE_PATH = os.path.join(GLOBAL_CACHE_DIR, 'meta', 'config')

CACHE_DIR_PREFIX = 'TEMP-HABITAT-'

CHUNKED_TRANSMISSION = os.environ.get('HABITAT_CHUNKED_TRANSMISSION', 'true').lower() == 'true'

ENTRIES_CACHE_TAG_PREFIX = 'habitat_entries'

MAX_DEPENDENCY_WAIT_TIME = int(os.environ.get('HABITAT_MAX_DEPENDENCY_WAIT_TIME', 1200))

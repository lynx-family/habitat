# Copyright 2024 The Lynx Authors. All rights reserved.
# Licensed under the Apache License Version 2.0 that can be found in the
# LICENSE file in the root directory of this source tree.

import os

from core.common.key_value_storage import KeyValueStorage, NotSet
from core.exceptions import HabitatException


class ConfigStorage(KeyValueStorage):

    def get(self, key, default=None):
        value = (
            os.environ.get("HABITAT_" + key.upper().replace(".", "_"))
            or default
            or super(ConfigStorage, self).get(key)
            or NotSet
        )
        if value is NotSet:
            raise HabitatException(
                f'Configuration {key} not found, please run "hab setup {key}" to setup a correct value'
            )
        return value

    def __iter__(self):
        config = self.data
        # read all environment variables that start with "HABITAT_". configurations in ~/.habitat_cache/meta/config
        # will be overridden by environment variables.
        config.update(
            {
                k.lower().replace("_", ".").replace("habitat.", ""): v
                for k, v in os.environ.items()
                if k.startswith("HABITAT_")
            }
        )
        return iter(config.items())

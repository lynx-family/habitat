# Copyright 2024 The Lynx Authors. All rights reserved.
# Licensed under the Apache License Version 2.0 that can be found in the
# LICENSE file in the root directory of this source tree.
import logging
from enum import Enum
from pathlib import Path

from core.common.file_stamp import FileStamp
from core.common.hash_tree import HashTree
from core.components.component import Component
from core.config_storage import ConfigStorage
from core.fetchers.http_fetcher import HttpFetcher
from core.settings import USER_CONFIG_STORAGE_PATH
from core.utils import is_http_url


class CheckMode(Enum):
    """
    This enum is used to identify HttpDependency.up_to_date() check mode.
    - FAST: hash the structure of target_dir.
    - STRICT: hash the structure of target_dir and the detailed file content.
    """

    FAST = "fast"
    STRICT = "strict"


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

    _up_to_date = None
    _check_mode = CheckMode.FAST

    def __init__(self, *args, **kwargs):
        super(HttpDependency, self).__init__(*args, **kwargs)
        self.fetcher = HttpFetcher(self)

        check_mode = ConfigStorage(USER_CONFIG_STORAGE_PATH).get(
            "http_dep.check_mode", default=CheckMode.FAST
        )
        if check_mode:
            self._check_mode = CheckMode(check_mode)

    def __create_file_stamp(self, type: str, name: str, target_dir: Path) -> FileStamp:
        extra = {
            "url": self.url,
            "decompress": getattr(self, "decompress", True),
            "paths": getattr(self, "paths", []),
        }
        return FileStamp(type, name, target_dir, extra=extra)

    def on_fetched(self, root_dir, options):
        super().on_fetched(root_dir, options)

        if self._up_to_date or options.force:
            return

        target_dir = Path(self.target_dir)
        stamp = self.__create_file_stamp(self.type, self.name, target_dir)
        tree = HashTree()
        fast_digest = tree.get_hex_digest(target_dir, full_hash=False)

        full_digest = None
        if self._check_mode == CheckMode.STRICT:
            full_digest = tree.get_hex_digest(target_dir, full_hash=True)

        stamp.write(fast_digest, full_digest)

    def up_to_date(self):
        target_dir = Path(self.target_dir)
        if not target_dir.exists():
            return False

        stamp = self.__create_file_stamp(self.type, self.name, target_dir)
        if not stamp.exists():
            logging.debug(f"File stamp does not exist: {stamp.stamp_path}")
            return False

        stamp_info = stamp.read()
        stamp_version = stamp_info.get("version", None)
        # stamp version mismatched
        if stamp_version != FileStamp.version:
            logging.debug(
                f"File stamp's version does not match: expected {FileStamp.version} but got {stamp_version}"
            )
            return False

        tree = HashTree()
        stamp_fast_digest = stamp_info.get("fast_digest", None)
        fast_digest = tree.get_hex_digest(target_dir, full_hash=False)
        if fast_digest != stamp_fast_digest:
            logging.debug(
                f"digest does not match: expected {fast_digest} but got {stamp_fast_digest}"
            )
            return False

        if self._check_mode == CheckMode.FAST:
            logging.info(
                f"Skip {self.name} because it is already up to date according to a fast hash"
            )
            self._up_to_date = True
            return True

        stamp_full_digest = stamp_info.get("full_digest", None)
        full_digest = tree.get_hex_digest(target_dir, full_hash=True)
        if full_digest != stamp_full_digest:
            logging.debug(
                f"full digest does not match: expected {full_digest} but got {stamp_full_digest}"
            )
            return False

        logging.info(
            f"Skip {self.name} because it is already up to date according to a strict hash"
        )
        self._up_to_date = True
        return True

# Copyright 2024 The Lynx Authors. All rights reserved.
# Licensed under the Apache License Version 2.0 that can be found in the
# LICENSE file in the root directory of this source tree.

import json
import os


class NotSet:
    pass


class KeyValueStorage:
    def __init__(self, file_path):
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        self.file_path = file_path
        self.data = {}
        try:
            with open(self.file_path, "r") as f:
                self.data = json.load(f)
        except FileNotFoundError:
            pass

    def set(self, key, value):
        self.data[key] = value
        with open(self.file_path, "w") as f:
            json.dump(self.data, f)

    def get(self, key):
        return self.data.get(key, NotSet)

    def delete(self, key):
        if key in self.data:
            del self.data[key]
            with open(self.file_path, "w") as f:
                json.dump(self.data, f)

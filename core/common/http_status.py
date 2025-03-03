# Copyright 2024 The Lynx Authors. All rights reserved.
# Licensed under the Apache License Version 2.0 that can be found in the
# LICENSE file in the root directory of this source tree.


def success(code):
    return 200 <= code <= 299


def client_error(code):
    return 400 <= code <= 499


def server_error(code):
    return 500 <= code <= 599

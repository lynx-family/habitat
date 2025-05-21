# Copyright 2025 The Lynx Authors. All rights reserved.
# Licensed under the Apache License Version 2.0 that can be found in the
# LICENSE file in the root directory of this source tree.

import copy
import platform


class DepsEnvBuild:
    _depsEnv = None

    @staticmethod
    def init_deps_env():
        if DepsEnvBuild._depsEnv is None:
            system = platform.system().lower()
            machine = platform.machine().lower()
            machine = "x86_64" if machine == "amd64" else machine
            DepsEnvBuild._depsEnv = {
                "system": system,
                "machine": machine,
            }

    @staticmethod
    def get_deps_env(custom={}):
        DepsEnvBuild.init_deps_env()
        deps_env_copy = copy.deepcopy(DepsEnvBuild._depsEnv)
        deps_env_copy.update(custom)
        return deps_env_copy

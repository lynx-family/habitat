# Copyright 2024 The Lynx Authors. All rights reserved.
# Licensed under the Apache License Version 2.0 that can be found in the
# LICENSE file in the root directory of this source tree.

import logging
import os.path
import shutil

from core.exceptions import HabitatException
from core.fetchers.fetcher import Fetcher
from core.utils import create_symlink


class LocalFetcher(Fetcher):

    def __init__(self, component, reference, symlink=False):
        super(LocalFetcher, self).__init__(component)
        self.reference = reference
        self.symlink = symlink

    async def fetch(self, *args, **kwargs):
        disable_link = not self.symlink
        if not self.reference.fetched:
            event = self.reference.parent.event_manager.register_consumer(str(self.reference.name))
            logging.debug(f'Reference component {self.reference} has not been fetched yet, waiting on event {event}')
            await event.wait()
            logging.debug(f'Got event {event}, start to fetch component {self.component}')

        for path in self.reference.fetched_paths:
            relpath = os.path.relpath(path, self.reference.target_dir)
            src = os.path.abspath(os.path.join(self.reference.target_dir, relpath))
            dst = os.path.abspath(os.path.join(self.component.target_dir, relpath))
            if disable_link:
                # if dst is an existing symlink, delete it or copytree() will throw an exception
                if os.path.islink(dst):
                    logging.debug(f'{dst} is an existing symlink, remove it.')
                    os.remove(dst)
                logging.debug(f'Copying {src} to {dst} instead of creating symlink.')
                shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=True)
                continue

            # if dst is link, delete it, as it might be an old link
            if os.path.islink(dst):
                os.remove(dst)
            # if src and dst is the same path in normpath, just continue
            if os.path.normpath(src) == os.path.normpath(dst):
                logging.warning(
                    f'src path is the same as dst path when creating symlink\n'
                    f'src: {src}\n'
                    f'dst: {dst}'
                )
                continue
            # if dst is already a directory, symlink will fail. just continue
            if os.path.exists(dst):
                logging.warning(
                    f'dst path {dst} is already a directory, delete it then create symlink'
                )
                continue

            try:
                create_symlink(src, dst)
            except Exception as e:
                raise HabitatException(f'an error occurred when trying to create symlink from {src} to {dst}') from e

        return self.reference.fetched_paths

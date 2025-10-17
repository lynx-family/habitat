# Copyright 2024 The Lynx Authors. All rights reserved.
# Licensed under the Apache License Version 2.0 that can be found in the
# LICENSE file in the root directory of this source tree.

import asyncio
import functools
import hashlib
import logging
import os
import platform
import shutil
import stat
import sys
from pathlib import Path
from urllib.parse import urlsplit

from core.common.cache_mixin import CacheMixin
from core.common.http_status import client_error, server_error, success
from core.common.httpx_client import HttpxClient
from core.exceptions import HabitatException
from core.fetchers.fetcher import Fetcher
from core.settings import DEBUG
from core.utils import ProgressBar, async_check_output, create_temp_dir, extract_archive

FILE_PART_SIZE = 20 * 1024 * 1024


def check_sha256(path: str, sha256: str):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(FILE_PART_SIZE), b""):
            h.update(block)
    return h.hexdigest() == sha256


def _get_content_length(header):
    size = header.get("Content-Length", None)
    return int(size) if size else None


def _check_range_supported(header):
    return True if header.get("Accept-Ranges") == "bytes" else False


def convert_url_to_cache_path(url: str) -> str:
    # if a http dependency's url is https://www.example.com/test/file.zip,
    # its cache path is www.example.com/test/file.zip
    return os.path.join(
        *[u for u in url.split("/") if u and u not in ["http:", "https:"]]
    )


def _rmtree(target_dir):
    if sys.version_info < (3, 12, 0):
        shutil.rmtree(target_dir, onerror=on_fs_error)
    else:
        shutil.rmtree(target_dir, onexc=on_fs_error)


def on_fs_error(func, path, _):
    if not os.path.exists(str(path)):
        return

    if platform.system() == "Windows":
        os.chmod(path, stat.S_IWRITE)
        func(path)


def move_to_target_dir(temp_dir, target_dir, is_single_file):
    sub_dirs = os.listdir(temp_dir)
    path = temp_dir
    # remove nested folder
    if len(sub_dirs) == 1 and (
        os.path.isdir(os.path.join(temp_dir, sub_dirs[0])) or is_single_file
    ):
        path = os.path.join(temp_dir, sub_dirs[0])

    if platform.system() == "Windows" and os.path.exists(str(target_dir)):
        os.chmod(target_dir, stat.S_IWRITE)
        os.chmod(path, stat.S_IWRITE)
        _rmtree(target_dir)
    shutil.move(path, target_dir)


def check_target_dir_existence(target_dir: str, override_exist: bool):
    # target_dir's parent directory should be existed.
    os.makedirs(os.path.dirname(target_dir), exist_ok=True)
    if not os.path.exists(target_dir):
        pass
    elif not override_exist:
        logging.info(f"{target_dir} existed, skip fetching.")
        return
    elif os.path.isdir(target_dir):
        logging.debug(f"directory {target_dir} is going to be overridden")
        _rmtree(target_dir)
    else:
        logging.debug(f"file {target_dir} is going to be overridden")
        os.remove(target_dir)


class HttpFetcher(Fetcher, CacheMixin):
    def __init__(self, component):
        super(HttpFetcher, self).__init__(component)
        self.url = self.component.url
        self.base_url = None
        self.path_url = None
        self._download_client = None

    @property
    def download_client(self) -> HttpxClient:
        if not self._download_client:
            self._update_download_url(self.url)
            self._download_client = HttpxClient(self.base_url, getattr(self.component, "http_headers", {}))
        return self._download_client

    async def download(self, item: str, root_dir: str, override_exist: bool):
        logging.info(
            f"{item} will be downloaded to path: {root_dir}, "
            f'the operation will {"not " if not override_exist else ""}override existing file.'
        )

        target_dir = os.path.join(root_dir, item)
        target_dir = str(Path(target_dir))
        component = self.component
        is_single_file = not getattr(component, "decompress", True)
        check_target_dir_existence(target_dir, override_exist)

        # update download url to get file name
        self._update_download_url(self.component.url)
        file_name = self.path_url.split("/")[-1]
        temp_dir = create_temp_dir(os.path.dirname(target_dir), name="HTTP")
        file_path = os.path.join(temp_dir, file_name)

        # retrieve file from cache, the key is the url of the dependency.
        skip_download = False
        url_cache_key = getattr(component, "original_url", self.url)
        cache = self.get_from_cache(convert_url_to_cache_path(url_cache_key))
        if cache:
            shutil.copy2(cache, file_path)
            skip_download = True

        header = {}
        if not skip_download:
            header = await self._send_head_request(item)
        partial = _check_range_supported(header)
        size = _get_content_length(header)

        if skip_download:
            pass
        elif partial and size:
            remained_size = size
            download_futures = []
            start = 0
            progress_bar = ProgressBar(
                total=size, title=f"Download {item}" if DEBUG else ""
            )
            while remained_size > 0:
                chunk_len = min(FILE_PART_SIZE, remained_size)
                end = start + chunk_len
                coroutine = asyncio.create_task(
                    self._download_part(
                        item,
                        start,
                        end - 1,
                        functools.partial(progress_bar.update, int(chunk_len * 0.8)),
                    )
                )
                download_futures.append(coroutine)
                start = end
                remained_size -= chunk_len

            results = await asyncio.gather(*download_futures)

            with open(file_path, "wb") as f:
                for r in results:
                    result, _ = r
                    f.write(result)
                    progress_bar.update(int(len(result) * 0.2))
        else:
            await self._download_entire(file_path, self.path_url)

        sha256 = getattr(component, "sha256", None)
        is_sha256_match = check_sha256(file_path, sha256)

        if sha256 and not is_sha256_match:
            raise HabitatException(
                f"{self.url}'s sha256 does not match {target_dir}'s sha256"
            )

        # store file to cache, the key is the url of the dependency.
        self.put_to_cache(convert_url_to_cache_path(url_cache_key), path=file_path)

        paths = getattr(component, "paths", [])
        if getattr(component, "decompress", True):
            extract_archive(file_path, temp_dir, paths)

        if not paths:
            move_to_target_dir(temp_dir, target_dir, is_single_file)

        for path in paths:
            move_to_target_dir(os.path.join(temp_dir, path), target_dir, False)

        _rmtree(temp_dir)

    async def _download_part(self, item: str, start, end, callback=None):
        logging.debug(f"download part [{start}, {end}] of {item}")
        try:
            # TODO(zouzhecheng): delete this when http client refactored.
            if (
                sys.version_info[0:3] < (3, 8, 0)
                and platform.system().lower() == "linux"
            ):
                url = f"{self.base_url}{self.path_url}"
                data = await async_check_output(
                    f"curl -k -s -S {url} --request GET --fail --stderr - --retry 3 --location "
                    f"--header 'Range: bytes={start}-{end}'",
                    shell=True,
                )
            else:
                _, _, data = await self.download_client.async_request(
                    "GET",
                    self.path_url,
                    extra_headers={"Range": f"bytes={start}-{end}"},
                    retry=2,
                    timeout=600,
                )
            if callback:
                callback()
            logging.debug(f"part [{start}, {end}] of {item} is downloaded")
            return data, (start, end)
        except Exception as e:
            raise HabitatException(
                f"Failed to download part {start}:{end} of object {item}"
            ) from e

    async def _download_entire(self, target_dir: str, url: str):
        """
        if client can not get content-length field by sending a HEAD request,
        just download the file straight away without setting up a progress bar.
        """
        resp, _, data = await self.download_client.async_request("GET", url)
        if server_error(resp.status_code) or client_error(resp.status_code):
            raise HabitatException(
                f"got a status code {resp.status_code} when downloading {url}"
            )
        if success(resp.status_code):
            pass

        with open(target_dir, "wb") as f:
            f.write(data)

    async def _send_head_request(self, item: str):
        # check if server supports Content-Length and Accept-Ranges
        resp, headers, _ = await self.download_client.async_request(
            "HEAD", self.path_url, suppress=True
        )
        if not success(resp.status_code):
            return {}
        return headers

    def _update_download_url(self, url):
        r = urlsplit(url)
        self.base_url = "".join([r.scheme, "://", r.netloc])
        self.path_url = r.path
        self.url = url
        # To be adapted with legacy test.
        self.component.url = url

    async def fetch(self, root_dir, options):
        component = self.component
        target_dir = component.target_dir

        if options.disable_cache:
            CacheMixin.cache_dir = None
        elif options.cache_dir:
            CacheMixin.cache_dir = os.path.join(options.cache_dir, "objects")

        await self.download(component.name, root_dir, options.force)
        return [target_dir]

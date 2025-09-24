import asyncio
import logging
import os
from urllib.parse import urlparse

import asyncio_atexit
import httpx

from core.common.http_status import client_error, server_error
from core.exceptions import HabitatException
from core.settings import SSL_VERIFY

MAX_CONCURRENCY = int(os.environ.get("HABITAT_CONCURRENCY", 50))


class HttpxClient:
    def __init__(self, base_url=None, headers=None):
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

        if not SSL_VERIFY:
            logging.warning("disable ssl/tls verify for http client")
        self._client = httpx.AsyncClient(follow_redirects=True, verify=SSL_VERIFY)
        parsed_url = urlparse(base_url)
        self._base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        self._headers = headers or {}
        asyncio_atexit.register(self._client.aclose)

    async def async_request(
        self, method: str, path: str, timeout=20, extra_headers=None, **kwargs
    ):
        suppress = kwargs.get("suppress", False)
        url = f'{self._base_url}{"" if path.startswith("/") else "/"}{path}'
        logging.debug(f"{self._base_url=}, {url=}")
        async with self._semaphore:
            resp = await self._client.request(
                method,
                url,
                headers={**self._headers, **(extra_headers or {})},
                timeout=timeout,
            )
            if server_error(resp.status_code) or client_error(resp.status_code):
                if not suppress:
                    raise HabitatException(
                        f"request got a status code {resp.status_code}"
                    )
                else:
                    return resp, resp.headers, None

            return resp, resp.headers, resp.content

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
import pytest

from core.common.httpx_client import HttpxClient, DEFAULT_RETRIES, DEFAULT_BACKOFF_BASE
from core.exceptions import HabitatException


def _make_response(status_code, content=b"ok"):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.headers = {"Content-Type": "text/plain"}
    resp.content = content
    return resp


@pytest.fixture
def client():
    with patch("core.common.httpx_client.asyncio_atexit"):
        c = HttpxClient(base_url="http://example.com")
    return c


class TestRetryOnServerError:
    def test_retry_succeeds_after_server_errors(self, client):
        """Server errors should be retried, and succeed when a 200 eventually comes."""
        responses = [_make_response(500), _make_response(502), _make_response(200)]
        client._client.request = AsyncMock(side_effect=responses)

        with patch("core.common.httpx_client.asyncio.sleep", new_callable=AsyncMock):
            resp, headers, content = asyncio.get_event_loop().run_until_complete(
                client.async_request("GET", "/test")
            )
        assert resp.status_code == 200
        assert content == b"ok"
        assert client._client.request.call_count == 3

    def test_retry_exhausted_raises_on_server_error(self, client):
        """After all retries exhausted on server errors, should raise HabitatException."""
        responses = [_make_response(500)] * (DEFAULT_RETRIES + 1)
        client._client.request = AsyncMock(side_effect=responses)

        with patch("core.common.httpx_client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(HabitatException, match="status code 500"):
                asyncio.get_event_loop().run_until_complete(
                    client.async_request("GET", "/test")
                )
        assert client._client.request.call_count == DEFAULT_RETRIES + 1

    def test_retry_exhausted_suppress_returns_none_content(self, client):
        """With suppress=True, exhausted retries on server error return (resp, headers, None)."""
        responses = [_make_response(503)] * (DEFAULT_RETRIES + 1)
        client._client.request = AsyncMock(side_effect=responses)

        with patch("core.common.httpx_client.asyncio.sleep", new_callable=AsyncMock):
            resp, headers, content = asyncio.get_event_loop().run_until_complete(
                client.async_request("GET", "/test", suppress=True)
            )
        assert resp.status_code == 503
        assert content is None


class TestNoRetryOnClientError:
    def test_client_error_not_retried(self, client):
        """Client errors (4xx) should NOT be retried."""
        client._client.request = AsyncMock(return_value=_make_response(404))

        with pytest.raises(HabitatException, match="status code 404"):
            asyncio.get_event_loop().run_until_complete(
                client.async_request("GET", "/test")
            )
        assert client._client.request.call_count == 1

    def test_client_error_suppress(self, client):
        """Client errors with suppress=True return (resp, headers, None) without retry."""
        client._client.request = AsyncMock(return_value=_make_response(400))

        resp, headers, content = asyncio.get_event_loop().run_until_complete(
            client.async_request("GET", "/test", suppress=True)
        )
        assert resp.status_code == 400
        assert content is None
        assert client._client.request.call_count == 1


class TestRetryOnNetworkError:
    def test_network_error_retried_then_succeeds(self, client):
        """Network exceptions should be retried, succeeding when resolved."""
        client._client.request = AsyncMock(
            side_effect=[httpx.ConnectError("conn refused"), _make_response(200)]
        )

        with patch("core.common.httpx_client.asyncio.sleep", new_callable=AsyncMock):
            resp, headers, content = asyncio.get_event_loop().run_until_complete(
                client.async_request("GET", "/test")
            )
        assert resp.status_code == 200
        assert client._client.request.call_count == 2

    def test_network_error_exhausted_raises(self, client):
        """After all retries on network errors, the original exception is raised."""
        client._client.request = AsyncMock(
            side_effect=httpx.ConnectError("conn refused")
        )

        with patch("core.common.httpx_client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(httpx.ConnectError):
                asyncio.get_event_loop().run_until_complete(
                    client.async_request("GET", "/test")
                )
        assert client._client.request.call_count == DEFAULT_RETRIES + 1


class TestExponentialBackoff:
    def test_backoff_delays_are_exponential(self, client):
        """Verify that sleep delays follow exponential backoff pattern."""
        responses = [_make_response(500), _make_response(500), _make_response(500), _make_response(200)]
        client._client.request = AsyncMock(side_effect=responses)

        with patch("core.common.httpx_client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            asyncio.get_event_loop().run_until_complete(
                client.async_request("GET", "/test")
            )

        expected_delays = [DEFAULT_BACKOFF_BASE * (2 ** i) for i in range(3)]
        actual_delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert actual_delays == expected_delays


class TestCustomRetryCount:
    def test_custom_retry_count(self, client):
        """The retry kwarg should override the default retry count."""
        responses = [_make_response(500)] * 2
        client._client.request = AsyncMock(side_effect=responses)

        with patch("core.common.httpx_client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(HabitatException):
                asyncio.get_event_loop().run_until_complete(
                    client.async_request("GET", "/test", retry=1)
                )
        assert client._client.request.call_count == 2

    def test_zero_retries_no_retry(self, client):
        """With retry=0, no retries should happen."""
        client._client.request = AsyncMock(return_value=_make_response(500))

        with pytest.raises(HabitatException):
            asyncio.get_event_loop().run_until_complete(
                client.async_request("GET", "/test", retry=0)
            )
        assert client._client.request.call_count == 1


class TestSuccessfulRequest:
    def test_successful_request_no_retry(self, client):
        """A successful request should return immediately without retries."""
        client._client.request = AsyncMock(return_value=_make_response(200, b"hello"))

        resp, headers, content = asyncio.get_event_loop().run_until_complete(
            client.async_request("GET", "/test")
        )
        assert resp.status_code == 200
        assert content == b"hello"
        assert client._client.request.call_count == 1

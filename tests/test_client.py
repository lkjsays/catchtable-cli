import unittest

import httpx

from catchtable_cli.client import CatchTableAPIError, CatchTableClient
from catchtable_cli.config import CatchTableConfig
from catchtable_cli.requests import autocomplete_request


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = CatchTableClient(
            CatchTableConfig(use_curl_cffi=False, session_cookie="", use_keychain=False)
        )
        self.addAsyncCleanup(self.client.close)
        await self.client._httpx_client.aclose()

    def transport(self, handler):
        self.client._httpx_client = httpx.AsyncClient(
            base_url="https://example.test", transport=httpx.MockTransport(handler)
        )

    async def test_body_and_query_reach_http_transport(self):
        def handle(request):
            self.assertEqual(request.url.params["test"], "1")
            self.assertEqual(request.content, b'{"query":"test","extra":true}')
            return httpx.Response(200, json={"data": {"suggestions": []}})

        self.transport(handle)
        result = await autocomplete_request(
            {"query": "test", "extra": True}, {"test": "1"}
        ).send(self.client)
        self.assertEqual(result, {"data": {"suggestions": []}})

    async def test_http_error_is_not_success(self):
        self.transport(lambda request: httpx.Response(401, json={"message": "auth"}))
        with self.assertRaises(httpx.HTTPStatusError):
            await self.client.autocomplete("test")

    async def test_api_error_is_not_success(self):
        self.transport(
            lambda request: httpx.Response(
                200, json={"isSuccess": False, "resultCode": "AUTH"}
            )
        )
        with self.assertRaises(CatchTableAPIError):
            await self.client.autocomplete("test")

    async def test_non_object_response_is_error(self):
        self.transport(lambda request: httpx.Response(200, json=[]))
        with self.assertRaises(RuntimeError):
            await self.client.autocomplete("test")

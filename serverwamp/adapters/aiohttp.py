import asyncio
import re
from abc import ABCMeta
from io import BytesIO
from typing import Optional, Mapping

import aiohttp
import msgpack
from aiohttp import WSMsgType, web

from serverwamp.connection import Connection
from serverwamp.json import (deserialize as deserialize_json,
                             serialize as serialize_json)

get_event_loop = getattr(asyncio, 'get_running_loop', asyncio.get_event_loop)

SUPPORTED_WS_PROTOCOLS = (
    'wamp.2.msgpack',
    'wamp.2.msgpack.batched',
    'wamp.2.json',
    'wamp.2.json.batched',
)
JSON_SPLIT_CHAR = '\x1e'


match_jsons_in_batch = re.compile(f'(.+?)(?:{JSON_SPLIT_CHAR}|$)').finditer


def generate_jsons_from_batch(batch: str):
    for match in match_jsons_in_batch(batch):
        yield match[1]


def collect_jsons_from_batch(batch: str):
    return batch.split(JSON_SPLIT_CHAR)


def connection_for_aiohttp_request(request: aiohttp.web.Request):
    ws = web.WebSocketResponse(protocols=SUPPORTED_WS_PROTOCOLS)
    await ws.prepare(request)
    cookies = request.cookies

    construct_connection = ws_protocol_connection_classes[ws.ws_protocol]
    connection = construct_connection(ws, cookies)
    return connection


class AiohttpWebSocketConnection(Connection, metaclass=ABCMeta):
    def __init__(
        self,
        ws: aiohttp.web.WebSocketResponse,
        cookies: Optional[Mapping[str, str]],
        compress_outbound=False
    ):
        super().__init__()
        self._compress_outbound = compress_outbound
        self._ws = ws

        self.transport_info['http_cookies'] = cookies

    async def close(self):
        await self._ws.close()


class AiohttpJSONWebSocketConnection(AiohttpWebSocketConnection):
    async def iterate_msgs(self):
        async for ws_msg in self._ws:
            if ws_msg.type == WSMsgType.TEXT:
                yield deserialize_json(ws_msg.data)

    async def send_msg(self, msg):
        await self._ws.send_json(
            msg,
            compress=self._compress_outbound
        )


class AiohttpBatchedJSONWebSocketConnection(AiohttpWebSocketConnection):
    async def iterate_msgs(self):
        async for ws_msg in self._ws:
            if ws_msg.type == WSMsgType.TEXT:
                for msg in generate_jsons_from_batch(ws_msg.data):
                    yield msg

    async def send_msg(self, msg):
        await self._ws.send_str(
            serialize_json(msg) + JSON_SPLIT_CHAR,
            compress=self._compress_outbound
        )

    async def send_msgs(self, msgs):
        await self._ws.send_str(
            JSON_SPLIT_CHAR.join(
                [serialize_json(msg) for msg in msgs] + [JSON_SPLIT_CHAR]
            ),
            compress=self._compress_outbound
        )


class AiohttpMsgPackWebSocketConnection(AiohttpWebSocketConnection):
    async def iterate_msgs(self):
        async for ws_msg in self._ws:
            if ws_msg.type == WSMsgType.BINARY:
                yield msgpack.unpackb(ws_msg.data, use_list=False)

    async def send_msg(self, msg):
        msg_bytes = msgpack.packb(msg)
        await self._ws.send_bytes(
            msg_bytes,
            compress=self._compress_outbound
        )


class AiohttpBatchedMsgPackWebSocketConnection(AiohttpWebSocketConnection):
    async def iterate_msgs(self):
        async for ws_msg in self._ws:
            if not ws_msg.type == WSMsgType.BINARY:
                continue

            with BytesIO(ws_msg.data) as msg_io:
                unpacker = msgpack.Unpacker(
                    msg_io,
                    use_list=False
                )
                for msg in unpacker:
                    yield msg

    async def send_msg(self, msg):
        msg_bytes = msgpack.packb(msg)
        await self._ws.send_bytes(
            msg_bytes,
            compress=self._compress_outbound
        )

    async def send_msgs(self, msgs):
        batch_bytes = bytearray()
        for msg in msgs:
            batch_bytes += msgpack.packb(msg)
        await self._ws.send_bytes(
            batch_bytes,
            compress=self._compress_outbound
        )


ws_protocol_connection_classes = {
    'wamp.2.msgpack': AiohttpMsgPackWebSocketConnection,
    'wamp.2.msgpack.batched': AiohttpBatchedMsgPackWebSocketConnection,
    'wamp.2.json': AiohttpJSONWebSocketConnection,
    'wamp.2.json.batched': AiohttpBatchedJSONWebSocketConnection
}

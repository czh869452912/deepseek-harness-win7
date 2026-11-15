"""Candidate Peer-aware RPC Fetch adapter and binary response carrier."""
import uuid
from types import SimpleNamespace

from dsh.cordis.json_text import stringify_json
from dsh.host.connection.rpc_host import response, rpc_fetch
from dsh.typert.rpc_result import json_projection


def full_response(rpc_id, result):
    attachments = result.get('attachments') if result['ok'] else None
    success = {key: value for key, value in result.items() if key != 'attachments'} if result['ok'] else result
    body = dict(type='server-response', rpcId=rpc_id, result=success)
    if not attachments:
        return response(200, stringify_json(json_projection(body)), {'content-type': 'application/json'})
    boundary = '----dsh-' + uuid.uuid4().hex
    chunks, metadata = [], []
    for index, attachment in enumerate(attachments):
        part = 'bytes-{}'.format(index)
        chunks.append(('--' + boundary + '\r\nContent-Disposition: form-data; name="' + part + '"; filename="blob"\r\nContent-Type: application/octet-stream\r\n\r\n').encode('ascii'))
        chunks.extend((bytes(attachment['bytes']), b'\r\n'))
        metadata.append(dict(path=list(attachment['path']), codec='bytes', part=part))
    body['attachments'] = metadata
    chunks.append(('--' + boundary + '\r\nContent-Disposition: form-data; name="metadata"\r\n\r\n').encode('ascii'))
    chunks.append(stringify_json(json_projection(body)).encode('utf-8'))
    chunks.append(('\r\n--' + boundary + '--\r\n').encode('ascii'))
    return response(200, b''.join(chunks), {'content-type': 'multipart/form-data; boundary=' + boundary})


def rpc_fetch_handler(channel, handler):
    async def fetch(request, peer):
        def invoke(endpoint, payload, signal):
            return handler(endpoint, payload, signal, peer)
        return await rpc_fetch(channel, invoke, request, 'gateway/bad-request',
                               lambda error: getattr(error, 'name', 'Error') + ': ' + str(error),
                               True, respond=full_response)
    return SimpleNamespace(requestBodyMode=lambda _: 'buffered', fetch=fetch)

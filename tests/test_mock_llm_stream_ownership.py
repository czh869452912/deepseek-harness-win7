import http.client
import importlib
import threading
from urllib.parse import urlparse

import pytest


@pytest.mark.parametrize('behavior', ('slow_success', 'partial_disconnect'))
def test_mock_closed_stream_does_not_read_another_request(monkeypatch, behavior):
    fixture = importlib.import_module('tests.1to1._support.llm_mock_server')
    original_handle = fixture._MockLlmHandler.handle_one_request
    original_finish = fixture._MockLlmHandler.finish
    reads = []
    finished = threading.Event()

    def handle(handler):
        reads.append(handler)
        return original_handle(handler)

    def finish(handler):
        try:
            return original_finish(handler)
        finally:
            finished.set()

    monkeypatch.setattr(fixture._MockLlmHandler, 'handle_one_request', handle)
    monkeypatch.setattr(fixture._MockLlmHandler, 'finish', finish)
    server = fixture.start_mock_llm_server(sequence=[behavior], chunkDelayMs=100,
        disconnectDelayMs=100, chunkSize=1)
    parsed = urlparse(server.baseURL)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
    response = None
    try:
        connection.request('POST', '/v1/chat/completions', body=b'{"model":"mock"}',
            headers={'content-type': 'application/json'})
        response = connection.getresponse()
        response.close()
        connection.close()
        assert finished.wait(5)
        assert len(server.requests) == 1
        assert server.requests[0].outcome == 'client_closed'
        assert len(reads) == 1
    finally:
        if response is not None:
            response.close()
        connection.close()
        server.close()()


def test_mock_completed_stream_keeps_connection_reusable():
    fixture = importlib.import_module('tests.1to1._support.llm_mock_server')
    server = fixture.start_mock_llm_server(sequence=['success', 'success'])
    parsed = urlparse(server.baseURL)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
    try:
        for expected_count in (1, 2):
            connection.request('POST', '/v1/chat/completions', body=b'{"model":"mock"}',
                headers={'content-type': 'application/json'})
            response = connection.getresponse()
            assert response.status == 200
            assert b'[DONE]' in response.read()
            response.close()
            assert len(server.requests) == expected_count
        assert [record.outcome for record in server.requests] == ['completed', 'completed']
    finally:
        connection.close()
        server.close()()



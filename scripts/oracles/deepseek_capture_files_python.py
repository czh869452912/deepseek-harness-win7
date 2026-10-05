"""Observe product Files API over real loopback HTTP, including multipart fields."""
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

from dsh.llm.deepseek_files import DeepSeekFilesClient, is_files_quota_error


def observe_files(fixture):
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self):
            request = dict(method=self.command, path=self.path, authorization=self.headers.get('Authorization'))
            if self.command == 'POST':
                data = self.rfile.read(int(self.headers['Content-Length']))
                message = BytesParser(policy=policy.default).parsebytes(
                    ('Content-Type: ' + self.headers['Content-Type'] + '\r\n\r\n').encode() + data)
                request['form'] = {}
                for part in message.iter_parts():
                    name = part.get_param('name', header='content-disposition')
                    body = part.get_payload(decode=True)
                    request['form'][name] = (dict(filename=part.get_filename(), mediaType=part.get_content_type(), bytes=list(body))
                                             if part.get_filename() else body.decode('utf-8'))
            requests.append(request)
            data = json.dumps(fixture['response']).encode('utf-8')
            self.send_response(fixture.get('status', 200))
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        do_POST = do_GET = do_DELETE = respond

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    result = dict(originPort=server.server_port, requests=requests)
    client = DeepSeekFilesClient('http://127.0.0.1:{}'.format(server.server_port), 'fixture-key')
    result['origin'] = dict(host=server.server_address[0], port=server.server_port, baseURL=client.base_url)
    try:
        operation = fixture['operation']
        if operation == 'upload':
            value = client.upload(bytes([1, 2, 3]), 'image/png', 'fixture.png', fixture.get('expiry', 3600))
        elif operation == 'list':
            value = client.list(**fixture.get('options', {}))
        else:
            value = getattr(client, operation)(fixture['fileId'])
        result['value'] = value
    except Exception as error:
        result['error'] = dict(code=getattr(error, 'code', type(error).__name__), name=getattr(error, 'name', type(error).__name__), message=getattr(error, 'message', str(error)), quota=is_files_quota_error(error))
        if getattr(error, 'failure', None) is not None:
            result['error']['failure'] = error.failure
        if getattr(error, 'status', None) is not None:
            result['error']['status'] = error.status
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
    return result

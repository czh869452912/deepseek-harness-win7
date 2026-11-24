import asyncio
import os
import sys

from dsh.host.desktop import process


class FixtureRuntime:
    def __init__(self):
        self.closed_bodies = 0

    async def fetch(self, request):
        if request['url'].endswith('/closed'):
            return dict(status=200, body=str(self.closed_bodies))
        if not request['url'].endswith('/large'):
            return dict(status=200, body=b'ok')

        async def body():
            try:
                for _ in range(64):
                    yield b'x' * 65536
            finally:
                self.closed_bodies += 1

        return dict(status=200, body=body())

    async def close(self):
        pass


async def fixture_runtime(_profile):
    return FixtureRuntime()


if 'legacy' in sys.argv:
    os.environ.pop('DSH_DESKTOP_RESPONSE_CREDIT', None)
process.run_desktop_host = fixture_runtime
output = sys.stdout.buffer
sys.stdout = sys.stderr
asyncio.run(process.serve('.', output))

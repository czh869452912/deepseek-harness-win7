"""Mount the registered service and exercise both independently owned HTTP channels."""
import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_otel_wire_probe import cases as wire_cases


def cases():
    return [dict(mode=mode) for mode in ['mount-only','normal','provider-unmounted','invalid-session','invalid-event']]


def prepare(output):
    path=output/'inputs.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


async def observe():
    from dsh.cordis.context import Context
    from dsh.boot.plugin_registry import resolve_harness_plugin
    rows=[]
    for entry in cases():
        captures=[];warnings=[];channels=[];ctx=Context();error=None
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_POST(self):
                data=self.rfile.read(int(self.headers['content-length']))
                captures.append(dict(path=self.path,document=json.loads(data),bytes=len(data)))
                self.send_response(200);self.send_header('Content-Length','2');self.end_headers();self.wfile.write(b'{}')
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
        thread=threading.Thread(target=server.serve_forever,kwargs=dict(poll_interval=.01));thread.start()
        try:
            fiber=ctx.plugin(resolve_harness_plugin('@deepseek-ai/dsh-otel'));await fiber
            service=ctx.get('otel');mounted=service is not None
            def options(label):
                return dict(scope=dict(name=label,version='1'),resourceAttributes={'service.name':label},
                    exporter=dict(url='http://127.0.0.1:'+str(server.server_port)+'/'+label),
                    processor=dict(maxExportBatchSize=512,scheduledDelayMillis=2147483647),
                    onFailure=lambda message,failure=None:warnings.append(dict(message=message,error=None if failure is None else str(failure))))
            if entry['mode'].startswith('invalid'):
                selected=options('invalid');selected['maxRequestBytes']=0;selected['exporter']['timeoutMillis']=0
                try:
                    if entry['mode']=='invalid-session':service.createSessionLogReporter(selected)
                    else:service.createEventReporter(selected)
                except Exception as failure:error=str(failure)
            elif entry['mode']!='mount-only':
                for label in ['event-a','event-b','session-a','session-b']:
                    channel=service.createEventReporter(options(label)) if label.startswith('event') else service.createSessionLogReporter(options(label))
                    if label.startswith('event'):channel.clock=lambda:1700000000999
                    channels.append(channel)
                if entry['mode']=='provider-unmounted':await fiber.dispose()
                records=wire_cases()
                def emit(index):
                    if index<2:channels[index].emit(records[1]['records'][0])
                    else:channels[index].reportSessionLog(records[0]['records'][0])
                for index in range(4):emit(index)
                await channels[0].shutdown();await channels[2].shutdown()
                for index in range(4):emit(index)
                await channels[1].shutdown();await channels[3].shutdown()
            await fiber.dispose()
            rows.append(dict(mounted=mounted,after=ctx.get('otel',False) is not None,
                captures=sorted(captures,key=lambda item:item['path']),warnings=warnings,error=error))
        finally:
            for channel in channels:await channel.shutdown()
            await ctx.fiber.dispose()
            await asyncio.get_running_loop().run_in_executor(None,server.shutdown);server.server_close();thread.join()
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_otel_service.mts','Actual mounted Cordis otel service and both Native end-to-end HTTP channel factories; independent shutdown and consumer ownership after service removal.',
        [Path(__file__).resolve(),ROOT/'dsh/session/otel_service_current.py',ROOT/'dsh/session/otel_event_channel_current.py',
         ROOT/'dsh/boot/plugin_registry_current.py',ROOT/'packages/telemetry/otel/package.json'],prepare=prepare)

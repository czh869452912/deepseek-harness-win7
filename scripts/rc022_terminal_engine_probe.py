"""Original xterm on Node and on the shipped Win7 QuickJS worker."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    return [
        [('write','$ make\r\nprogress 10%\rprogress 100%\r\n0123456789012345678901234\r\n终端输出\r\n$ ')],
        [('write','normal history\r\n$ '),('mark','normal'),('write','\x1b[?1049h\x1b[Hfull screen app'),('mark','alternate'),('write','\r\nnext'),('write','\x1b[?1049l')],
        [('write','done\r\n$ 0123456789abcdefghij'),('mark','wrapped'),('write',' More output\r\nnew line'),('resize',5,4),('resize',20,6)],
        [('write','zero\r\n$ '),('mark','old'),('write','\r\n'.join(str(index) for index in range(30))+'\r\nend')],
        [('write','prefix\x1b['),('write','31mRED\x1b[0m\r\nline'),('write','\x1b[1A\r\x1b[2Krewritten')],
        [('write','👩🏽\u200d💻🇨🇳a\u0301क्ष\r\nsecond'),('mark','unicode'),('write','\x1b[2J\x1b[Hcleared'),('resize',30,2)],
        [('write','one\r\n\r\n'),('mark','empty-tail'),('write','\x1b[3;1Htail\x1b[2;1Hmiddle')],
        [('write','\x1b[1;32mgreen\x1b[0m\x1b[4munder\x1b[24m\r\n\x1b[38;2;255;120;30mrgb\x1b[0m')],
    ]


async def observe():
    from dsh.cordis import Context
    from dsh.javascript.runtime import JavaScriptRuntime
    from dsh.terminal.screen_runtime import TerminalScreenRuntime
    ctx=Context();rows=[]
    try:
        await ctx.plugin(JavaScriptRuntime);await ctx.plugin(TerminalScreenRuntime)
        for index,actions in enumerate(cases()):
            screen=await ctx.terminalScreens.open(dict(cols=10,rows=4,scrollback=6));marks={}
            try:
                for step,action in enumerate(actions):
                    if action[0]=='write':await screen.write(action[1])
                    elif action[0]=='resize':await screen.resize(action[1],action[2])
                    elif action[0]=='mark':marks[action[1]]=screen.mark();await screen.drain()
                    rows.append(dict(case=index,step=step,snapshot=await screen.snapshot(),
                        page=screen.read(dict(offset=0,count=100,maxBytes=10000)),
                        small=screen.read(dict(offset=1,count=2,maxBytes=7)),
                        marks={name:mark.lines() for name,mark in marks.items()}))
            finally:await screen.dispose()
        rows.append(dict(name='disposed',engines=len(ctx.terminalScreens.engines),workers=len(ctx.jsRuntime._workers)))
        return rows
    finally:await ctx.fiber.dispose()


def prepare(output):
    path=output/'cases.json';path.write_text(json.dumps(cases(),ensure_ascii=True),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_terminal_engine.mts','Actual unchanged xterm headless/serialize dependencies run on Node24 versus the shipped Win7 QuickJS worker. Ordered writes, split escape parsing, cursor rewrite, ANSI serialization, Unicode, normal/alternate buffers, markers, trimming and resize/reflow compare snapshots, pages and marked lines after each operation. Existing Python JS runtime owns creation and disposal; no PTY/BrowserTerminal/controller acceptance.',
        [Path(__file__).resolve()]+[ROOT/path for path in ('dsh/terminal/screen_runtime.py','dsh/javascript/terminal-screen/manifest.json','dsh/javascript/terminal-screen/driver.js','dsh/javascript/terminal-screen/headless.js','dsh/javascript/terminal-screen/serialize.js')],prepare=prepare)

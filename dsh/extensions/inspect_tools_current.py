"""Current upstream read-only tools; Native creative lifecycle remains separate."""
import json
from pathlib import Path

from dsh.cordis.plugin import Plugin
from dsh.cordis.json_text import stringify_json
from dsh.core.session.json import UNDEFINED

DEFINITIONS=json.loads((Path(__file__).resolve().parents[1]/'resources/cordis_inspect_tools_022.json').read_text(encoding='utf-8'))


def _field(value,key,default=None):
    return value.get(key,default) if isinstance(value,dict) else getattr(value,key,default)


def _render(_args,value):
    text=json.dumps(json.loads(stringify_json(value)),ensure_ascii=False,indent=2)
    return [dict(type='text',text=text.encode('utf-8','backslashreplace').decode('utf-8'))]


class CurrentCordisInspectTools(Plugin):
    name='tool-cordis'
    inject=['tools','cordisInspect']

    def apply(self,ctx):
        async def listing(*_):
            return dict(providers=ctx.cordisInspect.list())

        async def query(args,execution):
            agent=_field(execution,'agent')
            if agent is None:
                raise ValueError('Cordis inspection requires an Agent-backed session')
            value=await ctx.cordisInspect.query(args['platform'],args['provider'],args['method'],
                args.get('input',UNDEFINED),agent,_field(execution,'signal'))
            return dict(platform=args['platform'],provider=args['provider'],method=args['method'],data=value)

        def present(args):
            return dict(card='generic',kind='read',title='Query Cordis '+args['platform']+' '+args['provider']+'.'+args['method'])

        for definition in DEFINITIONS:
            directory=definition['name']=='cordis_inspect_list'
            ctx.tools.register(dict(name=definition['name'],description=definition['description'],
                parameters=definition['parameters'],output=dict(schema=definition['outputSchema'],render=_render),
                execute=listing if directory else query,isConcurrencySafe=lambda *_:True,
                presentCall=(lambda *_:dict(card='generic',kind='read',title='List Cordis Inspect Providers')) if directory else present))

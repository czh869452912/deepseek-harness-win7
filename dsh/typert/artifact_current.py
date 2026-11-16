"""Restricted reader for current generated lazy Remote schema declarations.

No JavaScript is evaluated. Only the generator's memoized schema factories,
Remote definition assembly and invocations getter are accepted.
"""
import ast
import copy
import math
import re

from dsh.typert.artifact import ArtifactParser, Schema, TOKEN, UNDEFINED
from dsh.typert.artifact_binary import remove_program, is_bytes, encode_selected_data

CURRENT_TOKEN = re.compile(TOKEN.pattern.replace('|=>|', '|\\?\\?=|=>|'))


def json_value(value, active=None):
    if value is None or type(value) in (str, bool):return value
    if type(value) in (int, float) and math.isfinite(value):return value
    if not isinstance(value,(dict,list)):raise ValueError('typert: value is not JSON')
    active = set() if active is None else active
    if id(value) in active:raise ValueError('typert: cyclic JSON value')
    active.add(id(value))
    try:
        if isinstance(value, list):return [json_value(item, active) for item in value]
        if any(type(key) is not str for key in value):raise ValueError('typert: JSON keys must be strings')
        return {key:json_value(item, active) for key,item in value.items()}
    finally:active.remove(id(value))


class CurrentSchema(Schema):
    def parse(self, value):
        if self.kind == 'bytes':
            if not is_bytes(value):raise ValueError('typert: value is not Uint8Array')
            return value
        if self.kind == 'describe':return self.args[0].parse(value)
        if self.kind == 'json':return json_value(value)
        if self.kind == 'strictObject':
            if not isinstance(value, dict) or set(value)-set(self.args[0]):
                raise ValueError('typert: strict object has unknown fields')
            return Schema('object', self.args, self.bindings).parse(value)
        if self.kind == 'factory':return self.bindings[self.args[0]]().parse(value)
        if self.kind == 'current-lazy':return self.args[0].parse(value)
        return super().parse(value)


class SchemaFactory:
    def __init__(self, schema):self.schema = schema
    def __call__(self):return self.schema


class CodecSchema:
    def __init__(self, factory, codec):
        self.factory = factory
        self.projection = copy.deepcopy(codec['jsonSchema']) if 'jsonSchema' in codec else UNDEFINED
        self.error = codec.get('jsonSchemaError')
    def parse(self, value):return self.factory().parse(value)
    def to_json_schema(self, params=None):
        if self.projection is UNDEFINED or self.error is not None:
            raise ValueError(self.error or 'typert: generated codec has no JSON Schema')
        return copy.deepcopy(self.projection)


class RemoteInfo:
    def __init__(self, spec):
        if not isinstance(spec, dict) or set(spec)!={'package','methods'} or not isinstance(spec['methods'],dict):
            raise ValueError('typert: invalid generated Remote definition')
        self.descriptors = []
        def codecs(value):
            if isinstance(value,list):return [codecs(item) for item in value]
            if not isinstance(value,dict):return value
            result={key:codecs(item) for key,item in value.items()}
            if result.get('mode')=='strict':
                factory=result.get('create')
                if not isinstance(factory,SchemaFactory):raise ValueError('typert: codec requires a declared schema factory')
                result['schema']=CodecSchema(factory,result)
            return result
        for endpoint, definition in spec['methods'].items():
            if not isinstance(endpoint,str) or endpoint.count('/')!=1 or not all(endpoint.split('/')):
                raise ValueError('typert: invalid generated Remote endpoint')
            namespace,method=endpoint.split('/')
            row=codecs(definition)
            result=row.get('result',{})
            if isinstance(result.get('description'),str) and isinstance(result.get('jsonSchema'),dict):
                result['jsonSchema']=dict(result['jsonSchema'],description=result['description'])
                result['schema'].projection=copy.deepcopy(result['jsonSchema'])
            row.update(id=spec['package']+'#'+endpoint,namespace=namespace,method=method)
            row['parameters']=[dict(parameter,wire=parameter.get('wire',parameter['name'])) for parameter in row['parameters']]
            self.descriptors.append(row)


class CurrentArtifactParser(ArtifactParser):
    def __init__(self, source):
        source,self.byte_program=remove_program(source)
        self.tokens,self.position,self.bindings,self.caches,self.references=[],0,{},set(),set()
        cursor=0
        for match in CURRENT_TOKEN.finditer(source):
            if match.start()!=cursor:raise ValueError('typert: unsupported current artifact syntax at offset '+str(cursor))
            cursor=match.end();token=match.group()
            if not token.isspace() and not token.startswith(('/*','//')):self.tokens.append(token)
        if cursor!=len(source):raise ValueError('typert: unsupported current artifact suffix')

    def parse(self):
        for token in ('import','{','z','}','from'):self.take(token)
        if ast.literal_eval(self.take())!='zod':raise ValueError('typert: generated schema artifact must import zod')
        if self.peek()==';':self.take()
        for token in ('import','{','createTypertRemoteInfo','}','from'):self.take(token)
        if ast.literal_eval(self.take())!='@deepseek-ai/dsh-typert-protocol/remote-info':
            raise ValueError('typert: invalid generated Remote import')
        if self.peek()==';':self.take()
        exported=None
        while self.peek() is not None:
            public=self.peek()=='export'
            if public:self.take()
            declaration=self.take()
            if declaration=='let' and not public:
                name=self.take()
                if not re.fullmatch(r'[A-Za-z_$][\w$]*\$schema\d*\$value',name) or name in self.caches:
                    raise ValueError('typert: invalid schema cache declaration')
                self.caches.add(name)
                if self.peek()==';':self.take()
                continue
            if declaration!='const':raise ValueError('typert: only generated declarations are supported')
            name=self.take();self.take('=')
            if self.peek()=='(':
                for token in ('(',')','=>','('):self.take(token)
                cache=self.take()
                if cache!=name+'$value' or cache not in self.caches:raise ValueError('typert: schema factory cache differs')
                self.take('??=');schema=self.expression();self.take(')')
                if not isinstance(schema,Schema):raise ValueError('typert: schema factory must return a supported schema')
                value=SchemaFactory(schema)
            else:value=self.expression()
            if name in self.bindings:raise ValueError('typert: duplicate artifact binding: '+name)
            self.bindings[name]=value
            if public:
                if name!='TYPERT' or exported is not None:raise ValueError('typert: unsupported generated export: '+name)
                exported=value
            if self.peek()==';':self.take()
        if exported is None:raise ValueError('typert: artifact has no TYPERT export')
        if any(not isinstance(self.bindings.get(name),SchemaFactory) for name in self.references):
            raise ValueError('typert: unbound generated schema factory')
        return exported

    def expression(self):
        token=self.peek()
        if token=='value' and self.tokens[self.position+1:self.position+2]==['=>']:
            self.take('value');self.take('=>');factory=self.bindings.get(self.take())
            for part in ('(',')','.','parse','(','value',')'):self.take(part)
            if not self.byte_program or not isinstance(factory,SchemaFactory):
                raise ValueError('typert: unsupported generated result decoder')
            return factory().parse
        if token=='(':
            for part in ('(','value',',','writeBytes',')','=>','$encode0','(','value',',','writeBytes',',','[',']',',','new','Map','(',')',')'):self.take(part)
            if not self.byte_program:raise ValueError('typert: generated encoder has no qualified program')
            return encode_selected_data
        if token=='createTypertRemoteInfo':
            self.take();self.take('(');spec=self.expression();self.take(',');self.take('z');self.take(')')
            return RemoteInfo(spec)
        if token=='{':
            self.take();value={}
            while self.peek()!='}':
                key=self.take()
                if key=='get' and self.peek()=='invocations':
                    for part in ('invocations','(',')','{','return'):self.take(part)
                    target=self.bindings.get(self.take())
                    if not isinstance(target,RemoteInfo):raise ValueError('typert: invocations getter requires generated Remote info')
                    self.take('.');self.take('descriptors')
                    if self.peek()==';':self.take()
                    self.take('}');key,item='invocations',target.descriptors
                else:
                    key=ast.literal_eval(key) if key.startswith(('\'', '"')) else key
                    self.take(':');item=self.expression()
                if key in value:raise ValueError('typert: duplicate object key')
                value[key]=item
                if self.peek()!=',':break
                self.take()
            self.take('}');return value
        if token=='z':
            self.take();self.take('.');kind=self.take();self.take('(')
            if kind=='instanceof':
                self.take('Uint8Array');args=[];kind='bytes'
                if not self.byte_program:raise ValueError('typert: byte schema has no qualified program')
            elif kind=='lazy':
                for part in ('(',')','=>'):self.take(part)
                args=[self.expression()];kind='current-lazy'
            else:args=self.sequence(')')
            self.take(')')
            if kind not in {'unknown','undefined','void','string','number','boolean','literal','object','strictObject',
                    'array','record','union','intersection','json','never','current-lazy','bytes'}:
                raise ValueError('typert: unsupported current schema constructor: '+kind)
            value=CurrentSchema(kind,args,self.bindings)
        elif token is not None and re.fullmatch(r'[A-Za-z_$][\w$]*\$schema\d*',token) and self.tokens[self.position+1:self.position+2]==['(']:
            self.references.add(token)
            self.take();self.take('(');self.take(')');value=CurrentSchema('factory',[token],self.bindings)
        else:
            # The base parser handles only literal containers/binding reads.
            # Its modifier path is superseded below for current schemas.
            if token is not None and token in self.bindings:
                self.take();value=self.bindings[token]
            else:return super().expression()
        while self.peek()=='.':
            self.take();modifier=self.take();self.take('(')
            if not isinstance(value,Schema):raise ValueError('typert: schema modifier requires a schema')
            if modifier=='describe':
                description=self.expression()
                if not isinstance(description,str):raise ValueError('typert: schema description must be a string')
                value=CurrentSchema('describe',[value,description],self.bindings)
            elif modifier in ('readonly','optional'):value=CurrentSchema(modifier,[value],self.bindings)
            else:raise ValueError('typert: unsupported current artifact method '+modifier)
            self.take(')')
        return value

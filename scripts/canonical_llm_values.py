import hashlib
import json
import math
import re
import uuid


def uuid4(value):
    try:
        parsed=uuid.UUID(value)
        return str(parsed)==value and parsed.version==4 and parsed.variant==uuid.RFC_4122
    except (ValueError,TypeError,AttributeError):
        return False


def canonical(rows, side='native'):
    seen={}
    normalized=[]
    for row in rows:
        aliases={}
        counters={'message':0,'retry':0}
        def register(value,kind):
            valid=uuid4(value) or side=='native' and kind=='message' and isinstance(value,str) and (
                value.startswith('msg-') and uuid4(value[4:]) or re.fullmatch(r'(?:msg|assistant)-[0-9a-f]{8}',value))
            if not valid:
                raise ValueError('Invalid allocated '+kind+' identity')
            if value in seen and seen[value]!=row['name']:
                raise ValueError('Allocated identity shared across fixtures')
            seen[value]=row['name']
            token=(kind,counters[kind])
            if value in aliases:
                if aliases[value][0]!=kind:
                    raise ValueError('Allocated identity shared across kinds')
            else:
                aliases[value]=token
                counters[kind]+=1
        def collect(value):
            if isinstance(value,dict):
                if value.get('role') in ('user','assistant','tool') and 'id' in value:
                    register(value['id'],'message')
                if 'retryId' in value:
                    register(value['retryId'],'retry')
                for key in sorted(value):
                    collect(value[key])
            elif isinstance(value,list):
                for item in value:
                    collect(item)
        if row['group']=='retry':
            collect(row)
        def visit(value):
            if isinstance(value,str):
                return ['identity',*aliases[value]] if value in aliases else ['string',value]
            if isinstance(value,dict):
                return {key:visit(item) for key,item in value.items()}
            if isinstance(value,list):
                return [visit(item) for item in value]
            if type(value) is float:
                if not math.isfinite(value):
                    raise ValueError('Nonfinite observed number')
                return int(value) if value.is_integer() else value
            return value
        normalized.append(visit(row))
    return normalized


def observation_digest(rows, side='native'):
    return hashlib.sha256(json.dumps(canonical(rows, side=side),sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')).hexdigest()



"""Current model-visible job projection and bounded completion notices."""
from dsh.cordis.utils import js_to_string
from dsh.cordis.text import JS_WHITESPACE
from dsh.terminal.grapheme import utf8


def blocks(text):return [dict(type='text',text=text)]


def public_job(job):
    value={key:job[key] for key in ('id','kind','label','status','startedAt','finishedAt') if key in job}
    detail=job.get('progress',job.get('detail'))
    if detail is not None:value['detail']=detail
    return value


def status_line(job):return '[status: '+job['status']+(', '+job['detail'] if 'detail' in job else '')+']'


def render_delta(chunks,lossy,paths):
    visible=[chunk for chunk in chunks if chunk.get('channel')!='log']
    out=''.join(chunk['text'] for chunk in visible if chunk.get('channel')!='stderr')
    err=''.join(chunk['text'] for chunk in visible if chunk.get('channel')=='stderr')
    text=out+(('\n' if out and not out.endswith('\n') else '')+'[stderr]\n'+err if err else '')
    if not lossy and not any(chunk.get('gapBefore') is True for chunk in visible):return text
    return text+('\n' if text and not text.endswith('\n') else '')+'[some output was dropped from memory; full output: '+(', '.join(paths) if paths else '(unavailable)')+']'


def read_body(read):
    text=render_delta(read['chunks'],read['lossy'],read['job']['output'].get('spillPaths',[]))
    if 'result' in read:text+=('\n' if text and not text.endswith('\n') else '')+js_to_string(read['result'])
    return dict(text=text,job=public_job(read['job']))


def retain(text,maximum,head=False):
    data=utf8(text)
    return (data[:maximum] if head else data[-maximum:]).decode('utf-8',errors='ignore') if maximum>0 else ''


def fit(content,suffix,maximum,omitted):
    complete=content+suffix
    if maximum is None or len(utf8(complete))<=maximum:return complete
    fixed=('' if content.endswith(omitted.lstrip()) else omitted)+suffix
    size=len(utf8(fixed))
    return retain(fixed,maximum) if size>=maximum else retain(content,maximum-size)+fixed


def summary(text):
    data=text.encode('utf-16-le','surrogatepass')
    return text if len(data)<=240 else data[:238].decode('utf-16-le','surrogatepass')+'…'


def notice_detail(job):
    label=job['label'].lstrip(JS_WHITESPACE)
    if '\n' in label:label=label.split('\n',1)[0]+'…'
    return ' ('+job['kind']+': '+summary(label)+') finished '+status_line(public_job(job))


def inline_notice(job,output,maximum):
    head='background job '+job['id']+notice_detail(job)
    text=head+('. Output:\n'+(output[:-1] if output.endswith('\n') else output) if output else '. No new output.')
    return text if len(utf8(text))<=min(maximum,job.get('outputLimitBytes',float('inf'))) else None


def completion_notice(job):
    prefix='background job '+job['id'];detail=notice_detail(job);action='\nDone; job_output.'
    complete=prefix+detail+'. Read its output with job_output.';maximum=job.get('outputLimitBytes')
    if maximum is None or len(utf8(complete))<=maximum:return complete
    omitted='\n[notice truncated]';fixed=prefix+omitted+action;size=len(utf8(fixed))
    if size<=maximum:return prefix+retain(detail,maximum-size,True)+omitted+action
    if len(utf8(prefix+action))<=maximum:return prefix+action
    recovery='background job ended; use job_list for id.'
    return recovery if len(utf8(recovery))<=maximum else retain('job_list',maximum,True)

"""Current shell foreground, promotion and handed-off output rendering."""
from dsh.cordis.utils import js_to_string
from .jobs_current import sandbox_notes,HINT


def stream_text(output):return output['text']+('\n[output truncated; full output: '+output.get('spillPath','(unavailable)')+']' if output['truncated'] else '')


def render_result(result,escalation_modes=()):
    out=stream_text(result['stdout']);err=stream_text(result['stderr'])
    body=out+(('\n' if out and not out.endswith('\n') else '')+'[stderr]\n'+err if err else '') or '(no output)'
    markers=[];sandbox=result.get('sandbox')
    if sandbox and sandbox.get('denied'):markers=['[sandbox: file access denied under '+sandbox['mode']+' mode]']+([HINT] if escalation_modes else [])
    if result['timedOut']:markers.append('[timed out after '+js_to_string(result['timeoutMs'])+'ms]')
    if 'stopped' in result:markers.append('[stopped: '+result['stopped']+']')
    if result['signal'] is not None:markers.append('[killed by signal: '+result['signal']+']')
    elif result['exitCode']!=0:markers.append('[exit code: '+js_to_string(result['exitCode'])+']')
    return body+('' if body.endswith('\n') else '\n')+'\n'.join(markers) if markers else body


def render_promoted(result):
    text=result['output']
    return text+('\n' if text and not text.endswith('\n') else '')+'[still running after '+js_to_string(result['timeoutMs'])+'ms; moved to background job '+result['jobId']+']'


def render_job_read(delta,lossy,spill_paths,sandbox=None,escalation_modes=()):
    notices=[]
    if lossy:notices.append('[some output was dropped from memory; full output: '+(', '.join(spill_paths) if spill_paths else '(unavailable)')+']')
    notices.extend(sandbox_notes(sandbox,escalation_modes))
    return delta+('\n' if delta and not delta.endswith('\n') else '')+'\n'.join(notices) if notices else delta

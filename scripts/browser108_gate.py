"""Fixed observer identity and ZIP-bound extracted-browser acceptance."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parents[1]
PORTABLE_STEPS = [
    'original-shell-and-first-use-notice',
    'original-provider-onboarding-deferred-without-credentials',
    'original-sidebar-selects-cold-persisted-session',
    'installed-original-evaluator-client-calls-extracted-python-remote',
    'abrupt-browser-close-retains-same-host-and-installed-remote-service',
]


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def pinned_input():
    return json.loads((ROOT / 'scripts/browser108-input.json').read_text(encoding='utf-8'))


def validate_input(binary):
    binary = Path(binary).resolve()
    pin = pinned_input()
    if binary.name != 'chrome.exe' or binary.parent.name != 'chrome-win':
        raise ValueError('fixed Chromium 108 snapshot layout is required')
    directory = binary.parent.parent
    for name, expected in pin['files'].items():
        path = directory / name
        if path.resolve() != path or not path.is_file() or digest(path) != expected:
            raise ValueError('Chromium 108 input changed or missing: ' + name)
    return dict(binary=str(binary), binary_sha256=pin['binary_sha256'],
                input_sha256=digest(ROOT / 'scripts/browser108-input.json'))


def validate_observation(report, archive, adapter_sha256):
    pin = pinned_input()
    before, after = report.get('capabilitiesBefore', {}), report.get('capabilitiesAfter', {})
    if (report.get('passed') is not True or report.get('steps') != PORTABLE_STEPS or report.get('hostExitCode') != 0 or
            report.get('hostErrors') or report.get('exceptions') or report.get('consoleErrors') or
            report.get('browserBinarySha256') != pin['binary_sha256'] or
            report.get('browser', {}).get('product') != pin['protocol_product'] or
            report.get('browser', {}).get('revision') != pin['protocol_revision'] or
            'HeadlessChrome/108.0.5359.0' not in report.get('browser', {}).get('userAgent', '') or
            report.get('archiveSha256') != digest(archive) or
            report.get('compatibilitySha256') != adapter_sha256 or
            before.get('abortSignalAny') != 'undefined' or before.get('promiseWithResolvers') != 'undefined' or
            before.get('abortSignalTimeout') != 'function' or
            after.get('abortSignalAny') != 'function' or after.get('promiseWithResolvers') != 'function' or
            after.get('abortSignalTimeout') != 'function'):
        raise ValueError('ZIP-bound Chromium 108 observation is incomplete or changed')


def validate_profile_journeys(reports, archive, adapter_sha256, root, check_files=True):
    pin = pinned_input()
    root = Path(root).resolve()
    if not isinstance(reports, dict) or set(reports) != {'minimal', 'standard', 'cordis'}:
        raise ValueError('Chromium 108 profile lanes are incomplete')
    archive_modules = {}
    if not check_files:
        names = {name for report in reports.values() for phase in report.get('phases', [])
                 for name in phase.get('hostReceipt', {}).get('modules', {})}
        with zipfile.ZipFile(archive) as package:
            members = package.namelist()
            for name in names:
                member = root.name + '/' + name
                if members.count(member) != 1:
                    raise ValueError('Chromium 108 profile imports differ from verified ZIP')
                archive_modules[name] = hashlib.sha256(package.read(member)).hexdigest()
    for preset, report in reports.items():
        if (report.get('status') != 'qualified' or report.get('side') != 'native' or
                report.get('preset') != preset or report.get('errors') or report.get('consoleErrors') or
                report.get('archiveSha256') != digest(archive) or
                report.get('compatibilitySha256') != adapter_sha256 or
                [row.get('name') for row in report.get('phases', [])] != ['fresh', 'cold']):
            raise ValueError('ZIP-bound Chromium 108 profile journey differs')
        for phase in report['phases']:
            before, after = phase.get('capabilitiesBefore', {}), phase.get('capabilitiesAfter', {})
            host = phase.get('hostReceipt', {})
            identity = phase.get('browserIdentity', {})
            scenarios = ['WEB_REOPEN'] if phase['name'] == 'cold' else (
                ['WEB_TOOL', 'WEB_CANCEL'] if preset == 'minimal' else
                ['WEB_TOOL', 'WEB_QUESTION', 'WEB_APPROVAL', 'WEB_PLAN', 'WEB_CANCEL'] + (['WEB_CORDIS'] if preset == 'cordis' else []))
            final = phase.get('final', {})
            if (phase.get('scenarios') != scenarios or final.get('agentStatus') != 'idle' or
                    any(not any(event.get('type') == 'assistant/message' and
                        scenario + '_FINAL' in json.dumps(event.get('data'), ensure_ascii=True)
                        for event in final.get('events', [])) for scenario in scenarios if scenario != 'WEB_CANCEL') or
                    'WEB_CANCEL' in scenarios and not any(row.get('finallyAborted') is True and
                        row.get('detached') == 1 for row in final.get('cancellation', []))):
                raise ValueError('Chromium 108 profile scenario observations are incomplete')
            if preset != 'minimal':
                validate_plan_journey(phase)
            if (phase.get('passed') is not True or phase.get('hostErrors') or
                    phase.get('browserBinarySha256') != pin['binary_sha256'] or
                    identity.get('product') != pin['protocol_product'] or identity.get('revision') != pin['protocol_revision'] or
                    'HeadlessChrome/108.0.5359.0' not in identity.get('userAgent', '') or
                    before != dict(any='undefined', withResolvers='undefined', timeout='function') or
                    after != dict(any='function', withResolvers='function', timeout='function') or
                    host.get('root') != str(root) or host.get('executable') != str(root / 'python.exe') or
                    not host.get('python', '').startswith('3.8.10 ') or host.get('exitCode') != 0 or
                    host.get('failure') or host.get('phase') != phase['name'] or host.get('preset') != preset or
                    not host.get('requests') or not host.get('durableAfter') or
                    phase['name'] == 'cold' and not host.get('durableBefore')):
                raise ValueError('Chromium 108 profile runtime or capabilities differ')
            modules = host.get('modules', {})
            if not {'dsh/host/browser_compat/plugin.py', 'dsh/boot/profile_boot.py'}.issubset(modules):
                raise ValueError('Chromium 108 profile imports are incomplete')
            for name, expected in modules.items():
                path = root / name
                if ('\\' in name or ':' in name or Path(name).is_absolute() or '..' in Path(name).parts or
                        path.resolve() != path or check_files and (not path.is_file() or digest(path) != expected)):
                    raise ValueError('Chromium 108 profile imported bytes differ')
                if not check_files:
                    if archive_modules[name] != expected:
                        raise ValueError('Chromium 108 profile imports differ from verified ZIP')


def validate_plan_journey(phase):
    """Require the controlled real plan approval and its cold durable replay."""
    events = phase.get('final', {}).get('events', [])
    modes = [event for event in events if event.get('type') == 'plan/mode']
    calls = [event for event in events if event.get('type') == 'tool/call'
             and event.get('data', {}).get('name') == 'exit_plan_mode']
    if (len(modes) != 2 or [event.get('data') for event in modes] != [dict(active=True), dict(active=False)]
            or any(type(event['data']['active']) is not bool for event in modes) or len(calls) != 1):
        raise ValueError('Chromium 108 plan mode entry/exit or call is incomplete')
    call = calls[0]
    if call.get('data', {}).get('arguments') != json.dumps(dict(
            plan='# Controlled browser plan\n\nInspect the isolated workspace and report the result.'), separators=(',', ':')):
        raise ValueError('Chromium 108 plan review arguments differ')
    call_id = call['data'].get('callId')
    results = [(event, block) for event in events if event.get('type') == 'tool/result'
        for block in event.get('data', {}).get('message', {}).get('content', [])
        if block.get('type') == 'tool-result' and block.get('toolCallId') == call_id]
    text = 'Plan approved — plan mode exited; carry out the plan starting with your next step.'
    if (not call_id or len(results) != 1 or results[0][1].get('isError') is not False
            or results[0][1].get('content') != [dict(type='text', text=text)]
            or results[0][0].get('sourceEventSeqs') != [call.get('seq')]
            or not all(type(event.get('seq')) is int for event in (modes[0], call, results[0][0], modes[1]))
            or not modes[0]['seq'] < call['seq'] < results[0][0]['seq'] < modes[1]['seq']):
        raise ValueError('Chromium 108 approved plan result or durable ordering differs')
    positions = [next(index for index, event in enumerate(events) if event is expected)
                 for expected in (modes[0], call, results[0][0], modes[1])]
    if not all(left < right for left, right in zip(positions, positions[1:])):
        raise ValueError('Chromium 108 plan event array order differs')
    if phase.get('name') == 'fresh':
        panel = phase.get('planReviewPanel', {})
        if ('Controlled browser plan' not in panel.get('text', '')
                or panel.get('approveLabel', '').strip() != 'Approve'):
            raise ValueError('Chromium 108 original plan review control is absent')


def prepare(destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('fresh Chromium observer directory is required')
    destination.mkdir(parents=True)
    pin = pinned_input()
    archive = destination / 'observer.zip'
    urllib.request.urlretrieve(pin['source'], str(archive))
    if digest(archive) != pin['archive_sha256']:
        raise ValueError('downloaded Chromium snapshot differs from fixed input')
    with zipfile.ZipFile(archive) as package:
        for item in package.infolist():
            path = (destination / item.filename).resolve()
            path.relative_to(destination)
            if '\\' in item.filename or ':' in item.filename:
                raise ValueError('invalid observer archive path')
        package.extractall(destination)
    identity = validate_input(destination / pin['binary'])
    # Only this verified, reconstructible archive is removed; preserve extracted
    # fixed observer and acquisition identity for reuse.
    archive.unlink()
    (destination / 'acquisition.json').write_text(json.dumps(dict(identity,
        archive_sha256=pin['archive_sha256'], source=pin['source'], download_removed=True), indent=2) + '\n', encoding='utf-8')
    return identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', type=Path)
    parser.add_argument('--browser', type=Path)
    args = parser.parse_args()
    if bool(args.prepare) == bool(args.browser):
        parser.error('select exactly one of --prepare and --browser')
    print(json.dumps(prepare(args.prepare) if args.prepare else validate_input(args.browser)))


if __name__ == '__main__':
    main()

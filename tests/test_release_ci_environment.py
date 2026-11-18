import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

import pytest

from dsh.cordis import utils
from scripts import agent_dependencies_oracle


ROOT = Path(__file__).resolve().parents[1]


def test_actual_git_materialized_source_symlink_is_bound_as_original_target_bytes(tmp_path, monkeypatch):
    def git(*args, **options):
        return subprocess.check_output(['git', '-C', str(tmp_path)] + list(args), **options)

    git('init', '-q')
    git('config', 'core.symlinks', 'false')
    git('config', 'user.name', 'CI input test')
    git('config', 'user.email', 'ci-input@example.invalid')
    target = b'../.agents/skills'
    oid = git('hash-object', '-w', '--stdin', input=target).decode('ascii').strip()
    git('update-index', '--add', '--cacheinfo', '120000,' + oid + ',.claude/skills')
    git('checkout-index', '--all')
    git('commit', '-qm', 'Source link fixture')
    candidate = git('rev-parse', 'HEAD').decode('ascii').strip()
    monkeypatch.setattr(agent_dependencies_oracle, 'SOURCE_COMMIT', candidate)
    source = tmp_path / '.claude/skills'
    assert source.is_file() and not source.is_symlink() and source.read_bytes() == target
    assert git('status', '--porcelain') == b''
    inputs = agent_dependencies_oracle.source_inputs(tmp_path)
    assert inputs['reference/.claude/skills'] == hashlib.sha256(target).hexdigest()


@pytest.mark.parametrize('zone,offset', [('UTC', 0), ('Asia/Shanghai', 8)])
def test_actual_pinned_cosmokit_matches_explicit_utc_and_china_host_realms(tmp_path, monkeypatch, zone, offset):
    code = '''
import { Time } from %s;
import { formatProperty } from %s;
import fs from 'node:fs';
const fields = d => [d.getFullYear(),d.getMonth()+1,d.getDate(),d.getHours(),d.getMinutes(),d.getSeconds()];
const moment = new Date('2026-09-03T14:30:45Z');
const number = Time.getDateNumber(moment,-480);
fs.writeFileSync(process.env.DSH_ZONE_OBSERVATION, JSON.stringify({node:process.version, zone:Time.getTimezoneOffset(),number,
  restored:fields(Time.fromDateNumber(number,-480)),
  parsed:fields(Time.parseDate('Mar 5 2026 GMT')),
  property:formatProperty(new Date(0))}));
''' % (json.dumps((ROOT / 'reference/vendor/cosmokit/src/time.ts').as_uri()),
       json.dumps((ROOT / 'reference/vendor/cosmokit/src/string.ts').as_uri()))
    environment = dict(os.environ, TZ=zone, TSX_TSCONFIG_PATH=str(ROOT / 'reference/tsconfig.json'))
    script = tmp_path / 'observer.mts'
    script.write_text(code, encoding='utf-8')
    output = tmp_path / 'source.json'
    environment['DSH_ZONE_OBSERVATION'] = str(output)
    completed = subprocess.run(['node', '--import', (ROOT / 'reference/node_modules/tsx/dist/loader.mjs').as_uri(),
                                str(script)], cwd=str(ROOT), env=environment,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8', timeout=30)
    (tmp_path / 'runner.log').write_text(completed.stdout + completed.stderr, encoding='utf-8')
    assert completed.returncode == 0, completed.stderr
    source = json.loads(output.read_text(encoding='utf-8'))
    assert source['node'] == 'v24.9.0' and source['zone'] == -60 * offset
    epoch = datetime.datetime(1970, 1, 1)

    class HostClock:
        daylight = 0
        timezone = -offset * 3600
        altzone = -offset * 3600
        tzname = (source['property'].rsplit('(', 1)[1][:-2],) * 2

        def __getattr__(self, name):
            return getattr(time, name)

    monkeypatch.setattr(utils, 'time', HostClock())
    monkeypatch.setattr(utils, '_datetime_from_epoch', lambda seconds: epoch + datetime.timedelta(seconds=seconds, hours=offset))
    monkeypatch.setattr(utils, '_epoch_seconds_of', lambda value: value.timestamp() if value.tzinfo is not None else
                        (value - epoch).total_seconds() - offset * 3600)
    monkeypatch.setattr(utils.Time, '_timezone_offset', source['zone'])
    def fields(value):
        return [value.year, value.month, value.day, value.hour, value.minute, value.second]
    moment = datetime.datetime(2026, 9, 3, 14, 30, 45, tzinfo=datetime.timezone.utc)
    number = utils.Time.getDateNumber(moment, -480)
    assert number == source['number']
    assert fields(utils.Time.fromDateNumber(number, -480)) == source['restored']
    assert fields(utils.Time.parseDate('Mar 5 2026 GMT')) == source['parsed']
    assert utils.formatProperty(epoch + datetime.timedelta(hours=offset)) == source['property']

from pathlib import Path
import hashlib
import json
import sys

import pytest

from scripts.process_artifact_retention import configure_pytest_workspace, prune_pytest_session


pytest_plugins = ["pytest_asyncio"]


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    configure_pytest_workspace(config, Path(__file__).resolve().parents[1] / '.goose/out')


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.failed:
        # Persist immediately: a later interruption can prevent terminal/JUnit summaries.
        try:
            folder = item.config._tmp_path_factory.getbasetemp() / 'failed-reports'
            folder.mkdir(exist_ok=True)
            identity = hashlib.sha256((report.nodeid + ':' + report.when).encode('utf-8')).hexdigest()
            (folder / (identity + '.json')).write_text(json.dumps(dict(
                nodeid=report.nodeid, when=report.when, duration=report.duration,
                traceback=report.longreprtext), ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
        except OSError as error:
            sys.stderr.write('Could not retain pytest failure: ' + str(error) + '\n')


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    prune_pytest_session(session, exitstatus, Path(__file__).resolve().parents[1] / '.goose/out')

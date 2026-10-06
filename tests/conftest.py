from pathlib import Path

import pytest

from scripts.process_artifact_retention import configure_pytest_workspace, prune_pytest_session


pytest_plugins = ["pytest_asyncio"]


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    configure_pytest_workspace(config, Path(__file__).resolve().parents[1] / '.goose/out')


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    prune_pytest_session(session, exitstatus, Path(__file__).resolve().parents[1] / '.goose/out')

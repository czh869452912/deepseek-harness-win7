"""Exercise modern MCP result decoding before legacy list validation."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
from scripts import rc022_mcp_server_probe_probe as driver


def cases():
    rows = [dict(mode=mode, options={}, **extra)
        for mode in ('modern-input-state', 'modern-input-empty', 'modern-unknown-result',
                     'modern-invalid-tools', 'modern-missing-result-type',
                     'modern-state-once', 'modern-state-empty', 'modern-input-entry-malformed',
                     'modern-input-entry-nonstring', 'modern-input-entry-unknown',
                     'modern-input-entry-roots', 'modern-input-entry-sampling', 'modern-input-entry-elicitation')
        for extra in ({}, dict(aggregate=True, cursor=False))]
    rows.extend(dict(mode='modern-input-state', options={}, aggregate=True, direct=True,
        clientOptions=dict(inputRequired=setting), requestOptions=request)
        for setting, request in [({}, dict(allowInputRequired=True)),
            (dict(autoFulfill=False), {}), (dict(maxRounds=2), {})])
    return rows


def prepare(output):
    previous = driver.cases
    driver.cases = cases
    try:
        return driver.prepare(output)
    finally:
        driver.cases = previous


async def observe():
    previous = driver.cases
    driver.cases = cases
    try:
        return await driver.observe()
    finally:
        driver.cases = previous


if __name__ == '__main__':
    probe.native = observe
    try:
        probe.main('rc022_mcp_server_probe.mts',
            'Actual SDK HTTP probe and aggregate listing: modern input-required, malformed, '
            'unsupported and missing result types decode before legacy tools-list validation.',
            [Path(__file__).resolve(), ROOT/'dsh/mcp/protocol.py',
             ROOT/'dsh/mcp/negotiated_protocol_current.py',
             ROOT/'scripts/oracles/rc022_mcp_server_probe_peer.py'], prepare=prepare)
    finally:
        driver.stop_peer()

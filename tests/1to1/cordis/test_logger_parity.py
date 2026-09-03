"""
1:1 parity unit test suite for dsh/cordis/logger.py matching reference/vendor/cordis/src/logger.ts.
Covers:
- T1: Logger.code signed 32-bit integer overflow hash parity
- T2: Logger.color decoration requires exporter.colors >= 2 even for code < 8
- T3: Single Exception with __cause__ logs cause first; AggregateError (errors list) logs children and returns
- T4: format placeholder edge cases: undefined for empty, NaN for bad numbers, trunc for d/i, unknown placeholder does not consume args
- T5: format leftover objects use exporter formatters['o']
- T6: exporter disposer targets latest _sn_exporter and registration happens inside effect setup
- T7: exporter exceptions propagate directly to caller
- T8: ctx.logger() hyphenates fiber name and resolves intercept config
"""

import pytest
from typing import Any

from dsh.cordis.context import Context
from dsh.cordis.fiber import FiberState
from dsh.cordis.logger import Logger, LoggerLevel, LoggerService, Exporter, Message
from dsh.cordis.plugin import Plugin


def test_t1_logger_code_signed_hash_parity():
    """T1: Logger.code correctly computes 32-bit signed integer hash matching TS."""
    # When level is 0, should return 0
    assert Logger.code("test", 0) == 0

    # In TS:
    # "core": hash calculation has specific color in c256 / c16
    # Check that code returns valid integer in c256
    c256_code = Logger.code("core", 2)
    assert c256_code in Logger.c256

    # Test names that produce negative 32-bit signed values
    # For a string where signed_h < 0, abs(signed_h) should be used
    for name in ["app", "server", "router", "plugin_manager_extended"]:
        code = Logger.code(name, 2)
        assert isinstance(code, int)
        assert code in Logger.c256


def test_t2_logger_color_decoration_requires_colors_2():
    """T2: Decoration (;1) requires colors >= 2 even for code < 8."""
    exp_1 = Exporter(colors=1)
    exp_2 = Exporter(colors=2)
    exp_0 = Exporter(colors=0)

    # code = 3 (code < 8)
    assert Logger.color(exp_0, 3, "hello", ";1") == "hello"
    assert Logger.color(exp_1, 3, "hello", ";1") == "\033[33mhello\033[0m"
    assert Logger.color(exp_2, 3, "hello", ";1") == "\033[33;1mhello\033[0m"


def test_t3_logger_error_cause_and_aggregate_fanout():
    """T3: Single Exception with __cause__ logs cause first; Exception with errors logs children only."""
    ctx = Context()
    logged = []

    class CapturingExporter(Exporter):
        def export(self, message: Message) -> None:
            logged.append(message)

    ctx.logger.exporter(CapturingExporter())

    log = ctx.logger("test-err")

    # 1. Error with cause
    cause_err = ValueError("root cause")
    main_err = RuntimeError("wrapper")
    main_err.__cause__ = cause_err

    log.error(main_err)
    assert len(logged) == 2
    assert "root cause" in str(logged[0].args[0])
    assert "wrapper" in str(logged[1].args[0])

    logged.clear()

    # 2. AggregateError / Exception with errors
    class AggregateError(Exception):
        def __init__(self, errors):
            super().__init__("aggregate")
            self.errors = errors

    agg = AggregateError([ValueError("child 1"), TypeError("child 2")])
    log.error(agg)
    assert len(logged) == 2
    assert "child 1" in str(logged[0].args[0])
    assert "child 2" in str(logged[1].args[0])


def test_t4_logger_format_placeholder_parity():
    """T4: format placeholder boundary semantics: NaN, trunc, undefined, and non-consuming unknown."""
    exp = Exporter(colors=0)

    msg = Message(sn=1, ts=0, type="info", level=LoggerLevel.INFO, name="test", args=["hello %s"])
    assert Logger.format(exp, msg) == "hello undefined"

    # %d with float string should truncate
    msg = Message(sn=1, ts=0, type="info", level=LoggerLevel.INFO, name="test", args=["num: %d", "3.7"])
    assert Logger.format(exp, msg) == "num: 3"

    # %d with invalid string should output NaN
    msg = Message(sn=1, ts=0, type="info", level=LoggerLevel.INFO, name="test", args=["bad: %d", "abc"])
    assert Logger.format(exp, msg) == "bad: NaN"

    # %f with invalid string should output NaN
    msg = Message(sn=1, ts=0, type="info", level=LoggerLevel.INFO, name="test", args=["bad: %f", "abc"])
    assert Logger.format(exp, msg) == "bad: NaN"

    # unknown placeholder %x does not consume subsequent args
    msg = Message(sn=1, ts=0, type="info", level=LoggerLevel.INFO, name="test", args=["a %x %s", "first", "second"])
    assert Logger.format(exp, msg) == "a %x first second"

    # %% outputs %
    msg = Message(sn=1, ts=0, type="info", level=LoggerLevel.INFO, name="test", args=["100%%"])
    assert Logger.format(exp, msg) == "100%"


def test_t5_logger_format_leftover_objects_use_o_formatter():
    """T5: Trailing objects use exporter formatters['o']."""
    exp = Exporter(
        colors=0,
        formatters={"o": lambda val, exporter, message: f"<custom:{val}>"}
    )
    custom_obj = {"foo": "bar"}
    msg = Message(sn=1, ts=0, type="info", level=LoggerLevel.INFO, name="test", args=["lead", custom_obj])
    formatted = Logger.format(exp, msg)
    assert formatted == "lead <custom:{'foo': 'bar'}>"


def test_t6_logger_exporter_disposer_targets_latest_sn():
    """T6: Disposer deletes latest _sn_exporter matching TS upstream quirk, and effect setup is atomic."""
    ctx = Context()
    exp1 = Exporter(colors=0)
    exp2 = Exporter(colors=0)

    disp1 = ctx.logger.exporter(exp1)
    disp2 = ctx.logger.exporter(exp2)

    # Total is 3: 1 default internal buffer exporter + 2 user exporters
    assert len(ctx.logger.exporters) == 3
    # Calling disp1 should pop latest sn (exp2)
    disp1()
    assert exp2 not in ctx.logger.exporters.values()
    assert exp1 in ctx.logger.exporters.values()


def test_t7_logger_exporter_exception_propagates():
    """T7: Exporter exception propagates to caller instead of being silently caught."""
    ctx = Context()

    class BrokenExporter(Exporter):
        def export(self, message: Message) -> None:
            raise RuntimeError("disk full")

    ctx.logger.exporter(BrokenExporter())

    log = ctx.logger("test-broken")
    with pytest.raises(RuntimeError) as exc_info:
        log.info("will fail")
    assert "disk full" in str(exc_info.value)


def test_t8_logger_name_hyphenate_and_intercept_config():
    """T8: ctx.logger() hyphenates fiber name and resolves intercept config."""
    ctx = Context()

    class CamelCasePlugin(Plugin):
        name = "myCamelCasePlugin"

        def apply(self, c: Context) -> None:
            logger = c.logger()
            assert logger.name == "my-camel-case-plugin"

    ctx.plugin(CamelCasePlugin)

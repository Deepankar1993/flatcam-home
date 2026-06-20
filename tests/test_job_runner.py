"""Headless unit tests for appAutomation.job_runner.execute_lines.

Covers the NOVEL risk surface (spec 11.9 #2): abort-on-error and
stop-between-steps. Uses a mock eval function - no Qt, no tkinter.

    python -m pytest tests/test_job_runner.py
    python tests/test_job_runner.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from appAutomation import job_runner as jr


def test_all_steps_run_when_all_succeed():
    calls = []
    res = jr.execute_lines(lambda line: calls.append(line) or "ok",
                           ["a", "b", "c"])
    assert calls == ["a", "b", "c"]
    assert [r.ok for r in res] == [True, True, True]
    assert all(not r.skipped for r in res)


def test_exception_aborts_remaining_steps():
    calls = []

    def ev(line):
        calls.append(line)
        if line == "b":
            raise RuntimeError("boom")
        return "ok"

    res = jr.execute_lines(ev, ["a", "b", "c"])
    assert calls == ["a", "b"]                 # 'c' never ran
    assert res[0].ok and not res[0].skipped
    assert not res[1].ok and not res[1].skipped
    assert "boom" in res[1].message
    assert res[2].skipped                      # remainder skipped


def test_failure_string_return_aborts():
    res = jr.execute_lines(lambda line: "Operation failed: nope" if line == "x" else "ok",
                           ["ok1", "x", "ok2"])
    assert res[0].ok
    assert not res[1].ok and not res[1].skipped
    assert res[2].skipped


def test_bare_fail_return_is_failure():
    res = jr.execute_lines(lambda line: "fail", ["only"])
    assert not res[0].ok


def test_stop_between_steps_halts_cleanly():
    calls = []
    state = {"stop": False}

    def ev(line):
        calls.append(line)
        if line == "a":
            state["stop"] = True   # request stop after first step
        return "ok"

    res = jr.execute_lines(ev, ["a", "b", "c"], should_stop=lambda: state["stop"])
    assert calls == ["a"]          # 'b','c' never executed
    assert res[0].ok
    assert res[1].skipped and res[2].skipped


def test_on_step_callback_phases():
    phases = []
    jr.execute_lines(lambda line: "ok", ["a", "b"],
                     on_step=lambda phase, r: phases.append((phase, r.index)))
    assert phases == [("start", 0), ("finish", 0), ("start", 1), ("finish", 1)]


def test_read_error_enriches_message():
    def ev(line):
        raise RuntimeError("terse")

    res = jr.execute_lines(ev, ["a"], read_error=lambda: "rich errorInfo trace")
    assert res[0].message == "rich errorInfo trace"


def test_is_failure_result_markers():
    assert jr.is_failure_result("fail")
    assert jr.is_failure_result("FAIL")
    assert jr.is_failure_result("Operation failed: x")
    assert jr.is_failure_result("[ERROR] bad")
    assert not jr.is_failure_result("Tool object created")
    assert not jr.is_failure_result(None)
    assert not jr.is_failure_result("")


def _run_all():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print("PASS", fn.__name__)
        except Exception as e:  # noqa
            failed += 1
            print("FAIL", fn.__name__, "->", repr(e))
    print("\n%d passed, %d failed, %d total" % (len(fns) - failed, failed, len(fns)))
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run_all() else 0)

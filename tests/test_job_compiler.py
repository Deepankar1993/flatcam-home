"""Headless unit tests for appAutomation.job_compiler.

Runnable two ways:
    python -m pytest tests/test_job_compiler.py
    python tests/test_job_compiler.py        # no pytest needed

The centerpiece is QUOTING: Windows paths with spaces/backslashes must come out
brace-wrapped and slash-normalized, coordinate pairs must be space-free, and
set_sys must NEVER be emitted. (Spec section 11.9.)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from appAutomation import job_model as jm
from appAutomation import job_compiler as jc


# --------------------------------------------------------------------------- #
# Quoting - the critical correctness surface
# --------------------------------------------------------------------------- #
def test_path_with_spaces_is_braced_and_slash_normalized():
    step = jm.Step(jm.OPEN_GERBER,
                   {"file": r"C:\Users\my file\board.gbr", "outname": "top"})
    alias, tokens = jc.compile_step(step)
    assert alias == "open_gerber"
    # path token must be a single brace-wrapped, forward-slashed token
    assert tokens[0] == "{C:/Users/my file/board.gbr}"
    assert tokens[1:] == ["-outname", "{top}"]


def test_plain_path_still_braced():
    assert jc.tcl_path("C:/x/y.gbr") == "{C:/x/y.gbr}"
    assert jc.tcl_path(r"C:\x\y.gbr") == "{C:/x/y.gbr}"


def test_brace_in_path_is_rejected_not_corrupted():
    step = jm.Step(jm.OPEN_GERBER, {"file": "C:/weird{dir}/b.gbr", "outname": "t"})
    try:
        jc.compile_step(step)
    except jc.CompileError:
        return
    raise AssertionError("expected CompileError for a path containing braces")


def test_coordinate_pair_has_no_spaces():
    step = jm.Step(jm.CNCJOB,
                   {"name": "iso", "z_cut": -0.05, "toolchangexy": "0, 0",
                    "endxy": "10, 10", "outname": "iso_cnc"})
    line = jc.invocation_to_line(jc.compile_step(step))
    assert "{0,0}" in line
    assert "{10,10}" in line
    assert "0, 0" not in line


def test_no_set_sys_ever_emitted():
    job = _full_two_layer_job()
    for line in jc.compile_job_lines(job):
        assert "set_sys" not in line
        assert "setsys" not in line


# --------------------------------------------------------------------------- #
# Flag correctness (transcribed from tclCommands/* option dicts)
# --------------------------------------------------------------------------- #
def test_isolate_emits_verified_flags():
    step = jm.Step(jm.ISOLATE,
                   {"name": "top", "dia": 0.1, "passes": 2, "overlap": 10.0,
                    "combine": True, "iso_type": 2, "outname": "top_iso"})
    line = jc.invocation_to_line(jc.compile_step(step))
    assert line == ("isolate {top} -dia 0.1 -passes 2 -overlap 10 "
                    "-combine True -iso_type 2 -outname {top_iso}")


def test_cncjob_uses_z_cut_and_pp_flags():
    step = jm.Step(jm.CNCJOB,
                   {"name": "top_iso", "z_cut": -0.05, "z_move": 2.0,
                    "feedrate": 120.0, "pp": "default", "outname": "top_cnc"})
    line = jc.invocation_to_line(jc.compile_step(step))
    assert line.startswith("cncjob {top_iso}")
    assert "-z_cut -0.05" in line
    assert "-pp {default}" in line
    assert "-outname {top_cnc}" in line


def test_drillcncjob_flags():
    step = jm.Step(jm.DRILLCNCJOB,
                   {"name": "drl", "drilled_dias": "all", "drillz": -1.7,
                    "travelz": 2.0, "feedrate_z": 300.0, "pp": "default",
                    "outname": "drl_cnc"})
    line = jc.invocation_to_line(jc.compile_step(step))
    assert line.startswith("drillcncjob {drl}")
    assert "-drilled_dias {all}" in line
    assert "-drillz -1.7" in line


def test_write_gcode_two_positionals_and_quoted_path():
    step = jm.Step(jm.EXPORT_GCODE,
                   {"name": "top_cnc", "filename": r"D:\out put\top.gcode"})
    alias, tokens = jc.compile_step(step)
    assert alias == "write_gcode"
    assert tokens == ["{top_cnc}", "{D:/out put/top.gcode}"]


def test_disabled_step_is_skipped():
    step = jm.Step(jm.ISOLATE, {"name": "x", "outname": "y"}, enabled=False)
    assert jc.compile_step(step) is None
    job = jm.Job(steps=[step])
    assert jc.compile_job_lines(job) == []


def test_missing_required_param_raises():
    step = jm.Step(jm.ISOLATE, {"dia": 0.1})  # no 'name'
    try:
        jc.compile_step(step)
    except jc.CompileError:
        return
    raise AssertionError("expected CompileError for missing required param")


def test_float_formatting_is_clean():
    assert jc._fmt(2.0) == "2"
    assert jc._fmt(0.1) == "0.1"
    assert jc._fmt(-0.05) == "-0.05"
    assert jc._fmt(True) == "True"
    assert jc._fmt(3) == "3"


# --------------------------------------------------------------------------- #
# helpers / runner
# --------------------------------------------------------------------------- #
def _full_two_layer_job():
    job = jm.Job(name="2layer", units="MM")
    job.add_step(jm.Step(jm.OPEN_GERBER, {"file": "C:/b/top.gbr", "outname": "top"}))
    job.add_step(jm.Step(jm.OPEN_EXCELLON, {"file": "C:/b/drl.drl", "outname": "drl"}))
    job.add_step(jm.Step(jm.ISOLATE, {"name": "top", "dia": 0.1, "outname": "top_iso"}))
    job.add_step(jm.Step(jm.CNCJOB, {"name": "top_iso", "z_cut": -0.05,
                                     "pp": "default", "outname": "top_cnc"}))
    job.add_step(jm.Step(jm.DRILLCNCJOB, {"name": "drl", "drillz": -1.7,
                                          "outname": "drl_cnc"}))
    job.add_step(jm.Step(jm.EXPORT_GCODE, {"name": "top_cnc",
                                           "filename": "C:/out/top.gcode"}))
    return job


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

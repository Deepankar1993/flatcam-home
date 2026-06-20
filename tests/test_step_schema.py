"""Headless tests for appAutomation.step_schema."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from appAutomation import step_schema as sch
from appAutomation import job_model as jm
from appAutomation import job_compiler as jc


def test_every_step_type_has_a_schema():
    for st in jm.STEP_TYPES:
        assert sch.fields_for(st), "no schema for %s" % st
        assert st in sch.STEP_LABELS


def test_schema_field_keys_are_known_compiler_keys_or_bindings():
    # Every schema key for a generation step must be either a binding (name/outname/
    # file/filename) or an actual compiler flag for that step, so edits compile.
    flag_tables = {
        jm.ISOLATE: jc._ISOLATE_FLAGS, jm.NCC: jc._NCC_FLAGS,
        jm.CNCJOB: jc._CNCJOB_FLAGS, jm.DRILLCNCJOB: jc._DRILL_FLAGS,
        jm.CUTOUT: jc._CUTOUT_FLAGS,
    }
    bindings = {"name", "outname", "file", "filename"}
    for st, table in flag_tables.items():
        for f in sch.fields_for(st):
            k = f["key"]
            assert k in bindings or k in table, \
                "%s field %r is neither a binding nor a compiler flag" % (st, k)


def test_default_params_make_a_compilable_step():
    # A step built purely from defaults (plus a source name) must compile.
    for st in (jm.ISOLATE, jm.NCC, jm.CNCJOB, jm.DRILLCNCJOB, jm.CUTOUT):
        params = sch.default_params(st)
        params["name"] = "src"
        step = jm.Step(st, params)
        line = jc.invocation_to_line(jc.compile_step(step))
        assert line.startswith(jc.compile_step(step)[0])


def test_default_params_only_includes_fields_with_default():
    p = sch.default_params(jm.ISOLATE)
    assert "name" not in p          # FT_OBJECT has no default
    assert p["dia"] == 0.1 and p["passes"] == 1


def test_summarize_reads_key_params():
    step = jm.Step(jm.ISOLATE, {"name": "top.gbr", "dia": 0.1, "passes": 2})
    s = sch.summarize(step)
    assert "Isolate" in s and "top.gbr" in s and "0.1" in s


def test_choice_fields_have_value_label_pairs():
    for st in jm.STEP_TYPES:
        for f in sch.fields_for(st):
            if f["type"] == sch.FT_CHOICE:
                assert f["choices"] and all(len(c) == 2 for c in f["choices"])
                assert "default" in f


def _run_all():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn(); print("PASS", fn.__name__)
        except Exception as e:  # noqa
            failed += 1; print("FAIL", fn.__name__, "->", repr(e))
    print("\n%d passed, %d failed, %d total" % (len(fns) - failed, failed, len(fns)))
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run_all() else 0)

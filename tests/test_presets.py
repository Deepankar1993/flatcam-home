"""Headless tests for appAutomation.presets - presets must compile cleanly,
validate without errors, and preserve drill-before-cutout ordering."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from appAutomation import presets as pr
from appAutomation import job_model as jm
from appAutomation import job_compiler as jc


def test_iso_single_builds_valid_compilable_job():
    job = pr.build("iso_single",
                   {pr.TOP_COPPER: r"C:\b\top.gbr"}, r"C:\out", None)
    assert jm.ERROR not in [s for s, _ in job.validate()]
    lines = jc.compile_job_lines(job)
    assert any(l.startswith("open_gerber") for l in lines)
    assert any(l.startswith("isolate") for l in lines)
    assert any(l.startswith("cncjob") for l in lines)
    assert any(l.startswith("write_gcode") for l in lines)


def test_full_preset_drills_before_cutout():
    job = pr.build("iso_drill_cutout",
                   {pr.TOP_COPPER: "top.gbr", pr.DRILLS: "d.drl", pr.OUTLINE: "e.gbr"},
                   "out", None)
    types = [s.type for s in job.steps]
    assert jm.DRILLCNCJOB in types and jm.CUTOUT in types
    assert types.index(jm.DRILLCNCJOB) < types.index(jm.CUTOUT)
    # no validation errors and no cutout-before-drill warning
    probs = job.validate()
    assert jm.ERROR not in [s for s, _ in probs]
    assert not any("Drill first" in m for _, m in probs)


def test_preset_applies_profile_settings():
    prof = jm.Profile("GRBL", "MM", {jm.CNCJOB: {"z_cut": -0.05, "pp": "grbl"}})
    job = pr.build("iso_single", {pr.TOP_COPPER: "top.gbr"}, "out", prof)
    cnc = [s for s in job.steps if s.type == jm.CNCJOB][0]
    assert cnc.params["z_cut"] == -0.05
    assert cnc.params["pp"] == "grbl"
    assert job.units == "MM"


def test_missing_required_role_raises():
    try:
        pr.build("iso_single", {}, "out", None)
    except ValueError:
        return
    raise AssertionError("expected ValueError when Top Copper missing")


def test_all_presets_registered_and_buildable():
    for pid in pr.PRESET_ORDER:
        assert pid in pr.PRESETS
        job = pr.build(pid, {pr.TOP_COPPER: "t.gbr", pr.DRILLS: "d.drl",
                             pr.OUTLINE: "e.gbr"}, "out", None)
        assert len(job.steps) >= 3
        assert jm.ERROR not in [s for s, _ in job.validate()]


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

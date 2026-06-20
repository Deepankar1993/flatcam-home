"""Headless unit tests for appAutomation.job_model.

    python -m pytest tests/test_job_model.py
    python tests/test_job_model.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from appAutomation import job_model as jm


def _severities(problems):
    return [sev for sev, _ in problems]


# --------------------------------------------------------------------------- #
# JSON round-trip
# --------------------------------------------------------------------------- #
def test_job_json_round_trip_preserves_everything():
    job = jm.Job(name="My Board", units="MM",
                 profile=jm.Profile("GRBL 0.1mm", "MM",
                                    {jm.CNCJOB: {"z_cut": -0.05, "pp": "grbl"}}))
    job.add_step(jm.Step(jm.OPEN_GERBER, {"file": "a.gbr", "outname": "top"}))
    job.add_step(jm.Step(jm.ISOLATE, {"name": "top", "dia": 0.1, "outname": "top_iso"},
                         enabled=False))
    text = job.to_json()
    back = jm.Job.from_json(text)
    assert back.name == "My Board"
    assert back.units == "MM"
    assert back.profile.name == "GRBL 0.1mm"
    assert back.profile.settings[jm.CNCJOB]["z_cut"] == -0.05
    assert len(back.steps) == 2
    assert back.steps[1].enabled is False
    assert back.steps[1].params["dia"] == 0.1


def test_profile_apply_seeds_tunables_but_not_bindings():
    prof = jm.Profile("p", "MM", {jm.CNCJOB: {"z_cut": -0.05, "pp": "grbl",
                                              "outname": "SHOULD_NOT_LEAK"}})
    job = jm.Job(units="IN")
    job.add_step(jm.Step(jm.CNCJOB, {"name": "iso", "outname": "iso_cnc"}))
    prof.apply_to(job)
    s = job.steps[0]
    assert s.params["z_cut"] == -0.05      # tunable seeded
    assert s.params["pp"] == "grbl"        # tunable seeded
    assert s.params["outname"] == "iso_cnc"  # binding NOT overwritten
    assert job.units == "MM"               # units come from profile


def test_profile_does_not_overwrite_existing_step_value():
    prof = jm.Profile("p", "MM", {jm.CNCJOB: {"z_cut": -0.05}})
    job = jm.Job()
    job.add_step(jm.Step(jm.CNCJOB, {"name": "iso", "z_cut": -0.2, "outname": "c"}))
    prof.apply_to(job)
    assert job.steps[0].params["z_cut"] == -0.2  # step wins by default


# --------------------------------------------------------------------------- #
# validate() guardrails (spec 11.5)
# --------------------------------------------------------------------------- #
def test_bad_units_is_error():
    job = jm.Job(units="furlongs")
    assert jm.ERROR in _severities(job.validate())


def test_dangling_object_reference_is_error():
    job = jm.Job(units="MM")
    job.add_step(jm.Step(jm.ISOLATE, {"name": "nope", "outname": "iso"}))
    probs = job.validate()
    assert any(sev == jm.ERROR and "no earlier step produces" in msg
               for sev, msg in probs)


def test_valid_reference_chain_has_no_errors():
    job = jm.Job(units="MM")
    job.add_step(jm.Step(jm.OPEN_GERBER, {"file": "a.gbr", "outname": "top"}))
    job.add_step(jm.Step(jm.ISOLATE, {"name": "top", "dia": 0.1, "outname": "top_iso"}))
    job.add_step(jm.Step(jm.CNCJOB, {"name": "top_iso", "z_cut": -0.05, "outname": "c"}))
    job.add_step(jm.Step(jm.EXPORT_GCODE, {"name": "c", "filename": "o.gcode"}))
    assert jm.ERROR not in _severities(job.validate())


def test_open_step_requires_file_and_outname():
    job = jm.Job(units="MM")
    job.add_step(jm.Step(jm.OPEN_GERBER, {}))
    probs = job.validate()
    msgs = " ".join(m for _, m in probs)
    assert "no input file" in msgs
    assert "missing output object name" in msgs


def test_export_requires_filename():
    job = jm.Job(units="MM")
    job.add_step(jm.Step(jm.OPEN_GERBER, {"file": "a.gbr", "outname": "top"}))
    job.add_step(jm.Step(jm.CNCJOB, {"name": "top", "z_cut": -0.05, "outname": "c"}))
    job.add_step(jm.Step(jm.EXPORT_GCODE, {"name": "c"}))  # no filename
    assert any(sev == jm.ERROR and "G-code file path" in m for sev, m in job.validate())


def test_cutout_before_drill_warns():
    job = jm.Job(units="MM")
    job.add_step(jm.Step(jm.OPEN_GERBER, {"file": "a.gbr", "outname": "edge"}))
    job.add_step(jm.Step(jm.OPEN_EXCELLON, {"file": "d.drl", "outname": "drl"}))
    job.add_step(jm.Step(jm.CUTOUT, {"name": "edge", "dia": 1.0, "outname": "cut"}))
    job.add_step(jm.Step(jm.DRILLCNCJOB, {"name": "drl", "drillz": -1.7, "outname": "dc"}))
    assert any(sev == jm.WARNING and "Drill first" in m for sev, m in job.validate())


def test_positive_cut_z_warns():
    job = jm.Job(units="MM")
    job.add_step(jm.Step(jm.OPEN_GERBER, {"file": "a.gbr", "outname": "top"}))
    job.add_step(jm.Step(jm.ISOLATE, {"name": "top", "outname": "iso"}))
    job.add_step(jm.Step(jm.CNCJOB, {"name": "iso", "z_cut": 0.05, "outname": "c"}))
    assert any(sev == jm.WARNING and "will not cut" in m for sev, m in job.validate())


def test_implausible_depth_warns_units_hint():
    job = jm.Job(units="MM")
    job.add_step(jm.Step(jm.OPEN_GERBER, {"file": "a.gbr", "outname": "top"}))
    job.add_step(jm.Step(jm.ISOLATE, {"name": "top", "outname": "iso"}))
    job.add_step(jm.Step(jm.CNCJOB, {"name": "iso", "z_cut": -25.0, "outname": "c"}))
    assert any("units" in m for _, m in job.validate())


def test_new_step_id_is_stable():
    assert jm.new_step_id([]) == 1
    assert jm.new_step_id([1, 2, 4]) == 3
    assert jm.new_step_id([1, 2, 3]) == 4


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

"""Parity test: the compiler must emit the same command SHAPES as the proven
shipped example scripts (assets/examples/*.FlatScript). This ties our output to
a reference that is known to run end-to-end in the real app, without needing Qt.

    python tests/test_integration_parity.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from appAutomation import job_model as jm
from appAutomation import job_compiler as jc


def test_ncc_pipeline_matches_copper_clear_example():
    # Mirrors assets/examples/copper_clear_gerber.FlatScript:
    #   open_gerber test.gbr -outname gerber_file
    #   ncc gerber_file ... -outname gerber_ncc
    #   cncjob gerber_ncc -dia .. -z_cut .. -z_move .. -feedrate .. -outname gerber_ncc_cnc
    #   write_gcode gerber_ncc_cnc <path>
    job = jm.Job(name="parity", units="MM")
    job.add_step(jm.Step(jm.OPEN_GERBER, {"file": "test.gbr", "outname": "gerber_file"}))
    job.add_step(jm.Step(jm.NCC, {"name": "gerber_file", "overlap": 10.0,
                                  "tooldia": "0.254", "method": "seed",
                                  "margin": 2.0, "outname": "gerber_ncc"}))
    job.add_step(jm.Step(jm.CNCJOB, {"name": "gerber_ncc", "dia": 0.254,
                                     "z_cut": -0.05, "z_move": 3.0, "feedrate": 100.0,
                                     "outname": "gerber_ncc_cnc"}))
    job.add_step(jm.Step(jm.EXPORT_GCODE, {"name": "gerber_ncc_cnc",
                                           "filename": "out/copper_clear.gcode"}))

    lines = jc.compile_job_lines(job)
    assert lines[0].startswith("open_gerber ") and "-outname {gerber_file}" in lines[0]
    assert lines[1].startswith("ncc {gerber_file}")
    assert "-overlap 10" in lines[1] and "-tooldia {0.254}" in lines[1]
    assert "-method {seed}" in lines[1] and "-outname {gerber_ncc}" in lines[1]
    assert lines[2].startswith("cncjob {gerber_ncc}")
    for frag in ("-dia 0.254", "-z_cut -0.05", "-z_move 3", "-feedrate 100",
                 "-outname {gerber_ncc_cnc}"):
        assert frag in lines[2], frag
    assert lines[3].startswith("write_gcode {gerber_ncc_cnc} {out/copper_clear.gcode}")
    # every command is a known shipped Tcl command
    for line in lines:
        assert line.split()[0] in {"open_gerber", "open_excellon", "isolate",
                                   "ncc", "cncjob", "drillcncjob", "cutout",
                                   "write_gcode"}


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

"""Run all headless Job Automation tests (no Qt / no display required).

    python tests/run_all.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

MODULES = [
    "test_job_model",
    "test_job_compiler",
    "test_job_runner",
    "test_presets",
    "test_integration_parity",
]


def main():
    total_failed = 0
    for name in MODULES:
        mod = __import__(name)
        print("\n==== %s ====" % name)
        total_failed += mod._run_all()
    print("\n========================================")
    print("ALL SUITES: %s" % ("PASS" if total_failed == 0 else "%d FAILED" % total_failed))
    return total_failed


if __name__ == "__main__":
    sys.exit(1 if main() else 0)

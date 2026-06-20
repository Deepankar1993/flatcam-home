# ##########################################################
# FlatCAM Evo: Job Automation - execution core             #
# Pure Python. NO Qt, NO tkinter at module import.         #
# The Qt wrapper (in the plugin) supplies the eval fn.     #
# MIT Licence                                              #
# ##########################################################
"""
Sequencing + failure-detection logic for running a compiled Job.

This is deliberately Qt/tkinter-free so the *novel* behaviour - abort-on-error
and stop-between-steps - is unit-testable with a mock eval function. The plugin
wraps :func:`execute_lines`, passing ``self.app.shell.tcl.eval`` as ``eval_fn``
and emitting Qt signals from the ``on_step`` callback.

CRITICAL (spec section 11.3, senior-dev review C1/C2):

* ``eval_fn`` MUST be invoked on the GUI thread by the caller. The FlatCAM Tcl
  interpreter has tkinter thread-affinity and each signalled command spins its
  own nested Qt event loop (which is what keeps the GUI responsive per-step).
  Do NOT run this from a worker thread.
* A step is a FAILURE if ``eval_fn`` raises (``tkinter.TclError`` for real
  command errors) OR returns a string that signals failure. Relying only on a
  ``"fail"`` return value misses most errors, which surface as exceptions or as
  error strings like ``"Operation failed: ..."``.
"""

# Return-value substrings that indicate a failed command even when no exception
# was raised (transcribed from the Tcl command error returns).
FAILURE_MARKERS = (
    "Operation failed",
    "Could not retrieve",
    "[ERROR",
    "[WARNING_NOTCL",
    "Failed to",
)


def is_failure_result(result):
    """True if a (non-exception) Tcl return value indicates failure."""
    if result is None:
        return False
    s = str(result).strip()
    if s.lower() == "fail":
        return True
    return any(marker in s for marker in FAILURE_MARKERS)


class StepResult:
    __slots__ = ("index", "line", "ok", "message", "skipped")

    def __init__(self, index, line, ok, message="", skipped=False):
        self.index = index
        self.line = line
        self.ok = ok
        self.message = message
        self.skipped = skipped

    def __repr__(self):
        state = "SKIP" if self.skipped else ("OK" if self.ok else "FAIL")
        return "StepResult(#%d %s %r)" % (self.index, state, self.line)


def execute_lines(eval_fn, lines, on_step=None, should_stop=None,
                  is_failure=is_failure_result, read_error=None):
    """Run compiled Tcl ``lines`` one at a time, aborting on the first failure.

    :param eval_fn:    callable(line:str) -> str ; may raise on error.
    :param lines:      list of Tcl command strings (one per step).
    :param on_step:    optional callable(phase, StepResult) where phase is
                       'start' (before eval, ok/message unset) or 'finish'.
    :param should_stop: optional callable() -> bool, checked BEFORE each step;
                       a True return halts the run cleanly (remaining steps are
                       marked skipped). An in-flight step is never interrupted.
    :param is_failure: callable(result:str) -> bool for non-exception results.
    :param read_error: optional callable() -> str, used to fetch a richer error
                       message after an exception (e.g. Tcl ``errorInfo``).
    :returns: list[StepResult] (one per input line).
    """
    results = []
    aborted = False

    for index, line in enumerate(lines):
        # Stop requested or a previous step failed -> mark the rest as skipped.
        if aborted or (should_stop is not None and should_stop()):
            res = StepResult(index, line, ok=False, message="skipped", skipped=True)
            results.append(res)
            if on_step:
                on_step("finish", res)
            aborted = True
            continue

        start = StepResult(index, line, ok=False, message="")
        if on_step:
            on_step("start", start)

        try:
            raw = eval_fn(line)
        except Exception as exc:  # tkinter.TclError and anything else
            message = ""
            if read_error is not None:
                try:
                    message = str(read_error()) or ""
                except Exception:  # noqa
                    message = ""
            if not message:
                message = str(exc)
            res = StepResult(index, line, ok=False, message=message)
            results.append(res)
            if on_step:
                on_step("finish", res)
            aborted = True
            continue

        ok = not is_failure(raw)
        res = StepResult(index, line, ok=ok, message="" if ok else str(raw))
        results.append(res)
        if on_step:
            on_step("finish", res)
        if not ok:
            aborted = True

    return results

# ##########################################################
# FlatCAM Evo: Job Automation - Tcl compiler               #
# Pure Python. NO Qt, NO appMain imports. Headless-safe.   #
# MIT Licence                                              #
# ##########################################################
"""
Compile a ``Job`` into the existing, tested FlatCAM Tcl commands.

Design notes (see spec section 11.3/11.4):

* Output is a list of *structured per-step invocations*: ``(alias, [tokens])``
  where every token is already safely quoted. The runner joins the tokens of
  one step into a single line and ``tcl.eval``s it. We never build a multi-line
  script blob.
* Every file path (and any value that may contain whitespace or Tcl-special
  characters) is wrapped in Tcl braces ``{...}`` after normalizing ``\\`` -> ``/``.
  Braces suppress *all* Tcl substitution ($ , [ , \\), which neutralizes Windows
  paths with spaces. This is the single most important correctness rule here.
* ``set_sys`` is never emitted: it mutates global app state and breaks per-step
  isolation. Every parameter is passed as an explicit command flag. A parameter
  with no flag is simply not supported.

The flag tables below were transcribed from the actual ``tclCommands/*`` option
dictionaries, not from memory.
"""

from appAutomation import job_model as jm


class CompileError(ValueError):
    """Raised when a Job cannot be safely compiled (e.g. a path with braces)."""


# Tcl characters that force brace-quoting of a token.
_NEEDS_BRACE = set(' \t\n\r$[]"\\;{}')


def tcl_brace(value):
    """Quote an arbitrary string as a single safe Tcl token using braces.

    Braces disable every form of Tcl substitution, so the content is passed
    through literally. Backslashes are *not* normalized here (callers that pass
    paths should use :func:`tcl_path`). A literal unbalanced ``{``/``}`` cannot
    be represented inside braces, so we reject it rather than emit a corrupt
    command."""
    s = "" if value is None else str(value)
    if "{" in s or "}" in s:
        raise CompileError(
            "Value contains a brace character which cannot be safely quoted "
            "for Tcl: %r" % (s,))
    # Always brace - deterministic output and safe for empty strings too.
    return "{%s}" % s


def tcl_path(value):
    """Quote a filesystem path: normalize Windows backslashes to forward
    slashes (Tcl accepts ``/`` on Windows) then brace-quote."""
    s = "" if value is None else str(value)
    s = s.replace("\\", "/")
    return tcl_brace(s)


def _fmt(value):
    """Format a scalar param value as a bare (unquoted) Tcl token.
    Used for numbers / simple identifiers that never contain spaces."""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, float):
        # %g gives clean, deterministic output: 0.1 -> '0.1', -0.05 -> '-0.05',
        # 2.0 -> '2'. Good enough for Tcl float args and stable for tests.
        return "%g" % value
    if isinstance(value, int):
        return str(value)
    return str(value)


# --------------------------------------------------------------------------- #
# Per-step-type flag tables: param-key -> tcl-flag.
# Only keys present in a step's params (and not None) are emitted.
# Positional args are handled explicitly per step below.
# --------------------------------------------------------------------------- #
_ISOLATE_FLAGS = {
    "dia": "dia", "passes": "passes", "overlap": "overlap",
    "combine": "combine", "iso_type": "iso_type", "outname": "outname",
}
_NCC_FLAGS = {
    "tooldia": "tooldia", "overlap": "overlap", "order": "order",
    "margin": "margin", "method": "method", "connect": "connect",
    "contour": "contour", "offset": "offset", "rest": "rest",
    "all": "all", "ref": "ref", "box": "box", "outname": "outname",
}
_CNCJOB_FLAGS = {
    "dia": "dia", "z_cut": "z_cut", "z_move": "z_move", "feedrate": "feedrate",
    "feedrate_z": "feedrate_z", "feedrate_rapid": "feedrate_rapid",
    "extracut_length": "extracut_length", "dpp": "dpp",
    "toolchangez": "toolchangez", "toolchangexy": "toolchangexy",
    "startz": "startz", "endz": "endz", "endxy": "endxy",
    "spindlespeed": "spindlespeed", "dwelltime": "dwelltime",
    "pp": "pp", "outname": "outname",
}
_DRILL_FLAGS = {
    "drilled_dias": "drilled_dias", "drillz": "drillz", "dpp": "dpp",
    "travelz": "travelz", "feedrate_z": "feedrate_z",
    "feedrate_rapid": "feedrate_rapid", "spindlespeed": "spindlespeed",
    "toolchangez": "toolchangez", "toolchangexy": "toolchangexy",
    "startz": "startz", "endz": "endz", "endxy": "endxy",
    "dwelltime": "dwelltime", "pp": "pp", "opt_type": "opt_type",
    "diatol": "diatol", "outname": "outname",
}
_CUTOUT_FLAGS = {
    "type": "type", "dia": "dia", "margin": "margin",
    "gapsize": "gapsize", "gaps": "gaps", "outname": "outname",
}

# Coordinate-pair flags that must contain NO spaces (e.g. "0,0"). The Tcl
# tokenizer would otherwise split "0, 0" into two tokens.
_NOSPACE_COORD_FLAGS = {"toolchangexy", "endxy"}

# String flags whose value may contain spaces / specials and so must be braced
# (e.g. preprocessor names are safe, but be defensive for ref/box selectors).
# NOTE: 'combine'/'rest' carry bool-ish values and are emitted bare (True/False);
# they are intentionally NOT here. 'outname'/'name' are user object names that may
# contain spaces, so they are braced.
_STRING_FLAGS = {"pp", "opt_type", "order", "method", "connect", "contour",
                 "ref", "box", "gaps", "type", "tooldia", "drilled_dias",
                 "outname"}


def _emit_flags(params, flag_table):
    """Yield ['-flag', value_token] for each present, non-None param."""
    tokens = []
    for key, flag in flag_table.items():
        if key not in params:
            continue
        val = params[key]
        if val is None:
            continue
        if key in _NOSPACE_COORD_FLAGS:
            token = tcl_brace(str(val).replace(" ", ""))
        elif key in _STRING_FLAGS:
            token = tcl_brace(val)
        else:
            token = _fmt(val)
        tokens.append("-%s" % flag)
        tokens.append(token)
    return tokens


def compile_step(step):
    """Compile one ``Step`` into ``(alias, [tokens])`` or ``None`` if disabled.
    Raises ``CompileError`` for unsafe/incomplete steps."""
    if not step.enabled:
        return None

    t = step.type
    p = step.params

    if t == jm.OPEN_GERBER:
        _require(p, "file", t)
        tokens = [tcl_path(p["file"])]
        if p.get("outname"):
            tokens += ["-outname", tcl_brace(p["outname"])]
        return ("open_gerber", tokens)

    if t == jm.OPEN_EXCELLON:
        _require(p, "file", t)
        tokens = [tcl_path(p["file"])]
        if p.get("outname"):
            tokens += ["-outname", tcl_brace(p["outname"])]
        return ("open_excellon", tokens)

    if t == jm.ISOLATE:
        _require(p, "name", t)
        return ("isolate", [tcl_brace(p["name"])] + _emit_flags(p, _ISOLATE_FLAGS))

    if t == jm.NCC:
        _require(p, "name", t)
        return ("ncc", [tcl_brace(p["name"])] + _emit_flags(p, _NCC_FLAGS))

    if t == jm.CNCJOB:
        _require(p, "name", t)
        return ("cncjob", [tcl_brace(p["name"])] + _emit_flags(p, _CNCJOB_FLAGS))

    if t == jm.DRILLCNCJOB:
        _require(p, "name", t)
        return ("drillcncjob", [tcl_brace(p["name"])] + _emit_flags(p, _DRILL_FLAGS))

    if t == jm.CUTOUT:
        _require(p, "name", t)
        return ("cutout", [tcl_brace(p["name"])] + _emit_flags(p, _CUTOUT_FLAGS))

    if t == jm.EXPORT_GCODE:
        _require(p, "name", t)
        _require(p, "filename", t)
        return ("write_gcode", [tcl_brace(p["name"]), tcl_path(p["filename"])])

    raise CompileError("Cannot compile unknown step type: %r" % (t,))


def compile_job(job):
    """Compile a ``Job`` into a list of ``(alias, [tokens])`` for enabled steps."""
    out = []
    for step in job.steps:
        inv = compile_step(step)
        if inv is not None:
            out.append(inv)
    return out


def invocation_to_line(invocation):
    """Join an ``(alias, [tokens])`` invocation into a single Tcl line."""
    alias, tokens = invocation
    return " ".join([alias] + tokens)


def compile_job_lines(job):
    """Convenience: compile a ``Job`` directly to a list of Tcl command lines."""
    return [invocation_to_line(inv) for inv in compile_job(job)]


def _require(params, key, step_type):
    if not params.get(key):
        raise CompileError("Step %r is missing required parameter %r." % (step_type, key))

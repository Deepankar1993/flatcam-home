# ##########################################################
# FlatCAM Evo: Job Automation - step field schema          #
# Pure Python. NO Qt. Drives the per-step editor form and  #
# is unit-testable headlessly.                             #
# MIT Licence                                              #
# ##########################################################
"""
Declarative metadata describing the editable fields of each step type.

The UI reads this to build a dynamic parameter form for the selected step, and
``default_params`` seeds a freshly added step so it is fully specified (and thus
reproducible / compilable) from the start.

Field dict keys:
    key       - the param key written into Step.params (and emitted by the compiler)
    label     - human label for the form row
    type      - one of the FT_* field-type constants below
    default   - (optional) default value used when adding a step
    min/max   - (optional) numeric range
    precision - (optional) decimals for float fields
    choices   - (optional) list of (value, label) for FT_CHOICE
    obj_kind  - (optional) for FT_OBJECT: which loaded-object kind to suggest
    tooltip   - (optional) help text
"""

from appAutomation import job_model as jm

# Field types
FT_OBJECT = "object"      # an object name (editable combo: loaded objects + earlier outputs)
FT_FLOAT = "float"
FT_INT = "int"
FT_BOOL = "bool"
FT_CHOICE = "choice"
FT_STRING = "string"
FT_PATH_OPEN = "path_open"
FT_PATH_SAVE = "path_save"
FT_PREPROC = "preproc"    # preprocessor / G-code dialect name

_ISO_TYPES = [(0, "Exterior"), (1, "Interior"), (2, "Full")]
_NCC_METHODS = [("seed", "Seed"), ("lines", "Lines"), ("standard", "Standard")]
_CUTOUT_SHAPE = [("any", "Any shape"), ("rect", "Rectangular")]
_CUTOUT_GAPS = [("none", "None"), ("tb", "Top/Bottom"), ("lr", "Left/Right"),
                ("4", "One each side"), ("8", "Two each side")]


SCHEMA = {
    jm.OPEN_GERBER: [
        {"key": "file", "label": "Gerber file", "type": FT_PATH_OPEN},
        {"key": "outname", "label": "Output name", "type": FT_STRING, "default": "gerber"},
    ],
    jm.OPEN_EXCELLON: [
        {"key": "file", "label": "Excellon file", "type": FT_PATH_OPEN},
        {"key": "outname", "label": "Output name", "type": FT_STRING, "default": "drill"},
    ],
    jm.ISOLATE: [
        {"key": "name", "label": "Source Gerber", "type": FT_OBJECT, "obj_kind": "gerber"},
        {"key": "dia", "label": "Tool diameter", "type": FT_FLOAT,
         "default": 0.1, "min": 0.0001, "max": 100.0, "precision": 4},
        {"key": "passes", "label": "Passes", "type": FT_INT, "default": 1, "min": 1, "max": 99},
        {"key": "overlap", "label": "Overlap %", "type": FT_FLOAT,
         "default": 10.0, "min": 0.0, "max": 99.99, "precision": 2},
        {"key": "combine", "label": "Combine passes", "type": FT_BOOL, "default": True},
        {"key": "iso_type", "label": "Isolation", "type": FT_CHOICE,
         "choices": _ISO_TYPES, "default": 2},
        {"key": "outname", "label": "Output name", "type": FT_STRING, "default": "iso"},
    ],
    jm.NCC: [
        {"key": "name", "label": "Source Gerber", "type": FT_OBJECT, "obj_kind": "gerber"},
        {"key": "tooldia", "label": "Tool dia(s)", "type": FT_STRING, "default": "0.5"},
        {"key": "overlap", "label": "Overlap %", "type": FT_FLOAT,
         "default": 40.0, "min": 0.0, "max": 99.99, "precision": 2},
        {"key": "margin", "label": "Margin", "type": FT_FLOAT,
         "default": 1.0, "min": 0.0, "max": 100.0, "precision": 4},
        {"key": "method", "label": "Method", "type": FT_CHOICE,
         "choices": _NCC_METHODS, "default": "seed"},
        {"key": "rest", "label": "Rest machining", "type": FT_BOOL, "default": False},
        {"key": "outname", "label": "Output name", "type": FT_STRING, "default": "ncc"},
    ],
    jm.CNCJOB: [
        {"key": "name", "label": "Source Geometry", "type": FT_OBJECT, "obj_kind": "geometry"},
        {"key": "z_cut", "label": "Cut Z", "type": FT_FLOAT,
         "default": -0.05, "min": -100.0, "max": 0.0, "precision": 4},
        {"key": "z_move", "label": "Travel Z", "type": FT_FLOAT,
         "default": 2.0, "min": 0.0, "max": 100.0, "precision": 4},
        {"key": "feedrate", "label": "Feed rate XY", "type": FT_FLOAT,
         "default": 120.0, "min": 0.0, "max": 100000.0, "precision": 2},
        {"key": "feedrate_z", "label": "Feed rate Z", "type": FT_FLOAT,
         "default": 60.0, "min": 0.0, "max": 100000.0, "precision": 2},
        {"key": "pp", "label": "Preprocessor", "type": FT_PREPROC, "default": "default"},
        {"key": "outname", "label": "Output name", "type": FT_STRING, "default": "cnc"},
    ],
    jm.DRILLCNCJOB: [
        {"key": "name", "label": "Source Excellon", "type": FT_OBJECT, "obj_kind": "excellon"},
        {"key": "drilled_dias", "label": "Drill dias", "type": FT_STRING, "default": "all"},
        {"key": "drillz", "label": "Drill Z", "type": FT_FLOAT,
         "default": -1.7, "min": -100.0, "max": 0.0, "precision": 4},
        {"key": "travelz", "label": "Travel Z", "type": FT_FLOAT,
         "default": 2.0, "min": 0.0, "max": 100.0, "precision": 4},
        {"key": "feedrate_z", "label": "Feed rate Z", "type": FT_FLOAT,
         "default": 300.0, "min": 0.0, "max": 100000.0, "precision": 2},
        {"key": "pp", "label": "Preprocessor", "type": FT_PREPROC, "default": "default"},
        {"key": "outname", "label": "Output name", "type": FT_STRING, "default": "drill_cnc"},
    ],
    jm.CUTOUT: [
        {"key": "name", "label": "Source (outline)", "type": FT_OBJECT, "obj_kind": "gerber"},
        {"key": "type", "label": "Shape", "type": FT_CHOICE,
         "choices": _CUTOUT_SHAPE, "default": "any"},
        {"key": "dia", "label": "Tool diameter", "type": FT_FLOAT,
         "default": 1.0, "min": 0.0001, "max": 100.0, "precision": 4},
        {"key": "margin", "label": "Margin", "type": FT_FLOAT,
         "default": 0.0, "min": 0.0, "max": 100.0, "precision": 4},
        {"key": "gapsize", "label": "Gap size", "type": FT_FLOAT,
         "default": 3.0, "min": 0.0, "max": 100.0, "precision": 3},
        {"key": "gaps", "label": "Holding tabs", "type": FT_CHOICE,
         "choices": _CUTOUT_GAPS, "default": "4"},
        {"key": "outname", "label": "Output name", "type": FT_STRING, "default": "cutout"},
    ],
    jm.EXPORT_GCODE: [
        {"key": "name", "label": "CNC Job object", "type": FT_OBJECT, "obj_kind": "cncjob"},
        {"key": "filename", "label": "G-code file", "type": FT_PATH_SAVE},
    ],
}

# Human label for each step type (for the Add menu + table summary verb)
STEP_LABELS = {
    jm.OPEN_GERBER: "Open Gerber",
    jm.OPEN_EXCELLON: "Open Excellon",
    jm.ISOLATE: "Isolate",
    jm.NCC: "Copper clear (NCC)",
    jm.CNCJOB: "CNC Job",
    jm.DRILLCNCJOB: "Drill CNC Job",
    jm.CUTOUT: "Cutout",
    jm.EXPORT_GCODE: "Export G-code",
}


def fields_for(step_type):
    return SCHEMA.get(step_type, [])


def default_params(step_type):
    """Default param dict for a freshly added step (only fields that have a default)."""
    out = {}
    for f in fields_for(step_type):
        if "default" in f:
            out[f["key"]] = f["default"]
    return out


def summarize(step):
    """One-line human summary of a step for the table 'Step' column."""
    verb = STEP_LABELS.get(step.type, step.type)
    p = step.params
    src = p.get("name") or p.get("file") or ""
    extra = ""
    if step.type == jm.ISOLATE:
        extra = "dia %s, %s pass" % (p.get("dia", "?"), p.get("passes", "?"))
    elif step.type == jm.CNCJOB:
        extra = "Zcut %s, pp %s" % (p.get("z_cut", "?"), p.get("pp", "?"))
    elif step.type == jm.DRILLCNCJOB:
        extra = "Zdrill %s" % (p.get("drillz", "?"),)
    elif step.type == jm.CUTOUT:
        extra = "tabs %s" % (p.get("gaps", "?"),)
    elif step.type == jm.NCC:
        extra = "dia %s" % (p.get("tooldia", "?"),)
    elif step.type == jm.EXPORT_GCODE:
        src = p.get("filename", "")
    head = "%s: %s" % (verb, src) if src else verb
    return "%s  (%s)" % (head, extra) if extra else head

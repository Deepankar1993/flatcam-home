# ##########################################################
# FlatCAM Evo: Job Automation - built-in presets           #
# Pure Python. NO Qt. Builds a Job from file bindings.     #
# MIT Licence                                              #
# ##########################################################
"""
Built-in job presets: the "pick files -> preset -> Go" front door.

A preset takes a set of role-tagged file bindings (top copper, bottom copper,
drills, outline) plus an output directory and a Profile, and produces a fully
formed :class:`~appAutomation.job_model.Job` ready to compile and run.

Roles (all optional; a preset uses what it needs):
    top_copper, bottom_copper, drills, outline   -> filesystem paths

Object naming is deterministic so later steps can reference earlier outputs.
"""
import os

from appAutomation import job_model as jm

# Role keys
TOP_COPPER = "top_copper"
BOTTOM_COPPER = "bottom_copper"
DRILLS = "drills"
OUTLINE = "outline"

ROLES = [TOP_COPPER, BOTTOM_COPPER, DRILLS, OUTLINE]


def _out(out_dir, name, ext="gcode"):
    return os.path.join(out_dir or "", "%s.%s" % (name, ext))


def _iso_chain(steps, profile_settings, src_obj, tag, out_dir):
    """isolate -> cncjob -> export for one copper layer object named ``src_obj``."""
    iso_name = "%s_iso" % tag
    cnc_name = "%s_cnc" % tag
    iso_p = {"name": src_obj, "outname": iso_name}
    iso_p.update(profile_settings.get(jm.ISOLATE, {}))
    steps.append(jm.Step(jm.ISOLATE, iso_p, label="Isolate %s" % tag))

    cnc_p = {"name": iso_name, "outname": cnc_name}
    cnc_p.update(profile_settings.get(jm.CNCJOB, {}))
    steps.append(jm.Step(jm.CNCJOB, cnc_p, label="CNC Job %s" % tag))

    steps.append(jm.Step(jm.EXPORT_GCODE,
                         {"name": cnc_name, "filename": _out(out_dir, tag + "_iso")},
                         label="Export %s" % tag))


def build_isolation_single(bindings, out_dir, profile):
    """Single-sided isolation routing: open top copper -> isolate -> cnc -> export."""
    settings = profile.settings if profile else {}
    steps = []
    top = bindings.get(TOP_COPPER)
    if not top:
        raise ValueError("This preset needs a Top Copper Gerber file.")
    steps.append(jm.Step(jm.OPEN_GERBER, {"file": top, "outname": "top"},
                         label="Open Top Copper"))
    _iso_chain(steps, settings, "top", "top", out_dir)
    return jm.Job(name="Single-sided isolation", units=_units(profile),
                  steps=steps, profile=profile)


def build_isolation_drill_cutout(bindings, out_dir, profile):
    """Isolation + drilling + cutout. Drill BEFORE cutout (board stays fixed)."""
    settings = profile.settings if profile else {}
    steps = []
    top = bindings.get(TOP_COPPER)
    if not top:
        raise ValueError("This preset needs a Top Copper Gerber file.")
    steps.append(jm.Step(jm.OPEN_GERBER, {"file": top, "outname": "top"},
                         label="Open Top Copper"))
    if bindings.get(DRILLS):
        steps.append(jm.Step(jm.OPEN_EXCELLON,
                             {"file": bindings[DRILLS], "outname": "drl"},
                             label="Open Drills"))
    if bindings.get(OUTLINE):
        steps.append(jm.Step(jm.OPEN_GERBER,
                             {"file": bindings[OUTLINE], "outname": "edge"},
                             label="Open Outline"))

    _iso_chain(steps, settings, "top", "top", out_dir)

    # Drill first.
    if bindings.get(DRILLS):
        drill_p = {"name": "drl", "drilled_dias": "all", "outname": "drl_cnc"}
        drill_p.update(settings.get(jm.DRILLCNCJOB, {}))
        steps.append(jm.Step(jm.DRILLCNCJOB, drill_p, label="Drill CNC Job"))
        steps.append(jm.Step(jm.EXPORT_GCODE,
                             {"name": "drl_cnc", "filename": _out(out_dir, "drill")},
                             label="Export Drill"))
    # Cutout last so the board does not shift mid-drill.
    if bindings.get(OUTLINE):
        cut_p = {"name": "edge", "outname": "edge_cut"}
        cut_p.update(settings.get(jm.CUTOUT, {}))
        steps.append(jm.Step(jm.CUTOUT, cut_p, label="Cutout"))
        cnc_p = {"name": "edge_cut", "outname": "edge_cnc"}
        cnc_p.update(settings.get(jm.CNCJOB, {}))
        steps.append(jm.Step(jm.CNCJOB, cnc_p, label="CNC Job Cutout"))
        steps.append(jm.Step(jm.EXPORT_GCODE,
                             {"name": "edge_cnc", "filename": _out(out_dir, "cutout")},
                             label="Export Cutout"))
    return jm.Job(name="Isolation + Drill + Cutout", units=_units(profile),
                  steps=steps, profile=profile)


def build_ncc_groundplane(bindings, out_dir, profile):
    """Copper pour clearing (NCC): open top -> ncc -> cnc -> export."""
    settings = profile.settings if profile else {}
    steps = []
    top = bindings.get(TOP_COPPER)
    if not top:
        raise ValueError("This preset needs a Top Copper Gerber file.")
    steps.append(jm.Step(jm.OPEN_GERBER, {"file": top, "outname": "top"},
                         label="Open Top Copper"))
    ncc_p = {"name": "top", "outname": "top_ncc"}
    ncc_p.update(settings.get(jm.NCC, {}))
    steps.append(jm.Step(jm.NCC, ncc_p, label="Clear Copper (NCC)"))
    cnc_p = {"name": "top_ncc", "outname": "top_ncc_cnc"}
    cnc_p.update(settings.get(jm.CNCJOB, {}))
    steps.append(jm.Step(jm.CNCJOB, cnc_p, label="CNC Job"))
    steps.append(jm.Step(jm.EXPORT_GCODE,
                         {"name": "top_ncc_cnc", "filename": _out(out_dir, "ncc")},
                         label="Export"))
    return jm.Job(name="NCC ground-plane", units=_units(profile),
                  steps=steps, profile=profile)


def _units(profile):
    return profile.units if profile else "MM"


# Registry: id -> (human label, builder, description)
PRESETS = {
    "iso_single": ("Single-sided isolation",
                   build_isolation_single,
                   "Open top copper, isolate, generate CNC job, export G-code."),
    "iso_drill_cutout": ("Isolation + Drill + Cutout",
                         build_isolation_drill_cutout,
                         "Full single-sided board: isolate, drill, then cut out."),
    "ncc_groundplane": ("NCC ground-plane",
                        build_ncc_groundplane,
                        "Clear excess copper (negative paint), CNC job, export."),
}

PRESET_ORDER = ["iso_single", "iso_drill_cutout", "ncc_groundplane"]


def build(preset_id, bindings, out_dir, profile=None):
    """Build a Job for ``preset_id`` from ``bindings`` (role->path) and ``out_dir``."""
    if preset_id not in PRESETS:
        raise ValueError("Unknown preset id: %r" % (preset_id,))
    _label, builder, _desc = PRESETS[preset_id]
    return builder(bindings, out_dir, profile)

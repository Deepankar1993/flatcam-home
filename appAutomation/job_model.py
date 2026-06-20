# ##########################################################
# FlatCAM Evo: Job Automation - data model                 #
# Pure Python. NO Qt, NO appMain imports. Headless-safe.   #
# MIT Licence                                              #
# ##########################################################
"""
Data model for the Job Automation feature.

Two independent concepts, deliberately separated (see design spec section 11.2):

* ``Profile`` - the *durable* machine/material/tool settings (feeds, cut depth,
  preprocessor/dialect, units). Tuned once, reused across many boards.
* ``Job`` - the *per-board* thing: an ordered list of ``Step`` plus the file
  bindings for this particular board, optionally carrying an embedded Profile.

Everything here is plain data + validation. Turning a ``Job`` into runnable Tcl
is the job of ``job_compiler`` (kept separate so the compiler stays a pure
function and is the single place new step types are added).
"""

import json
import copy

# --------------------------------------------------------------------------- #
# Step type identifiers
# --------------------------------------------------------------------------- #
OPEN_GERBER = "open_gerber"
OPEN_EXCELLON = "open_excellon"
ISOLATE = "isolate"
NCC = "ncc"
CNCJOB = "cncjob"
DRILLCNCJOB = "drillcncjob"
CUTOUT = "cutout"
EXPORT_GCODE = "export_gcode"

# Ordered for UI listing / docs.
STEP_TYPES = [
    OPEN_GERBER, OPEN_EXCELLON, ISOLATE, NCC,
    CNCJOB, DRILLCNCJOB, CUTOUT, EXPORT_GCODE,
]

# Steps that load a file into a new object.
OPEN_STEPS = {OPEN_GERBER, OPEN_EXCELLON}
# Steps that produce a new named object usable by later steps.
PRODUCING_STEPS = {OPEN_GERBER, OPEN_EXCELLON, ISOLATE, NCC, CNCJOB, DRILLCNCJOB, CUTOUT}
# Steps that produce a CNCJob (its output can be exported with write_gcode).
CNC_PRODUCING_STEPS = {CNCJOB, DRILLCNCJOB}

# Param keys that belong to the *Job/run* (the board), not the reusable Profile.
# Everything else on a step is a profile-owned tunable.
BINDING_KEYS = {"file", "filename", "outname", "name"}

# Severity levels returned by validate().
ERROR = "error"
WARNING = "warning"

VALID_UNITS = ("MM", "IN")


def new_step_id(existing_ids):
    """Return the smallest positive int id not already present (stable, testable)."""
    n = 1
    taken = set(existing_ids)
    while n in taken:
        n += 1
    return n


class Step:
    """One pipeline action. ``type`` is one of the STEP_TYPES; ``params`` holds
    both run bindings (file/outname/name) and profile-owned tunables."""

    __slots__ = ("id", "type", "label", "enabled", "side", "params")

    def __init__(self, type, params=None, label=None, enabled=True, id=None, side="top"):
        if type not in STEP_TYPES:
            raise ValueError("Unknown step type: %r" % (type,))
        self.id = id
        self.type = type
        self.label = label or type
        self.enabled = bool(enabled)
        # 'side' seam for a future Mirror / 2-sided feature (spec 11.6); unused in V1 logic.
        self.side = side
        self.params = dict(params) if params else {}

    # --- binding / tunable partition --------------------------------------- #
    def bindings(self):
        return {k: v for k, v in self.params.items() if k in BINDING_KEYS}

    def tunables(self):
        return {k: v for k, v in self.params.items() if k not in BINDING_KEYS}

    def produced_name(self):
        """Name of the object this step creates, if any."""
        if self.type not in PRODUCING_STEPS:
            return None
        return self.params.get("outname")

    # --- serialization ----------------------------------------------------- #
    def to_dict(self):
        return {
            "id": self.id,
            "type": self.type,
            "label": self.label,
            "enabled": self.enabled,
            "side": self.side,
            "params": copy.deepcopy(self.params),
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            type=d["type"],
            params=d.get("params"),
            label=d.get("label"),
            enabled=d.get("enabled", True),
            id=d.get("id"),
            side=d.get("side", "top"),
        )


class Profile:
    """Durable, reusable machine/material settings. ``settings`` maps a step
    type to a dict of default tunables for that step type."""

    __slots__ = ("name", "units", "settings")

    def __init__(self, name="Default", units="MM", settings=None):
        self.name = name
        self.units = units
        self.settings = copy.deepcopy(settings) if settings else {}

    def apply_to(self, job, overwrite=False):
        """Seed each step's profile-owned tunables from this profile.
        With overwrite=False (default) existing step values win (the step can
        override the profile); with overwrite=True the profile wins."""
        for step in job.steps:
            defaults = self.settings.get(step.type, {})
            for k, v in defaults.items():
                if k in BINDING_KEYS:
                    continue
                if overwrite or k not in step.params:
                    step.params[k] = copy.deepcopy(v)
        job.units = self.units

    def to_dict(self):
        return {"name": self.name, "units": self.units,
                "settings": copy.deepcopy(self.settings)}

    @classmethod
    def from_dict(cls, d):
        return cls(name=d.get("name", "Default"),
                   units=d.get("units", "MM"),
                   settings=d.get("settings"))


class Job:
    """An ordered pipeline for one board: steps + an optional embedded Profile."""

    FORMAT_VERSION = 1

    __slots__ = ("name", "units", "steps", "profile")

    def __init__(self, name="Untitled Job", units="MM", steps=None, profile=None):
        self.name = name
        self.units = units
        self.steps = list(steps) if steps else []
        self.profile = profile

    # --- step helpers ------------------------------------------------------ #
    def add_step(self, step):
        if step.id is None:
            step.id = new_step_id(s.id for s in self.steps if s.id is not None)
        self.steps.append(step)
        return step

    def enabled_steps(self):
        return [s for s in self.steps if s.enabled]

    # --- validation -------------------------------------------------------- #
    def validate(self):
        """Return a list of (severity, message). ERROR entries must block Run;
        WARNING entries are surfaced but do not block. Runtime-only checks
        (e.g. loaded-object units mismatch) are done by the runner, not here."""
        problems = []

        if self.units not in VALID_UNITS:
            problems.append((ERROR, "Job units must be one of %s (got %r)."
                             % (", ".join(VALID_UNITS), self.units)))

        produced = set()       # object names available to later steps
        saw_drill = False
        saw_cutout_before_drill = False

        for idx, step in enumerate(self.enabled_steps(), start=1):
            p = step.params

            # --- file bindings on open / export ---
            if step.type in OPEN_STEPS:
                if not p.get("file"):
                    problems.append((ERROR, "Step %d (%s): no input file selected."
                                     % (idx, step.type)))
                if not p.get("outname"):
                    problems.append((ERROR, "Step %d (%s): missing output object name."
                                     % (idx, step.type)))
            if step.type == EXPORT_GCODE and not p.get("filename"):
                problems.append((ERROR, "Step %d (export): no output G-code file path set."
                                 % idx))

            # --- dangling object reference ---
            ref = p.get("name")
            if ref is not None and step.type not in OPEN_STEPS:
                if ref not in produced:
                    problems.append((ERROR,
                                     "Step %d (%s) references object %r which no earlier "
                                     "step produces." % (idx, step.type, ref)))
                elif step.type == EXPORT_GCODE and ref not in self._cnc_names_upto(idx):
                    problems.append((WARNING,
                                     "Step %d (export) references %r which is not a CNC "
                                     "Job object." % (idx, ref)))

            # --- cut-Z / depth sanity (board-saver, spec 11.5) ---
            self._depth_sanity(idx, step, problems)

            # --- ordering: cutout before drilling shifts the board ---
            if step.type == DRILLCNCJOB:
                saw_drill = True
            if step.type == CUTOUT and not saw_drill:
                # remember; only warn if a drill step exists later
                saw_cutout_before_drill = True

            # register produced object for later refs
            pn = step.produced_name()
            if pn:
                produced.add(pn)

        if saw_cutout_before_drill and any(
                s.type == DRILLCNCJOB for s in self.enabled_steps()):
            problems.append((WARNING,
                             "A Cutout step runs before Drilling. Drill first so the "
                             "board does not shift or come loose during drilling."))

        return problems

    def _cnc_names_upto(self, idx):
        names = set()
        for i, step in enumerate(self.enabled_steps(), start=1):
            if i >= idx:
                break
            if step.type in CNC_PRODUCING_STEPS:
                pn = step.produced_name()
                if pn:
                    names.add(pn)
        return names

    @staticmethod
    def _depth_sanity(idx, step, problems):
        # Implausible cut depths are a classic board/tool wrecker.
        if step.type == CNCJOB and "z_cut" in step.params:
            z = _as_float(step.params.get("z_cut"))
            if z is not None:
                if z >= 0:
                    problems.append((WARNING, "Step %d (cncjob): cut Z is %s (>= 0); "
                                     "the tool will not cut." % (idx, z)))
                elif abs(z) > 10:
                    problems.append((WARNING, "Step %d (cncjob): cut Z is %s; that is very "
                                     "deep - check units (mm vs inch)." % (idx, z)))
        if step.type == DRILLCNCJOB and "drillz" in step.params:
            z = _as_float(step.params.get("drillz"))
            if z is not None and z >= 0:
                problems.append((WARNING, "Step %d (drillcncjob): drill Z is %s (>= 0); "
                                 "it will not drill." % (idx, z)))

    # --- serialization ----------------------------------------------------- #
    def to_dict(self):
        return {
            "format": "FlatJob",
            "version": self.FORMAT_VERSION,
            "name": self.name,
            "units": self.units,
            "profile": self.profile.to_dict() if self.profile else None,
            "steps": [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, d):
        prof = d.get("profile")
        return cls(
            name=d.get("name", "Untitled Job"),
            units=d.get("units", "MM"),
            steps=[Step.from_dict(s) for s in d.get("steps", [])],
            profile=Profile.from_dict(prof) if prof else None,
        )

    def to_json(self, indent=2):
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_json(cls, text):
        return cls.from_dict(json.loads(text))


def _as_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

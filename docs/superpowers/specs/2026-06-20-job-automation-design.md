# Job Automation — Design Spec

**Date:** 2026-06-20
**Status:** Revised after adversarial review (devil's-advocate / senior-dev / industry-veteran)
**Feature branch target:** `Beta_8.998`

> **Read §11 (Revisions) first** — it supersedes the original §3–§7 where they conflict.
> The original sections are kept for the design-rationale trail.

## 1. Problem

Preparing a PCB in FlatCAM Evo is highly repetitive. For every board the user manually:
load Gerber/Excellon → open the Isolation tool, set diameter/passes/overlap, generate
geometry → select the geometry, set cut-Z/feedrate/travel, generate the CNC job →
generate drilling → cutout → plot → export G-code. Dozens of clicks, repeated identically
for every board, every revision. There is no way to "set it once and run".

**Goal:** Let the user configure a board-prep pipeline **once** in the UI, save it as a
named, reusable *Job*, and run the whole sequence — generate geometry → CNC job → plot →
(optional) export — with one click and live per-step feedback.

## 2. Key research finding (why this is small, not huge)

FlatCAM already ships a complete, battle-tested **Tcl command layer** that performs every
generation step headlessly and **already solves async sequencing**:

- Commands: `open_gerber`, `open_excellon`, `isolate`, `cncjob`, `drillcncjob`, `cutout`/`geocutout`,
  `ncc`, `paint`, `milldrills`, `write_gcode`, `export_gcode`, `set_sys`, `plot_all`, `plot_objects`.
  (`tclCommands/`, registered via `register_all_commands()`.)
- `TclCommandSignaled` blocks the Tcl interpreter (QEventLoop) until the background worker
  finishes, so steps run strictly in order with no race conditions — the single hardest part
  of any pipeline runner is already done and tested.
- `script_processing(script_code)` (`appMain.py`) already executes a multi-line script
  line-by-line, aborting on any `result == 'fail'`.
- `set_sys <key> <value>` writes any of the ~500 `app.options` keys live, so per-step settings
  overrides need no new generation code.

**Conclusion:** We do **not** re-implement CAM generation. The new feature is a **workflow layer**:
a visual step builder + named-profile persistence + a progress-reporting executor that
*compiles the visual job into the existing Tcl commands and runs them through the existing engine*.
This keeps the blast radius tiny and reuses proven code.

## 3. Scope (V1 — YAGNI)

**In scope:**
- A new `ToolJobAutomation` plugin panel (AppTool) in the Plugins menu.
- An ordered, drag-reorderable **step table**. Each step is one pipeline action with its own
  parameters configured in a form.
- Supported step types in V1 (the common board pipeline):
  `Open Gerber`, `Open Excellon`, `Isolate`, `Geometry→CNCJob (cncjob)`, `Drill CNCJob (drillcncjob)`,
  `Cutout`, `Plot All`, `Export G-Code (write_gcode)`. (NCC/Paint deferred — same mechanism, add later.)
- **Save / Load named Job profiles** as JSON (`.FlatJob`) under the app data dir, plus
  Import/Export to an arbitrary path.
- **Run / Stop** with a live progress view: per-step status (pending / running / done / failed),
  the compiled command, and the resulting object name. Stop aborts before the next step.
- A preferences page for plugin defaults (e.g. "save project on finish", default export folder).

**Out of scope for V1 (explicitly deferred):**
- Multi-board folder iteration ("run this job over every Gerber in a folder").
- Conditional / branching logic, retries.
- Scheduling / run-on-project-open hooks.
- A graphical node editor. (Linear step list only.)

These are deferred, not designed away — section 8 notes the extension seams.

## 4. Architecture

Three units, each independently testable:

### 4.1 `JobModel` (pure data — no Qt, no app)
- `Step`: `{id, type, label, enabled, params: dict}`.
- `Job`: `{name, version, units, steps: [Step]}`.
- `to_dict()` / `from_dict()` for JSON round-trip.
- `validate()` → list of human-readable problems (e.g. "Step 3 cncjob references object
  'top_iso' not produced by an earlier step").
- **No imports from appMain/Qt** so it is unit-testable headlessly with plain `python`.

### 4.2 `JobCompiler` (pure function — `Job → list[str]` of Tcl lines)
- Maps each `Step` to its Tcl command string using the verified command signatures
  (`isolate <name> -dia .. -passes .. -overlap .. -outname ..`, `cncjob <name> -z_cut .. -pp ..`,
  `drillcncjob`, `cutout`, `write_gcode <name> <file>`, `plot_all`).
- Emits a `set_sys` line only for parameters that have **no** dedicated command option
  (keeps global-state mutation minimal — see Risk R2).
- Pure, deterministic, **unit-testable** (assert exact Tcl output for a given Job) — this is the
  core correctness surface and gets the heaviest tests.

### 4.3 `JobRunner` (executor + progress, Qt-aware)
- Takes the compiled Tcl lines and executes them through the **existing** engine:
  for each line, run it and inspect the result, mirroring `script_processing`'s
  fail-abort semantics, but emitting a Qt signal per step (`step_started`, `step_finished(ok, msg)`).
- Uses the existing shell/Tcl interpreter (`self.app.shell` / `tcl.eval`) so `TclCommandSignaled`
  blocking and worker dispatch are reused unchanged. The run itself is kicked onto a worker so
  the GUI stays responsive; signals marshal status back to the panel.
- `Stop` sets an abort flag checked between steps.

### 4.4 UI (`ToolJobAutomation` + `JobAutomationUI`)
- Follows the verified AppTool pattern (skeleton already drafted from `ToolCalculators`).
- Top: Job name + Load/Save/Import/Export buttons.
- Middle: `FCTable(drag_drop=True)` step list (#, Type, Summary, enabled checkbox);
  Add/Remove/Duplicate step buttons; an editor form below that binds to the selected step's params
  using `FCDoubleSpinner`/`FCSpinner`/`FCComboBox`/`RadioSet`/`FCCheckBox`.
- Bottom: Run / Stop buttons + a read-only progress list reflecting `JobRunner` signals.

## 5. Data flow

```
User edits steps in UI ──► JobModel (in memory)
        │  Save                              ▲ Load
        ▼                                    │
   .FlatJob JSON  ◄────────────────────────────────
        │
   Run ▼
   JobModel ──JobCompiler──► [tcl lines] ──JobRunner──► app.shell/tcl.eval ──► existing Tcl commands
        ▲                                                      │
        └─────────── progress signals (step ok/fail) ◄─────────┘
```

## 6. Error handling
- Pre-run `JobModel.validate()` blocks Run on structural errors (missing file, dangling object ref).
- Per-step: a `fail` result aborts the sequence (matching existing `script_processing`), the failing
  step is marked red with the interpreter error, remaining steps stay `pending`.
- `Stop` aborts cleanly between steps; an in-flight `TclCommandSignaled` step is allowed to finish
  (no mid-operation kill — matches the rest of the app).
- All user-facing strings wrapped in `_()`.

## 7. Testing strategy
The app has **no test suite** and is a GUI Qt app (Playwright/browser tools do **not** apply to Qt).
Testing is therefore layered:
1. **Headless unit tests** (new, runnable without a display) for `JobModel` (JSON round-trip,
   validate) and `JobCompiler` (exact Tcl emitted for representative jobs). These are pure-Python
   and need no Qt — the highest-value, cheapest safety net.
2. **Tcl integration smoke test**: a sample `.FlatJob` whose compiled script matches the existing
   shipped `assets/examples/*.FlatScript` pipelines, run via the existing `--shellfile --headless=1`
   path on the bundled example Gerbers, asserting expected output objects/files.
3. **Manual GUI verification checklist** (documented in the plan): load files, build a job, save,
   reload, run, observe per-step progress, export G-code.

## 8. Extension seams (for deferred features)
- `JobModel` already carries arbitrary `params`; folder-iteration becomes a `forEach` wrapper step.
- `JobCompiler` is the single place new step types are added (one mapping function each).
- `JobRunner` signals already model per-step status; retries/conditionals slot in as runner policy.

## 9. Files touched
- New: `appPlugins/ToolJobAutomation.py` (UI + plugin), `appCommon/JobModel.py`,
  `appCommon/JobCompiler.py`, `appCommon/JobRunner.py`,
  `appGUI/preferences/tools/ToolsJobAutomationPrefGroupUI.py`,
  `tests/test_job_compiler.py`, `tests/test_job_model.py`.
- Edit: `appPlugins/__init__.py` (import), `appMain.py` (`__init__` null decl, `install_tools()`
  instantiate+install, `app_plugins` list), `defaults.py` (`tools_job_auto_*` keys),
  `appGUI/preferences/.../Plugins2PreferencesUI.py` + `PreferencesUIManager.py` (wire prefs),
  `CHANGELOG.md`, `FEATURES.md`.

## 10. Open decisions (resolved by default, autonomous mode)
- **D1 Engine = compile-to-Tcl** (not a native async executor). Rationale: reuses the only code
  path that already solves sequencing; lowest risk. *(Alternative considered: direct pipeline calls
  via `new_object` callbacks — rejected for V1 as it re-derives async ordering that Tcl already nails.)*
- **D2 Profile format = JSON `.FlatJob`** in app data dir, consistent with `.FlatConfig`/`.FlatScript`.
- **D3 Linear step list**, not a node graph (YAGNI).

---

## 11. REVISIONS (post-review) — authoritative for V1

Three reviews converged. The engineering instinct (compile to the existing, tested Tcl
commands) was endorsed; the *threading*, *quoting*, *failure-detection*, and *product model*
all required correction. The following supersedes earlier sections on conflict.

### 11.1 Value reframing (devil's-advocate + veteran)
Execution is mostly solved by the existing Tcl layer; the genuine, non-redundant value is
**reproducibility + authoring UX**, delivered by the *Profile/Job separation* below — something
a hard-coded `.FlatScript` cannot express. The headline capability is "tune your machine/material
settings **once**, re-apply to any board's files, with guardrails," not "save clicks."

### 11.2 Profile vs Job separation (veteran — highest-value change)
- **Profile** (durable): all machine/material/tool tunables — feeds, cut-Z, travel-Z, spindle,
  isolation dia/passes/overlap, preprocessor (G-code dialect), **units**. Tuned once, reused across
  hundreds of boards. *This is the product.*
- **Job** (per-board): an ordered list of steps + **file bindings** (role-tagged: top copper /
  bottom copper / drills / outline) + a reference to a Profile. File paths resolved at run time.
- Persistence: a single JSON file may hold `{profile, bindings, steps}`; "Save Profile" writes only
  the `profile` section for reuse. `JobModel` splits `params` into *profile tunables* vs *run bindings*.

### 11.3 Execution model — CORRECTED (senior dev C1/C2, devil's-advocate #4)
- The runner drives `self.app.shell.tcl.eval(line)` **one step at a time on the GUI thread**
  (NOT a worker — tkinter has thread affinity and each `TclCommandSignaled` already spins its own
  nested `QEventLoop` + worker dispatch, which is what keeps the GUI responsive). This reuses the
  exact path the Script "Run" button already uses.
- Failure detection per step (do NOT rely on `result == 'fail'`):
  catch `tk.TclError` (then read `tcl.eval("set errorInfo")` for the message) **and** treat a
  returned `"fail"` or a known error-string prefix (`"Operation failed"`, `"Could not retrieve"`,
  `"[ERROR"`, `"[WARNING"`) as failure. On failure: mark step red, abort remaining steps.
- `JobCompiler` emits **structured per-step invocations** `(command_alias, [tcl_tokens])`, already
  quoted; the runner joins tokens into one line per step. No multi-line script blob.

### 11.4 Quoting/escaping — MANDATORY (senior dev H1)
- Every file path and any space-bearing value is emitted as a **Tcl brace token** `{...}` with
  backslashes normalized to `/`. Braces suppress all Tcl substitution (`$`, `[`, `\`), neutralizing
  Windows paths with spaces. Reject/escape literal `{`/`}` in paths.
- `toolchangexy`/`endxy` emitted as `0,0` (no spaces).
- **No `set_sys`** in the compiler. Every parameter passes as an explicit command flag; if a needed
  parameter has no command flag, that step type is out of V1 scope (avoids global-state leakage).

### 11.5 Guardrails in `validate()` — board-savers (veteran #4)
- **Units hard-block:** if a loaded Gerber/Excellon's units differ from the Job units → block Run.
- **Cut-Z sanity:** warn if |cut-Z| is implausibly large; for Cutout warn if cut-Z won't exceed
  typical board thickness (won't cut through).
- **Ordering:** warn if a Cutout step precedes Drill for the same board (board shifts mid-drill).
- Dangling object-ref check (a step references an outname no earlier step produced) and missing files.

### 11.6 Step set — REVISED (veteran #1)
V1 step types: `Open Gerber`, `Open Excellon`, `Isolate` (allow **multiple** isolation steps for
multi-tool/rest), `NCC` (copper clear — promoted to V1, it is a primary workflow), `CNCJob`
(geometry→cnc), `Drill CNCJob`, `Cutout`, `Export G-Code`. **`Plot All` is dropped as a user step**
— the runner auto-plots each produced object and offers a verify gate before export.
Model carries a `side` field seam so a future Mirror/2-sided step slots in without rework.

### 11.7 UX — front door + advanced (veteran #5)
- Front door: role-tagged **file pickers** + a **Profile/preset** selector + a big **Run** button +
  live per-step progress (pending/running/done/failed) + auto-plot verify gate.
- The drag-reorderable **step editor** is demoted into a collapsible "Advanced — Edit steps" section.
- Ship 2–3 built-in presets (single-sided V-bit isolation, NCC ground-plane, drill+cutout).

### 11.8 Code placement / registration (senior dev H2/H3)
- `JobModel`/`JobCompiler` are standalone modules with **no Qt and no `appCommon.Common` import**
  (so headless unit tests import cleanly). Place under `appCommon/` only if package import has no
  side effects; otherwise a new `appAutomation/` package.
- Registration checklist adds the **top-of-`appMain.py` import** of the plugin (mirror how
  `ToolCalculator` is imported), in addition to `appPlugins/__init__.py`, `install_tools()`,
  and the `app_plugins` list.

### 11.9 Testing — inverted priorities (all three)
1. **Compiler quoting tests are the centerpiece**: Windows path w/ spaces+backslashes → `{C:/.../x.gbr}`;
   `toolchangexy` → `0,0`; assert **no `set_sys`** ever emitted.
2. **Runner abort/Stop semantics test**: a mock `tcl.eval` that raises `TclError` aborts the
   sequence; Stop flag halts between steps. (This is the novel risk surface — must be tested, not
   left to a manual checklist.)
3. **Headless integration smoke**: compile a sample Job over the bundled `assets/examples` Gerbers,
   run via `--shellfile --headless=1`, assert output G-code files exist. (Tests the Tcl path; noted.)
4. `JobModel` round-trip + each `validate()` guardrail (units block, cutout-before-drill, dangling ref).

### 11.10 V2 seam (documented, not built)
Native Python command-pattern (call object pipeline methods directly) is the better long-term design
but duplicates the Tcl layer's large default-resolution logic — deferred. Mirror/2-sided, folder
iteration, auto-leveling hooks, conditional/retry all slot onto the existing seams (`Step.params`,
one compiler mapping per type, runner per-step signals).

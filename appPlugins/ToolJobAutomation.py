# ##########################################################
# FlatCAM Evo: Job Automation Plugin                       #
# File Author: FlatCAM Evo Team                            #
# MIT Licence                                              #
# ##########################################################

from PyQt6 import QtWidgets, QtGui, QtCore
from appTool import AppTool
from appGUI.GUIElements import (VerticalScrollArea, FCLabel, FCButton, FCFrame,
                                GLay, FCEntry, FCComboBox, FCTable, FCCheckBox,
                                FCSpinner, FCDoubleSpinner)

import logging
import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

log = logging.getLogger('base')

# Preset combo index -> preset id
_PRESET_BY_INDEX = ["iso_drill_cutout", "ncc_groundplane"]
_PRESET_LABELS = [_("Isolation routing"), _("Copper clear (NCC ground-plane)")]
_PRESET_DESC = [
    _("Isolate the copper of the selected Gerber, generate the CNC job and export. "
      "Optionally add drilling and board cutout below."),
    _("Clear all excess copper (negative paint) of the selected Gerber, "
      "generate the CNC job and export."),
]


class ToolJobAutomation(AppTool):
    plugin_tooltip = _("Job Automation: pick loaded board objects, choose a workflow, "
                       "and run the whole geometry -> CNC job -> export pipeline at once.")

    def __init__(self, app):
        AppTool.__init__(self, app)

        self.app = app
        self.decimals = self.app.decimals

        self.current_job = None
        self._stop = False

        self.ui = JobAutomationUI(layout=self.layout, app=self.app)
        self.pluginName = self.ui.pluginName

    def run(self, toggle=True):
        self.app.defaults.report_usage("ToolJobAutomation()")

        if toggle:
            if self.app.ui.splitter.sizes()[0] == 0:
                self.app.ui.splitter.setSizes([1, 1])

            found_idx = None
            for idx in range(self.app.ui.notebook.count()):
                if self.app.ui.notebook.widget(idx).objectName() == "plugin_tab":
                    found_idx = idx
                    break
            if not found_idx:
                try:
                    self.app.ui.notebook.addTab(self.app.ui.plugin_tab, _("Plugin"))
                except RuntimeError:
                    self.app.ui.plugin_tab = QtWidgets.QWidget()
                    self.app.ui.plugin_tab.setObjectName("plugin_tab")
                    self.app.ui.plugin_tab_layout = QtWidgets.QVBoxLayout(self.app.ui.plugin_tab)
                    self.app.ui.plugin_tab_layout.setContentsMargins(2, 2, 2, 2)

                    self.app.ui.plugin_scroll_area = VerticalScrollArea()
                    self.app.ui.plugin_tab_layout.addWidget(self.app.ui.plugin_scroll_area)
                    self.app.ui.notebook.addTab(self.app.ui.plugin_tab, _("Plugin"))
                self.app.ui.notebook.setCurrentWidget(self.app.ui.plugin_tab)

            try:
                if self.app.ui.plugin_scroll_area.widget().objectName() == self.pluginName and found_idx:
                    if not self.app.ui.notebook.currentWidget() is self.app.ui.plugin_tab:
                        self.app.ui.notebook.setCurrentWidget(self.app.ui.plugin_tab)
                    else:
                        self.app.ui.notebook.setCurrentWidget(self.app.ui.properties_tab)
                        self.app.ui.notebook.removeTab(2)
                        if not self.app.collection.get_list():
                            self.app.ui.splitter.setSizes([0, 1])
            except AttributeError:
                pass
        else:
            if self.app.ui.splitter.sizes()[0] == 0:
                self.app.ui.splitter.setSizes([1, 1])

        super().run()
        self.set_tool_ui()
        self.app.ui.notebook.setTabText(2, _("Job Automation"))

    def install(self, icon=None, separator=None, **kwargs):
        AppTool.install(self, icon, separator, shortcut='Alt+J', **kwargs)

    def set_tool_ui(self):
        self.clear_ui(self.layout)
        self.ui = JobAutomationUI(layout=self.layout, app=self.app)
        self.pluginName = self.ui.pluginName

        # seed the output folder from the saved default
        try:
            self.ui.outdir_entry.set_value(self.app.options.get("tools_job_auto_output_dir", ""))
        except Exception:
            pass

        # preselect the currently active Gerber object as Top Copper
        try:
            sel = self.app.collection.get_active()
            if sel is not None and sel.kind == 'gerber':
                self.ui.top_combo.set_value(sel.obj_options['name'])
        except Exception:
            pass

        self.connect_signals_at_init()
        self._sync_optional_rows()
        self._on_preset_changed(self.ui.preset_combo.currentIndex())

    def connect_signals_at_init(self):
        self.ui.top_import_btn.clicked.connect(lambda: self._import_gerber(self.ui.top_combo))
        self.ui.drills_import_btn.clicked.connect(lambda: self._import_excellon(self.ui.drills_combo))
        self.ui.outline_import_btn.clicked.connect(lambda: self._import_gerber(self.ui.outline_combo))

        self.ui.drills_cb.toggled.connect(self._sync_optional_rows)
        self.ui.outline_cb.toggled.connect(self._sync_optional_rows)

        self.ui.outdir_browse_btn.clicked.connect(self._browse_outdir)
        self.ui.adv_toggle.toggled.connect(self.ui.adv_frame.setVisible)
        self.ui.preset_combo.currentIndexChanged.connect(self._on_preset_changed)

        self.ui.build_plan_btn.clicked.connect(self.on_build_plan)
        self.ui.run_btn.clicked.connect(self.on_run)
        self.ui.stop_btn.clicked.connect(self.on_stop)
        self.ui.save_job_btn.clicked.connect(self.on_save_job)
        self.ui.load_job_btn.clicked.connect(self.on_load_job)
        self.ui.reset_button.clicked.connect(self.set_tool_ui)

    # ---------------------------------------------------------------- helpers
    def _sync_optional_rows(self, *_a):
        """Enable/disable the optional Drills/Outline pickers from their checkboxes,
        and only show them for the Isolation preset."""
        is_iso = self.ui.preset_combo.currentIndex() == 0
        for cb, combo, btn in (
                (self.ui.drills_cb, self.ui.drills_combo, self.ui.drills_import_btn),
                (self.ui.outline_cb, self.ui.outline_combo, self.ui.outline_import_btn)):
            cb.setEnabled(is_iso)
            on = is_iso and cb.get_value()
            combo.setEnabled(on)
            btn.setEnabled(on)

    def _on_preset_changed(self, idx):
        if 0 <= idx < len(_PRESET_DESC):
            self.ui.preset_desc_label.setText(_PRESET_DESC[idx])
        self._sync_optional_rows()

    def _browse_outdir(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(
            None, _("Select Output Folder"), "")
        if path:
            self.ui.outdir_entry.set_value(path)

    def _import_gerber(self, combo):
        flt = _("Gerber Files (*.gbr *.ger *.gtl *.gbl *.gts *.gbs *.gto *.gbo "
                "*.gko *.gm1 *.gtp *.gbp);;All Files (*)")
        path, _sel = QtWidgets.QFileDialog.getOpenFileName(None, _("Import Gerber"), "", flt)
        if path:
            # model-bound combo with is_last=True auto-selects the new Gerber
            self.app.worker_task.emit({'fcn': self.app.f_handlers.open_gerber, 'params': [path]})

    def _import_excellon(self, combo):
        flt = _("Excellon Files (*.drl *.exc *.xln *.ncd *.tap *.drd *.txt *.nc);;All Files (*)")
        path, _sel = QtWidgets.QFileDialog.getOpenFileName(None, _("Import Excellon"), "", flt)
        if path:
            self.app.worker_task.emit({'fcn': self.app.f_handlers.open_excellon, 'params': [path]})

    def _gather_profile(self):
        from appAutomation import job_model as jm
        ui = self.ui
        pp = ui.pp_combo.currentText() if ui.pp_combo.count() else "default"
        travel = ui.travelz_entry.get_value()
        feed = ui.feedrate_entry.get_value()
        settings = {
            jm.ISOLATE: {
                "dia": ui.iso_dia_entry.get_value(),
                "passes": int(ui.iso_passes_entry.get_value()),
                "overlap": ui.iso_overlap_entry.get_value(),
            },
            jm.CNCJOB: {
                "z_cut": ui.cutz_entry.get_value(),
                "z_move": travel,
                "feedrate": feed,
                "pp": pp,
            },
            jm.DRILLCNCJOB: {
                "drillz": ui.drillz_entry.get_value(),
                "travelz": travel,
                "feedrate_z": feed,
                "pp": pp,
            },
            jm.CUTOUT: {
                "dia": ui.cut_dia_entry.get_value(),
                "gapsize": ui.cut_gap_entry.get_value(),
                "gaps": "4",
                "margin": 0.0,
                "cut_z": ui.cut_z_entry.get_value(),
            },
        }
        return jm.Profile(name="Custom", units=ui.units_combo.currentText(),
                          settings=settings)

    # ------------------------------------------------------------- build plan
    def on_build_plan(self):
        from appAutomation import presets, job_model
        from appAutomation.job_compiler import compile_job_lines, CompileError

        idx = self.ui.preset_combo.currentIndex()
        preset_id = _PRESET_BY_INDEX[idx]

        top = self.ui.top_combo.currentText().strip()
        bindings = {presets.TOP_COPPER: top}
        if idx == 0:  # isolation preset supports optional drilling/cutout
            if self.ui.drills_cb.get_value() and self.ui.drills_combo.currentText().strip():
                bindings[presets.DRILLS] = self.ui.drills_combo.currentText().strip()
            if self.ui.outline_cb.get_value() and self.ui.outline_combo.currentText().strip():
                bindings[presets.OUTLINE] = self.ui.outline_combo.currentText().strip()

        out_dir = self.ui.outdir_entry.get_value().strip()
        try:
            self.app.options["tools_job_auto_output_dir"] = out_dir
        except Exception:
            pass

        profile = self._gather_profile()

        try:
            job = presets.build_from_objects(preset_id, bindings, out_dir, profile)
        except Exception as e:
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Could not build job"), str(e)))
            return

        has_error = False
        for severity, msg in job.validate():
            if severity == job_model.ERROR:
                self.app.inform.emit('[ERROR_NOTCL] %s' % msg)
                has_error = True
            else:
                self.app.inform.emit('[WARNING_NOTCL] %s' % msg)
        if has_error:
            self.ui.run_btn.setEnabled(False)
            return

        try:
            lines = compile_job_lines(job)
        except CompileError as e:
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Compile error"), str(e)))
            self.ui.run_btn.setEnabled(False)
            return

        self.current_job = job
        self._populate_plan(job, lines)
        self.ui.run_btn.setEnabled(True)
        self.ui.status_label.setText(_("Plan ready: %d steps. Click Run Job.") % len(lines))
        self.app.inform.emit('[success] %s' % _("Job plan built. Ready to Run."))

    def _populate_plan(self, job, lines):
        steps = job.enabled_steps()
        self.ui.plan_table.setRowCount(len(lines))
        for row, (step, line) in enumerate(zip(steps, lines)):
            num = QtWidgets.QTableWidgetItem(str(row + 1))
            num.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
            name = QtWidgets.QTableWidgetItem(step.label)
            name.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
            name.setToolTip(line)
            status = QtWidgets.QTableWidgetItem(_("pending"))
            status.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
            self.ui.plan_table.setItem(row, 0, num)
            self.ui.plan_table.setItem(row, 1, name)
            self.ui.plan_table.setItem(row, 2, status)

    # -------------------------------------------------------------------- run
    def on_run(self):
        if self.current_job is None:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("No job plan. Click 'Build Plan' first."))
            return
        if not getattr(self.app, 'shell', None) or not getattr(self.app.shell, 'tcl', None):
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Tcl shell is not initialized."))
            return

        from appAutomation.job_compiler import compile_job_lines, CompileError
        from appAutomation import job_runner

        try:
            lines = compile_job_lines(self.current_job)
        except CompileError as e:
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Compile error"), str(e)))
            return

        self._stop = False
        self.ui.run_btn.setEnabled(False)
        self.ui.stop_btn.setEnabled(True)
        self.ui.status_label.setText(_("Running..."))

        def read_error():
            try:
                return self.app.shell.tcl.eval('set errorInfo')
            except Exception:
                return ""

        job_runner.execute_lines(
            eval_fn=lambda ln: self.app.shell.tcl.eval(ln),
            lines=lines,
            on_step=self._on_step,
            should_stop=lambda: self._stop,
            read_error=read_error,
        )

        self.ui.run_btn.setEnabled(True)
        self.ui.stop_btn.setEnabled(False)

        failed = any(self.ui.plan_table.item(r, 2) and
                     self.ui.plan_table.item(r, 2).text() == _("failed")
                     for r in range(self.ui.plan_table.rowCount()))
        if self._stop:
            self.ui.status_label.setText(_("Stopped by user."))
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("Job stopped by user."))
        elif failed:
            self.ui.status_label.setText(_("Finished with errors."))
        else:
            self.ui.status_label.setText(_("Job finished successfully."))
            self.app.inform.emit('[success] %s' % _("Job finished."))
            try:
                self.app.plot_all()
            except Exception:
                pass

    def _on_step(self, phase, r):
        row = r.index
        if row >= self.ui.plan_table.rowCount():
            return
        item = self.ui.plan_table.item(row, 2)
        if item is None:
            item = QtWidgets.QTableWidgetItem()
            self.ui.plan_table.setItem(row, 2, item)

        if phase == 'start':
            item.setText(_("running"))
            item.setBackground(QtGui.QColor(255, 200, 50))
            self.ui.plan_table.scrollToItem(item)
        else:
            if r.skipped:
                item.setText(_("skipped"))
                item.setBackground(QtGui.QColor(180, 180, 180))
            elif r.ok:
                item.setText(_("done"))
                item.setBackground(QtGui.QColor(100, 200, 100))
            else:
                item.setText(_("failed"))
                item.setBackground(QtGui.QColor(220, 80, 80))
                self.app.inform.emit('[ERROR_NOTCL] %s' %
                                     (_("Step %d failed: %s") % (r.index + 1, r.message)))
        QtWidgets.QApplication.processEvents()

    def on_stop(self):
        self._stop = True

    # ------------------------------------------------------------- save/load
    def on_save_job(self):
        if self.current_job is None:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("No job to save. Build a plan first."))
            return
        path, _sel = QtWidgets.QFileDialog.getSaveFileName(
            None, _("Save Job"), "", _("FlatJob Files (*.FlatJob);;All Files (*)"))
        if not path:
            return
        if not path.lower().endswith('.flatjob'):
            path += '.FlatJob'
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(self.current_job.to_json())
            self.app.inform.emit('[success] %s' % (_("Job saved: %s") % path))
        except Exception as e:
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Save failed"), str(e)))

    def on_load_job(self):
        from appAutomation.job_model import Job
        from appAutomation.job_compiler import compile_job_lines, CompileError

        path, _sel = QtWidgets.QFileDialog.getOpenFileName(
            None, _("Load Job"), "", _("FlatJob Files (*.FlatJob);;All Files (*)"))
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                job = Job.from_json(f.read())
        except Exception as e:
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Load failed"), str(e)))
            return

        self.current_job = job
        try:
            lines = compile_job_lines(job)
        except CompileError as e:
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Compile error"), str(e)))
            return
        self._populate_plan(job, lines)
        self.ui.run_btn.setEnabled(True)
        self.ui.status_label.setText(_("Loaded %d steps from file.") % len(lines))
        self.app.inform.emit('[success] %s' % (_("Job loaded: %s") % path))


class JobAutomationUI:

    pluginName = _("Job Automation")

    def __init__(self, layout, app):
        self.app = app
        self.decimals = self.app.decimals
        self.layout = layout

        # ## Title
        title_label = FCLabel("%s" % self.pluginName, size=16, bold=True)
        title_label.setToolTip(_("Run a whole board pipeline (isolate / drill / cutout -> "
                                 "CNC job -> export) from objects already loaded in the project."))
        self.layout.addWidget(title_label)

        # #############################################################
        # ## Source objects (loaded in the project)
        # #############################################################
        self.layout.addWidget(FCLabel('%s' % _("Source Objects"), color='darkorange', bold=True))
        src_frame = FCFrame()
        self.layout.addWidget(src_frame)
        src_grid = GLay(v_spacing=5, h_spacing=3)
        src_frame.setLayout(src_grid)

        # Top Copper (required) - Gerber picker bound to the collection
        top_lbl = FCLabel('%s:' % _("Top Copper"))
        top_lbl.setToolTip(_("Gerber object (already loaded) to isolate or copper-clear."))
        self.top_combo = self._object_combo(0, "Gerber")
        self.top_import_btn = self._import_btn(_("Import a Gerber file into the project."))
        src_grid.addWidget(top_lbl, 0, 0)
        src_grid.addWidget(self.top_combo, 0, 1)
        src_grid.addWidget(self.top_import_btn, 0, 2)

        # Drills (optional) - Excellon picker
        self.drills_cb = FCCheckBox('%s' % _("Drilling"))
        self.drills_cb.setToolTip(_("Include a drilling step from an Excellon object."))
        self.drills_combo = self._object_combo(1, "Excellon")
        self.drills_import_btn = self._import_btn(_("Import an Excellon file into the project."))
        src_grid.addWidget(self.drills_cb, 2, 0)
        src_grid.addWidget(self.drills_combo, 2, 1)
        src_grid.addWidget(self.drills_import_btn, 2, 2)

        # Outline (optional) - Gerber picker
        self.outline_cb = FCCheckBox('%s' % _("Cutout"))
        self.outline_cb.setToolTip(_("Include a board cutout step from an outline Gerber object."))
        self.outline_combo = self._object_combo(0, "Gerber")
        self.outline_import_btn = self._import_btn(_("Import an outline Gerber into the project."))
        src_grid.addWidget(self.outline_cb, 4, 0)
        src_grid.addWidget(self.outline_combo, 4, 1)
        src_grid.addWidget(self.outline_import_btn, 4, 2)

        # #############################################################
        # ## Workflow preset
        # #############################################################
        self.layout.addWidget(FCLabel('%s' % _("Workflow"), color='blue', bold=True))
        wf_frame = FCFrame()
        self.layout.addWidget(wf_frame)
        wf_grid = GLay(v_spacing=5, h_spacing=3)
        wf_frame.setLayout(wf_grid)

        preset_lbl = FCLabel('%s:' % _("Preset"))
        self.preset_combo = FCComboBox()
        self.preset_combo.addItems(_PRESET_LABELS)
        wf_grid.addWidget(preset_lbl, 0, 0)
        wf_grid.addWidget(self.preset_combo, 0, 1)

        self.preset_desc_label = FCLabel("")
        self.preset_desc_label.setWordWrap(True)
        wf_grid.addWidget(self.preset_desc_label, 2, 0, 1, 2)

        # #############################################################
        # ## Output + units
        # #############################################################
        self.layout.addWidget(FCLabel('%s' % _("Output"), color='blue', bold=True))
        out_frame = FCFrame()
        self.layout.addWidget(out_frame)
        out_grid = GLay(v_spacing=5, h_spacing=3)
        out_frame.setLayout(out_grid)

        units_lbl = FCLabel('%s:' % _("Units"))
        self.units_combo = FCComboBox()
        self.units_combo.addItems(["MM", "IN"])
        out_grid.addWidget(units_lbl, 0, 0)
        out_grid.addWidget(self.units_combo, 0, 1)

        outdir_lbl = FCLabel('%s:' % _("Folder"))
        outdir_lbl.setToolTip(_("Folder where the generated G-code files will be saved."))
        self.outdir_entry = FCEntry()
        self.outdir_entry.setPlaceholderText(_("Path to output folder..."))
        self.outdir_browse_btn = self._import_btn(_("Browse for the output folder."))
        out_grid.addWidget(outdir_lbl, 2, 0)
        out_grid.addWidget(self.outdir_entry, 2, 1)
        out_grid.addWidget(self.outdir_browse_btn, 2, 2)

        # #############################################################
        # ## Advanced parameters (collapsible)
        # #############################################################
        self.adv_toggle = QtWidgets.QToolButton()
        self.adv_toggle.setText(_("  Advanced parameters"))
        self.adv_toggle.setCheckable(True)
        self.adv_toggle.setChecked(False)
        self.adv_toggle.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.adv_toggle.setArrowType(QtCore.Qt.ArrowType.RightArrow)
        self.adv_toggle.toggled.connect(
            lambda c: self.adv_toggle.setArrowType(
                QtCore.Qt.ArrowType.DownArrow if c else QtCore.Qt.ArrowType.RightArrow))
        self.layout.addWidget(self.adv_toggle)

        self.adv_frame = FCFrame()
        self.adv_frame.setVisible(False)
        self.layout.addWidget(self.adv_frame)
        adv_grid = GLay(v_spacing=5, h_spacing=3)
        self.adv_frame.setLayout(adv_grid)

        r = 0
        self.iso_dia_entry = self._dspin(adv_grid, r, _("Isolation tool dia"),
                                         0.0001, 100.0, 0.1, 4); r += 2
        self.iso_passes_entry = self._ispin(adv_grid, r, _("Isolation passes"), 1, 99, 1); r += 2
        self.iso_overlap_entry = self._dspin(adv_grid, r, _("Overlap %"), 0.0, 99.99, 10.0, 2); r += 2
        self.cutz_entry = self._dspin(adv_grid, r, _("Cut Z (isolation)"), -100.0, 0.0, -0.05, 4); r += 2
        self.travelz_entry = self._dspin(adv_grid, r, _("Travel Z"), 0.0, 100.0, 2.0, 4); r += 2
        self.feedrate_entry = self._dspin(adv_grid, r, _("Feed rate"), 0.0, 100000.0, 120.0, 2); r += 2
        self.drillz_entry = self._dspin(adv_grid, r, _("Drill Z"), -100.0, 0.0, -1.7, 4); r += 2
        self.cut_dia_entry = self._dspin(adv_grid, r, _("Cutout tool dia"), 0.0001, 100.0, 1.0, 4); r += 2
        self.cut_z_entry = self._dspin(adv_grid, r, _("Cutout Z (through)"), -100.0, 0.0, -1.6, 4); r += 2
        self.cut_gap_entry = self._dspin(adv_grid, r, _("Cutout gap size"), 0.0, 100.0, 3.0, 3); r += 2

        pp_lbl = FCLabel('%s:' % _("Preprocessor"))
        pp_lbl.setToolTip(_("G-code dialect / post-processor."))
        self.pp_combo = FCComboBox()
        try:
            for k in sorted(self.app.preprocessors.keys()):
                self.pp_combo.addItem(k)
            di = self.pp_combo.findText("default")
            if di >= 0:
                self.pp_combo.setCurrentIndex(di)
        except Exception:
            self.pp_combo.addItem("default")
        adv_grid.addWidget(pp_lbl, r, 0)
        adv_grid.addWidget(self.pp_combo, r, 1)

        # #############################################################
        # ## Build / Plan
        # #############################################################
        self.build_plan_btn = FCButton(_("Build Plan"), bold=True)
        self.build_plan_btn.setIcon(QtGui.QIcon(self.app.resource_location + '/properties32.png'))
        self.build_plan_btn.setToolTip(_("Build and validate the step plan from the choices above."))
        self.layout.addWidget(self.build_plan_btn)

        self.layout.addWidget(FCLabel('%s' % _("Job Plan"), color='blue', bold=True))
        self.plan_table = FCTable()
        self.plan_table.setColumnCount(3)
        self.plan_table.setHorizontalHeaderLabels([_("#"), _("Step"), _("Status")])
        self.plan_table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.plan_table.horizontalHeader().setSectionResizeMode(
            1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.plan_table.horizontalHeader().setSectionResizeMode(
            2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.plan_table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.plan_table.setMinimumHeight(140)
        self.layout.addWidget(self.plan_table)

        self.status_label = FCLabel(_("Pick a Top Copper object and a workflow, then Build Plan."))
        self.status_label.setWordWrap(True)
        self.layout.addWidget(self.status_label)

        # #############################################################
        # ## Run / Stop / Save / Load
        # #############################################################
        btn_frame = FCFrame()
        self.layout.addWidget(btn_frame)
        btn_grid = GLay(v_spacing=5, h_spacing=3)
        btn_frame.setLayout(btn_grid)

        self.run_btn = FCButton(_("Run Job"), bold=True)
        self.run_btn.setIcon(QtGui.QIcon(self.app.resource_location + '/run32.png'))
        self.run_btn.setToolTip(_("Execute all steps in the plan, in order."))
        self.run_btn.setEnabled(False)
        self.stop_btn = FCButton(_("Stop"))
        self.stop_btn.setToolTip(_("Stop after the current step completes."))
        self.stop_btn.setEnabled(False)
        btn_grid.addWidget(self.run_btn, 0, 0)
        btn_grid.addWidget(self.stop_btn, 0, 1)

        self.save_job_btn = FCButton(_("Save Job"))
        self.save_job_btn.setToolTip(_("Save this plan as a .FlatJob file."))
        self.load_job_btn = FCButton(_("Load Job"))
        self.load_job_btn.setToolTip(_("Load a plan from a .FlatJob file."))
        btn_grid.addWidget(self.save_job_btn, 2, 0)
        btn_grid.addWidget(self.load_job_btn, 2, 1)

        GLay.set_common_column_size([src_grid, wf_grid, out_grid, adv_grid], 0)

        self.layout.addStretch(1)

        self.reset_button = FCButton(_("Reset Tool"), bold=True)
        self.reset_button.setIcon(QtGui.QIcon(self.app.resource_location + '/reset32.png'))
        self.reset_button.setToolTip(_("Reset the tool to defaults."))
        self.layout.addWidget(self.reset_button)

    # ---------------------------------------------------------------- helpers
    def _object_combo(self, group_index, obj_type):
        """A combo bound to the project object collection, restricted to one kind."""
        combo = FCComboBox()
        combo.setModel(self.app.collection)
        combo.setRootModelIndex(self.app.collection.index(group_index, 0, QtCore.QModelIndex()))
        combo.obj_type = obj_type
        combo.is_last = True
        return combo

    def _import_btn(self, tooltip):
        btn = FCButton(_("..."))
        btn.setToolTip(tooltip)
        btn.setFixedWidth(34)
        return btn

    def _dspin(self, grid, row, label, lo, hi, default, prec):
        lbl = FCLabel('%s:' % label)
        sp = FCDoubleSpinner()
        sp.set_precision(prec)
        sp.set_range(lo, hi)
        sp.set_value(default)
        grid.addWidget(lbl, row, 0)
        grid.addWidget(sp, row, 1)
        return sp

    def _ispin(self, grid, row, label, lo, hi, default):
        lbl = FCLabel('%s:' % label)
        sp = FCSpinner()
        sp.set_range(lo, hi)
        sp.set_value(default)
        grid.addWidget(lbl, row, 0)
        grid.addWidget(sp, row, 1)
        return sp

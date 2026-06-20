# ##########################################################
# FlatCAM Evo: Job Automation Plugin                       #
# File Author: FlatCAM Evo Team                            #
# MIT Licence                                              #
# ##########################################################

from PyQt6 import QtWidgets, QtGui, QtCore
from appTool import AppTool
from appGUI.GUIElements import (VerticalScrollArea, FCLabel, FCButton, FCFrame,
                                GLay, FCEntry, FCComboBox, FCTable)

import logging
import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

log = logging.getLogger('base')


class ToolJobAutomation(AppTool):
    plugin_tooltip = _("Job Automation: build a PCB machining job from file bindings and a preset, "
                       "then run the compiled Tcl commands in sequence.")

    def __init__(self, app):
        AppTool.__init__(self, app)

        self.app = app
        self.decimals = self.app.decimals

        # current compiled job
        self.current_job = None
        self._stop = False

        # #############################################################################
        # ######################### Tool GUI ##########################################
        # #############################################################################
        self.ui = JobAutomationUI(layout=self.layout, app=self.app)
        self.pluginName = self.ui.pluginName

    def run(self, toggle=True):
        self.app.defaults.report_usage("ToolJobAutomation()")

        if toggle:
            # if the splitter is hidden, display it
            if self.app.ui.splitter.sizes()[0] == 0:
                self.app.ui.splitter.setSizes([1, 1])

            # if the Tool Tab is hidden display it, else hide it but only if the objectName is the same
            found_idx = None
            for idx in range(self.app.ui.notebook.count()):
                if self.app.ui.notebook.widget(idx).objectName() == "plugin_tab":
                    found_idx = idx
                    break
            # show the Tab
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
                # focus on Tool Tab
                self.app.ui.notebook.setCurrentWidget(self.app.ui.plugin_tab)

            try:
                if self.app.ui.plugin_scroll_area.widget().objectName() == self.pluginName and found_idx:
                    # if the Tool Tab is not focused, focus on it
                    if not self.app.ui.notebook.currentWidget() is self.app.ui.plugin_tab:
                        # focus on Tool Tab
                        self.app.ui.notebook.setCurrentWidget(self.app.ui.plugin_tab)
                    else:
                        # else remove the Tool Tab
                        self.app.ui.notebook.setCurrentWidget(self.app.ui.properties_tab)
                        self.app.ui.notebook.removeTab(2)

                        # if there are no objects loaded in the app then hide the Notebook widget
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

        self.connect_signals_at_init()

    def connect_signals_at_init(self):
        self.ui.top_browse_btn.clicked.connect(lambda: self._browse_file(self.ui.top_entry))
        self.ui.bot_browse_btn.clicked.connect(lambda: self._browse_file(self.ui.bot_entry))
        self.ui.drills_browse_btn.clicked.connect(lambda: self._browse_file(self.ui.drills_entry,
                                                                             excellon=True))
        self.ui.outline_browse_btn.clicked.connect(lambda: self._browse_file(self.ui.outline_entry))
        self.ui.outdir_browse_btn.clicked.connect(self._browse_outdir)

        self.ui.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        self.ui.build_plan_btn.clicked.connect(self.on_build_plan)
        self.ui.run_btn.clicked.connect(self.on_run)
        self.ui.stop_btn.clicked.connect(self.on_stop)
        self.ui.save_job_btn.clicked.connect(self.on_save_job)
        self.ui.load_job_btn.clicked.connect(self.on_load_job)
        self.ui.reset_button.clicked.connect(self.set_tool_ui)

        # populate preset description on first show
        self._on_preset_changed(0)

    # -------------------------------------------------------------------------
    # File browse helpers
    # -------------------------------------------------------------------------
    def _browse_file(self, entry_widget, excellon=False):
        if excellon:
            filter_str = _("Excellon Files (*.drl *.exc *.xln *.ncd *.tap *.drd *.txt *.nc);;All Files (*)")
        else:
            filter_str = _("Gerber Files (*.gbr *.ger *.gtl *.gbl *.gts *.gbs *.gto *.gbo *.gko *.gm1 *.g2 *.g3 *.gp1 *.gtp *.gbp *.drl);;All Files (*)")
        path, _sel = QtWidgets.QFileDialog.getOpenFileName(
            None, _("Select File"), "", filter_str)
        if path:
            entry_widget.set_value(path)

    def _browse_outdir(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(
            None, _("Select Output Folder"), "")
        if path:
            self.ui.outdir_entry.set_value(path)

    # -------------------------------------------------------------------------
    # Preset handling
    # -------------------------------------------------------------------------
    def _on_preset_changed(self, idx):
        from appAutomation import presets
        if idx < 0 or idx >= len(presets.PRESET_ORDER):
            return
        preset_id = presets.PRESET_ORDER[idx]
        _label, _builder, description = presets.PRESETS[preset_id]
        self.ui.preset_desc_label.setText(description)

    # -------------------------------------------------------------------------
    # Build Plan
    # -------------------------------------------------------------------------
    def on_build_plan(self):
        from appAutomation import presets
        from appAutomation import job_model
        from appAutomation.job_compiler import compile_job_lines, CompileError

        idx = self.ui.preset_combo.currentIndex()
        if idx < 0:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("No preset selected."))
            return

        preset_id = presets.PRESET_ORDER[idx]

        bindings = {
            presets.TOP_COPPER: self.ui.top_entry.get_value().strip(),
            presets.BOTTOM_COPPER: self.ui.bot_entry.get_value().strip(),
            presets.DRILLS: self.ui.drills_entry.get_value().strip(),
            presets.OUTLINE: self.ui.outline_entry.get_value().strip(),
        }
        # Remove empty bindings so the preset can decide what is optional
        bindings = {k: v for k, v in bindings.items() if v}

        out_dir = self.ui.outdir_entry.get_value().strip()
        # persist the chosen output folder as the new default
        try:
            self.app.options["tools_job_auto_output_dir"] = out_dir
        except Exception:
            pass

        try:
            job = presets.build(preset_id, bindings, out_dir, None)
        except Exception as e:
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Could not build job"), str(e)))
            return

        problems = job.validate()
        has_error = False
        for severity, msg in problems:
            if severity == job_model.ERROR:
                self.app.inform.emit('[ERROR_NOTCL] %s' % msg)
                has_error = True
            else:
                self.app.inform.emit('[WARNING_NOTCL] %s' % msg)

        if has_error:
            self.ui.run_btn.setEnabled(False)
            return

        # Compile to Tcl lines for the plan table
        try:
            lines = compile_job_lines(job)
        except CompileError as e:
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Compile error"), str(e)))
            self.ui.run_btn.setEnabled(False)
            return

        # Store job for Run
        self.current_job = job

        # Populate the plan table
        enabled_steps = job.enabled_steps()
        self.ui.plan_table.setRowCount(len(lines))
        for row, (step, line) in enumerate(zip(enabled_steps, lines)):
            num_item = QtWidgets.QTableWidgetItem(str(row + 1))
            num_item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
            step_item = QtWidgets.QTableWidgetItem(step.label)
            step_item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
            step_item.setToolTip(line)
            status_item = QtWidgets.QTableWidgetItem(_("pending"))
            status_item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)

            self.ui.plan_table.setItem(row, 0, num_item)
            self.ui.plan_table.setItem(row, 1, step_item)
            self.ui.plan_table.setItem(row, 2, status_item)

        self.ui.run_btn.setEnabled(True)
        self.app.inform.emit('[success] %s' % _("Job plan built. Ready to Run."))

    # -------------------------------------------------------------------------
    # Run
    # -------------------------------------------------------------------------
    def on_run(self):
        if self.current_job is None:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("No job plan. Click 'Build Plan' first."))
            return

        # Ensure shell/Tcl is available
        if not getattr(self.app, 'shell', None):
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Tcl shell is not initialized."))
            return
        if not getattr(self.app.shell, 'tcl', None):
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Tcl interpreter is not available."))
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

        def eval_fn(line):
            return self.app.shell.tcl.eval(line)

        def read_error():
            try:
                return self.app.shell.tcl.eval('set errorInfo')
            except Exception:
                return ""

        job_runner.execute_lines(
            eval_fn=eval_fn,
            lines=lines,
            on_step=self._on_step,
            should_stop=lambda: self._stop,
            read_error=read_error
        )

        # Restore button states
        self.ui.run_btn.setEnabled(True)
        self.ui.stop_btn.setEnabled(False)

        # Check if all ok
        # (we check the table status column for any "failed" cell)
        all_ok = True
        for row in range(self.ui.plan_table.rowCount()):
            item = self.ui.plan_table.item(row, 2)
            if item and item.text() == _("failed"):
                all_ok = False
                break

        if all_ok and not self._stop:
            self.app.inform.emit('[success] %s' % _("Job finished."))
            try:
                self.app.plot_all()
            except Exception:
                pass
        elif self._stop:
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("Job stopped by user."))

    def _on_step(self, phase, r):
        """Callback fired by execute_lines for each step start/finish."""
        row = r.index
        if row >= self.ui.plan_table.rowCount():
            return

        status_item = self.ui.plan_table.item(row, 2)
        if status_item is None:
            status_item = QtWidgets.QTableWidgetItem()
            self.ui.plan_table.setItem(row, 2, status_item)

        if phase == 'start':
            status_item.setText(_("running"))
            status_item.setBackground(QtGui.QColor(255, 200, 50))  # amber
        else:  # 'finish'
            if r.skipped:
                status_item.setText(_("skipped"))
                status_item.setBackground(QtGui.QColor(180, 180, 180))  # grey
            elif r.ok:
                status_item.setText(_("done"))
                status_item.setBackground(QtGui.QColor(100, 200, 100))  # green
            else:
                status_item.setText(_("failed"))
                status_item.setBackground(QtGui.QColor(220, 80, 80))  # red
                self.app.inform.emit('[ERROR_NOTCL] %s' %
                                     (_("Step %d failed: %s") % (r.index + 1, r.message)))

        QtWidgets.QApplication.processEvents()

    def on_stop(self):
        self._stop = True

    # -------------------------------------------------------------------------
    # Save / Load Job JSON
    # -------------------------------------------------------------------------
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
            self.app.inform.emit('[success] %s' % (_("Job saved to: %s") % path))
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
                text = f.read()
            job = Job.from_json(text)
        except Exception as e:
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Load failed"), str(e)))
            return

        self.current_job = job

        # Compile and populate plan table
        try:
            lines = compile_job_lines(job)
        except CompileError as e:
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Compile error"), str(e)))
            return

        enabled_steps = job.enabled_steps()
        self.ui.plan_table.setRowCount(len(lines))
        for row, (step, line) in enumerate(zip(enabled_steps, lines)):
            num_item = QtWidgets.QTableWidgetItem(str(row + 1))
            num_item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
            step_item = QtWidgets.QTableWidgetItem(step.label)
            step_item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
            step_item.setToolTip(line)
            status_item = QtWidgets.QTableWidgetItem(_("pending"))
            status_item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)

            self.ui.plan_table.setItem(row, 0, num_item)
            self.ui.plan_table.setItem(row, 1, step_item)
            self.ui.plan_table.setItem(row, 2, status_item)

        self.ui.run_btn.setEnabled(True)
        self.app.inform.emit('[success] %s' % (_("Job loaded from: %s") % path))


class JobAutomationUI:

    pluginName = _("Job Automation")

    def __init__(self, layout, app):
        self.app = app
        self.decimals = self.app.decimals
        self.layout = layout

        # ## Title
        title_label = FCLabel("%s" % self.pluginName, size=16, bold=True)
        self.layout.addWidget(title_label)

        # #############################################################################
        # ## Files section
        # #############################################################################
        files_label = FCLabel('%s' % _("Input Files"), color='blue', bold=True)
        self.layout.addWidget(files_label)

        files_frame = FCFrame()
        self.layout.addWidget(files_frame)

        files_grid = GLay(v_spacing=5, h_spacing=3)
        files_frame.setLayout(files_grid)

        # Top Copper
        top_lbl = FCLabel('%s:' % _("Top Copper"))
        top_lbl.setToolTip(_("Gerber file for the top copper layer. Leave empty if not needed."))
        self.top_entry = FCEntry()
        self.top_entry.setPlaceholderText(_("Path to top copper Gerber..."))
        self.top_browse_btn = FCButton(_("..."))
        self.top_browse_btn.setToolTip(_("Browse for top copper Gerber file."))
        self.top_browse_btn.setFixedWidth(30)

        files_grid.addWidget(top_lbl, 0, 0)
        files_grid.addWidget(self.top_entry, 0, 1)
        files_grid.addWidget(self.top_browse_btn, 0, 2)

        # Bottom Copper
        bot_lbl = FCLabel('%s:' % _("Bottom Copper"))
        bot_lbl.setToolTip(_("Gerber file for the bottom copper layer. Leave empty if not needed."))
        self.bot_entry = FCEntry()
        self.bot_entry.setPlaceholderText(_("Path to bottom copper Gerber..."))
        self.bot_browse_btn = FCButton(_("..."))
        self.bot_browse_btn.setToolTip(_("Browse for bottom copper Gerber file."))
        self.bot_browse_btn.setFixedWidth(30)

        files_grid.addWidget(bot_lbl, 2, 0)
        files_grid.addWidget(self.bot_entry, 2, 1)
        files_grid.addWidget(self.bot_browse_btn, 2, 2)

        # Drills (Excellon)
        drills_lbl = FCLabel('%s:' % _("Drills (Excellon)"))
        drills_lbl.setToolTip(_("Excellon drill file. Leave empty if not needed."))
        self.drills_entry = FCEntry()
        self.drills_entry.setPlaceholderText(_("Path to Excellon drill file..."))
        self.drills_browse_btn = FCButton(_("..."))
        self.drills_browse_btn.setToolTip(_("Browse for Excellon drill file."))
        self.drills_browse_btn.setFixedWidth(30)

        files_grid.addWidget(drills_lbl, 4, 0)
        files_grid.addWidget(self.drills_entry, 4, 1)
        files_grid.addWidget(self.drills_browse_btn, 4, 2)

        # Outline (Board edge)
        outline_lbl = FCLabel('%s:' % _("Outline"))
        outline_lbl.setToolTip(_("Gerber file for the board outline/edge cuts. Leave empty if not needed."))
        self.outline_entry = FCEntry()
        self.outline_entry.setPlaceholderText(_("Path to outline Gerber..."))
        self.outline_browse_btn = FCButton(_("..."))
        self.outline_browse_btn.setToolTip(_("Browse for outline Gerber file."))
        self.outline_browse_btn.setFixedWidth(30)

        files_grid.addWidget(outline_lbl, 6, 0)
        files_grid.addWidget(self.outline_entry, 6, 1)
        files_grid.addWidget(self.outline_browse_btn, 6, 2)

        # #############################################################################
        # ## Output folder
        # #############################################################################
        outdir_label = FCLabel('%s' % _("Output"), color='blue', bold=True)
        self.layout.addWidget(outdir_label)

        out_frame = FCFrame()
        self.layout.addWidget(out_frame)

        out_grid = GLay(v_spacing=5, h_spacing=3)
        out_frame.setLayout(out_grid)

        outdir_lbl = FCLabel('%s:' % _("Output Folder"))
        outdir_lbl.setToolTip(_("Folder where generated G-code files will be saved."))
        self.outdir_entry = FCEntry()
        self.outdir_entry.setPlaceholderText(_("Path to output folder..."))
        self.outdir_browse_btn = FCButton(_("..."))
        self.outdir_browse_btn.setToolTip(_("Browse for output folder."))
        self.outdir_browse_btn.setFixedWidth(30)

        out_grid.addWidget(outdir_lbl, 0, 0)
        out_grid.addWidget(self.outdir_entry, 0, 1)
        out_grid.addWidget(self.outdir_browse_btn, 0, 2)

        # #############################################################################
        # ## Preset
        # #############################################################################
        preset_section_label = FCLabel('%s' % _("Preset"), color='blue', bold=True)
        self.layout.addWidget(preset_section_label)

        preset_frame = FCFrame()
        self.layout.addWidget(preset_frame)

        preset_grid = GLay(v_spacing=5, h_spacing=3)
        preset_frame.setLayout(preset_grid)

        preset_lbl = FCLabel('%s:' % _("Preset"))
        preset_lbl.setToolTip(_("Choose a built-in machining preset."))
        self.preset_combo = FCComboBox()
        self.preset_combo.setToolTip(_("Select a machining workflow preset."))

        # Populate presets
        from appAutomation import presets as _presets
        for pid in _presets.PRESET_ORDER:
            label, _builder, _desc = _presets.PRESETS[pid]
            self.preset_combo.addItem(label)

        preset_grid.addWidget(preset_lbl, 0, 0)
        preset_grid.addWidget(self.preset_combo, 0, 1)

        self.preset_desc_label = FCLabel("")
        self.preset_desc_label.setWordWrap(True)
        preset_grid.addWidget(self.preset_desc_label, 2, 0, 1, 2)

        # #############################################################################
        # ## Build Plan button
        # #############################################################################
        self.build_plan_btn = FCButton(_("Build Plan"), bold=True)
        self.build_plan_btn.setIcon(QtGui.QIcon(self.app.resource_location + '/properties32.png'))
        self.build_plan_btn.setToolTip(
            _("Build the job plan from the selected files and preset.")
        )
        self.layout.addWidget(self.build_plan_btn)

        # #############################################################################
        # ## Plan Table
        # #############################################################################
        plan_label = FCLabel('%s' % _("Job Plan"), color='blue', bold=True)
        self.layout.addWidget(plan_label)

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
        self.plan_table.setMinimumHeight(120)
        self.layout.addWidget(self.plan_table)

        # #############################################################################
        # ## Run / Stop / Save / Load buttons
        # #############################################################################
        btn_frame = FCFrame()
        self.layout.addWidget(btn_frame)

        btn_grid = GLay(v_spacing=5, h_spacing=3)
        btn_frame.setLayout(btn_grid)

        self.run_btn = FCButton(_("Run Job"), bold=True)
        self.run_btn.setIcon(QtGui.QIcon(self.app.resource_location + '/run32.png'))
        self.run_btn.setToolTip(_("Execute all steps in the plan."))
        self.run_btn.setEnabled(False)

        self.stop_btn = FCButton(_("Stop"))
        self.stop_btn.setToolTip(_("Request job stop after the current step completes."))
        self.stop_btn.setEnabled(False)

        btn_grid.addWidget(self.run_btn, 0, 0)
        btn_grid.addWidget(self.stop_btn, 0, 1)

        self.save_job_btn = FCButton(_("Save Job"))
        self.save_job_btn.setToolTip(_("Save the current job plan as a .FlatJob file."))

        self.load_job_btn = FCButton(_("Load Job"))
        self.load_job_btn.setToolTip(_("Load a job plan from a .FlatJob file."))

        btn_grid.addWidget(self.save_job_btn, 2, 0)
        btn_grid.addWidget(self.load_job_btn, 2, 1)

        GLay.set_common_column_size([files_grid, out_grid, preset_grid, btn_grid], 0)

        self.layout.addStretch(1)

        # ## Reset Tool
        self.reset_button = FCButton(_("Reset Tool"), bold=True)
        self.reset_button.setIcon(QtGui.QIcon(self.app.resource_location + '/reset32.png'))
        self.reset_button.setToolTip(_("Will reset the tool parameters."))
        self.layout.addWidget(self.reset_button)

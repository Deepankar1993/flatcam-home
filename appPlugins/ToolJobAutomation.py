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

from copy import deepcopy
import logging
import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

log = logging.getLogger('base')

# Front-door presets: (label, preset_id, include_optional_drill_cutout)
_PRESETS = [
    (_("Isolation routing"), "iso_drill_cutout", False),
    (_("Isolation + Drilling + Cutout"), "iso_drill_cutout", True),
    (_("Copper clear (NCC ground-plane)"), "ncc_groundplane", False),
]
_PRESET_DESC = [
    _("Isolate the selected Top Copper, make the CNC job and export."),
    _("Isolate, then drill (Excellon) and cut out the board (Outline). "
      "Pick those objects below."),
    _("Clear all excess copper of the Top Copper, make the CNC job and export."),
]

# Hidden column holding the step uid
_UID_COL = 4


class ToolJobAutomation(AppTool):
    plugin_tooltip = _("Job Automation: build an editable pipeline of steps from loaded "
                       "board objects, tune each step, then run it all at once.")

    def __init__(self, app):
        AppTool.__init__(self, app)
        self.app = app
        self.decimals = self.app.decimals

        from appAutomation import job_model as jm
        self.jm = jm
        self.job = jm.Job(units=self.app.app_units.upper() if hasattr(self.app, 'app_units') else "MM")
        self._building = False          # guard while (re)building the table
        self.form_fields = {}           # key -> (field_dict, widget) for the selected step
        self._selected_uid = None

        self.ui = JobAutomationUI(layout=self.layout, app=self.app)
        self.pluginName = self.ui.pluginName

    # ------------------------------------------------------------------- shell
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

        try:
            self.ui.outdir_entry.set_value(self.app.options.get("tools_job_auto_output_dir", ""))
        except Exception:
            pass
        try:
            sel = self.app.collection.get_active()
            if sel is not None and sel.kind == 'gerber':
                self.ui.top_combo.set_value(sel.obj_options['name'])
        except Exception:
            pass

        self.connect_signals_at_init()
        self._on_preset_changed(self.ui.preset_combo.currentIndex())
        self.build_table()
        self._clear_step_form()

    def connect_signals_at_init(self):
        self.ui.top_import_btn.clicked.connect(lambda: self._import(self.app.f_handlers.open_gerber, True))
        self.ui.drills_import_btn.clicked.connect(lambda: self._import(self.app.f_handlers.open_excellon, False))
        self.ui.outline_import_btn.clicked.connect(lambda: self._import(self.app.f_handlers.open_gerber, True))
        self.ui.outdir_browse_btn.clicked.connect(self._browse_outdir)
        self.ui.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        self.ui.create_btn.clicked.connect(self.on_create_from_preset)

        self.ui.add_btn.clicked.connect(self.on_add_step)
        self.ui.del_btn.clicked.connect(self.on_delete_step)
        self.ui.dup_btn.clicked.connect(self.on_duplicate_step)
        self.ui.up_btn.clicked.connect(lambda: self.on_move(-1))
        self.ui.down_btn.clicked.connect(lambda: self.on_move(1))
        self.ui.clear_btn.clicked.connect(self.on_clear)

        self.ui.steps_table.clicked.connect(self.on_row_selected)
        self.ui.steps_table.itemChanged.connect(self.on_item_changed)
        try:
            self.ui.steps_table.drag_drop_sig.connect(self.on_reorder)
        except Exception:
            pass

        self.ui.run_btn.clicked.connect(self.on_run)
        self.ui.stop_btn.clicked.connect(self.on_stop)
        self.ui.save_job_btn.clicked.connect(self.on_save_job)
        self.ui.load_job_btn.clicked.connect(self.on_load_job)
        self.ui.reset_button.clicked.connect(self.set_tool_ui)

    # -------------------------------------------------------------- front door
    def _on_preset_changed(self, idx):
        if 0 <= idx < len(_PRESET_DESC):
            self.ui.preset_desc_label.setText(_PRESET_DESC[idx])
        include_opt = (0 <= idx < len(_PRESETS) and _PRESETS[idx][2])
        for w in (self.ui.drills_cb, self.ui.drills_combo, self.ui.drills_import_btn,
                  self.ui.outline_cb, self.ui.outline_combo, self.ui.outline_import_btn):
            w.setVisible(include_opt)

    def _browse_outdir(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(None, _("Select Output Folder"), "")
        if path:
            self.ui.outdir_entry.set_value(path)

    def _import(self, opener, is_gerber):
        if is_gerber:
            flt = _("Gerber Files (*.gbr *.ger *.gtl *.gbl *.gts *.gbs *.gko *.gm1);;All Files (*)")
        else:
            flt = _("Excellon Files (*.drl *.exc *.xln *.ncd *.tap *.txt *.nc);;All Files (*)")
        path, _sel = QtWidgets.QFileDialog.getOpenFileName(None, _("Import file"), "", flt)
        if path:
            self.app.worker_task.emit({'fcn': opener, 'params': [path]})

    def on_create_from_preset(self):
        from appAutomation import presets
        idx = self.ui.preset_combo.currentIndex()
        label, preset_id, include_opt = _PRESETS[idx]

        top = self.ui.top_combo.currentText().strip()
        bindings = {presets.TOP_COPPER: top}
        if include_opt:
            if self.ui.drills_cb.get_value() and self.ui.drills_combo.currentText().strip():
                bindings[presets.DRILLS] = self.ui.drills_combo.currentText().strip()
            if self.ui.outline_cb.get_value() and self.ui.outline_combo.currentText().strip():
                bindings[presets.OUTLINE] = self.ui.outline_combo.currentText().strip()

        out_dir = self.ui.outdir_entry.get_value().strip()
        try:
            self.app.options["tools_job_auto_output_dir"] = out_dir
        except Exception:
            pass

        try:
            job = presets.build_from_objects(preset_id, bindings, out_dir, None)
        except Exception as e:
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Could not create plan"), str(e)))
            return
        job.units = self.ui.units_combo.currentText()
        self.job = job
        self._normalize_steps()
        self.build_table()
        self._clear_step_form()
        self.ui.status_label.setText(_("Created %d steps. Select a step to edit it.")
                                     % len(self.job.enabled_steps()))
        self.app.inform.emit('[success] %s' % _("Plan created. You can now edit each step."))

    def _normalize_steps(self):
        """Fill each step with its schema defaults so it is fully specified and the
        editor form reflects real values."""
        from appAutomation import step_schema as sch
        for s in self.job.steps:
            for k, v in sch.default_params(s.type).items():
                s.params.setdefault(k, v)
            if s.id is None:
                s.id = self.jm.new_step_id(x.id for x in self.job.steps if x.id is not None)

    # ------------------------------------------------------------ step table
    def build_table(self, select_uid=None):
        self._building = True
        t = self.ui.steps_table
        steps = self.job.steps
        t.setRowCount(len(steps))
        from appAutomation import step_schema as sch
        for row, step in enumerate(steps):
            if step.id is None:
                step.id = self.jm.new_step_id(x.id for x in steps if x.id is not None)
            on_item = QtWidgets.QTableWidgetItem()
            on_item.setFlags(QtCore.Qt.ItemFlag.ItemIsUserCheckable | QtCore.Qt.ItemFlag.ItemIsEnabled)
            on_item.setCheckState(QtCore.Qt.CheckState.Checked if step.enabled
                                  else QtCore.Qt.CheckState.Unchecked)
            t.setItem(row, 0, on_item)

            num = QtWidgets.QTableWidgetItem(str(row + 1))
            num.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
            t.setItem(row, 1, num)

            desc = QtWidgets.QTableWidgetItem(sch.summarize(step))
            desc.setFlags(QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsEnabled)
            t.setItem(row, 2, desc)

            status = QtWidgets.QTableWidgetItem(_("pending"))
            status.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
            t.setItem(row, 3, status)

            uid = QtWidgets.QTableWidgetItem(str(step.id))
            t.setItem(row, _UID_COL, uid)
        self._building = False

        if select_uid is not None:
            self._select_uid(select_uid)

    def _row_of_uid(self, uid):
        t = self.ui.steps_table
        for row in range(t.rowCount()):
            it = t.item(row, _UID_COL)
            if it and int(it.text()) == int(uid):
                return row
        return None

    def _select_uid(self, uid):
        row = self._row_of_uid(uid)
        if row is not None:
            self.ui.steps_table.selectRow(row)
            self.on_row_selected()

    def _selected_step(self):
        t = self.ui.steps_table
        rows = sorted(set(i.row() for i in t.selectedIndexes()))
        if not rows:
            return None
        it = t.item(rows[0], _UID_COL)
        if not it:
            return None
        uid = int(it.text())
        for s in self.job.steps:
            if s.id == uid:
                return s
        return None

    def on_item_changed(self, item):
        if self._building or item.column() != 0:
            return
        row = item.row()
        uid_it = self.ui.steps_table.item(row, _UID_COL)
        if not uid_it:
            return
        uid = int(uid_it.text())
        for s in self.job.steps:
            if s.id == uid:
                s.enabled = (item.checkState() == QtCore.Qt.CheckState.Checked)
                break

    def on_row_selected(self):
        step = self._selected_step()
        if step is None:
            return
        self._selected_uid = step.id
        self.build_step_form(step)

    # --------------------------------------------------------- table editing
    def on_add_step(self):
        from appAutomation import step_schema as sch
        st = self.ui.add_type_combo.currentData()
        step = self.jm.Step(st, sch.default_params(st))
        self.job.add_step(step)
        self.build_table(select_uid=step.id)

    def on_delete_step(self):
        t = self.ui.steps_table
        uids = []
        for r in sorted(set(i.row() for i in t.selectedIndexes())):
            it = t.item(r, _UID_COL)
            if it:
                uids.append(int(it.text()))
        if not uids:
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("Select a step to delete."))
            return
        self.job.steps = [s for s in self.job.steps if s.id not in uids]
        self.build_table()
        self._clear_step_form()
        self.ui.status_label.setText(_("Deleted %d step(s).") % len(uids))

    def on_duplicate_step(self):
        step = self._selected_step()
        if step is None:
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("Select a step to duplicate."))
            return
        idx = self.job.steps.index(step)
        clone = self.jm.Step.from_dict(step.to_dict())
        clone.id = self.jm.new_step_id(x.id for x in self.job.steps if x.id is not None)
        self.job.steps.insert(idx + 1, clone)
        self.build_table(select_uid=clone.id)

    def on_move(self, delta):
        step = self._selected_step()
        if step is None:
            return
        i = self.job.steps.index(step)
        j = i + delta
        if 0 <= j < len(self.job.steps):
            self.job.steps[i], self.job.steps[j] = self.job.steps[j], self.job.steps[i]
            self.build_table(select_uid=step.id)

    def on_clear(self):
        self.job.steps = []
        self.build_table()
        self._clear_step_form()
        self.ui.status_label.setText(_("Plan cleared."))

    def on_reorder(self, *args):
        t = self.ui.steps_table
        order = []
        for row in range(t.rowCount()):
            it = t.item(row, _UID_COL)
            if it:
                order.append(int(it.text()))
        by_id = {s.id: s for s in self.job.steps}
        self.job.steps = [by_id[u] for u in order if u in by_id]
        QtCore.QTimer.singleShot(20, self.build_table)

    # --------------------------------------------------------- per-step form
    def _clear_step_form(self):
        self.form_fields = {}
        lay = self.ui.settings_layout
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        self.ui.settings_hint.setVisible(True)

    def build_step_form(self, step):
        from appAutomation import step_schema as sch
        self._clear_step_form()
        self.ui.settings_hint.setVisible(False)
        grid = self.ui.settings_layout

        hdr = FCLabel('%s' % sch.STEP_LABELS.get(step.type, step.type), color='indigo', bold=True)
        grid.addWidget(hdr, 0, 0, 1, 2)

        row = 1
        for field in sch.fields_for(step.type):
            key = field["key"]
            lbl = FCLabel('%s:' % _(field["label"]))
            if field.get("tooltip"):
                lbl.setToolTip(_(field["tooltip"]))
            widget = self._make_widget(field, step)
            grid.addWidget(lbl, row, 0)
            grid.addWidget(widget, row, 1)
            self.form_fields[key] = (field, widget)
            row += 1

        # connect AFTER values are set, so programmatic loads don't write back
        for key, (field, widget) in self.form_fields.items():
            self._connect_field(step.id, key, field, widget)

    def _make_widget(self, field, step):
        from appAutomation import step_schema as sch
        ftype = field["type"]
        key = field["key"]
        val = step.params.get(key, field.get("default"))

        if ftype in (sch.FT_FLOAT,):
            w = FCDoubleSpinner()
            w.set_precision(field.get("precision", 4))
            w.set_range(field.get("min", -100000.0), field.get("max", 100000.0))
            if val is not None:
                w.set_value(float(val))
            return w
        if ftype == sch.FT_INT:
            w = FCSpinner()
            w.set_range(int(field.get("min", 0)), int(field.get("max", 99999)))
            if val is not None:
                w.set_value(int(val))
            return w
        if ftype == sch.FT_BOOL:
            w = FCCheckBox()
            w.set_value(bool(val))
            return w
        if ftype == sch.FT_CHOICE:
            w = FCComboBox()
            w._values = [c[0] for c in field["choices"]]
            for cval, clabel in field["choices"]:
                w.addItem(_(clabel))
            if val in w._values:
                w.setCurrentIndex(w._values.index(val))
            return w
        if ftype == sch.FT_PREPROC:
            w = FCComboBox()
            try:
                items = sorted(self.app.preprocessors.keys())
            except Exception:
                items = ["default"]
            w.addItems(items)
            if val in items:
                w.setCurrentIndex(items.index(val))
            return w
        if ftype == sch.FT_OBJECT:
            w = FCComboBox()
            w.setEditable(True)
            cands = self._object_candidates(field.get("obj_kind"), step.id)
            w.addItems(cands)
            # Preserve the stored name even if it isn't a current candidate
            # (object not loaded yet, or produced by a later step). set_value()
            # would fall back to index 0 and silently lose it.
            if val:
                idx = w.findText(str(val))
                if idx >= 0:
                    w.setCurrentIndex(idx)
                else:
                    w.setEditText(str(val))
            else:
                w.setEditText("")
            return w
        if ftype in (sch.FT_PATH_OPEN, sch.FT_PATH_SAVE):
            container = QtWidgets.QWidget()
            hl = QtWidgets.QHBoxLayout(container)
            hl.setContentsMargins(0, 0, 0, 0)
            entry = FCEntry()
            if val:
                entry.set_value(str(val))
            btn = FCButton(_("..."))
            btn.setFixedWidth(34)
            hl.addWidget(entry)
            hl.addWidget(btn)
            container._entry = entry
            save = (ftype == sch.FT_PATH_SAVE)
            btn.clicked.connect(lambda _c=False, e=entry, s=save: self._browse_path(e, s))
            return container
        # fallback: string
        w = FCEntry()
        if val is not None:
            w.set_value(str(val))
        return w

    def _browse_path(self, entry, save):
        if save:
            path, _sel = QtWidgets.QFileDialog.getSaveFileName(None, _("Select file"), "",
                                                              _("G-code (*.gcode *.nc *.tap);;All Files (*)"))
        else:
            path, _sel = QtWidgets.QFileDialog.getOpenFileName(None, _("Select file"), "",
                                                              _("All Files (*)"))
        if path:
            entry.set_value(path)

    def _connect_field(self, uid, key, field, widget):
        from appAutomation import step_schema as sch
        ftype = field["type"]
        cb = lambda *a, u=uid, k=key: self._write_field(u, k)
        if ftype == sch.FT_BOOL:
            widget.stateChanged.connect(cb)
        elif ftype in (sch.FT_CHOICE, sch.FT_PREPROC):
            widget.currentIndexChanged.connect(cb)
        elif ftype == sch.FT_OBJECT:
            widget.currentIndexChanged.connect(cb)
            try:
                widget.lineEdit().editingFinished.connect(cb)
            except Exception:
                pass
        elif ftype in (sch.FT_PATH_OPEN, sch.FT_PATH_SAVE):
            widget._entry.editingFinished.connect(cb)
        elif ftype in (sch.FT_FLOAT, sch.FT_INT):
            widget.editingFinished.connect(cb)
        else:
            widget.editingFinished.connect(cb)

    def _read_widget(self, field, widget):
        from appAutomation import step_schema as sch
        ftype = field["type"]
        if ftype == sch.FT_FLOAT:
            return float(widget.get_value())
        if ftype == sch.FT_INT:
            return int(widget.get_value())
        if ftype == sch.FT_BOOL:
            return bool(widget.get_value())
        if ftype == sch.FT_CHOICE:
            i = widget.currentIndex()
            return widget._values[i] if 0 <= i < len(widget._values) else field.get("default")
        if ftype == sch.FT_PREPROC:
            return widget.currentText()
        if ftype == sch.FT_OBJECT:
            return widget.get_value()
        if ftype in (sch.FT_PATH_OPEN, sch.FT_PATH_SAVE):
            return widget._entry.get_value()
        return widget.get_value()

    def _write_field(self, uid, key):
        step = None
        for s in self.job.steps:
            if s.id == uid:
                step = s
                break
        if step is None or key not in self.form_fields:
            return
        field, widget = self.form_fields[key]
        try:
            step.params[key] = self._read_widget(field, widget)
        except Exception:
            return
        # refresh the table summary cell for this step
        from appAutomation import step_schema as sch
        row = self._row_of_uid(uid)
        if row is not None:
            self._building = True
            it = self.ui.steps_table.item(row, 2)
            if it:
                it.setText(sch.summarize(step))
            self._building = False

    def _object_candidates(self, obj_kind, upto_uid):
        names = []
        try:
            names += [o.obj_options['name'] for o in self.app.collection.get_list()
                      if obj_kind is None or o.kind == obj_kind]
        except Exception:
            pass
        for s in self.job.steps:
            if s.id == upto_uid:
                break
            pn = s.produced_name()
            if pn:
                names.append(pn)
        seen, out = set(), []
        for n in names:
            if n and n not in seen:
                seen.add(n)
                out.append(n)
        return out

    # ----------------------------------------------------------------- run
    def on_run(self):
        from appAutomation import job_model
        from appAutomation.job_compiler import compile_job_lines, CompileError
        from appAutomation import job_runner

        if not self.job.enabled_steps():
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("No steps to run. Add or create steps first."))
            return
        # set external objects = referenced names not produced by steps (loaded objects)
        self._refresh_external_objects()

        has_error = False
        for severity, msg in self.job.validate():
            if severity == job_model.ERROR:
                self.app.inform.emit('[ERROR_NOTCL] %s' % msg)
                has_error = True
            else:
                self.app.inform.emit('[WARNING_NOTCL] %s' % msg)
        if has_error:
            return
        if not getattr(self.app, 'shell', None) or not getattr(self.app.shell, 'tcl', None):
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Tcl shell is not initialized."))
            return
        try:
            lines = compile_job_lines(self.job)
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
            lines=lines, on_step=self._on_step,
            should_stop=lambda: getattr(self, '_stop', False), read_error=read_error)

        self.ui.run_btn.setEnabled(True)
        self.ui.stop_btn.setEnabled(False)
        failed = any(self.ui.steps_table.item(r, 3) and
                     self.ui.steps_table.item(r, 3).text() == _("failed")
                     for r in range(self.ui.steps_table.rowCount()))
        if getattr(self, '_stop', False):
            self.ui.status_label.setText(_("Stopped by user."))
        elif failed:
            self.ui.status_label.setText(_("Finished with errors."))
        else:
            self.ui.status_label.setText(_("Job finished successfully."))
            self.app.inform.emit('[success] %s' % _("Job finished."))
            try:
                self.app.plot_all()
            except Exception:
                pass

    def _refresh_external_objects(self):
        produced = set()
        for s in self.job.steps:
            pn = s.produced_name()
            if pn:
                produced.add(pn)
        ext = set()
        for s in self.job.enabled_steps():
            ref = s.params.get("name")
            if ref and ref not in produced:
                ext.add(ref)
        self.job.external_objects = ext

    def _on_step(self, phase, r):
        # map the runner's enabled-step index to the table row
        enabled = self.job.enabled_steps()
        if r.index >= len(enabled):
            return
        uid = enabled[r.index].id
        row = self._row_of_uid(uid)
        if row is None:
            return
        item = self.ui.steps_table.item(row, 3)
        if item is None:
            item = QtWidgets.QTableWidgetItem()
            self.ui.steps_table.setItem(row, 3, item)
        if phase == 'start':
            item.setText(_("running")); item.setBackground(QtGui.QColor(255, 200, 50))
            self.ui.steps_table.scrollToItem(item)
        else:
            if r.skipped:
                item.setText(_("skipped")); item.setBackground(QtGui.QColor(180, 180, 180))
            elif r.ok:
                item.setText(_("done")); item.setBackground(QtGui.QColor(100, 200, 100))
            else:
                item.setText(_("failed")); item.setBackground(QtGui.QColor(220, 80, 80))
                self.app.inform.emit('[ERROR_NOTCL] %s' %
                                     (_("Step %d failed: %s") % (r.index + 1, r.message)))
        QtWidgets.QApplication.processEvents()

    def on_stop(self):
        self._stop = True

    # --------------------------------------------------------------- save/load
    def on_save_job(self):
        if not self.job.steps:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Nothing to save."))
            return
        self._refresh_external_objects()
        path, _sel = QtWidgets.QFileDialog.getSaveFileName(
            None, _("Save Job"), "", _("FlatJob Files (*.FlatJob);;All Files (*)"))
        if not path:
            return
        if not path.lower().endswith('.flatjob'):
            path += '.FlatJob'
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(self.job.to_json())
            self.app.inform.emit('[success] %s' % (_("Job saved: %s") % path))
        except Exception as e:
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Save failed"), str(e)))

    def on_load_job(self):
        path, _sel = QtWidgets.QFileDialog.getOpenFileName(
            None, _("Load Job"), "", _("FlatJob Files (*.FlatJob);;All Files (*)"))
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                self.job = self.jm.Job.from_json(f.read())
        except Exception as e:
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Load failed"), str(e)))
            return
        self._normalize_steps()
        self.build_table()
        self._clear_step_form()
        self.ui.status_label.setText(_("Loaded %d steps.") % len(self.job.steps))
        self.app.inform.emit('[success] %s' % (_("Job loaded: %s") % path))


class JobAutomationUI:
    pluginName = _("Job Automation")

    def __init__(self, layout, app):
        from appAutomation import job_model as jm
        from appAutomation import step_schema as sch
        self.app = app
        self.decimals = self.app.decimals
        self.layout = layout

        title = FCLabel("%s" % self.pluginName, size=16, bold=True)
        title.setToolTip(_("Build and run a full board pipeline from loaded objects."))
        self.layout.addWidget(title)

        # ---- Quick start -------------------------------------------------
        self.layout.addWidget(FCLabel('%s' % _("Quick Start"), color='darkorange', bold=True))
        qs = FCFrame()
        self.layout.addWidget(qs)
        qg = GLay(v_spacing=4, h_spacing=3)
        qs.setLayout(qg)

        self.top_combo = self._obj_combo(0, "Gerber")
        self.top_import_btn = self._dots(_("Import a Gerber into the project."))
        qg.addWidget(FCLabel('%s:' % _("Top Copper")), 0, 0)
        qg.addWidget(self.top_combo, 0, 1)
        qg.addWidget(self.top_import_btn, 0, 2)

        self.drills_cb = FCCheckBox('%s' % _("Drills"))
        self.drills_combo = self._obj_combo(1, "Excellon")
        self.drills_import_btn = self._dots(_("Import an Excellon into the project."))
        qg.addWidget(self.drills_cb, 2, 0)
        qg.addWidget(self.drills_combo, 2, 1)
        qg.addWidget(self.drills_import_btn, 2, 2)

        self.outline_cb = FCCheckBox('%s' % _("Outline"))
        self.outline_combo = self._obj_combo(0, "Gerber")
        self.outline_import_btn = self._dots(_("Import an outline Gerber into the project."))
        qg.addWidget(self.outline_cb, 4, 0)
        qg.addWidget(self.outline_combo, 4, 1)
        qg.addWidget(self.outline_import_btn, 4, 2)

        qg.addWidget(FCLabel('%s:' % _("Preset")), 6, 0)
        self.preset_combo = FCComboBox()
        for label, _pid, _opt in _PRESETS:
            self.preset_combo.addItem(label)
        qg.addWidget(self.preset_combo, 6, 1, 1, 2)
        self.preset_desc_label = FCLabel("")
        self.preset_desc_label.setWordWrap(True)
        qg.addWidget(self.preset_desc_label, 7, 0, 1, 3)

        qg.addWidget(FCLabel('%s:' % _("Units")), 8, 0)
        self.units_combo = FCComboBox()
        self.units_combo.addItems(["MM", "IN"])
        qg.addWidget(self.units_combo, 8, 1, 1, 2)

        qg.addWidget(FCLabel('%s:' % _("Output")), 9, 0)
        self.outdir_entry = FCEntry()
        self.outdir_entry.setPlaceholderText(_("Folder for exported G-code..."))
        self.outdir_browse_btn = self._dots(_("Browse for the output folder."))
        qg.addWidget(self.outdir_entry, 9, 1)
        qg.addWidget(self.outdir_browse_btn, 9, 2)

        self.create_btn = FCButton(_("Create Plan from Preset"), bold=True)
        self.create_btn.setIcon(QtGui.QIcon(self.app.resource_location + '/properties32.png'))
        self.layout.addWidget(self.create_btn)

        # ---- Steps -------------------------------------------------------
        self.layout.addWidget(FCLabel('%s' % _("Steps"), color='blue', bold=True))
        self.steps_table = FCTable(drag_drop=True)
        self.steps_table.setColumnCount(5)
        self.steps_table.setHorizontalHeaderLabels(['', _("#"), _("Step"), _("Status"), 'uid'])
        self.steps_table.setColumnHidden(_UID_COL, True)
        hh = self.steps_table.horizontalHeader()
        hh.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.steps_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.steps_table.setMinimumHeight(150)
        self.layout.addWidget(self.steps_table)

        tb = FCFrame()
        self.layout.addWidget(tb)
        tbg = GLay(v_spacing=4, h_spacing=3)
        tb.setLayout(tbg)
        self.add_type_combo = FCComboBox()
        for st in jm.STEP_TYPES:
            self.add_type_combo.addItem(sch.STEP_LABELS[st], st)
        self.add_btn = FCButton(_("Add"))
        self.del_btn = FCButton(_("Delete"))
        self.dup_btn = FCButton(_("Duplicate"))
        self.up_btn = FCButton(_("Up"))
        self.down_btn = FCButton(_("Down"))
        self.clear_btn = FCButton(_("Clear"))
        tbg.addWidget(self.add_type_combo, 0, 0)
        tbg.addWidget(self.add_btn, 0, 1)
        tbg.addWidget(self.del_btn, 0, 2)
        tbg.addWidget(self.dup_btn, 1, 0)
        tbg.addWidget(self.up_btn, 1, 1)
        tbg.addWidget(self.down_btn, 1, 2)
        tbg.addWidget(self.clear_btn, 2, 0, 1, 3)

        # ---- Step settings (dynamic) ------------------------------------
        self.layout.addWidget(FCLabel('%s' % _("Step Settings"), color='blue', bold=True))
        self.settings_frame = FCFrame()
        self.layout.addWidget(self.settings_frame)
        self.settings_layout = GLay(v_spacing=4, h_spacing=3)
        self.settings_frame.setLayout(self.settings_layout)
        self.settings_hint = FCLabel(_("Select a step above to edit its parameters."))
        self.settings_hint.setWordWrap(True)
        self.settings_layout.addWidget(self.settings_hint, 0, 0, 1, 2)

        self.status_label = FCLabel(_("Create a plan or add steps to begin."))
        self.status_label.setWordWrap(True)
        self.layout.addWidget(self.status_label)

        # ---- Run / Save / Load ------------------------------------------
        rb = FCFrame()
        self.layout.addWidget(rb)
        rg = GLay(v_spacing=4, h_spacing=3)
        rb.setLayout(rg)
        self.run_btn = FCButton(_("Run Job"), bold=True)
        self.run_btn.setIcon(QtGui.QIcon(self.app.resource_location + '/run32.png'))
        self.stop_btn = FCButton(_("Stop"))
        self.stop_btn.setEnabled(False)
        rg.addWidget(self.run_btn, 0, 0)
        rg.addWidget(self.stop_btn, 0, 1)
        self.save_job_btn = FCButton(_("Save Job"))
        self.load_job_btn = FCButton(_("Load Job"))
        rg.addWidget(self.save_job_btn, 1, 0)
        rg.addWidget(self.load_job_btn, 1, 1)

        self.layout.addStretch(1)
        self.reset_button = FCButton(_("Reset Tool"), bold=True)
        self.reset_button.setIcon(QtGui.QIcon(self.app.resource_location + '/reset32.png'))
        self.layout.addWidget(self.reset_button)

    def _obj_combo(self, group_index, obj_type):
        c = FCComboBox()
        c.setModel(self.app.collection)
        c.setRootModelIndex(self.app.collection.index(group_index, 0, QtCore.QModelIndex()))
        c.obj_type = obj_type
        c.is_last = True
        return c

    def _dots(self, tooltip):
        b = FCButton(_("..."))
        b.setToolTip(tooltip)
        b.setFixedWidth(34)
        return b

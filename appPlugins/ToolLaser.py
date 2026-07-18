# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# File Author: Marius Adrian Stanciu (c)                   #
# Date: 6/11/2026                                          #
# MIT Licence                                              #
# ##########################################################

import os

from PyQt6 import QtWidgets, QtCore, QtGui
from appTool import AppTool
from appGUI.GUIElements import VerticalScrollArea, FCLabel, FCButton, FCFrame, GLay, FCComboBox, FCCheckBox, \
    RadioSet, FCDoubleSpinner, FCSpinner, FCFileSaveDialog

from appPlugins import laser_core

import logging

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

log = logging.getLogger('base')


class ToolLaser(AppTool):
    plugin_tooltip = _("Generates laser engraving or cutting G-Code aimed at laser engravers, using S-power commands to control the beam instead of a spinning cutter. It builds laser-mode toolpaths from your geometry and exports the job. Select the source object, set the laser power and feedrate parameters, then generate and export the laser CNCJob.")

    def __init__(self, app):
        AppTool.__init__(self, app)

        self.app = app
        self.decimals = self.app.decimals

        # Material presets
        self.presets = laser_core.load_laser_presets(
            os.path.join(self.app.app_home, 'assets', 'resources', 'laser_presets.json'))
        self.preset_by_name = {p['name']: p for p in self.presets}

        # the generated laser CNCJob object, used by the export button
        self.laser_cncjob = None

        # True while the UI is being filled programmatically, so that loading values
        # does not look like a manual edit and flip the preset to 'Custom'
        self._loading_ui = False

        # #############################################################################################################
        # ######################################## Tool GUI ###########################################################
        # #############################################################################################################
        self.ui = LaserUI(layout=self.layout, app=self.app, presets=self.presets)
        self.pluginName = self.ui.pluginName

        # #############################################################################################################
        # #####################################    Signals     ########################################################
        # #############################################################################################################
        self.connect_signals_at_init()

    def on_type_obj_index_changed(self, val):
        obj_type = 2 if val == 'geo' else 0
        self.ui.object_combo.setRootModelIndex(self.app.collection.index(obj_type, 0, QtCore.QModelIndex()))
        self.ui.object_combo.setCurrentIndex(0)
        self.ui.object_combo.obj_type = {
            "grb": "gerber", "geo": "geometry"
        }[val]

    def run(self, toggle=True):
        self.app.defaults.report_usage("ToolLaser()")

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

        self.app.ui.notebook.setTabText(2, _("Laser"))

    def install(self, icon=None, separator=None, **kwargs):
        AppTool.install(self, icon, separator, **kwargs)

    def connect_signals_at_init(self):
        # #############################################################################
        # ############################ SIGNALS ########################################
        # #############################################################################
        self.ui.type_obj_radio.activated_custom.connect(self.on_type_obj_index_changed)
        self.ui.preset_combo.currentIndexChanged.connect(self.on_preset_changed)
        self.ui.power_source_radio.activated_custom.connect(self.on_power_source_changed)

        self.ui.generate_button.clicked.connect(self.on_generate)
        self.ui.export_button.clicked.connect(self.on_export)

        self.ui.reset_button.clicked.connect(self.set_tool_ui)

        # Editing any parameter that a preset owns switches the preset to 'Custom', so the
        # edit is not silently overwritten the next time the preset is (re)applied.
        self.ui.power_entry.valueChanged.connect(self.on_param_edited)
        self.ui.speed_entry.valueChanged.connect(self.on_param_edited)
        self.ui.passes_entry.valueChanged.connect(self.on_param_edited)
        self.ui.air_assist_cb.stateChanged.connect(self.on_param_edited)
        self.ui.mode_radio.activated_custom.connect(self.on_param_edited)

    def set_tool_ui(self):

        self.clear_ui(self.layout)
        self.ui = LaserUI(layout=self.layout, app=self.app, presets=self.presets)
        self.pluginName = self.ui.pluginName
        self.connect_signals_at_init()

        self._loading_ui = True

        # The preset is applied FIRST: it fills the parameters it owns (power, speed,
        # passes, air assist, laser mode). The last used values are restored after it, so
        # a manual change - e.g. Constant (M3) instead of the preset's Dynamic (M4) -
        # survives reopening the plugin instead of being reset by the preset.
        self.ui.preset_combo.set_value(self.app.options["tools_laser_preset"])
        self.on_preset_changed()

        # parameters from the application defaults
        self.ui.power_entry.set_value(int(self.app.options["tools_laser_power_pct"]))
        self.ui.power_max_entry.set_value(int(self.app.options["tools_laser_power_max"]))
        self.ui.speed_entry.set_value(float(self.app.options["tools_laser_speed"]))
        self.ui.beam_entry.set_value(float(self.app.options["tools_laser_beam_width"]))
        self.ui.passes_entry.set_value(int(self.app.options["tools_laser_passes"]))
        self.ui.overlap_entry.set_value(float(self.app.options["tools_laser_overlap"]))
        self.ui.air_assist_cb.set_value(self.app.options["tools_laser_air_assist"])
        self.ui.mode_radio.set_value(self.app.options["tools_laser_mode"])

        # populate the preprocessor combo with ONLY laser preprocessors and select one
        self.ui.pp_laser_combo.clear()
        laser_pps = sorted(name for name in self.app.preprocessors.keys() if 'laser' in name.lower())
        self.ui.pp_laser_combo.addItems(laser_pps)
        for it in range(self.ui.pp_laser_combo.count()):
            self.ui.pp_laser_combo.setItemData(
                it, self.ui.pp_laser_combo.itemText(it), QtCore.Qt.ItemDataRole.ToolTipRole)
        wanted_pp = self.app.options.get("tools_laser_ppname", "GRBL_laser")
        if wanted_pp in laser_pps:
            self.ui.pp_laser_combo.set_value(wanted_pp)
        elif laser_pps:
            self.ui.pp_laser_combo.set_value(laser_pps[0])

        # power source; when the power is set in the sender (LaserGRBL) the Power entry is disabled
        power_source = 'app' if self.app.options["tools_laser_power_in_app"] else 'sender'
        self.ui.power_source_radio.set_value(power_source)
        self.on_power_source_changed(power_source)

        self._loading_ui = False

        # select in the Source Object combobox the object that is selected in the Project Tab, if any
        obj = self.app.collection.get_active()
        if obj and obj.kind in ['gerber', 'geometry']:
            obj_type = {'gerber': 'grb', 'geometry': 'geo'}[obj.kind]
            self.ui.type_obj_radio.set_value(obj_type)
            # run once to update the obj_type attribute in the FCCombobox so the last object is showed in cb
            self.on_type_obj_index_changed(val=obj_type)
            self.ui.object_combo.set_value(obj.obj_options['name'])
        else:
            self.ui.type_obj_radio.set_value('grb')
            # run once to update the obj_type attribute in the FCCombobox so the last object is showed in cb
            self.on_type_obj_index_changed(val='grb')

    def on_preset_changed(self, index=None):
        """Fill the laser parameters from the selected material preset.
        Selecting 'Custom' changes nothing."""
        preset_name = self.ui.preset_combo.get_value()
        preset = self.preset_by_name.get(preset_name)
        if preset is None or preset_name == 'Custom':
            return

        # filling the parameters from the preset is not a manual edit
        was_loading = self._loading_ui
        self._loading_ui = True
        try:
            self.ui.power_entry.set_value(int(preset['power_pct']))
            self.ui.speed_entry.set_value(float(preset['speed']))
            self.ui.passes_entry.set_value(int(preset['passes']))
            self.ui.air_assist_cb.set_value(bool(preset['air_assist']))
            self.ui.mode_radio.set_value(preset['laser_mode'])
        finally:
            self._loading_ui = was_loading

    def on_param_edited(self, *args):
        """A parameter owned by a preset was changed by hand: switch the preset to
        'Custom' so the value is kept instead of being overwritten by the preset."""
        if self._loading_ui:
            return
        if self.ui.preset_combo.get_value() == 'Custom':
            return
        if self.ui.preset_combo.findText('Custom') < 0:
            return
        self.ui.preset_combo.set_value('Custom')

    def on_power_source_changed(self, val):
        """When the power is set in the sender (LaserGRBL), the Power entry is greyed out."""
        self.ui.power_entry.setDisabled(val == 'sender')

    def _resolve_geometry(self, source_obj, beam_width):
        """Return (geometry_object, is_internal) to trace. For a Gerber source create an
        internal 'follow' geometry (the centerline of the Gerber traces)."""
        if source_obj.kind == 'geometry':
            return source_obj, False

        if source_obj.kind == 'gerber':
            trace_name = '%s_laser_trace' % source_obj.obj_options['name']

            # follow_geo() -> app_obj.new_object() runs synchronously when called from the
            # main thread (the object_created signal is delivered directly), so the new
            # object is in the collection when the call returns. The collection may rename
            # it on a name collision, therefore detect it by diffing the collection names.
            names_before = set(self.app.collection.get_names())
            source_obj.follow_geo(outname=trace_name)

            geo = None
            for new_name in set(self.app.collection.get_names()) - names_before:
                candidate = self.app.collection.get_by_name(new_name)
                if candidate is not None and candidate.kind == 'geometry':
                    geo = candidate
                    break

            if geo is None:
                self.app.inform.emit('[ERROR_NOTCL] %s' % _("Could not create the laser trace geometry."))
                return None, False

            # follow_geo() labels the trace with the default milling tool diameter
            # (e.g. 2.4mm) which is misleading for a laser; use the beam width
            geo.obj_options['tools_mill_tooldia'] = beam_width
            for tool_uid in geo.tools:
                geo.tools[tool_uid]['tooldia'] = self.app.dec_format(float(beam_width), self.decimals)
                geo.tools[tool_uid]['data']['tools_mill_tooldia'] = beam_width
            return geo, True

        self.app.inform.emit('[ERROR_NOTCL] %s' % _("Select a Gerber or Geometry object."))
        return None, False

    def _make_widened_geometry(self, base_name, widened_geometry, beam_width):
        """Create an internal multi-geo Geometry object holding the widened (sideways
        overlapping passes) geometry, so the generation engine traces it on both of
        its code paths."""
        widen_name = '%s_laser_widen' % base_name
        decimals = self.decimals

        def widen_init(new_obj, app_obj):
            new_obj.multigeo = True
            new_obj.solid_geometry = widened_geometry
            new_obj.obj_options['tools_mill_tooldia'] = beam_width

            default_data = {}
            for opt_key, opt_val in app_obj.options.items():
                if opt_key.find('geometry_') == 0:
                    default_data[opt_key[len('geometry_'):]] = opt_val
                if opt_key.find('tools_mill_') == 0:
                    default_data[opt_key] = opt_val
            default_data['tools_mill_tooldia'] = beam_width
            default_data['name'] = widen_name

            new_obj.tools = {
                1: {
                    'tooldia': app_obj.dec_format(float(beam_width), decimals),
                    'data': default_data,
                    'solid_geometry': widened_geometry
                }
            }

        names_before = set(self.app.collection.get_names())
        self.app.app_obj.new_object("geometry", widen_name, widen_init)
        for new_name in set(self.app.collection.get_names()) - names_before:
            candidate = self.app.collection.get_by_name(new_name)
            if candidate is not None and candidate.kind == 'geometry':
                return candidate
        return None

    def on_generate(self):
        """Generate a CNCJob object with laser G-code from the selected source object."""
        obj_name = self.ui.object_combo.currentText()
        source_obj = self.app.collection.get_by_name(obj_name)
        if source_obj is None:
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Object not found"), str(obj_name)))
            return

        # remember the source (Gerber/Geometry) name and a sensible export folder so the
        # exported .nc defaults to the source's name inside a "Job" folder. FlatCAM does not
        # keep a per-object path, so use the last folder a file was opened from (the project
        # folder) as the base - captured now, while it still points at this project.
        self.laser_source_name = source_obj.obj_options['name']
        base_dir = self.app.get_last_folder() or self.app.get_last_save_folder()
        self.laser_job_dir = os.path.join(base_dir, 'Job') if base_dir else None

        # laser parameters from the UI
        power_in_app = self.ui.power_source_radio.get_value() == 'app'
        power_pct = self.ui.power_entry.get_value()
        power_max = float(self.ui.power_max_entry.get_value())
        speed = self.ui.speed_entry.get_value()
        beam_width = float(self.ui.beam_entry.get_value())
        n_passes = int(self.ui.passes_entry.get_value())
        overlap = float(self.ui.overlap_entry.get_value())
        air_assist = self.ui.air_assist_cb.get_value()
        laser_mode = self.ui.mode_radio.get_value()

        geo, is_internal = self._resolve_geometry(source_obj, beam_width)
        if geo is None:
            return

        # with an overlap above 0% the passes widen the cut sideways: replace the
        # geometry with offset contours and trace the result a single time
        repeat_passes = n_passes
        if n_passes > 1 and overlap > 0:
            widened, ok = laser_core.widen_passes(geo.solid_geometry, beam_width, n_passes, overlap)
            if ok:
                if is_internal:
                    # the trace object is ours; let it hold (and show) the widened passes
                    geo.solid_geometry = widened
                    for tool_uid in geo.tools:
                        geo.tools[tool_uid]['solid_geometry'] = widened
                else:
                    # do not touch the user's object; widen into an internal geometry
                    widen_geo = self._make_widened_geometry(
                        source_obj.obj_options['name'], widened, beam_width)
                    if widen_geo is None:
                        self.app.inform.emit(
                            '[ERROR_NOTCL] %s' % _("Could not create the widened laser geometry."))
                        return
                    geo = widen_geo
                repeat_passes = 1
            else:
                self.app.inform.emit(
                    '[WARNING_NOTCL] %s' % _("Could not widen the passes; the passes will "
                                             "burn the same line instead."))

        params = {
            'power_in_app': power_in_app,
            'power_pct': power_pct,
            'power_max': power_max,
            'speed': speed,
            'air_assist': air_assist,
            'laser_mode': laser_mode,
            'ppname': self.ui.pp_laser_combo.get_value(),
        }

        tools_dict = laser_core.build_laser_tools_dict(
            geo.obj_options, params, geo.solid_geometry, beam_width=beam_width)

        out_name = '%s_laser' % source_obj.obj_options['name']

        # Generate the CNCJob with the same engine the Milling plugin uses; unlike the
        # legacy GeometryObject.mtool_gen_cncjob() it forwards the laser parameters
        # (tools_mill_laser_on, tools_mill_min_power) to the G-code generator.
        # With use_thread=False it runs synchronously on the main thread, so the new
        # object is in the collection when the call returns; the collection may rename
        # it on a name collision, therefore detect it by diffing the collection names.
        names_before = set(self.app.collection.get_names())
        self.app.milling_tool.generate_cnc_job_handler(
            geo_obj=geo, outname=out_name, tools_dict=tools_dict,
            toolchange=False, plot=True, use_thread=False, from_tcl=True)

        cncjob = None
        for new_name in set(self.app.collection.get_names()) - names_before:
            candidate = self.app.collection.get_by_name(new_name)
            if candidate is not None and candidate.kind == 'cncjob':
                cncjob = candidate
                break

        if cncjob is None:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Laser job generation failed."))
            return

        # the milling engine switches to the Properties tab; come back to this plugin
        self.app.ui.notebook.setCurrentWidget(self.app.ui.plugin_tab)

        # multiple passes burning the same line: repeat the cut body (laser ON .. laser
        # OFF) of each tool G-code; not used when the passes were widened sideways
        if repeat_passes > 1:
            repeated_any = False
            for tool_uid in cncjob.tools:
                new_gcode, ok = laser_core.repeat_cut_passes(cncjob.tools[tool_uid]['gcode'], repeat_passes)
                if ok:
                    cncjob.tools[tool_uid]['gcode'] = new_gcode
                    repeated_any = True
            if not repeated_any:
                self.app.inform.emit(
                    '[WARNING_NOTCL] %s' % _("Could not apply multiple passes; generated a single pass. "
                                             "You can set passes in LaserGRBL instead."))

        # The export - and the CNCJob object's own 'Save CNC Code' button - write
        # cncjob.source_file, so rebuild it from the per-tool G-code. This propagates the
        # repeated passes and also makes sure the start G-code is included (the
        # multi-geometry engine path leaves it out of source_file).
        total_gcode = ''
        for tool_uid in cncjob.tools:
            total_gcode += cncjob.tools[tool_uid]['gcode']
        cncjob.source_file = cncjob.gc_start + total_gcode

        self.laser_cncjob = cncjob

        # remember the used parameters
        self.app.options['tools_laser_power_pct'] = power_pct
        self.app.options['tools_laser_power_max'] = power_max
        self.app.options['tools_laser_speed'] = speed
        self.app.options['tools_laser_beam_width'] = beam_width
        self.app.options['tools_laser_passes'] = n_passes
        self.app.options['tools_laser_overlap'] = overlap
        self.app.options['tools_laser_air_assist'] = air_assist
        self.app.options['tools_laser_mode'] = laser_mode
        self.app.options['tools_laser_ppname'] = self.ui.pp_laser_combo.get_value()
        self.app.options['tools_laser_power_in_app'] = power_in_app
        self.app.options['tools_laser_preset'] = self.ui.preset_combo.get_value()

        self.app.inform.emit('[success] %s' % _("Laser job generated. Use 'Export for LaserGRBL'."))

    def on_export(self):
        """Save the laser job G-code to a file that can be loaded in LaserGRBL."""
        if self.laser_cncjob is None:
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("Generate a laser job first."))
            return

        dir_file_to_save = self._default_export_filepath()

        _filter_ = "G-Code Files (*.nc *.gcode *.ngc);;All Files (*.*)"
        try:
            filename, _f = FCFileSaveDialog.get_saved_filename(
                caption=_("Export for LaserGRBL"),
                directory=dir_file_to_save,
                ext_filter=_filter_
            )
        except TypeError:
            filename, _f = FCFileSaveDialog.get_saved_filename(
                caption=_("Export for LaserGRBL"),
                ext_filter=_filter_
            )

        if str(filename) == '':
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("Export cancelled ..."))
            return

        self._export_to_file(filename)

    def _default_export_filepath(self):
        """Build the default path the Export dialog opens at: a "Job" folder next to the
        source (created if needed), with a file named after the source Gerber/Geometry."""
        src_name = getattr(self, 'laser_source_name', None)
        if src_name:
            default_name = str(src_name) + '_laser'
        else:
            default_name = str(self.laser_cncjob.obj_options['name'])

        target_dir = None
        job_dir = getattr(self, 'laser_job_dir', None)
        if job_dir:
            if not os.path.isdir(job_dir):
                try:
                    os.makedirs(job_dir, exist_ok=True)
                except OSError:
                    job_dir = None
            target_dir = job_dir
        if not target_dir:
            last_folder = self.app.options['tools_laser_last_export_folder']
            if last_folder and os.path.isdir(last_folder):
                target_dir = last_folder
            else:
                target_dir = self.app.get_last_save_folder() or ''

        return os.path.join(target_dir, default_name + '.nc')

    def _export_to_file(self, filename):
        """Write the generated laser job G-code to the given file, through the same
        handler used by the CNCJob object's 'Save CNC Code' button."""
        filename = str(filename)
        ret_val = self.laser_cncjob.export_gcode_handler(filename, is_gcode=True, rename_object=False)
        if ret_val == 'fail':
            return 'fail'

        # remember the folder for the next export
        self.app.options['tools_laser_last_export_folder'] = os.path.dirname(filename)


class LaserUI:

    pluginName = _("Laser")

    def __init__(self, layout, app, presets):
        self.app = app
        self.decimals = self.app.decimals
        self.layout = layout
        self.presets = presets

        self.tools_frame = QtWidgets.QFrame()
        self.tools_frame.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.tools_frame)
        self.tools_box = QtWidgets.QVBoxLayout()
        self.tools_box.setContentsMargins(0, 0, 0, 0)
        self.tools_frame.setLayout(self.tools_box)

        # ## Title
        title_label = FCLabel("%s" % self.pluginName, size=16, bold=True)
        title_label.setToolTip(
            _("Generate a GRBL laser job from a Gerber or Geometry object.")
        )
        self.tools_box.addWidget(title_label)

        # #############################################################################################################
        # Source Object Frame
        # #############################################################################################################
        self.obj_combo_label = FCLabel('%s' % _("Source Object"), color='darkorange', bold=True)
        self.obj_combo_label.setToolTip(
            _("The object whose geometry will be traced by the laser.")
        )
        self.tools_box.addWidget(self.obj_combo_label)

        obj_frame = FCFrame()
        self.tools_box.addWidget(obj_frame)

        obj_grid = GLay(v_spacing=5, h_spacing=3)
        obj_frame.setLayout(obj_grid)

        # Type of object used as the source for the laser job
        self.type_obj_radio = RadioSet([{'label': _('Gerber'), 'value': 'grb'},
                                        {'label': _('Geometry'), 'value': 'geo'}])

        self.type_obj_radio_label = FCLabel('%s:' % _("Type"))
        self.type_obj_radio_label.setToolTip(
            _("Specify the type of object used as source for the laser job.\n"
              "The object can be of type: Gerber or Geometry.\n"
              "The selection here decide the type of objects that will be\n"
              "in the Source Object combobox.")
        )
        obj_grid.addWidget(self.type_obj_radio_label, 0, 0)
        obj_grid.addWidget(self.type_obj_radio, 0, 1)

        # List of objects that can be the source of the laser job
        self.object_combo = FCComboBox()
        self.object_combo.setModel(self.app.collection)
        self.object_combo.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        self.object_combo.is_last = True

        obj_grid.addWidget(self.object_combo, 2, 0, 1, 2)

        # #############################################################################################################
        # Parameters Frame
        # #############################################################################################################
        self.param_label = FCLabel('%s' % _("Parameters"), color='blue', bold=True)
        self.param_label.setToolTip(
            _("Laser engraving/cutting parameters.")
        )
        self.tools_box.addWidget(self.param_label)

        param_frame = FCFrame()
        self.tools_box.addWidget(param_frame)

        param_grid = GLay(v_spacing=5, h_spacing=3)
        param_frame.setLayout(param_grid)

        # Material preset
        self.preset_label = FCLabel('%s:' % _("Material preset"))
        self.preset_label.setToolTip(
            _("A set of laser parameters suited for a certain material.\n"
              "Selecting a preset will fill the parameters below.\n"
              "Select 'Custom' to set the parameters manually.")
        )
        self.preset_combo = FCComboBox()
        self.preset_combo.addItems([p['name'] for p in self.presets])

        param_grid.addWidget(self.preset_label, 0, 0)
        param_grid.addWidget(self.preset_combo, 0, 1)

        # Power source
        self.power_source_label = FCLabel('%s:' % _("Power source"))
        self.power_source_label.setToolTip(
            _("Where the laser power is set. Either way an S value is written in the\n"
              "G-code (GRBL needs it - the laser is off without one):\n"
              "- 'Set in FlatCAM' -> the Power %% below is baked into every move.\n"
              "- 'Set in LaserGRBL' -> the job is written at full power; trim it live\n"
              "  with LaserGRBL's power-override slider while the job runs.")
        )
        self.power_source_radio = RadioSet([{'label': _('Set in FlatCAM'), 'value': 'app'},
                                            {'label': _('Set in LaserGRBL'), 'value': 'sender'}])

        param_grid.addWidget(self.power_source_label, 2, 0)
        param_grid.addWidget(self.power_source_radio, 2, 1)

        # Power
        self.power_label = FCLabel('%s:' % _("Power"))
        self.power_label.setToolTip(
            _("Laser power as a percentage of the maximum power.")
        )
        self.power_entry = FCSpinner(suffix='%', callback=self.confirmation_message_int)
        self.power_entry.set_range(0, 100)

        param_grid.addWidget(self.power_label, 4, 0)
        param_grid.addWidget(self.power_entry, 4, 1)

        # Max power (S value) - must match the controller's $30 setting
        self.power_max_label = FCLabel('%s:' % _("Max power (S)"))
        self.power_max_label.setToolTip(
            _("The S value that means 100% power, i.e. your GRBL controller's $30\n"
              "setting (default 1000; some boards use 255). The Power % is scaled\n"
              "against this, so it must match $30 or the percentage will be wrong.")
        )
        self.power_max_entry = FCSpinner(callback=self.confirmation_message_int)
        self.power_max_entry.set_range(1, 100000)

        param_grid.addWidget(self.power_max_label, 5, 0)
        param_grid.addWidget(self.power_max_entry, 5, 1)

        # Speed
        speed_unit = _("mm/min") if str(self.app.app_units).upper() == 'MM' else _("in/min")
        self.speed_label = FCLabel('%s:' % _("Speed"))
        self.speed_label.setToolTip(
            '%s\n%s.' % (_("The speed of the laser head while the laser is on,"), speed_unit)
        )
        self.speed_entry = FCDoubleSpinner(suffix=speed_unit, callback=self.confirmation_message)
        self.speed_entry.set_range(1.0000, 100000.0000)
        self.speed_entry.set_precision(self.decimals)
        self.speed_entry.setSingleStep(10)

        param_grid.addWidget(self.speed_label, 6, 0)
        param_grid.addWidget(self.speed_entry, 6, 1)

        # Beam width
        size_unit = _("mm") if str(self.app.app_units).upper() == 'MM' else _("in")
        self.beam_label = FCLabel('%s:' % _("Beam width"))
        self.beam_label.setToolTip(
            _("The diameter of the laser spot on the material.\n"
              "Used as the tool size and as the step for overlapping passes.")
        )
        self.beam_entry = FCDoubleSpinner(suffix=size_unit, callback=self.confirmation_message)
        self.beam_entry.set_range(0.0100, 10.0000)
        self.beam_entry.set_precision(self.decimals)
        self.beam_entry.setSingleStep(0.01)

        param_grid.addWidget(self.beam_label, 7, 0)
        param_grid.addWidget(self.beam_entry, 7, 1)

        # Passes
        self.passes_label = FCLabel('%s:' % _("Passes"))
        self.passes_label.setToolTip(
            _("How many times the laser traces the job.\n"
              "With Pass overlap 0% every pass burns the same line\n"
              "(deeper cut, e.g. to cut through the material).\n"
              "With Pass overlap above 0% every pass is shifted sideways\n"
              "by the beam width minus the overlap (wider cut).")
        )
        self.passes_entry = FCSpinner(callback=self.confirmation_message_int)
        self.passes_entry.set_range(1, 100)

        param_grid.addWidget(self.passes_label, 8, 0)
        param_grid.addWidget(self.passes_entry, 8, 1)

        # Pass overlap
        self.overlap_label = FCLabel('%s:' % _("Pass overlap"))
        self.overlap_label.setToolTip(
            _("How much a pass overlaps the previous one, as a percentage\n"
              "of the beam width.\n"
              "0% -> all passes burn the same line (cut deeper).\n"
              "Above 0% -> every pass is offset sideways, widening the cut;\n"
              "useful to widen a PCB isolation gap or engrave thick lines.")
        )
        self.overlap_entry = FCDoubleSpinner(suffix='%', callback=self.confirmation_message)
        self.overlap_entry.set_range(0.0000, 99.0000)
        self.overlap_entry.set_precision(self.decimals)
        self.overlap_entry.setSingleStep(5)

        param_grid.addWidget(self.overlap_label, 9, 0)
        param_grid.addWidget(self.overlap_entry, 9, 1)

        # Air assist
        self.air_assist_cb = FCCheckBox('%s' % _("Air assist"))
        self.air_assist_cb.setToolTip(
            _("When checked, the air assist pump is turned on\n"
              "for the duration of the job.")
        )
        param_grid.addWidget(self.air_assist_cb, 10, 0, 1, 2)

        # Laser mode
        self.mode_label = FCLabel('%s:' % _("Laser mode"))
        self.mode_label.setToolTip(
            _("Laser power mode:\n"
              "- 'Dynamic (M4)' -> power is adjusted with the speed; best for engraving\n"
              "- 'Constant (M3)' -> constant power; best for cutting.")
        )
        self.mode_radio = RadioSet([{'label': _('Dynamic (M4)'), 'value': 'M4'},
                                    {'label': _('Constant (M3)'), 'value': 'M3'}])

        param_grid.addWidget(self.mode_label, 12, 0)
        param_grid.addWidget(self.mode_radio, 12, 1)

        # Preprocessor (laser G-code dialect) - only laser preprocessors are listed
        self.pp_label = FCLabel('%s:' % _("Preprocessor"))
        self.pp_label.setToolTip(
            _("The preprocessor (G-code dialect) used to generate the laser job.\n"
              "Only laser preprocessors are listed, so the output always uses laser\n"
              "on/off (M3/M4/M5) commands instead of spindle and Z plunge moves.")
        )
        self.pp_laser_combo = FCComboBox()
        param_grid.addWidget(self.pp_label, 14, 0)
        param_grid.addWidget(self.pp_laser_combo, 14, 1)

        GLay.set_common_column_size([obj_grid, param_grid], 0)

        # #############################################################################################################
        # Buttons
        # #############################################################################################################
        self.generate_button = FCButton(_("Generate Laser Job"), bold=True)
        self.generate_button.setIcon(QtGui.QIcon(self.app.resource_location + '/cnc32.png'))
        self.generate_button.setToolTip(
            _("Generate a CNCJob object with laser G-code\n"
              "made using the parameters above.")
        )
        self.tools_box.addWidget(self.generate_button)

        self.export_button = FCButton(_("Export for LaserGRBL"), bold=True)
        self.export_button.setIcon(QtGui.QIcon(self.app.resource_location + '/save_as.png'))
        self.export_button.setToolTip(
            _("Save the generated laser G-code to a file\n"
              "that can be loaded in LaserGRBL.")
        )
        self.tools_box.addWidget(self.export_button)

        self.layout.addStretch(1)

        # ## Reset Tool
        self.reset_button = FCButton(_("Reset Tool"), bold=True)
        self.reset_button.setIcon(QtGui.QIcon(self.app.resource_location + '/reset32.png'))
        self.reset_button.setToolTip(
            _("Will reset the tool parameters.")
        )
        self.layout.addWidget(self.reset_button)

    def confirmation_message(self, accepted, minval, maxval):
        if accepted is False:
            self.app.inform[str, bool].emit('[WARNING_NOTCL] %s: [%.*f, %.*f]' % (_("Edited value is out of range"),
                                                                                  self.decimals,
                                                                                  minval,
                                                                                  self.decimals,
                                                                                  maxval), False)
        else:
            self.app.inform[str, bool].emit('[success] %s' % _("Edited value is within limits."), False)

    def confirmation_message_int(self, accepted, minval, maxval):
        if accepted is False:
            self.app.inform[str, bool].emit('[WARNING_NOTCL] %s: [%d, %d]' %
                                            (_("Edited value is out of range"), minval, maxval), False)
        else:
            self.app.inform[str, bool].emit('[success] %s' % _("Edited value is within limits."), False)

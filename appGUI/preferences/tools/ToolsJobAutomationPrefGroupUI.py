
from PyQt6 import QtWidgets

from appGUI.GUIElements import FCCheckBox, FCLabel, GLay, FCFrame
from appGUI.preferences.OptionsGroupUI import OptionsGroupUI

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


class ToolsJobAutomationPrefGroupUI(OptionsGroupUI):
    def __init__(self, app, parent=None):
        super(ToolsJobAutomationPrefGroupUI, self).__init__(self, parent=parent)

        self.setTitle(str(_("Job Automation Plugin")))
        self.decimals = app.decimals
        self.options = app.options

        # #############################################################################################################
        # Job Automation Frame
        # #############################################################################################################
        self.ja_label = FCLabel('%s' % _("Job Automation Settings"), color='blue', bold=True)
        self.layout.addWidget(self.ja_label)

        ja_frame = FCFrame()
        self.layout.addWidget(ja_frame)

        ja_grid = GLay(v_spacing=5, h_spacing=3)
        ja_frame.setLayout(ja_grid)

        # Save on Finish
        self.save_on_finish_label = FCLabel('%s:' % _("Save on Finish"))
        self.save_on_finish_label.setToolTip(
            _("When checked, the application will save the project\n"
              "automatically after a job finishes successfully.")
        )
        self.save_on_finish_cb = FCCheckBox()
        self.save_on_finish_cb.setToolTip(
            _("Auto-save project after successful job completion.")
        )

        ja_grid.addWidget(self.save_on_finish_label, 0, 0)
        ja_grid.addWidget(self.save_on_finish_cb, 0, 1)

        GLay.set_common_column_size([ja_grid], 0)

        self.layout.addStretch()

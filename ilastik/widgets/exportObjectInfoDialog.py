###############################################################################
#   ilastik: interactive learning and segmentation toolkit
#
#       Copyright (C) 2011-2016, the ilastik developers
#                                <team@ilastik.org>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# In addition, as a special exception, the copyright holders of
# ilastik give you permission to combine ilastik with applets,
# workflows and plugins which are not covered under the GNU
# General Public License.
#
# See the LICENSE file for details. License information is also available
# on the ilastik web site at:
#                  http://ilastik.org/license.html
###############################################################################
from __future__ import division
from PyQt4 import uic
from PyQt4.QtCore import *
from PyQt4.QtGui import *

import os.path
import re
from operator import mul

FILE_TYPES = ["h5", "csv"]
REQ_MSG = " (REQUIRED)"
RAW_LAYER_SIZE_LIMIT = 1000000
ALLOWED_EXTENSIONS = ["hdf5", "hd5", "h5", "csv"]
DEFAULT_REQUIRED_FEATURES = ["Count", "Coord<Minimum>", "Coord<Maximum>", "RegionCenter", ]
DIALOG_FILTERS = {
    "h5": "HDF 5 (*.h5 *.hd5 *.hdf5)",
    "csv": "CSV (*.csv)",
    "any": "Any (*.*)",
}


class ExportObjectInfoDialog(QDialog):
    """
    This is a QDialog that asks for the settings for
    the exportObjectInfo operator
    :param dimensions: the dimensions of the raw image [t, x, y, z, c]
    :type dimensions: list
    :param feature_table: nested dict of the computed feature names
    :type feature_table: dict
    :param req_features: list of the features that must be exported. None for default
    :type req_features: list or None
    :param parent: the parent QWidget for this dialog
    :type parent: QWidget or None
    :param filename: The filename to use as default
    :type filename: str or None
    """
    def __init__(self, dimensions, feature_table, req_features=None, selected_features=None, title=None, parent=None, filename=None):
        super(ExportObjectInfoDialog, self).__init__(parent)

        ui_class, widget_class = uic.loadUiType(os.path.split(__file__)[0] + "/exportObjectInfoDialog.ui")
        self.ui = ui_class()
        self.ui.setupUi(self)

        self.setWindowTitle(title)

        self.raw_size = reduce(mul, dimensions, 1)

        if req_features is None:
            req_features = []
        req_features.extend(DEFAULT_REQUIRED_FEATURES)
        
        if selected_features is None:
            selected_features = []

        self._setup_features(feature_table, req_features, selected_features)
        self.ui.featureView.setHeaderLabels(("Select Features",))
        self.ui.featureView.expandAll()

        if filename is not None and self.is_valid_path(filename):
            self.ui.exportPath.setText(filename)
            self.ui.fileFormat.setCurrentIndex(self._get_file_type_index_from_filename(filename))
        else:
            self.ui.exportPath.setText(os.path.expanduser("~") + "/exported_data.h5")
            
        self.ui.exportPath.dropEvent = self._drop_event
        # self.ui.forceUniqueIds.setEnabled(dimensions[0] > 1)
        self.ui.compressFrame.setVisible(False)

    def _get_file_type_index_from_filename(self, filename):
        extension = filename.rsplit(".", 1)[1].lower()
        idx = ALLOWED_EXTENSIONS.index(extension)
        if idx < 3:
            return 0 # file type "h5"
        return 1 # file type "csv"

    def checked_features(self):
        """
        :returns: iterator for all features (names) to export
        :rtype: generator object
        """
        flags = QTreeWidgetItemIterator.Checked
        it = QTreeWidgetItemIterator(self.ui.featureView, flags)
        while it.value():
            text = str(it.value().text(0))
            if text[-len(REQ_MSG):] == REQ_MSG:
                text = text[:-len(REQ_MSG)]
            yield text
            it += 1

    def settings(self):
        """
        file type: the export format (h5 or csv)
        file path: location of the exported file
        compression: dict that contains compression information for h5py
        normalize: make the labeling rois binary
        margin: the margin that should be added around the rois
        include raw: if True include the whole raw image instead of separate rois
        :returns: all settings that can be changed inside the dialog
        :rtype: dict
        """
        s = {
            "file type": unicode(FILE_TYPES[self.ui.fileFormat.currentIndex()]),
            "file path": unicode(self.ui.exportPath.text()),
            "compression": {}
        }

        if s["file type"] == "h5":
            s.update({
                "normalize": True,  # self.ui.normalizeLabeling.checkState() == Qt.Checked,
                "margin": self.ui.addMargin.value(),
                "compression": self._compression_settings(),
                "include raw": self.ui.includeRaw.checkState(),
            })
        return s

    def _drop_event(self, event):
        data = event.mimeData()
        if data.hasText():
            pattern = r"([^/]+)\://(.*)"
            match = re.findall(pattern, data.text())
            if match:
                text = unicode(match[0][1]).strip()
            else:
                text = data.text()
            self.ui.exportPath.setText(text)

    def _setup_features(self, features, req_features, selected_features, max_depth=2, parent=None):
        if max_depth == 2 and not features:
            item = QTreeWidgetItem(parent)
            item.setText(0, "All Default Features will be exported.")
            self.ui.selectAllFeatures.setEnabled(False)
            self.ui.selectNoFeatures.setEnabled(False)
            return
        if max_depth == 0:
            return
        if parent is None:
            parent = self.ui.featureView
        for entry, child in features.iteritems():
            item = QTreeWidgetItem(parent)
            try:
                #if it's the feature name, show the human version of the text
                item.setText(0, child["displaytext"])
            except KeyError:
                item.setText(0, entry)
            self._setup_features(child, req_features, selected_features, max_depth-1, item)
            if child == {} or max_depth == 1:  # no children
                state = Qt.Unchecked
                if entry in selected_features:
                    state = Qt.Checked
                if entry in req_features:
                    state = Qt.Checked
                    item.setDisabled(True)
                    item.setText(0, "%s%s" % (item.text(0), REQ_MSG))
                item.setCheckState(0, state)

    # slot is called from button.click
    def select_all_features(self):
        flags = QTreeWidgetItemIterator.Enabled | \
            QTreeWidgetItemIterator.NoChildren | \
            QTreeWidgetItemIterator.NotChecked
        it = QTreeWidgetItemIterator(self.ui.featureView, flags)
        while it.value():
            it.value().setCheckState(0, Qt.Checked)
            it += 1

    # slot is called from button.click
    def select_no_features(self):
        flags = QTreeWidgetItemIterator.Enabled | \
            QTreeWidgetItemIterator.NoChildren | \
            QTreeWidgetItemIterator.Checked
        it = QTreeWidgetItemIterator(self.ui.featureView, flags)
        while it.value():
            it.value().setCheckState(0, Qt.Unchecked)
            it += 1

    # slot is called from buttonBox.accept
    def validate_before_exit(self):
        if self.ui.exportPath.text() == "":
            title = "Warning"
            text = "Please enter a file name!"
            # noinspection PyArgumentList
            QMessageBox.information(self.parent(), title, text)
            self.ui.toolBox.setCurrentIndex(0)
            return
        else:
            path = unicode(self.ui.exportPath.text())
            if not self.is_valid_path(path):
                title = "Warning"
                text = "No file extension or invalid file extension ( %s )\nAllowed: %s"
                match = path.rsplit(".", 1)
                if len(match) == 1:
                    ext = "<none>"
                else:
                    ext = match[1]
                text %= (ext, ", ".join(ALLOWED_EXTENSIONS))
                # noinspection PyArgumentList
                QMessageBox.information(self.parent(), title, text)
                return

        self.accept()

    def is_valid_path(self, path):
        match = path.rsplit(".", 1)
        if len(match) == 1 or match[1] not in ALLOWED_EXTENSIONS:
            return False
        return True

    # slot is called from button.click
    def choose_path(self):
        filters = ";;".join(DIALOG_FILTERS.values())
        current_extension = FILE_TYPES[self.ui.fileFormat.currentIndex()]
        current_filter = DIALOG_FILTERS[current_extension]
        path = QFileDialog.getSaveFileName(self.parent(), "Save File", self.ui.exportPath.text(), filters,
                                           current_filter)
        path = unicode(path)
        if path != "":
            match = path.rsplit(".", 1)
            if len(match) == 1:
                path = "%s.%s" % (path, current_extension)
            self.ui.exportPath.setText(path)

    # slot is called from checkBox.change
    def include_raw_changed(self, state):
        if state == Qt.Checked\
                and self.raw_size >= RAW_LAYER_SIZE_LIMIT:
            title = "Warning"
            text = "Raw layer is very large (%d%s). Do you really want to include it?"
            text %= (self.raw_size // 3, " Pixel")
            buttons = QMessageBox.Yes | QMessageBox.No
            button = QMessageBox.question(self.parent(), title, text, buttons)
            if button == QMessageBox.No:
                self.ui.includeRaw.setCheckState(Qt.Unchecked)

    # slot is called from comboBox.change
    def change_compression(self, qstring):
        hidden = str(qstring) != "gzip"
        self.ui.gzipRate.setHidden(hidden)
        self.ui.rateLabel.setHidden(hidden)

    # slot is called from combobox.indexchanged
    def file_format_changed(self, index):
        path = unicode(self.ui.exportPath.text())
        match = path.rsplit(".", 1)
        path = "%s.%s" % (match[0], FILE_TYPES[index])
        self.ui.exportPath.setText(path)

        for widget in (self.ui.includeRaw, self.ui.marginLabel, self.ui.addMargin):
            widget.setEnabled(FILE_TYPES[index] != "csv")

    def _compression_settings(self):
        settings = {}
        if self.ui.enableCompression.checkState() == Qt.Checked:
            settings["compression"] = str(self.ui.compressionType.currentText())
            settings["shuffle"] = str(self.ui.enableShuffling.checkState() == Qt.Checked)
            if settings["compression"] == "gzip":
                settings["compression_opts"] = self.ui.gzipRate.value()
        return settings

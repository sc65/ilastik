from PyQt4 import uic, QtGui, QtCore

import os
import logging
import sys
import re
import traceback
import math
import random
import h5py

import pgmlink

from ilastik.applets.base.applet import DatasetConstraintError
from ilastik.applets.tracking.base.trackingBaseGui import TrackingBaseGui
from ilastik.utility.exportingOperator import ExportingGui
from ilastik.utility.gui.threadRouter import threadRouted
from ilastik.utility.gui.titledMenu import TitledMenu
from ilastik.utility.ipcProtocol import Protocol
from ilastik.shell.gui.ipcManager import IPCFacade
from ilastik.config import cfg as ilastik_config
from ilastik.utility import bind

from lazyflow.request.request import Request

logger = logging.getLogger(__name__)
traceLogger = logging.getLogger('TRACE.' + __name__)

class StructuredTrackingGui(TrackingBaseGui, ExportingGui):
    
    withMergers = True
    @threadRouted
    def _setMergerLegend(self, labels, selection):   
        param = self.topLevelOperatorView.Parameters.value
        if 'withMergerResolution' in param.keys():
            if param['withMergerResolution']:
                selection = 1
        elif self._drawer.mergerResolutionBox.isChecked():
            selection = 1

        for i in range(2,len(labels)+1):
            if i <= selection:
                labels[i-1].setVisible(True)
            else:
                labels[i-1].setVisible(False)

        # hide merger legend if selection < 2
        self._drawer.label_4.setVisible(selection > 1)
        labels[0].setVisible(selection > 1)

    def __init__(self, parentApplet, topLevelOperatorView):
        """
        """
        self._initColors()

        self.topLevelOperatorView = topLevelOperatorView
        super(TrackingBaseGui, self).__init__(parentApplet, topLevelOperatorView)
        self.mainOperator = topLevelOperatorView
        if self.mainOperator.LabelImage.meta.shape:
            self.editor.dataShape = self.mainOperator.LabelImage.meta.shape

        self.applet = self.mainOperator.parent.parent.trackingApplet
        self._drawer.mergerResolutionBox.setChecked(True)
        self.connect( self, QtCore.SIGNAL('postInformationMessage(QString)'), self.postInformationMessage)

        self.parentApplet = parentApplet
        self._headless = False

    def _loadUiFile(self):
        localDir = os.path.split(__file__)[0]
        self._drawer = uic.loadUi(localDir+"/drawer.ui")
        
        parameters = self.topLevelOperatorView.Parameters.value        
        if 'maxDist' in parameters.keys():
            self._drawer.maxDistBox.setValue(parameters['maxDist'])
        if 'maxObj' in parameters.keys():
            self._drawer.maxObjectsBox.setValue(parameters['maxObj'])
        if 'maxNearestNeighbors' in parameters.keys():
            self._drawer.maxObjectsBox.setValue(parameters['maxNearestNeighbors'])
        if 'divThreshold' in parameters.keys():
            self._drawer.divThreshBox.setValue(parameters['divThreshold'])
        if 'avgSize' in parameters.keys():
            self._drawer.avgSizeBox.setValue(parameters['avgSize'][0])
        if 'withTracklets' in parameters.keys():
            self._drawer.trackletsBox.setChecked(parameters['withTracklets'])
        if 'sizeDependent' in parameters.keys():
            self._drawer.sizeDepBox.setChecked(parameters['sizeDependent'])
        if 'detWeight' in parameters.keys():
            self._drawer.detWeightBox.setValue(parameters['detWeight'])
        if 'divWeight' in parameters.keys():
            self._drawer.divWeightBox.setValue(parameters['divWeight'])
        if 'transWeight' in parameters.keys():
            self._drawer.transWeightBox.setValue(parameters['transWeight'])
        if 'withDivisions' in parameters.keys():
            self._drawer.divisionsBox.setChecked(parameters['withDivisions'])
        if 'withOpticalCorrection' in parameters.keys():
            self._drawer.opticalBox.setChecked(parameters['withOpticalCorrection'])
        if 'withClassifierPrior' in parameters.keys():
            self._drawer.classifierPriorBox.setChecked(parameters['withClassifierPrior'])
        if 'withMergerResolution' in parameters.keys():
            self._drawer.mergerResolutionBox.setChecked(parameters['withMergerResolution'])
        if 'borderAwareWidth' in parameters.keys():
            self._drawer.bordWidthBox.setValue(parameters['borderAwareWidth'])
        if 'cplex_timeout' in parameters.keys():
            self._drawer.timeoutBox.setText(str(parameters['cplex_timeout']))
        if 'appearanceCost' in parameters.keys():
            self._drawer.appearanceBox.setValue(parameters['appearanceCost'])
        if 'disappearanceCost' in parameters.keys():
            self._drawer.disappearanceBox.setValue(parameters['disappearanceCost'])
        
        return self._drawer

    def initAppletDrawerUi(self):
        self._previousCrop = -1
        self._currentCrop = -1
        self._currentCropName = ""
        self._maxNearestNeighbors = 1

        super(StructuredTrackingGui, self).initAppletDrawerUi()

        self.realOperator = self.topLevelOperatorView.Labels.getRealOperator()
        for i, op in enumerate(self.realOperator.innerOperators):
            self.operator = op

        self._allowedTimeoutInputRegEx = re.compile('^[0-9]*$')
        self._drawer.timeoutBox.textChanged.connect(self._onTimeoutBoxChanged)

        if not ilastik_config.getboolean("ilastik", "debug"):
            def checkboxAssertHandler(checkbox, assertEnabled=True):
                if checkbox.isChecked() == assertEnabled:
                    checkbox.hide()
                else:
                    checkbox.setEnabled(False)

            checkboxAssertHandler(self._drawer.trackletsBox, True)

            if self._drawer.classifierPriorBox.isChecked():
                self._drawer.hardPriorBox.hide()
                self._drawer.classifierPriorBox.hide()
                self._drawer.sizeDepBox.hide()
            else:
                self._drawer.hardPriorBox.setEnabled(False)
                self._drawer.classifierPriorBox.setEnabled(False)
                self._drawer.sizeDepBox.setEnabled(False)

            checkboxAssertHandler(self._drawer.opticalBox, False)
            checkboxAssertHandler(self._drawer.mergerResolutionBox, True)

            self._drawer.maxDistBox.hide()
            self._drawer.label_2.hide()
            self._drawer.label_5.hide()
            self._drawer.divThreshBox.hide()
            self._drawer.label_25.hide()
            self._drawer.avgSizeBox.hide()
          
        self.mergerLabels = [
            self._drawer.merg1,
            self._drawer.merg2,
            self._drawer.merg3,
            self._drawer.merg4,
            self._drawer.merg5,
            self._drawer.merg6,
            self._drawer.merg7]

        for i in range(len(self.mergerLabels)):
            self._labelSetStyleSheet(self.mergerLabels[i], self.mergerColors[i+1])
        
        self._drawer.maxObjectsBox.valueChanged.connect(self._onMaxObjectsBoxChanged)
        self._drawer.mergerResolutionBox.stateChanged.connect(self._onMaxObjectsBoxChanged)

        self._drawer.StructuredLearningButton.clicked.connect(self._onRunStructuredLearningButtonPressed)

        self._drawer.divWeightBox.valueChanged.connect(self._onDivisionWeightBoxChanged)                
        self._drawer.detWeightBox.valueChanged.connect(self._onDetectionWeightBoxChanged)                
        self._drawer.transWeightBox.valueChanged.connect(self._onTransitionWeightBoxChanged)                
        self._drawer.appearanceBox.valueChanged.connect(self._onAppearanceWeightBoxChanged)                
        self._drawer.disappearanceBox.valueChanged.connect(self._onDisappearanceWeightBoxChanged)                
        self._drawer.maxNearestNeighborsSpinBox.valueChanged.connect(self._onMaxNearestNeighborsSpinBoxChanged)

        self._drawer.OnesButton.clicked.connect(self._onOnesButtonPressed)
        self._drawer.ZerosButton.clicked.connect(self._onZerosButtonPressed)
        self._drawer.RandomButton.clicked.connect(self._onRandomButtonPressed)

        self._divisionWeight = self.topLevelOperatorView.DivisionWeight.value
        self._detectionWeight = self.topLevelOperatorView.DetectionWeight.value
        self._transitionWeight = self.topLevelOperatorView.TransitionWeight.value
        self._appearanceWeight = self.topLevelOperatorView.AppearanceWeight.value
        self._disappearanceWeight = self.topLevelOperatorView.DisappearanceWeight.value

        self._drawer.detWeightBox.setValue(self._detectionWeight)
        self._drawer.divWeightBox.setValue(self._divisionWeight)
        self._drawer.transWeightBox.setValue(self._transitionWeight)
        self._drawer.appearanceBox.setValue(self._appearanceWeight)
        self._drawer.disappearanceBox.setValue(self._disappearanceWeight)

        self._maxNumObj = self.topLevelOperatorView.MaxNumObj.value
        self._drawer.maxObjectsBox.setValue(self.topLevelOperatorView.MaxNumObj.value)
        self._onMaxObjectsBoxChanged()
        self._drawer.maxObjectsBox.setReadOnly(True)

        self.topLevelOperatorView.Labels.notifyReady( bind(self._updateLabelsFromOperator) )
        self.topLevelOperatorView.Divisions.notifyReady( bind(self._updateDivisionsFromOperator) )

        self.operator.labels = self.operator.Labels.value
        self.topLevelOperatorView._updateCropsFromOperator()

        self._drawer.trainingToHardConstraints.setChecked(False)
        self._drawer.trainingToHardConstraints.setVisible(False) # will be used when we can handle sparse annotations
        self._drawer.exportButton.setVisible(True)
        self._drawer.exportTifButton.setVisible(False)

        self.topLevelOperatorView._detectionWeight = self._detectionWeight
        self.topLevelOperatorView._divisionWeight = self._divisionWeight
        self.topLevelOperatorView._transitionWeight = self._transitionWeight
        self.topLevelOperatorView._appearanceWeight = self._appearanceWeight
        self.topLevelOperatorView._disappearanceWeight = self._disappearanceWeight

    def _onOnesButtonPressed(self):
        val = math.sqrt(1.0/5)
        self.topLevelOperatorView.DivisionWeight.setValue(val)
        self.topLevelOperatorView.DetectionWeight.setValue(val)
        self.topLevelOperatorView.TransitionWeight.setValue(val)
        self.topLevelOperatorView.AppearanceWeight.setValue(val)
        self.topLevelOperatorView.DisappearanceWeight.setValue(val)

        self._divisionWeight = self.topLevelOperatorView.DivisionWeight.value
        self._detectionWeight = self.topLevelOperatorView.DetectionWeight.value
        self._transitionWeight = self.topLevelOperatorView.TransitionWeight.value
        self._appearanceWeight = self.topLevelOperatorView.AppearanceWeight.value
        self._disappearanceWeight = self.topLevelOperatorView.DisappearanceWeight.value

        self._drawer.detWeightBox.setValue(self._detectionWeight)
        self._drawer.divWeightBox.setValue(self._divisionWeight)
        self._drawer.transWeightBox.setValue(self._transitionWeight)
        self._drawer.appearanceBox.setValue(self._appearanceWeight)
        self._drawer.disappearanceBox.setValue(self._disappearanceWeight)

    def _onRandomButtonPressed(self):
        weights = []
        for i in range(5):
            weights.append(random.random())
        sltWeightNorm = 0
        for i in range(5):
           sltWeightNorm += weights[i] * weights[i]
        sltWeightNorm = math.sqrt(sltWeightNorm)
        self.topLevelOperatorView.DivisionWeight.setValue(weights[0]/sltWeightNorm)
        self.topLevelOperatorView.DetectionWeight.setValue(weights[1]/sltWeightNorm)
        self.topLevelOperatorView.TransitionWeight.setValue(weights[2]/sltWeightNorm)
        self.topLevelOperatorView.AppearanceWeight.setValue(weights[3]/sltWeightNorm)
        self.topLevelOperatorView.DisappearanceWeight.setValue(weights[4]/sltWeightNorm)

        self._divisionWeight = self.topLevelOperatorView.DivisionWeight.value
        self._detectionWeight = self.topLevelOperatorView.DetectionWeight.value
        self._transitionWeight = self.topLevelOperatorView.TransitionWeight.value
        self._appearanceWeight = self.topLevelOperatorView.AppearanceWeight.value
        self._disappearanceWeight = self.topLevelOperatorView.DisappearanceWeight.value

        self._drawer.detWeightBox.setValue(self._detectionWeight)
        self._drawer.divWeightBox.setValue(self._divisionWeight)
        self._drawer.transWeightBox.setValue(self._transitionWeight)
        self._drawer.appearanceBox.setValue(self._appearanceWeight)
        self._drawer.disappearanceBox.setValue(self._disappearanceWeight)

    def _onZerosButtonPressed(self):
        self.topLevelOperatorView.DivisionWeight.setValue(0)
        self.topLevelOperatorView.DetectionWeight.setValue(0)
        self.topLevelOperatorView.TransitionWeight.setValue(0)
        self.topLevelOperatorView.AppearanceWeight.setValue(0)
        self.topLevelOperatorView.DisappearanceWeight.setValue(0)

        self._divisionWeight = self.topLevelOperatorView.DivisionWeight.value
        self._detectionWeight = self.topLevelOperatorView.DetectionWeight.value
        self._transitionWeight = self.topLevelOperatorView.TransitionWeight.value
        self._appearanceWeight = self.topLevelOperatorView.AppearanceWeight.value
        self._disappearanceWeight = self.topLevelOperatorView.DisappearanceWeight.value

        self._drawer.detWeightBox.setValue(self._detectionWeight)
        self._drawer.divWeightBox.setValue(self._divisionWeight)
        self._drawer.transWeightBox.setValue(self._transitionWeight)
        self._drawer.appearanceBox.setValue(self._appearanceWeight)
        self._drawer.disappearanceBox.setValue(self._disappearanceWeight)

    @threadRouted
    def _onTimeoutBoxChanged(self, *args):
        inString = str(self._drawer.timeoutBox.text())
        if self._allowedTimeoutInputRegEx.match(inString) is None:
            self._drawer.timeoutBox.setText(inString.decode("utf8").encode("ascii", "replace")[:-1])

    def _onMaxNumObjChanged(self):
        self._maxNumObj = self.topLevelOperatorView.MaxNumObj.value
        self._setMergerLegend(self.mergerLabels, self._maxNumObj)
        self._drawer.maxObjectsBox.setValue(self._maxNumObj)

    @threadRouted
    def _onDivisionWeightBoxChanged(self, *args):
        self._divisionWeight = self._drawer.divWeightBox.value()
        self.topLevelOperatorView.DivisionWeight.setValue(self._divisionWeight)

    @threadRouted
    def _onDetectionWeightBoxChanged(self, *args):
        self._detectionWeight = self._drawer.detWeightBox.value()
        self.topLevelOperatorView.DetectionWeight.setValue(self._detectionWeight)

    @threadRouted
    def _onTransitionWeightBoxChanged(self, *args):
        self._transitionWeight = self._drawer.transWeightBox.value()
        self.topLevelOperatorView.TransitionWeight.setValue(self._transitionWeight)

    @threadRouted
    def _onAppearanceWeightBoxChanged(self, *args):
        self._appearanceWeight = self._drawer.appearanceBox.value()
        self.topLevelOperatorView.AppearanceWeight.setValue(self._appearanceWeight)

    @threadRouted
    def _onDisappearanceWeightBoxChanged(self, *args):
        self._disappearanceWeight = self._drawer.disappearanceBox.value()
        self.topLevelOperatorView.DisappearanceWeight.setValue(self._disappearanceWeight)

    @threadRouted
    def _onMaxNearestNeighborsSpinBoxChanged(self, *args):
        self._maxNearestNeighbors = self._drawer.maxNearestNeighborsSpinBox.value()

    def _setRanges(self, *args):
        super(StructuredTrackingGui, self)._setRanges()
        maxx = self.topLevelOperatorView.LabelImage.meta.shape[1] - 1
        maxy = self.topLevelOperatorView.LabelImage.meta.shape[2] - 1
        maxz = self.topLevelOperatorView.LabelImage.meta.shape[3] - 1
        
        maxBorder = min(maxx, maxy)
        if maxz != 0:
            maxBorder = min(maxBorder, maxz)
        self._drawer.bordWidthBox.setRange(0, maxBorder/2)
        
    def _onMaxObjectsBoxChanged(self):
        self._setMergerLegend(self.mergerLabels, self._drawer.maxObjectsBox.value())
        self._maxNumObj = self._drawer.maxObjectsBox.value()
        self.topLevelOperatorView.MaxNumObjOut.setValue(self._maxNumObj)

    @threadRouted
    def _updateLabelsFromOperator(self):
        self.operator.labels = self.topLevelOperatorView.Labels.wait()

    @threadRouted
    def _updateDivisionsFromOperator(self):
        self.operator.divisions = self.topLevelOperatorView.Divisions.wait()

    def getLabel(self, time, track):
        for label in self.operator.labels[time].keys():
            if self.operator.labels[time][label] == set([track]):
                return label
        return False

    def _onRunStructuredLearningButtonPressed(self, withBatchProcessing=False):

        self.topLevelOperatorView._runStructuredLearning(
            (self._drawer.from_z.value(),self._drawer.to_z.value()),
            self._maxNumObj,
            self._maxNearestNeighbors,
            self._drawer.maxDistBox.value(),
            self._drawer.divThreshBox.value(),
            (self._drawer.x_scale.value(), self._drawer.y_scale.value(), self._drawer.z_scale.value()),
            (self._drawer.from_size.value(), self._drawer.to_size.value()),
            self._drawer.divisionsBox.isChecked(),
            self._drawer.bordWidthBox.value(),
            self._drawer.classifierPriorBox.isChecked(),
            withBatchProcessing)

    def _onTrackButtonPressed( self ):
        if not self.mainOperator.ObjectFeatures.ready():
            self._criticalMessage("You have to compute object features first.")            
            return
        
        def _track():    
            self.applet.busy = True
            self.applet.appletStateUpdateRequested.emit()
            maxDist = self._drawer.maxDistBox.value()
            maxObj = self._drawer.maxObjectsBox.value()        
            divThreshold = self._drawer.divThreshBox.value()
            
            from_t = self._drawer.from_time.value()
            to_t = self._drawer.to_time.value()
            from_x = self._drawer.from_x.value()
            to_x = self._drawer.to_x.value()
            from_y = self._drawer.from_y.value()
            to_y = self._drawer.to_y.value()        
            from_z = self._drawer.from_z.value()
            to_z = self._drawer.to_z.value()        
            from_size = self._drawer.from_size.value()
            to_size = self._drawer.to_size.value()        
            
            self.time_range =  range(from_t, to_t + 1)
            avgSize = [self._drawer.avgSizeBox.value()]

            cplex_timeout = None
            if len(str(self._drawer.timeoutBox.text())):
                cplex_timeout = int(self._drawer.timeoutBox.text())

            withTracklets = True
            sizeDependent = self._drawer.sizeDepBox.isChecked()
            hardPrior = self._drawer.hardPriorBox.isChecked()
            classifierPrior = self._drawer.classifierPriorBox.isChecked()
            detWeight = self._drawer.detWeightBox.value()
            divWeight = self._drawer.divWeightBox.value()
            transWeight = self._drawer.transWeightBox.value()
            withDivisions = self._drawer.divisionsBox.isChecked()        
            withOpticalCorrection = self._drawer.opticalBox.isChecked()
            withMergerResolution = self._drawer.mergerResolutionBox.isChecked()
            borderAwareWidth = self._drawer.bordWidthBox.value()
            withArmaCoordinates = True
            appearanceCost = self._drawer.appearanceBox.value()
            disappearanceCost = self._drawer.disappearanceBox.value()
    
            ndim=3
            if (to_z - from_z == 0):
                ndim=2
            
            try:
                if True:
                    self.mainOperator.track(
                        time_range = self.time_range,
                        x_range = (from_x, to_x + 1),
                        y_range = (from_y, to_y + 1),
                        z_range = (from_z, to_z + 1),
                        size_range = (from_size, to_size + 1),
                        x_scale = self._drawer.x_scale.value(),
                        y_scale = self._drawer.y_scale.value(),
                        z_scale = self._drawer.z_scale.value(),
                        maxDist=maxDist,
                        maxObj = maxObj,
                        divThreshold=divThreshold,
                        avgSize=avgSize,
                        withTracklets=withTracklets,
                        sizeDependent=sizeDependent,
                        detWeight=detWeight,
                        divWeight=divWeight,
                        transWeight=transWeight,
                        withDivisions=withDivisions,
                        withOpticalCorrection=withOpticalCorrection,
                        withClassifierPrior=classifierPrior,
                        ndim=ndim,
                        withMergerResolution=withMergerResolution,
                        borderAwareWidth = borderAwareWidth,
                        withArmaCoordinates = withArmaCoordinates,
                        cplex_timeout = cplex_timeout,
                        appearance_cost = appearanceCost,
                        disappearance_cost = disappearanceCost,
                        #graph_building_parameter_changed = True,
                        #trainingToHardConstraints = self._drawer.trainingToHardConstraints.isChecked(),
                        max_nearest_neighbors = self._maxNearestNeighbors,
                        solverName="ILP"
                        )
            except Exception:
                ex_type, ex, tb = sys.exc_info()
                traceback.print_tb(tb)
                self._criticalMessage("Exception(" + str(ex_type) + "): " + str(ex))
                return
        
        def _handle_finished(*args):
            self.applet.busy = False
            self.applet.appletStateUpdateRequested.emit()
            self.applet.progressSignal.emit(100)
            self._drawer.TrackButton.setEnabled(True)
            self._drawer.exportButton.setEnabled(True)
            self._drawer.exportTifButton.setEnabled(True)
            self._setLayerVisible("Objects", False) 
            
        def _handle_failure( exc, exc_info ):
            self.applet.busy = False
            self.applet.appletStateUpdateRequested.emit()
            self.applet.progressSignal.emit(100)
            traceback.print_exception(*exc_info)
            sys.stderr.write("Exception raised during tracking.  See traceback above.\n")
            self._drawer.TrackButton.setEnabled(True)
        
        self.applet.progressSignal.emit(0)
        self.applet.progressSignal.emit(-1)
        req = Request( _track )
        req.notify_failed( _handle_failure )
        req.notify_finished( _handle_finished )
        req.submit()

    def menus(self):
        m = QtGui.QMenu("&Export", self.volumeEditorWidget)
        m.addAction("Export Tracking Information").triggered.connect(self.show_export_dialog)

        return [m]

    def get_raw_shape(self):
        return self.topLevelOperatorView.RawImage.meta.shape

    def get_feature_names(self):
        params = self.topLevelOperatorView.Parameters
        if params.ready() and params.value["withDivisions"]:
            return self.topLevelOperatorView.ComputedFeatureNamesWithDivFeatures([]).wait()
        return self.topLevelOperatorView.ComputedFeatureNames([]).wait()

    def get_color(self, pos5d):
        slicing = tuple(slice(i, i+1) for i in pos5d)
        color = self.mainOperator.CachedOutput(slicing).wait()
        return color.flat[0]

    def get_object(self, pos5d):
        slicing = tuple(slice(i, i+1) for i in pos5d)
        label = self.mainOperator.RelabeledImage(slicing).wait()
        return label.flat[0], pos5d[0]

    @property
    def gui_applet(self):
        return self.applet

    def get_export_dialog_title(self):
        return "Export Tracking Information"

    # def handleEditorRightClick(self, position5d, win_coord):
    #     debug = ilastik_config.getboolean("ilastik", "debug")
    #
    #     obj, time = self.get_object(position5d)
    #     if obj == 0:
    #         menu = TitledMenu(["Background"])
    #         if debug:
    #             menu.addAction("Clear Hilite", IPCFacade().broadcast(Protocol.cmd("clear")))
    #         menu.exec_(win_coord)
    #         return
    #
    #     try:
    #         extra = self.mainOperator.extra_track_ids
    #     except (IndexError, KeyError):
    #         extra = {}
    #
    #     # if this is a resolved merger, find which of the merged IDs we actually clicked on
    #     if time in extra and obj in extra[time]:
    #         colors = [self.mainOperator.label2color[time][t] for t in extra[time][obj]]
    #         tracks = [self.mainOperator.track_id[time][t] for t in extra[time][obj]]
    #         selected_track = self.get_color(position5d)
    #         idx = colors.index(selected_track)
    #         color = colors[idx]
    #         track = tracks[idx]
    #     else:
    #         try:
    #             color = self.mainOperator.label2color[time][obj]
    #             track = [self.mainOperator.track_id[time][obj]][0]
    #         except (IndexError, KeyError):
    #             color = None
    #             track = []
    #
    #     if track:
    #         children, parents = self.mainOperator.track_family(track)
    #     else:
    #         children, parents = None, None
    #
    #     menu = TitledMenu([
    #         "Object {} of lineage id {}".format(obj, color),
    #         "Track id: " + (str(track) or "None"),
    #     ])
    #
    #     if not debug:
    #         menu.exec_(win_coord)
    #         return
    #
    #     if any(IPCFacade().sending):
    #
    #         obj_sub_menu = menu.addMenu("Hilite Object")
    #         for mode in Protocol.ValidHiliteModes:
    #             where = Protocol.simple("and", ilastik_id=obj, time=time)
    #             cmd = Protocol.cmd(mode, where)
    #             obj_sub_menu.addAction(mode.capitalize(), IPCFacade().broadcast(cmd))
    #
    #         sub_menus = [
    #             ("Tracks", Protocol.simple_in, tracks),
    #             ("Parents", Protocol.simple_in, parents),
    #             ("Children", Protocol.simple_in, children)
    #         ]
    #         for name, protocol, args in sub_menus:
    #             if args:
    #                 sub = menu.addMenu("Hilite {}".format(name))
    #                 for mode in Protocol.ValidHiliteModes[:-1]:
    #                     mode = mode.capitalize()
    #                     where = protocol("track_id*", args)
    #                     cmd = Protocol.cmd(mode, where)
    #                     sub.addAction(mode, IPCFacade().broadcast(cmd))
    #             else:
    #                 sub = menu.addAction("Hilite {}".format(name))
    #                 sub.setEnabled(False)
    #
    #         menu.addAction("Clear Hilite", IPCFacade().broadcast(Protocol.cmd("clear")))
    #     else:
    #         menu.addAction("Open IPC Server Window", IPCFacade().show_info)
    #         menu.addAction("Start IPC Server", IPCFacade().start)
    #
    #     menu.exec_(win_coord)

    def handleEditorRightClick(self, position5d, win_coord):
        debug = ilastik_config.getboolean("ilastik", "debug")

        obj, time = self.get_object(position5d)
        if obj == 0:
            menu = TitledMenu(["Background"])
            if debug:
                menu.addAction("Clear Hilite", IPCFacade().broadcast(Protocol.cmd("clear")))
            menu.exec_(win_coord)
            return

        hypothesesGraph = self.mainOperator.HypothesesGraph.value

        if hypothesesGraph == None:
            color = None
            track = None
        else:
            color = hypothesesGraph.getLineageId(time, obj)
            track = hypothesesGraph.getTrackId(time, obj)

        children = None
        parents = None

        menu = TitledMenu([
            "Object {} of lineage id {}".format(obj, color),
            "Track id: " + (str(track) or "None"),
        ])

        if not debug:
            menu.exec_(win_coord)
            return

        if any(IPCFacade().sending):

            obj_sub_menu = menu.addMenu("Hilite Object")
            for mode in Protocol.ValidHiliteModes:
                where = Protocol.simple("and", ilastik_id=obj, time=time)
                cmd = Protocol.cmd(mode, where)
                obj_sub_menu.addAction(mode.capitalize(), IPCFacade().broadcast(cmd))

            sub_menus = [
                ("Tracks", Protocol.simple_in, tracks),
                ("Parents", Protocol.simple_in, parents),
                ("Children", Protocol.simple_in, children)
            ]
            for name, protocol, args in sub_menus:
                if args:
                    sub = menu.addMenu("Hilite {}".format(name))
                    for mode in Protocol.ValidHiliteModes[:-1]:
                        mode = mode.capitalize()
                        where = protocol("track_id*", args)
                        cmd = Protocol.cmd(mode, where)
                        sub.addAction(mode, IPCFacade().broadcast(cmd))
                else:
                    sub = menu.addAction("Hilite {}".format(name))
                    sub.setEnabled(False)

            menu.addAction("Clear Hilite", IPCFacade().broadcast(Protocol.cmd("clear")))
        else:
            menu.addAction("Open IPC Server Window", IPCFacade().show_info)
            menu.addAction("Start IPC Server", IPCFacade().start)

        menu.exec_(win_coord)

    def _informationMessage(self, prompt):
        self.emit( QtCore.SIGNAL('postInformationMessage(QString)'), prompt)

    @threadRouted
    def postInformationMessage(self, prompt):
        QtGui.QMessageBox.information(self, "Info:", prompt, QtGui.QMessageBox.Ok)


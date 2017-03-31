###############################################################################
#   ilastik: interactive learning and segmentation toolkit
#
#       Copyright (C) 2011-2014, the ilastik developers
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
#		   http://ilastik.org/license.html
###############################################################################
from lazyflow.graph import Graph
from ilastik.workflow import Workflow
from ilastik.applets.dataSelection import DataSelectionApplet, DatasetInfo
from ilastik.applets.tracking.manual.manualTrackingApplet import ManualTrackingApplet
from ilastik.applets.objectExtraction.objectExtractionApplet import ObjectExtractionApplet
from ilastik.applets.thresholdTwoLevels.thresholdTwoLevelsApplet import ThresholdTwoLevelsApplet
from lazyflow.operators.opReorderAxes import OpReorderAxes
from ilastik.applets.tracking.base.trackingBaseDataExportApplet import TrackingBaseDataExportApplet

class ManualTrackingWorkflow( Workflow ):
    workflowName = "Manual Tracking Workflow"
    workflowDisplayName = "Manual Tracking Workflow [Inputs: Raw Data, Pixel Prediction Map]"
    workflowDescription = "Manual tracking of objects, based on Prediction Maps or (binary) Segmentation Images"    

    @property
    def applets(self):
        return self._applets
    
    @property
    def imageNameListSlot(self):
        return self.dataSelectionApplet.topLevelOperator.ImageName

    def __init__( self, shell, headless, workflow_cmdline_args, project_creation_args, *args, **kwargs ):
        graph = kwargs['graph'] if 'graph' in kwargs else Graph()
        if 'graph' in kwargs: del kwargs['graph']
        super(ManualTrackingWorkflow, self).__init__(shell, headless, workflow_cmdline_args, project_creation_args, graph=graph, *args, **kwargs)
        
        data_instructions = 'Use the "Raw Data" tab to load your intensity image(s).\n\n'\
                            'Use the "Prediction Maps" tab to load your pixel-wise probability image(s).'
        ## Create applets 
        self.dataSelectionApplet = DataSelectionApplet(self, 
                                                       "Input Data", 
                                                       "Input Data", 
                                                       forceAxisOrder=['txyzc'],
                                                       instructionText=data_instructions,
                                                       max_lanes=1
                                                       )
        opDataSelection = self.dataSelectionApplet.topLevelOperator
        opDataSelection.DatasetRoles.setValue( ['Raw Data', 'Prediction Maps'] )                
        
        self.thresholdTwoLevelsApplet = ThresholdTwoLevelsApplet( self, 
                                                                  "Threshold and Size Filter", 
                                                                  "ThresholdTwoLevels" )
                     
        self.objectExtractionApplet = ObjectExtractionApplet(name="Object Feature Computation",
                                                             workflow=self, interactive=False)
        
        self.trackingApplet = ManualTrackingApplet( workflow=self )
        self.default_export_filename = '{dataset_dir}/{nickname}-exported_data.csv'
        self.dataExportApplet = TrackingBaseDataExportApplet(self, 
                                                             "Tracking Result Export", 
                                                             default_export_filename=self.default_export_filename)
        
        opDataExport = self.dataExportApplet.topLevelOperator
        opDataExport.SelectionNames.setValue( ['Manual Tracking', 'Object Identities'] )
        opDataExport.WorkingDirectory.connect( opDataSelection.WorkingDirectory )

        # Extra configuration for object export table (as CSV table or HDF5 table)
        opTracking = self.trackingApplet.topLevelOperator
        self.dataExportApplet.set_exporting_operator(opTracking)
        self.dataExportApplet.post_process_lane_export = self.post_process_lane_export
        
        self._applets = []        
        self._applets.append(self.dataSelectionApplet)        
        self._applets.append(self.thresholdTwoLevelsApplet)
        self._applets.append(self.objectExtractionApplet)        
        self._applets.append(self.trackingApplet)
        self._applets.append(self.dataExportApplet)
            
    def connectLane(self, laneIndex):
        opData = self.dataSelectionApplet.topLevelOperator.getLane(laneIndex)        
        opObjExtraction = self.objectExtractionApplet.topLevelOperator.getLane(laneIndex)
        opTracking = self.trackingApplet.topLevelOperator.getLane(laneIndex)    
        opTwoLevelThreshold = self.thresholdTwoLevelsApplet.topLevelOperator.getLane(laneIndex)
        opDataExport = self.dataExportApplet.topLevelOperator.getLane(laneIndex)
                        
        ## Connect operators ##
        op5Raw = OpReorderAxes(parent=self)
        op5Raw.AxisOrder.setValue("txyzc")
        op5Raw.Input.connect(opData.ImageGroup[0])
        
        opTwoLevelThreshold.InputImage.connect( opData.ImageGroup[1] )
        opTwoLevelThreshold.RawInput.connect( opData.ImageGroup[0] ) # Used for display only
        # Use OpReorderAxis for both input datasets such that they are guaranteed to 
        # have the same axis order after thresholding
        op5Binary = OpReorderAxes( parent=self )        
        op5Binary.AxisOrder.setValue("txyzc")
        op5Binary.Input.connect( opTwoLevelThreshold.CachedOutput )        
        
        opObjExtraction.RawImage.connect( op5Raw.Output )
        opObjExtraction.BinaryImage.connect( op5Binary.Output )
        
        opTracking.RawImage.connect( op5Raw.Output )
        opTracking.BinaryImage.connect( op5Binary.Output )
        opTracking.LabelImage.connect( opObjExtraction.LabelImage )
        opTracking.ObjectFeatures.connect( opObjExtraction.RegionFeatures )
        opTracking.ComputedFeatureNames.connect(opObjExtraction.Features)

        opDataExport.Inputs.resize(2)
        opDataExport.Inputs[0].connect( opTracking.TrackImage )
        opDataExport.Inputs[1].connect( opTracking.LabelImage )
        opDataExport.RawData.connect( op5Raw.Output )
        opDataExport.RawDatasetInfo.connect( opData.DatasetGroup[0] )

    def post_process_lane_export(self, lane_index):
        # FIXME: This probably only works for the non-blockwise export slot.
        #        We should assert that the user isn't using the blockwise slot.
        settings, selected_features = self.trackingApplet.topLevelOperator.getLane(lane_index).get_table_export_settings()
        if settings:
            raw_dataset_info = self.dataSelectionApplet.topLevelOperator.DatasetGroup[lane_index][0].value
            if raw_dataset_info.location == DatasetInfo.Location.FileSystem:
                filename_suffix = raw_dataset_info.nickname
            else:
                filename_suffix = str(lane_index)
            req = self.trackingApplet.topLevelOperator.getLane(lane_index).export_object_data(
                        lane_index, 
                        # FIXME: Even in non-headless mode, we can't show the gui because we're running in a non-main thread.
                        #        That's not a huge deal, because there's still a progress bar for the overall export.
                        show_gui=False, 
                        filename_suffix=filename_suffix)
            req.wait()         
    
    def _inputReady(self, nRoles):
        slot = self.dataSelectionApplet.topLevelOperator.ImageGroup
        if len(slot) > 0:
            input_ready = True
            for sub in slot:
                input_ready = input_ready and \
                    all([sub[i].ready() for i in range(nRoles)])
        else:
            input_ready = False

        return input_ready

    def handleAppletStateUpdateRequested(self):
        """
        Overridden from Workflow base class
        Called when an applet has fired the :py:attr:`Applet.statusUpdateSignal`
        """
        # If no data, nothing else is ready.        
        input_ready = self._inputReady(2) and not self.dataSelectionApplet.busy
        
        opThresholding = self.thresholdTwoLevelsApplet.topLevelOperator
        thresholdingOutput = opThresholding.CachedOutput
        thresholding_ready = input_ready and \
                       len(thresholdingOutput) > 0 

        opObjectExtraction = self.objectExtractionApplet.topLevelOperator
        features_ready = thresholding_ready

        opTracking = self.trackingApplet.topLevelOperator
        tracking_ready = features_ready and \
                           len(opTracking.Labels) > 0 and \
                           opTracking.Labels.ready() and \
                           opTracking.TrackImage.ready() 
        
        busy = False
        busy |= self.dataSelectionApplet.busy
        busy |= self.dataExportApplet.busy    
        busy |= self.trackingApplet.busy    
        self._shell.enableProjectChanges( not busy )
        
        self._shell.setAppletEnabled(self.dataSelectionApplet, not busy)
        self._shell.setAppletEnabled(self.thresholdTwoLevelsApplet, input_ready and not busy)
        self._shell.setAppletEnabled(self.objectExtractionApplet, thresholding_ready and not busy)        
        self._shell.setAppletEnabled(self.trackingApplet, features_ready and not busy)
        self._shell.setAppletEnabled(self.dataExportApplet, tracking_ready and not busy and \
                                        self.dataExportApplet.topLevelOperator.Inputs[0][0].ready() )

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
import os
import glob
import uuid
import numpy
import vigra

from lazyflow.graph import Operator, InputSlot, OutputSlot, OperatorWrapper
from lazyflow.utility.jsonConfig import RoiTuple
from lazyflow.operators.ioOperators import OpStreamingHdf5Reader, OpInputDataReader
from lazyflow.operators.valueProviders import OpMetadataInjector
from lazyflow.operators.opArrayPiper import OpArrayPiper
from ilastik.applets.base.applet import DatasetConstraintError

from ilastik.utility import OpMultiLaneWrapper
from lazyflow.utility import PathComponents, isUrl, make_absolute
from lazyflow.operators.opReorderAxes import OpReorderAxes

class DatasetInfo(object):
    """
    Struct-like class for describing dataset info.
    """
    class Location():
        FileSystem = 0
        ProjectInternal = 1
        PreloadedArray = 2
        
    def __init__(self, filepath=None, jsonNamespace=None, cwd=None, preloaded_array=None):
        """
        filepath: may be a globstring or a full hdf5 path+dataset
        
        jsonNamespace: If provided, overrides default settings after filepath is applied
        
        cwd: The working directory for interpeting relative paths.  If not provided, os.getcwd() is used.
        
        preloaded_array: Instead of providing a filePath to read from, a pre-loaded array can be directly provided.
                         In that case, you'll probably want to configure the axistags member, or provide a tagged vigra.VigraArray.
        """
        assert preloaded_array is None or not filepath, "You can't provide filepath and a preloaded_array"
        cwd = cwd or os.getcwd()
        self.preloaded_array = preloaded_array # See description above.
        Location = DatasetInfo.Location
        self._filePath = ""                 # The original path to the data (also used as a fallback if the data isn't in the project yet)
        self._datasetId = ""                # The name of the data within the project file (if it is stored locally)
        self.allowLabels = True             # OBSOLETE: Whether or not this dataset should be used for training a classifier.
        self.drange = None
        self.normalizeDisplay = True
        self.fromstack = False
        self.nickname = ""
        self.axistags = None
        self.subvolume_roi = None
        self.location = Location.FileSystem
        self.display_mode = 'default' # choices: default, grayscale, rgba, random-colortable, binary-mask.

        if self.preloaded_array is not None:
            self.filePath = "" # set property to ensure unique _datasetId
            self.location = Location.PreloadedArray
            self.fromstack = False
            self.nickname = "preloaded-{}-array".format( self.preloaded_array.dtype.name )
            if hasattr(self.preloaded_array, 'axistags'):
                self.axistags = self.preloaded_array.axistags

        # Set defaults for location, nickname, filepath, and fromstack
        if filepath:
            # Check for sequences (either globstring or separated paths),
            file_list = None
            if '*' in filepath:
                file_list = glob.glob(filepath)
                file_list = sorted(file_list)
            if not isUrl(filepath) and os.path.pathsep in filepath:
                file_list = filepath.split(os.path.pathsep)
            
            # For stacks, choose nickname based on a common prefix
            if file_list:
                fromstack = True
    
                # Convert all paths to absolute 
                file_list = map(lambda f: make_absolute(f, cwd), file_list)
                if '*' in filepath:
                    filepath = make_absolute(filepath, cwd)
                else:
                    filepath = os.path.pathsep.join( file_list )
    
                # Add an underscore for each wildcard digit
                prefix = os.path.commonprefix(file_list)
                num_wildcards = len(file_list[-1]) - len(prefix) - len( os.path.splitext(file_list[-1])[1] )
                nickname = PathComponents(prefix).filenameBase + ("_"*num_wildcards)
            else:
                fromstack = False
                if not isUrl(filepath):
                    # Convert all (non-url) paths to absolute 
                    filepath = make_absolute(filepath, cwd)
                nickname = PathComponents(filepath).filenameBase

            self.location = DatasetInfo.Location.FileSystem
            self.nickname = nickname
            self.filePath = filepath
            self.fromstack = fromstack

        if jsonNamespace is not None:
            self.updateFromJson( jsonNamespace )

    @property
    def filePath(self):
        return self._filePath
    
    @filePath.setter
    def filePath(self, newPath):
        self._filePath = newPath
        # Reset our id any time the filepath changes
        self._datasetId = str(uuid.uuid1())
    
    @property
    def datasetId(self):
        return self._datasetId
    
    DatasetInfoSchema = \
    {
        "_schema_name" : "dataset-info",
        "_schema_version" : 0.1,
        
        "filepath" : str,
        "drange" : tuple,
        "nickname" : str,
        "axistags" : str,
        "subvolume_roi" : RoiTuple()
    }
    
    def __str__(self):
        s = "{ "
        s += "filepath: {},\n".format(self.filePath)
        s += "location: {}\n".format( { DatasetInfo.Location.FileSystem: "FileSystem",
                                        DatasetInfo.Location.ProjectInternal: "ProjectInternal",
                                        DatasetInfo.Location.PreloadedArray: "PreloadedArray"
                                      }[self.location] )
        s += "nickname: {},\n".format( self.nickname )
        if self.axistags:
            s +="axistags: {},\n".format(self.axistags)
        if self.drange:
            s += "drange: {},\n".format( self.drange )
        s += "normalizeDisplay: {}\n".format( self.normalizeDisplay )
        if self.fromstack:
            s += "fromstack: {}\n".format( self.fromstack )
        if self.subvolume_roi:
            s += "subvolume_roi: {},\n".format( self.subvolume_roi )
        s += " }\n"
        return s

    def updateFromJson(self, namespace):
        """
        Given a namespace object returned by a JsonConfigParser,
        update the corresponding non-None fields of this DatasetInfo.
        """
        self.filePath = namespace.filepath or self.filePath        
        self.drange = namespace.drange or self.drange
        self.nickname = namespace.nickname or self.nickname
        if namespace.axistags is not None:
            self.axistags = vigra.defaultAxistags(namespace.axistags)
        self.subvolume_roi = namespace.subvolume_roi or self.subvolume_roi

class OpDataSelection(Operator):
    """
    The top-level operator for the data selection applet, implemented as a single-image operator.
    The applet uses an OperatorWrapper to make it suitable for use in a workflow.
    """
    name = "OpDataSelection"
    category = "Top-level"
    
    SupportedExtensions = OpInputDataReader.SupportedExtensions

    # Inputs
    RoleName = InputSlot(stype='string', value='')
    ProjectFile = InputSlot(stype='object', optional=True) #: The project hdf5 File object (already opened)
    ProjectDataGroup = InputSlot(stype='string', optional=True) #: The internal path to the hdf5 group where project-local datasets are stored within the project file
    WorkingDirectory = InputSlot(stype='filestring') #: The filesystem directory where the project file is located
    Dataset = InputSlot(stype='object') #: A DatasetInfo object

    # Outputs
    Image = OutputSlot() #: The output image
    AllowLabels = OutputSlot(stype='bool') #: A bool indicating whether or not this image can be used for training

    _NonTransposedImage = OutputSlot() #: The output slot, in the data's original axis ordering (regardless of forceAxisOrder)

    ImageName = OutputSlot(stype='string') #: The name of the output image
    
    class InvalidDimensionalityError(Exception):
        """Raised if the user tries to replace the dataset with a new one of differing dimensionality."""
        def __init__(self, message ):
            super( OpDataSelection.InvalidDimensionalityError, self ).__init__()
            self.message = message
        
        def __str__(self):
            return self.message

    def __init__(self, forceAxisOrder=False, *args, **kwargs):
        """
        forceAxisOrder: How to auto-reorder the input data before connecting it to the rest of the workflow.
                        Should be a list of input orders that are allowed by the workflow
                        For example, if the workflow can handle 2D and 3D, you might pass ['yxc', 'zyxc'].
                        If it only handles exactly 5D, you might pass 'tzyxc', assuming that's how you wrote the workflow.
        """
        super(OpDataSelection, self).__init__(*args, **kwargs)
        self.forceAxisOrder = forceAxisOrder
        self._opReaders = []

        # If the gui calls disconnect() on an input slot without replacing it with something else,
        #  we still need to clean up the internal operator that was providing our data.
        self.ProjectFile.notifyUnready(self.internalCleanup)
        self.ProjectDataGroup.notifyUnready(self.internalCleanup)
        self.WorkingDirectory.notifyUnready(self.internalCleanup)
        self.Dataset.notifyUnready(self.internalCleanup)

    def internalCleanup(self, *args):
        if len(self._opReaders) > 0:
            self.Image.disconnect()
            self._NonTransposedImage.disconnect()
            for reader in reversed(self._opReaders):
                reader.cleanUp()
            self._opReaders = []
    
    def setupOutputs(self):
        self.internalCleanup()
        datasetInfo = self.Dataset.value

        try:
            # Data only comes from the project file if the user said so AND it exists in the project
            datasetInProject = (datasetInfo.location == DatasetInfo.Location.ProjectInternal)
            datasetInProject &= self.ProjectFile.ready()
            if datasetInProject:
                internalPath = self.ProjectDataGroup.value + '/' + datasetInfo.datasetId
                datasetInProject &= internalPath in self.ProjectFile.value
    
            # If we should find the data in the project file, use a dataset reader
            if datasetInProject:
                opReader = OpStreamingHdf5Reader(parent=self)
                opReader.Hdf5File.setValue(self.ProjectFile.value)
                opReader.InternalPath.setValue(internalPath)
                providerSlot = opReader.OutputImage
            elif datasetInfo.location == DatasetInfo.Location.PreloadedArray:
                preloaded_array = datasetInfo.preloaded_array
                assert preloaded_array is not None
                if not hasattr(preloaded_array, 'axistags'):
                    # Guess the axis order, since one was not provided.
                    axisorders = { 2 : 'yx',
                                   3 : 'zyx',
                                   4 : 'zyxc',
                                   5 : 'tzyxc' }

                    shape = preloaded_array.shape
                    ndim = preloaded_array.ndim            
                    assert ndim != 0, "Support for 0-D data not yet supported"
                    assert ndim != 1, "Support for 1-D data not yet supported"
                    assert ndim <= 5, "No support for data with more than 5 dimensions."
        
                    axisorder = axisorders[ndim]
                    if ndim == 3 and shape[2] <= 4:
                        # Special case: If the 3rd dim is small, assume it's 'c', not 'z'
                        axisorder = 'yxc'
                    preloaded_array = vigra.taggedView(preloaded_array, axisorder)
                opReader = OpArrayPiper(parent=self)
                opReader.Input.setValue( preloaded_array )
                providerSlot = opReader.Output
            else:
                # Use a normal (filesystem) reader
                opReader = OpInputDataReader(parent=self)
                if datasetInfo.subvolume_roi is not None:
                    opReader.SubVolumeRoi.setValue( datasetInfo.subvolume_roi )
                opReader.WorkingDirectory.setValue( self.WorkingDirectory.value )
                opReader.FilePath.setValue(datasetInfo.filePath)
                providerSlot = opReader.Output
            self._opReaders.append(opReader)
            
            # Inject metadata if the dataset info specified any.
            # Also, inject if if dtype is uint8, which we can reasonably assume has drange (0,255)
            metadata = {}
            metadata['display_mode'] = datasetInfo.display_mode
            role_name = self.RoleName.value
            if 'c' not in providerSlot.meta.getTaggedShape():
                num_channels = 0
            else:
                num_channels = providerSlot.meta.getTaggedShape()['c']
            if num_channels > 1:
                metadata['channel_names'] = ["{}-{}".format(role_name, i) for i in range(num_channels)]
            else:
                metadata['channel_names'] = [role_name]
                 
            if datasetInfo.drange is not None:
                metadata['drange'] = datasetInfo.drange
            elif providerSlot.meta.dtype == numpy.uint8:
                # SPECIAL case for uint8 data: Provide a default drange.
                # The user can always override this herself if she wants.
                metadata['drange'] = (0,255)
            if datasetInfo.normalizeDisplay is not None:
                metadata['normalizeDisplay'] = datasetInfo.normalizeDisplay
            if datasetInfo.axistags is not None:
                if len(datasetInfo.axistags) != len(providerSlot.meta.shape):
                    # This usually only happens when we copied a DatasetInfo from another lane,
                    # and used it as a 'template' to initialize this lane.
                    # This happens in the BatchProcessingApplet when it attempts to guess the axistags of 
                    # batch images based on the axistags chosen by the user in the interactive images.
                    # If the interactive image tags don't make sense for the batch image, you get this error.
                    raise Exception( "Your dataset's provided axistags ({}) do not have the "
                                     "correct dimensionality for your dataset, which has {} dimensions."
                                     .format( "".join(tag.key for tag in datasetInfo.axistags), len(providerSlot.meta.shape) ) )
                metadata['axistags'] = datasetInfo.axistags
            if datasetInfo.subvolume_roi is not None:
                metadata['subvolume_roi'] = datasetInfo.subvolume_roi
                
                # FIXME: We are overwriting the axistags metadata to intentionally allow 
                #        the user to change our interpretation of which axis is which.
                #        That's okay, but technically there's a special corner case if 
                #        the user redefines the channel axis index.  
                #        Technically, it invalidates the meaning of meta.ram_usage_per_requested_pixel.
                #        For most use-cases, that won't really matter, which is why I'm not worrying about it right now.
            
            opMetadataInjector = OpMetadataInjector( parent=self )
            opMetadataInjector.Input.connect( providerSlot )
            opMetadataInjector.Metadata.setValue( metadata )
            providerSlot = opMetadataInjector.Output
            self._opReaders.append( opMetadataInjector )

            self._NonTransposedImage.connect(providerSlot)
            
            if self.forceAxisOrder:
                assert isinstance(self.forceAxisOrder, list), \
                    "forceAxisOrder should be a *list* of preferred axis orders"
                
                # Before we re-order, make sure no non-singleton 
                #  axes would be dropped by the forced order.
                provider_order = "".join(providerSlot.meta.getAxisKeys())
                tagged_provider_shape = providerSlot.meta.getTaggedShape()

                minimal_axes = filter( lambda (k,v): v > 1, tagged_provider_shape.items() )
                minimal_axes = set(k for k,v in minimal_axes)

                # Pick the shortest of the possible 'forced' orders that
                # still contains all the axes of the original dataset.
                candidate_orders = list(self.forceAxisOrder)
                candidate_orders = filter(lambda order: minimal_axes.issubset(set(order)),
                                          candidate_orders)

                if len(candidate_orders) == 0:
                    msg = "The axes of your dataset ({}) are not compatible with any of the allowed"\
                          " axis configurations used by this workflow ({}). Please fix them."\
                          .format(provider_order, self.forceAxisOrder)
                    raise DatasetConstraintError("DataSelection", msg)

                output_order = sorted(candidate_orders, key=len)[0] # the shortest one
                output_order = "".join( output_order )

                op5 = OpReorderAxes(parent=self)
                op5.AxisOrder.setValue(output_order)
                op5.Input.connect(providerSlot)
                providerSlot = op5.Output
                self._opReaders.append(op5)
            
            # If the channel axis is not last (or is missing),
            #  make sure the axes are re-ordered so that channel is last.
            if providerSlot.meta.axistags.index('c') != len( providerSlot.meta.axistags )-1:
                op5 = OpReorderAxes( parent=self )
                keys = providerSlot.meta.getTaggedShape().keys()
                try:
                    # Remove if present.
                    keys.remove('c')
                except ValueError:
                    pass
                # Append
                keys.append('c')
                op5.AxisOrder.setValue( "".join( keys ) )
                op5.Input.connect( providerSlot )
                providerSlot = op5.Output
                self._opReaders.append( op5 )
            
            # Connect our external outputs to the internal operators we chose
            self.Image.connect(providerSlot)
            
            # Set the image name and usage flag
            self.AllowLabels.setValue( datasetInfo.allowLabels )
            
            # If the reading operator provides a nickname, use it.
            if self.Image.meta.nickname is not None:
                datasetInfo.nickname = self.Image.meta.nickname
            
            imageName = datasetInfo.nickname
            if imageName == "":
                imageName = datasetInfo.filePath
            self.ImageName.setValue(imageName)
        
        except:
            self.internalCleanup()
            raise

    def propagateDirty(self, slot, subindex, roi):
        # Output slots are directly connected to internal operators
        pass

    @classmethod
    def getInternalDatasets(cls, filePath):
        return OpInputDataReader.getInternalDatasets( filePath )

class OpDataSelectionGroup( Operator ):
    # Inputs
    ProjectFile = InputSlot(stype='object', optional=True)
    ProjectDataGroup = InputSlot(stype='string', optional=True)
    WorkingDirectory = InputSlot(stype='filestring')
    DatasetRoles = InputSlot(stype='object')

    DatasetGroup = InputSlot(stype='object', level=1, optional=True) # Must mark as optional because not all subslots are required.

    # Outputs
    ImageGroup = OutputSlot(level=1)
    
    # These output slots are provided as a convenience, since otherwise it is tricky to create a lane-wise multislot of level-1 for only a single role.
    # (It can be done, but requires OpTransposeSlots to invert the level-2 multislot indexes...) 
    Image = OutputSlot() # The first dataset. Equivalent to ImageGroup[0]
    Image1 = OutputSlot() # The second dataset. Equivalent to ImageGroup[1]
    Image2 = OutputSlot() # The third dataset. Equivalent to ImageGroup[2]
    AllowLabels = OutputSlot(stype='bool') # Pulled from the first dataset only.

    _NonTransposedImageGroup = OutputSlot(level=1)

    # Must be the LAST slot declared in this class.
    # When the shell detects that this slot has been resized,
    #  it assumes all the others have already been resized.
    ImageName = OutputSlot() # Name of the first dataset is used.  Other names are ignored.
    
    def __init__(self, forceAxisOrder=None, *args, **kwargs):
        super(OpDataSelectionGroup, self).__init__(*args, **kwargs)
        self._opDatasets = None
        self._roles = []
        self._forceAxisOrder = forceAxisOrder

        def handleNewRoles(*args):
            self.DatasetGroup.resize( len(self.DatasetRoles.value) )
        self.DatasetRoles.notifyReady( handleNewRoles )
        
    def setupOutputs(self):
        # Create internal operators
        if self.DatasetRoles.value != self._roles:
            self._roles = self.DatasetRoles.value
            # Clean up the old operators
            self.ImageGroup.disconnect()
            self.Image.disconnect()
            self.Image1.disconnect()
            self.Image2.disconnect()
            self._NonTransposedImageGroup.disconnect()
            if self._opDatasets is not None:
                self._opDatasets.cleanUp()
    
            self._opDatasets = OperatorWrapper( OpDataSelection, parent=self, operator_kwargs={ 'forceAxisOrder' : self._forceAxisOrder },
                                                broadcastingSlotNames=['ProjectFile', 'ProjectDataGroup', 'WorkingDirectory'] )
            self.ImageGroup.connect( self._opDatasets.Image )
            self._NonTransposedImageGroup.connect( self._opDatasets._NonTransposedImage )
            self._opDatasets.Dataset.connect( self.DatasetGroup )
            self._opDatasets.ProjectFile.connect( self.ProjectFile )
            self._opDatasets.ProjectDataGroup.connect( self.ProjectDataGroup )
            self._opDatasets.WorkingDirectory.connect( self.WorkingDirectory )

        for role_index, opDataSelection in enumerate(self._opDatasets):
            opDataSelection.RoleName.setValue(self._roles[role_index])

        if len( self._opDatasets.Image ) > 0:
            self.Image.connect( self._opDatasets.Image[0] )
            
            if len(self._opDatasets.Image) >= 2:
                self.Image1.connect( self._opDatasets.Image[1] )
            else:
                self.Image1.disconnect()
                self.Image1.meta.NOTREADY = True

            if len(self._opDatasets.Image) >= 3:
                self.Image2.connect( self._opDatasets.Image[2] )
            else:
                self.Image2.disconnect()
                self.Image2.meta.NOTREADY = True
                
            self.ImageName.connect( self._opDatasets.ImageName[0] )
            self.AllowLabels.connect( self._opDatasets.AllowLabels[0] )
        else:
            self.Image.disconnect()
            self.Image1.disconnect()
            self.Image2.disconnect()
            self.ImageName.disconnect()
            self.AllowLabels.disconnect()
            self.Image.meta.NOTREADY = True
            self.Image1.meta.NOTREADY = True
            self.Image2.meta.NOTREADY = True
            self.ImageName.meta.NOTREADY = True
            self.AllowLabels.meta.NOTREADY = True

    def execute(self, slot, subindex, rroi, result):
            assert False, "Unknown or unconnected output slot: {}".format( slot.name )

    def propagateDirty(self, slot, subindex, roi):
        # Output slots are directly connected to internal operators
        pass

class OpMultiLaneDataSelectionGroup( OpMultiLaneWrapper ):
    # TODO: Provide output slots DatasetsByRole and ImagesByRole as a convenience 
    #       to save clients the trouble of instantiating/using OpTransposeSlots.
    def __init__(self, forceAxisOrder=False, *args, **kwargs):
        kwargs.update( { 'operator_kwargs' : {'forceAxisOrder' : forceAxisOrder},
                         'broadcastingSlotNames' : ['ProjectFile', 'ProjectDataGroup', 'WorkingDirectory', 'DatasetRoles'] } )
        super( OpMultiLaneDataSelectionGroup, self ).__init__(OpDataSelectionGroup, *args, **kwargs )
    
        # 'value' slots
        assert self.ProjectFile.level == 0
        assert self.ProjectDataGroup.level == 0
        assert self.WorkingDirectory.level == 0
        assert self.DatasetRoles.level == 0
        
        # Indexed by [lane][role]
        assert self.DatasetGroup.level == 2, "DatasetGroup is supposed to be a level-2 slot, indexed by [lane][role]"
    
    def addLane(self, laneIndex):
        """Reimplemented from base class."""
        numLanes = len(self.innerOperators)
        
        # Only add this lane if we don't already have it
        # We might be called from within the context of our own insertSlot signal.
        if numLanes == laneIndex:
            super( OpMultiLaneDataSelectionGroup, self ).addLane( laneIndex )

    def removeLane(self, laneIndex, finalLength):
        """Reimplemented from base class."""
        numLanes = len(self.innerOperators)
        if numLanes > finalLength:
            super( OpMultiLaneDataSelectionGroup, self ).removeLane( laneIndex, finalLength )









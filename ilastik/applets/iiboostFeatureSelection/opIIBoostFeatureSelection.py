import copy
import numpy
import vigra

from lazyflow.graph import Operator, InputSlot, OutputSlot
from lazyflow.operators.operators import OpSlicedBlockedArrayCache

from ilastik.applets.featureSelection.opFeatureSelection import OpFeatureSelection
from iiboost import computeEigenVectorsOfHessianImage

class OpIIBoostFeatureSelection(Operator):
    """
    This operator produces an output image with the following channels
    
    0: Raw Input (the input is just duplicated as an output channel)
    1-10: The 9 elements of the hessian eigenvector matrix (a 3x3 matrix flattened into 9 channels)
    11-11+N: Any features provided by the standard OpFeatureSelection operator.
    
    This operator owns an instance of the standard OpFeatureSelection operator, and 
    exposes the same slot interface so the GUI can configure that inner operator transparently. 
    """
    
    # All inputs are directly passed to internal OpFeatureSelection
    InputImage = InputSlot()
    Scales = InputSlot()
    FeatureIds = InputSlot()
    SelectionMatrix = InputSlot()
    FeatureListFilename = InputSlot(stype="str", optional=True)

    # This output is only for the GUI.  It's taken directly from OpFeatureSelection
    FeatureLayers = OutputSlot(level=1)

    # These outputs are taken from OpFeatureSelection, but we add to them.
    OutputImage = OutputSlot()
    CachedOutputImage = OutputSlot()

    def __init__(self, filter_implementation, *args, **kwargs):
        super( OpIIBoostFeatureSelection, self ).__init__(*args, **kwargs)
        self.opFeatureSelection = OpFeatureSelection(filter_implementation, parent=self)
        
        self.opFeatureSelection.InputImage.connect( self.InputImage )
        self.opFeatureSelection.Scales.connect( self.Scales )
        self.opFeatureSelection.FeatureIds.connect( self.FeatureIds )
        self.opFeatureSelection.SelectionMatrix.connect( self.SelectionMatrix )
        self.opFeatureSelection.FeatureListFilename.connect( self.FeatureListFilename )
        
        self.FeatureLayers.connect( self.opFeatureSelection.FeatureLayers )

        self.WINDOW_SIZE = self.opFeatureSelection.WINDOW_SIZE
        
        # Note: OutputImage and CachedOutputImage are not directly connected.
        #       Their data is obtained in execute(), below.
        
        self.opHessianEigenvectors = OpHessianEigenvectors( parent=self )
        self.opHessianEigenvectors.Input.connect( self.InputImage )
        
        # The operator above produces an image with weird axes,
        #  so let's convert it to a multi-channel image for easy handling.
        self.opConvertToChannels = OpConvertEigenvectorsToChannels( parent=self )
        self.opConvertToChannels.Input.connect( self.opHessianEigenvectors.Output )
        
        # Create a cache for the hessian eigenvector image data
        self.opHessianEigenvectorCache = OpSlicedBlockedArrayCache(parent=self)
        self.opHessianEigenvectorCache.name = "opHessianEigenvectorCache"
        self.opHessianEigenvectorCache.Input.connect(self.opConvertToChannels.Output)
        self.opHessianEigenvectorCache.fixAtCurrent.setValue(False)

    def setupOutputs(self):
        # Output shape is the same as the inner operator, 
        #  except with 10 extra channels (1 raw + 9 hessian eigenvector elements)
        output_shape = self.opFeatureSelection.OutputImage.meta.shape
        output_shape = output_shape[:-1] + ( output_shape[-1] + 10, )

        self.OutputImage.meta.assignFrom( self.opFeatureSelection.OutputImage.meta )
        self.CachedOutputImage.meta.assignFrom( self.opFeatureSelection.CachedOutputImage.meta )
        self.OutputImage.meta.shape = output_shape
        self.CachedOutputImage.meta.shape = output_shape

        # Copy the cache block settings from the standard pixel feature operator.
        self.opHessianEigenvectorCache.innerBlockShape.setValue( self.opFeatureSelection.opPixelFeatureCache.innerBlockShape.value )
        self.opHessianEigenvectorCache.outerBlockShape.setValue( self.opFeatureSelection.opPixelFeatureCache.outerBlockShape.value )

    def propagateDirty(self, slot, subindex, roi):
        # All channels are dirty
        num_channels = self.OutputImage.meta.shape[-1]
        dirty_start = tuple(roi.start[:-1]) + (num_channels,)
        dirty_stop = tuple(roi.stop[:-1]) + (num_channels,)
        self.OutputImage.setDirty(dirty_start, dirty_stop)

    def execute(self, slot, subindex, roi, result):
        assert slot == self.OutputImage or slot == self.CachedOutputImage

        # Combine all three 'feature' images into one big result
        spatial_roi = ( tuple(roi.start[:-1]), tuple(roi.stop[:-1]) )
        
        raw_roi = ( spatial_roi[0] + (0,),
                    spatial_roi[1] + (1,) )

        hess_ev_roi = ( spatial_roi[0] + (0,),
                        spatial_roi[1] + (9,) )

        features_roi = ( spatial_roi[0] + (0,),
                         spatial_roi[1] + (roi.stop[-1]-10,) )

        # Raw request is the same in either case (there is no cache)
        raw_req = self.InputImage(*raw_roi)
        if self.InputImage.meta.dtype == self.OutputImage.meta.dtype:
            raw_req.writeInto(result[...,0:1])
            raw_req.wait()
        else:
            # Can't use writeInto because we need an implicit dtype cast here.
            result[...,0:1] = raw_req.wait()            
        
        # Pull the rest of the channels from different sources, depending on cached/uncached slot.        
        if slot == self.OutputImage:
            hev_req = self.opConvertToChannels.Output(*hess_ev_roi).writeInto(result[...,1:10])
            feat_req = self.opFeatureSelection.OutputImage(*features_roi).writeInto(result[...,10:])
        elif slot == self.CachedOutputImage:
            hev_req = self.opHessianEigenvectorCache.Output(*hess_ev_roi).writeInto(result[...,1:10])
            feat_req = self.opFeatureSelection.CachedOutputImage(*features_roi).writeInto(result[...,10:])
        
        hev_req.submit()
        feat_req.submit()
        hev_req.wait()
        feat_req.wait()

class OpHessianEigenvectors( Operator ):
    """
    Operator to call iiboost's hessian eigenvector function.
    Takes a 3D 1-channel image as input and returns a 5D xyzij output, 
    where the i,j axes are the eigenvector index and eigenvector element index, respectively.
    """
    Input = InputSlot()
    Sigma = InputSlot(value=3.5) # FIXME: What is the right sigma to use?
    Output = OutputSlot()
    
    def __init__(self, *args, **kwargs):
        super( OpHessianEigenvectors, self ).__init__(*args, **kwargs)
        self.z_anisotropy_factor = 1.0
    
    def setupOutputs(self):
        assert len(self.Input.meta.shape) == 4, "Data must be exactly 3D+c (no time axis)"
        assert self.Input.meta.getAxisKeys()[-1] == 'c'
        assert self.Input.meta.shape[-1] == 1, "Input must be 1-channel"
        self.Output.meta.assignFrom(self.Input.meta)
        self.Output.meta.dtype = numpy.float32
        self.Output.meta.shape = self.Input.meta.shape[:-1] + (3,3)
        
        # axistags: start with input, drop channel and append i,j
        input_axistags = copy.copy(self.Input.meta.axistags)
        tag_list = [tag for tag in input_axistags]
        tag_list = tag_list[:-1]
        tag_list.append( vigra.AxisInfo('i', description='eigenvector index') )
        tag_list.append( vigra.AxisInfo('j', description='eigenvector component') )
        
        self.Output.meta.axistags = vigra.AxisTags(tag_list)

        # Calculate anisotropy factor.
        x_tag = self.Input.meta.axistags['x']
        z_tag = self.Input.meta.axistags['z']
        self.z_anisotropy_factor = 1.0
        if z_tag.resolution != 0.0 and x_tag.resolution != 0.0:
            self.z_anisotropy_factor = z_tag.resolution / x_tag.resolution

    
    def execute(self, slot, subindex, roi, result):
        # Remove i,j slices from roi, append channel slice to roi.
        # FIXME: Add halo?
        input_roi = ( tuple(roi.start[:-2]) + (0,),
                      tuple(roi.stop[:-2]) + (1,) )

        # Request input
        input_data = self.Input(*input_roi).wait()
        
        # Drop singleton channel axis
        input_data = input_data[...,0]
        
        # We need a uint8 array, in C-order.
        input_data = input_data.astype( numpy.uint8, order='C', copy=False )

        # Compute. (Note that we drop the 
        eigenvectors = computeEigenVectorsOfHessianImage(input_data, 
                                                         zAnisotropyFactor=self.z_anisotropy_factor, 
                                                         sigma=self.Sigma.value)
        
        # sanity checks...
        assert (eigenvectors.shape[:-2] == (numpy.array(input_roi[1]) - input_roi[0])[:-1]).all(), \
            "eigenvector image has unexpected shape: {}".format( eigenvectors.shape )
        assert eigenvectors.shape[-2:] == (3,3)

        # Copy to output.        
        result[:] = eigenvectors[..., slice(roi.start[-1], roi.stop[-1])]

    def propagateDirty(self, slot, subindex, roi):
        dirty_start = tuple(roi.start[:-1]) + (0,0)
        dirty_stop = tuple(roi.stop[:-1]) + (3,3)
        self.Output.setDirty(dirty_start, dirty_stop)


class OpConvertEigenvectorsToChannels(Operator):
    """
    Reshapes the 3D+i,j output from OpHessianEigenvectors into a 3D+c array, 
    where the 3x3 i,j axes have been converted to a single (9,) channel axis.
    
    This is only useful because most operators in lazyflow expect a channel axis, 
    and don't know how to handle (i,j) pixels.
    """
    Input = InputSlot()
    Output = OutputSlot()
    
    def setupOutputs(self):
        input_shape = self.Input.meta.shape
        input_axiskeys = self.Input.meta.getAxisKeys()
        assert input_shape[-2:] == (3,3)
        assert input_axiskeys[-2:] == ['i', 'j']

        tag_list = [tag for tag in self.Input.meta.axistags]
        tag_list = tag_list[:-2]
        tag_list.append( vigra.defaultAxistags('c')[0] )

        self.Output.meta.assignFrom(self.Input.meta)
        self.Output.meta.shape = input_shape[:-2] + (9,)
        self.Output.meta.axistags = vigra.AxisTags(tag_list)

    def execute(self, slot, subindex, roi, result):
        # We could go through the necessary contortions to avoid this requirement, 
        #  but it's not a realistic use-case for now.
        assert roi.start[-1] == 0, "Requests to this operator must include all channels"
        assert roi.stop[-1] == 9, "Requests to this operator must include all channels"
        
        input_roi = ( tuple(roi.start[:-1]) + (0,0),
                      tuple(roi.stop[:-1]) + (3,3) )
        
        input_shape = numpy.array(input_roi[1]) - input_roi[0]

        if result.flags["C_CONTIGUOUS"]:
            result = result.reshape( input_shape )
            self.Input(*input_roi).writeInto(result).wait()
        else:
            input_data = self.Input(*input_roi).wait()
            assert input_data.shape[-2:] == (3,3)
            input_data = input_data.reshape(input_data.shape[:-2] + (9,))
            assert input_data.shape == result.shape
            result[:] = input_data[:]
        
    def propagateDirty(self, slot, subindex, roi):
        dirty_start = tuple(roi.start[:-2]) + (0)
        dirty_stop = tuple(roi.stop[:-2]) + (9)
        self.Output.setDirty(dirty_start, dirty_stop)
            








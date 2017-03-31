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
#           http://ilastik.org/license.html
###############################################################################
import os
import imp
import numpy as np
import h5py
import sys

import ilastik
from lazyflow.utility.timer import timeLogged

import logging
logger = logging.getLogger(__name__)

class TestConservationTrackingHeadless(object):    
    PROJECT_FILE = 'data/inputdata/smallVideoConservationTracking.ilp'
    RAW_DATA_FILE = 'data/inputdata/smallVideo.h5'
    BINARY_SEGMENTATION_FILE = 'data/inputdata/smallVideoSimpleSegmentation.h5'

    EXPECTED_TRACKING_RESULT_FILE = 'data/inputdata/smallVideo_Tracking-Result.h5'
    EXPECTED_SHAPE = (7, 408, 408, 1, 1) # Expected shape for tracking results HDF5 files
    
    EXPECTED_CSV_FILE = 'data/inputdata/smallVideo_CSV-Table.csv'
    EXPECTED_NUM_ROWS = 23 # Number of lines expected in exported csv file
    EXPECTED_NUM_LINEAGES = 3
    EXPECTED_MERGER_NUM = 2 # Number of mergers expected in exported csv file
    EXPECTED_NUM_DIVISION_CHILDREN = 2 # Number of tracks that have their "parent" set, meaning they are children of a division

    @classmethod
    def setupClass(cls):
        logger.info('starting setup...')
        cls.original_cwd = os.getcwd()

        # Load the ilastik startup script as a module.
        # Do it here in setupClass to ensure that it isn't loaded more than once.
        logger.info('looking for ilastik.py...')
        ilastik_entry_file_path = os.path.join( os.path.split( os.path.realpath(ilastik.__file__) )[0], "../ilastik.py" )
        if not os.path.exists( ilastik_entry_file_path ):
            raise RuntimeError("Couldn't find ilastik.py startup script: {}".format( ilastik_entry_file_path ))
            
        cls.ilastik_startup = imp.load_source( 'ilastik_startup', ilastik_entry_file_path )


    @classmethod
    def teardownClass(cls):
        removeFiles = [cls.EXPECTED_TRACKING_RESULT_FILE, cls.EXPECTED_CSV_FILE]

        # Clean up: Delete any test files we generated
        for f in removeFiles:
            try:
                os.remove(f)
            except:
                pass


    @timeLogged(logger)
    def testTrackingHeadless(self):        
        # TODO: When Hytra is supported on Windows, we shouldn't skip the test and throw an assert instead
        try:
            import hytra
        except ImportError as e:
            logger.warn( "Hytra tracking pipeline couldn't be imported: " + str(e) )
            raise nose.SkipTest
        
        # Skip test because there are missing files
        if not os.path.isfile(self.PROJECT_FILE) or not os.path.isfile(self.RAW_DATA_FILE) or not os.path.isfile(self.BINARY_SEGMENTATION_FILE):
            logger.info("Test files not found.")   
        
        args = ' --project='+self.PROJECT_FILE
        args += ' --headless'
        
        args += ' --export_source=Tracking-Result'
        args += ' --raw_data '+self.RAW_DATA_FILE+'/data'
        args += ' --segmentation_image '+self.BINARY_SEGMENTATION_FILE+'/exported_data'

        sys.argv = ['ilastik.py'] # Clear the existing commandline args so it looks like we're starting fresh.
        sys.argv += args.split()

        # Start up the ilastik.py entry script as if we had launched it from the command line
        self.ilastik_startup.main()
        
        # Examine the HDF5 output for basic attributes
        with h5py.File(self.EXPECTED_TRACKING_RESULT_FILE, 'r') as f:
            assert 'exported_data' in f, 'Dataset does not exist in tracking result file'
            shape = f['exported_data'].shape
            assert shape == self.EXPECTED_SHAPE, 'Exported data has wrong shape: {}'.format(shape)
            data = f['exported_data'].value
            assert len(np.unique(data)) == self.EXPECTED_NUM_LINEAGES + 1 # background also shows up, hence + 1

    @timeLogged(logger)
    def testCSVExport(self):
        # TODO: When Hytra is supported on Windows, we shouldn't skip the test and throw an assert instead
        try:
            import hytra
        except ImportError as e:
            logger.warn("Hytra tracking pipeline couldn't be imported: " + str(e))
            raise nose.SkipTest

        # Skip test because there are missing files
        if not os.path.isfile(self.PROJECT_FILE) or not os.path.isfile(self.RAW_DATA_FILE) or not os.path.isfile(
                self.BINARY_SEGMENTATION_FILE):
            logger.info("Test files not found.")

        args = ' --project=' + self.PROJECT_FILE
        args += ' --headless'

        args += ' --export_source=Plugin'
        args += ' --export_plugin=CSV-Table'
        args += ' --raw_data ' + self.RAW_DATA_FILE + '/data'
        args += ' --segmentation_image ' + self.BINARY_SEGMENTATION_FILE + '/exported_data'

        sys.argv = ['ilastik.py']  # Clear the existing commandline args so it looks like we're starting fresh.
        sys.argv += args.split()

        # Start up the ilastik.py entry script as if we had launched it from the command line
        self.ilastik_startup.main()

        # Load csv file
        data = np.genfromtxt(self.EXPECTED_CSV_FILE, dtype=float, delimiter=',', names=True)

        # Check for expected number of rows in csv table
        assert data.shape[0] == self.EXPECTED_NUM_ROWS, 'Number of rows in csv file differs from expected'

        # Check that csv contains RegionRadii and RegionAxes (necessary for animal tracking)
        assert 'Radii_of_the_object_0' in data.dtype.names, 'RegionRadii not found in csv file (required for animal tracking)'
        assert 'Principal_components_of_the_object_0' in data.dtype.names, 'RegionAxes not found in csv file (required for animal tracking)'

        # Check for expected number of mergers
        mergerIds = set([])
        for row, mergerId in enumerate(data['mergerLabelId']):
            if mergerId != 0:
                mergerIds.add((int(data['frame'][row]), int(mergerId)))
        merger_count = len(mergerIds)
        assert merger_count == self.EXPECTED_MERGER_NUM, 'Number of mergers in csv file differs from expected'

        tracks_with_parent = 0
        for p in data['parentTrackId']:
            if p != 0:
                tracks_with_parent += 1

        # Check for expected number of rows in divisions csv table (we only have one division in the video)
        assert tracks_with_parent == self.EXPECTED_NUM_DIVISION_CHILDREN, 'Number of children divisions differs from expected'


if __name__ == "__main__":
    # Make the program quit on Ctrl+C
    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    import sys
    import nose
    sys.argv.append("--nocapture")    # Don't steal stdout.  Show it on the console as usual.
    sys.argv.append("--nologcapture") # Don't set the logging level to DEBUG.  Leave it alone.
    nose.run(defaultTest=__file__)

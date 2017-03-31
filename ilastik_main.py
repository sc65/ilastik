import sys
import os

import ilastik.config
from ilastik.config import cfg as ilastik_config

import logging
logger = logging.getLogger(__name__)

import argparse
parser = argparse.ArgumentParser( description="start an ilastik workflow" )

# Common options
parser.add_argument('--headless', help="Don't start the ilastik gui.", action='store_true', default=False)
parser.add_argument('--project', help='A project file to open on startup.', required=False)
parser.add_argument('--readonly', help="Open all projects in read-only mode, to ensure you don't accidentally make changes.", default=False)

parser.add_argument('--new_project', help='Create a new project with the specified name.  Must also specify --workflow.', required=False)
parser.add_argument('--workflow', help='When used with --new_project, specifies the workflow to use.', required=False)

parser.add_argument('--clean_paths', help='Remove ilastik-unrelated directories from PATH and PYTHONPATH.', action='store_true', default=False)
parser.add_argument('--redirect_output', help='A filepath to redirect stdout to', required=False)

parser.add_argument('--debug', help='Start ilastik in debug mode.', action='store_true', default=False)
parser.add_argument('--logfile', help='A filepath to dump all log messages to.', required=False)
parser.add_argument('--process_name', help='A process name (used for logging purposes).', required=False)
parser.add_argument('--configfile', help='A custom path to a user config file for expert ilastik settings.', required=False)
parser.add_argument('--fullscreen', help='Show Window in fullscreen mode.', action='store_true', default=False)

parser.add_argument('--start_recording', help='Open the recorder controls and immediately start recording', action='store_true', default=False)
parser.add_argument('--playback_script', help='An event recording to play back after the main window has opened.', required=False)
parser.add_argument('--playback_speed', help='Speed to play the playback script.', default=1.0, type=float)
parser.add_argument('--exit_on_failure', help='Immediately call exit(1) if an unhandled exception occurs.', action='store_true', default=False)
parser.add_argument('--exit_on_success', help='Quit the app when the playback is complete.', action='store_true', default=False)

def main( parsed_args, workflow_cmdline_args=[], init_logging=True ):
    """
    init_logging: Skip logging config initialization by setting this to False.
                  (Useful when opening multiple projects in a Python script.)
    """
    this_path = os.path.dirname(__file__)
    ilastik_dir = os.path.abspath(os.path.join(this_path, "..%s.." % os.path.sep))
    _update_debug_mode( parsed_args )
    
    # If necessary, redirect stdout BEFORE logging is initialized
    _redirect_output( parsed_args )

    if init_logging:
        _init_logging( parsed_args ) # Initialize logging before anything else

    _init_configfile( parsed_args )
    
    _init_threading_logging_monkeypatch()
    _validate_arg_compatibility( parsed_args )

    # Extra initialization functions.
    # These are called during app startup, but before the shell is created.
    preinit_funcs = []
    preinit_funcs.append( _import_opengm ) # Must be first (or at least before vigra).
    
    lazyflow_config_fn = _prepare_lazyflow_config( parsed_args )
    if lazyflow_config_fn:
        preinit_funcs.append( lazyflow_config_fn )

    # More initialization functions.
    # These will be called AFTER the shell is created.
    # The shell is provided as a parameter to the function.
    postinit_funcs = []
    load_fn = _prepare_auto_open_project( parsed_args )
    if load_fn:
        postinit_funcs.append( load_fn )
    
    create_fn = _prepare_auto_create_new_project( parsed_args )
    if create_fn:
        postinit_funcs.append( create_fn )

    _enable_faulthandler()
    _init_excepthooks( parsed_args )
    eventcapture_mode, playback_args = _prepare_test_recording_and_playback( parsed_args )    

    if ilastik_config.getboolean("ilastik", "debug"):
        message = 'Starting ilastik in debug mode from "%s".' % ilastik_dir
        logger.info(message)
        print message     # always print the startup message
    else:
        message = 'Starting ilastik from "%s".' % ilastik_dir
        logger.info(message)
        print message     # always print the startup message
    
    # Headless launch
    if parsed_args.headless:
        # If any applet imports the GUI in headless mode, that's a mistake.
        # To help developers catch such mistakes, we replace PyQt with a dummy module, so we'll see import errors.
        import ilastik
        dummy_module_dir = os.path.join( os.path.split(ilastik.__file__)[0], "headless_dummy_modules" )
        sys.path.insert(0, dummy_module_dir)

        # Run pre-init
        for f in preinit_funcs:
            f()
        
        from ilastik.shell.headless.headlessShell import HeadlessShell
        shell = HeadlessShell( workflow_cmdline_args )

        # Run post-init
        for f in postinit_funcs:
            f(shell)
        return shell
    # Normal launch
    else:
        from ilastik.shell.gui.startShellGui import startShellGui
        sys.exit(startShellGui(workflow_cmdline_args, eventcapture_mode, playback_args, preinit_funcs, postinit_funcs))

def _init_configfile( parsed_args ):
    # If the user provided a custom config path to use instead of the default .ilastikrc,
    # Re-initialize the config module for it.
    if parsed_args.configfile:
        ilastik.config.init_ilastik_config( parsed_args.configfile )

stdout_redirect_file = None
old_stdout = None
old_stderr = None
def _redirect_output( parsed_args ):
    if parsed_args.redirect_output:        
        global old_stdout, old_stderr
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        
        global stdout_redirect_file
        stdout_redirect_file = open( parsed_args.redirect_output, 'a' )
        sys.stdout = stdout_redirect_file
        sys.stderr = stdout_redirect_file
        
        # Close the file when we exit...
        import atexit
        atexit.register( stdout_redirect_file.close )

def _update_debug_mode( parsed_args ):
    # Force debug mode if any of these flags are active.
    if parsed_args.debug \
    or parsed_args.start_recording \
    or parsed_args.playback_script \
    or ilastik_config.getboolean('ilastik', 'debug'):
        # There are two places that debug mode can be checked.
        # Make sure both are set.
        ilastik_config.set('ilastik', 'debug', 'true')
        parsed_args.debug = True

def _init_logging( parsed_args ):
    from ilastik.ilastik_logging import default_config, startUpdateInterval, DEFAULT_LOGFILE_PATH

    logfile_path = parsed_args.logfile or DEFAULT_LOGFILE_PATH
    process_name = ""
    if parsed_args.process_name:
        process_name = parsed_args.process_name + " "

    if ilastik_config.getboolean('ilastik', 'debug') or parsed_args.headless:
        default_config.init(process_name, default_config.OutputMode.BOTH, logfile_path)
    else:
        default_config.init(process_name, default_config.OutputMode.LOGFILE_WITH_CONSOLE_ERRORS, logfile_path)
        startUpdateInterval(10) # 10 second periodic refresh
    
    if parsed_args.redirect_output:
        logger.info( "All console output is being redirected to: {}"
                     .format( parsed_args.redirect_output ) )

def _init_threading_logging_monkeypatch():
    # Monkey-patch thread starts if this special logger is active
    thread_start_logger = logging.getLogger("thread_start")
    if thread_start_logger.isEnabledFor(logging.DEBUG):
        import threading
        ordinary_start = threading.Thread.start
        def logged_start(self):
            ordinary_start(self)
            thread_start_logger.debug( "Started thread: id={:x}, name={}".format( self.ident, self.name ) )
        threading.Thread.start = logged_start

def _validate_arg_compatibility( parsed_args ):
    # Check for bad input options
    if parsed_args.workflow is not None and parsed_args.new_project is None:
        sys.stderr.write("The --workflow argument may only be used with the --new_project argument.")
        sys.exit(1)
    if parsed_args.workflow is None and parsed_args.new_project is not None:
        sys.stderr.write("No workflow specified.  The --new_project argument must be used in conjunction with the --workflow argument.")
        sys.exit(1)
    if parsed_args.project is not None and parsed_args.new_project is not None:
        sys.stderr.write("The --project and --new_project settings cannot be used together.  Choose one (or neither).")
        sys.exit(1)

    if parsed_args.headless and \
       ( parsed_args.start_recording or \
         parsed_args.playback_script or \
         parsed_args.fullscreen or \
         parsed_args.exit_on_failure or \
         parsed_args.exit_on_success ):
        sys.stderr.write("Some of the command-line options you provided are not supported in headless mode.  Exiting.")
        sys.exit(1)

def _import_opengm():
    # Import opengm first if possible, to make sure it is included before vigra.
    # Otherwise the import fails and we will not get access to GraphCut thresholding
    try:
        import opengm
    except:
        pass

def _prepare_lazyflow_config( parsed_args ):
    # Check environment variable settings.
    n_threads = os.getenv("LAZYFLOW_THREADS", None)
    total_ram_mb = os.getenv("LAZYFLOW_TOTAL_RAM_MB", None)
    status_interval_secs = int( os.getenv("LAZYFLOW_STATUS_MONITOR_SECONDS", "0") )

    # Convert str -> int
    if n_threads is not None:
        n_threads = int(n_threads)
    total_ram_mb = total_ram_mb and int(total_ram_mb)

    # If not in env, check config file.
    if n_threads is None:
        n_threads = ilastik_config.getint('lazyflow', 'threads')
        if n_threads == -1:
            n_threads = None
    total_ram_mb = total_ram_mb or ilastik_config.getint('lazyflow', 'total_ram_mb')
    
    # Note that n_threads == 0 is valid and useful for debugging.
    if (n_threads is not None) or total_ram_mb or status_interval_secs:
        def _configure_lazyflow_settings():
            import lazyflow
            import lazyflow.request
            from lazyflow.utility import Memory
            from lazyflow.operators.cacheMemoryManager import CacheMemoryManager

            if status_interval_secs:
                memory_logger = logging.getLogger('lazyflow.operators.cacheMemoryManager')
                memory_logger.setLevel(logging.DEBUG)
                CacheMemoryManager().setRefreshInterval(status_interval_secs)

            if n_threads is not None:
                logger.info("Resetting lazyflow thread pool with {} threads.".format( n_threads ))
                lazyflow.request.Request.reset_thread_pool(n_threads)
            if total_ram_mb > 0:
                if total_ram_mb < 500:
                    raise Exception("In your current configuration, RAM is limited to {} MB."
                                    "  Remember to specify RAM in MB, not GB."
                                    .format( total_ram_mb ))
                ram = total_ram_mb * 1024**2
                fmt = Memory.format(ram)
                logger.info("Configuring lazyflow RAM limit to {}".format(fmt))
                Memory.setAvailableRam(ram)
        return _configure_lazyflow_settings
    return None

def _monkey_patch_h5py(shell):
    """
    This workaround avoids error messages from HDF5 when accessing non-existing
    files, datasets, and dataset attributes from non-main threads.

    See also:
    - https://github.com/h5py/h5py/issues/580
    - https://github.com/h5py/h5py/issues/582
    """
    import os
    import h5py

    old_dataset_getitem = h5py.Group.__getitem__
    def new_dataset_getitem(group, key):
        if key not in group:
            raise KeyError("Unable to open object (Object '{}' doesn't exist)".format( key ))
        return old_dataset_getitem(group, key)
    h5py.Group.__getitem__ = new_dataset_getitem

    old_file_init = h5py.File.__init__
    def new_file_init(f, name, mode=None, driver=None, libver=None, userblock_size=None, **kwds):#, swmr=False, **kwds):
        if isinstance(name, (str, buffer)) and (mode is None or mode == 'a'):
            if not os.path.exists(name):
                mode = 'w'
        old_file_init(f, name, mode, driver, libver, userblock_size, **kwds)#, swmr, **kwds)
    h5py.File.__init__ = new_file_init

    old_attr_getitem = h5py._hl.attrs.AttributeManager.__getitem__
    def new_attr_getitem(attrs, key):
        if key not in attrs:
            raise KeyError("Can't open attribute (Can't locate attribute: '{}')".format(key))
        return old_attr_getitem(attrs, key)
    h5py._hl.attrs.AttributeManager.__getitem__ = new_attr_getitem

def _prepare_auto_open_project( parsed_args ):
    if parsed_args.project is None:
        return None

    from lazyflow.utility.pathHelpers import PathComponents, isUrl

    # Make sure project file exists.
    if not isUrl(parsed_args.project) and not os.path.exists(parsed_args.project):
        raise RuntimeError("Project file '" + parsed_args.project + "' does not exist.")

    parsed_args.project = os.path.expanduser(parsed_args.project)
    #convert path to convenient format
    path = PathComponents(parsed_args.project).totalPath()
    
    def loadProject(shell):
        # This should work for both the IlastikShell and the HeadlessShell
        shell.openProjectFile(path, parsed_args.readonly)
    return loadProject

def _prepare_auto_create_new_project( parsed_args ):
    if parsed_args.new_project is None:
        return None
    parsed_args.new_project = os.path.expanduser(parsed_args.new_project)
    # convert path to convenient format
    from lazyflow.utility.pathHelpers import PathComponents
    path = PathComponents(parsed_args.new_project).totalPath()
    def createNewProject(shell):
        import ilastik.workflows
        from ilastik.workflow import getWorkflowFromName
        workflow_class = getWorkflowFromName(parsed_args.workflow)
        if workflow_class is None:
            raise Exception("'{}' is not a valid workflow type.".format( parsed_args.workflow ))
        # This should work for both the IlastikShell and the HeadlessShell
        shell.createAndLoadNewProject(path, workflow_class)
    return createNewProject

def _prepare_test_recording_and_playback( parsed_args ):
    if parsed_args.start_recording or parsed_args.playback_script:
        # Disable the opengl widgets during recording and playback.
        # Somehow they can cause random segfaults if used during recording playback.
        import volumina
        volumina.NO3D = True

    # Enable test-case recording?
    eventcapture_mode = None
    playback_args = {}
    if parsed_args.start_recording:
        assert not parsed_args.playback_script is False, "Can't record and play back at the same time!  Choose one or the other"
        eventcapture_mode = 'record'
    elif parsed_args.playback_script is not None:
        # Only import GUI modules in non-headless mode.
        from PyQt4.QtGui import QApplication
        eventcapture_mode = 'playback'
        # See EventRecordingApp.create_app() for details
        playback_args['playback_script'] = parsed_args.playback_script
        playback_args['playback_speed'] = parsed_args.playback_speed
        # Auto-exit on success?
        if parsed_args.exit_on_success:
            playback_args['finish_callback'] = QApplication.quit
    return eventcapture_mode, playback_args

def _enable_faulthandler():
    try:
        # Enable full stack trace printout in case of a segfault
        # (Requires the faulthandler module from PyPI)
        import faulthandler
    except ImportError:
        return
    else:
        faulthandler.enable()

def _init_excepthooks( parsed_args ):
    # Initialize global exception handling behavior
    import ilastik.excepthooks
    if parsed_args.exit_on_failure:
        # Auto-exit on uncaught exceptions (useful for testing)
        ilastik.excepthooks.init_early_exit_excepthook()
    elif not ilastik_config.getboolean('ilastik', 'debug') and not parsed_args.headless:
        # Show most uncaught exceptions to the user (default behavior)
        ilastik.excepthooks.init_user_mode_excepthook()
    else:
        # Log all exceptions as errors
        ilastik.excepthooks.init_developer_mode_excepthook()

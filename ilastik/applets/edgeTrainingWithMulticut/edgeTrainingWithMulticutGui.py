from PyQt4.QtGui import QWidget, QVBoxLayout, QGroupBox, QSpacerItem, QSizePolicy

from ilastik.applets.edgeTraining.edgeTrainingGui import EdgeTrainingGui
from ilastik.applets.multicut.multicutGui import MulticutGuiMixin

class EdgeTrainingWithMulticutGui(MulticutGuiMixin, EdgeTrainingGui):
    
    def __init__(self, parentApplet, topLevelOperatorView):
        self.__cleanup_fns = []
        MulticutGuiMixin.__init__(self, parentApplet, topLevelOperatorView)
        EdgeTrainingGui.__init__(self, parentApplet, topLevelOperatorView)

    def _after_init(self):
        EdgeTrainingGui._after_init(self)
        MulticutGuiMixin._after_init(self)

    def initAppletDrawerUi(self):
        training_controls = EdgeTrainingGui.createDrawerControls(self)
        training_controls.layout().setContentsMargins(5,0,5,0)
        training_layout = QVBoxLayout()
        training_layout.addWidget( training_controls )
        training_layout.setContentsMargins(0,0,0,0)
        training_box = QGroupBox( "Training", parent=self )
        training_box.setLayout(training_layout)
        training_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        multicut_controls = MulticutGuiMixin.createDrawerControls(self)
        multicut_controls.layout().setContentsMargins(5,0,5,0)
        multicut_layout = QVBoxLayout()
        multicut_layout.addWidget( multicut_controls )
        multicut_layout.setContentsMargins(0,0,0,0)
        multicut_box = QGroupBox( "Multicut", parent=self )
        multicut_box.setLayout(multicut_layout)
        multicut_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        drawer_layout = QVBoxLayout()
        drawer_layout.addWidget(training_box)
        drawer_layout.addWidget(multicut_box)
        drawer_layout.setSpacing(2)
        drawer_layout.setContentsMargins(5,5,5,5)
        drawer_layout.addSpacerItem( QSpacerItem(0, 10, QSizePolicy.Minimum, QSizePolicy.Expanding) )
        
        self._drawer = QWidget(parent=self)
        self._drawer.setLayout(drawer_layout)        

        # GUI will be initialized in _after_init()
        #self.configure_gui_from_operator()

    def appletDrawer(self):
        return self._drawer

    def stopAndCleanUp(self):
        # Unsubscribe to all signals
        for fn in self.__cleanup_fns:
            fn()

        # Base classes
        EdgeTrainingGui.stopAndCleanUp(self)
        MulticutGuiMixin.stopAndCleanUp(self)

    def setupLayers(self):
        layers = []
        edgeTrainingLayers = EdgeTrainingGui.setupLayers(self)

        mc_disagreement_layer = MulticutGuiMixin.create_multicut_disagreement_layer(self)
        if mc_disagreement_layer:
            layers.append(mc_disagreement_layer)
        
        mc_edge_layer = MulticutGuiMixin.create_multicut_edge_layer(self)
        if mc_edge_layer:
            layers.append(mc_edge_layer)

        mc_seg_layer = MulticutGuiMixin.create_multicut_segmentation_layer(self)
        if mc_seg_layer:
            layers.append(mc_seg_layer)

        layers += edgeTrainingLayers
        return layers
    
    def configure_gui_from_operator(self, *args):
        EdgeTrainingGui.configure_gui_from_operator(self)
        MulticutGuiMixin.configure_gui_from_operator(self)
    
    def configure_operator_from_gui(self):
        EdgeTrainingGui.configure_operator_from_gui(self)
        MulticutGuiMixin.configure_operator_from_gui(self)

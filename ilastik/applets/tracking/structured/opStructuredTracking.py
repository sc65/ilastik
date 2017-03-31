import numpy as np
import math

from lazyflow.graph import InputSlot, OutputSlot
from lazyflow.stype import Opaque
from lazyflow.rtype import List
from ilastik.utility import bind

from ilastik.applets.tracking.conservation.opConservationTracking import OpConservationTracking
from ilastik.applets.base.applet import DatasetConstraintError
from ilastik.applets.objectExtraction.opObjectExtraction import default_features_key

try:
    import multiHypoTracking_with_cplex as mht
except ImportError:
    try:
        import multiHypoTracking_with_gurobi as mht
    except ImportError:
        raise ImportError("Could not find any ILP solver")

import logging
logger = logging.getLogger(__name__)

class OpStructuredTracking(OpConservationTracking):
    Crops = InputSlot()
    Labels = InputSlot(stype=Opaque, rtype=List)
    Divisions = InputSlot(stype=Opaque, rtype=List)
    Annotations = InputSlot(stype=Opaque)
    MaxNumObj = InputSlot()

    DivisionWeight = OutputSlot()
    DetectionWeight = OutputSlot()
    TransitionWeight = OutputSlot()
    AppearanceWeight = OutputSlot()
    DisappearanceWeight = OutputSlot()
    MaxNumObjOut = OutputSlot()

    def __init__(self, parent=None, graph=None):
        super(OpStructuredTracking, self).__init__(parent=parent, graph=graph)

        self.labels = {}
        self.divisions = {}
        self.Annotations.setValue({})
        self._ndim = 3

        self._parent = parent

        self.DivisionWeight.setValue(0.6)
        self.DetectionWeight.setValue(0.6)
        self.TransitionWeight.setValue(0.01)
        self.AppearanceWeight.setValue(0.3)
        self.DisappearanceWeight.setValue(0.2)

        self.MaxNumObjOut.setValue(1)

        self.transition_parameter = 5
        self.detectionWeight = 1
        self.divisionWeight = 1
        self.transitionWeight = 1
        self.appearanceWeight = 1
        self.disappearanceWeight = 1

        self.Crops.notifyReady(bind(self._updateCropsFromOperator) )
        self.Labels.notifyReady( bind(self._updateLabelsFromOperator) )
        self.Divisions.notifyReady( bind(self._updateDivisionsFromOperator) )

    def _updateLabelsFromOperator(self):
        self.labels = self.Labels.value

    def _updateDivisionsFromOperator(self):
        self.divisions = self.Divisions.value

    def setupOutputs(self):
        super(OpStructuredTracking, self).setupOutputs()
        self._ndim = 2 if self.LabelImage.meta.shape[3] == 1 else 3

        for t in range(self.LabelImage.meta.shape[0]):
            if t not in self.labels.keys():
                self.labels[t]={}

    def execute(self, slot, subindex, roi, result):

        if slot is self.Labels:
            result=self.Labels.wait()

        elif slot is self.Divisions:
            result=self.Divisions.wait()

        else:
            super(OpStructuredTracking, self).execute(slot, subindex, roi, result)

        return result

    def _updateCropsFromOperator(self):
        self._crops = self.Crops.value

    def _runStructuredLearning(self,
            z_range,
            maxObj,
            maxNearestNeighbors,
            maxDist,
            divThreshold,
            scales,
            size_range,
            withDivisions,
            borderAwareWidth,
            withClassifierPrior,
            withBatchProcessing=False):

        if not withBatchProcessing:
            gui = self.parent.parent.trackingApplet._gui.currentGui()

        emptyAnnotations = False
        for crop in self.Annotations.value.keys():
            emptyCrop = self.Annotations.value[crop]["divisions"]=={} and self.Annotations.value[crop]["labels"]=={}
            if emptyCrop and not withBatchProcessing:
                gui._criticalMessage("Error: Weights can not be calculated because training annotations for crop {} are missing. ".format(crop) +\
                                  "Go back to Training applet and Save your training for each crop.")
            emptyAnnotations = emptyAnnotations or emptyCrop

        if emptyAnnotations:
            return [self.DetectionWeight.value, self.DivisionWeight.value, self.TransitionWeight.value, self.AppearanceWeight.value, self.DisappearanceWeight.value]

        self._updateCropsFromOperator()
        median_obj_size = [0]

        from_z = z_range[0]
        to_z = z_range[1]
        ndim=3
        if (to_z - from_z == 0):
            ndim=2

        time_range = [0, self.LabelImage.meta.shape[0]-1]
        x_range = [0, self.LabelImage.meta.shape[1]]
        y_range = [0, self.LabelImage.meta.shape[2]]
        z_range = [0, self.LabelImage.meta.shape[3]]

        parameters = self.Parameters.value

        parameters['maxDist'] = maxDist
        parameters['maxObj'] = maxObj
        parameters['divThreshold'] = divThreshold
        parameters['withDivisions'] = withDivisions
        parameters['withClassifierPrior'] = withClassifierPrior
        parameters['borderAwareWidth'] = borderAwareWidth
        parameters['scales'] = scales
        parameters['time_range'] = [min(time_range), max(time_range)]
        parameters['x_range'] = x_range
        parameters['y_range'] = y_range
        parameters['z_range'] = z_range
        parameters['max_nearest_neighbors'] = maxNearestNeighbors

        # Set a size range with a minimum area equal to the max number of objects (since the GMM throws an error if we try to fit more gaussians than the number of pixels in the object)
        size_range = (max(maxObj, size_range[0]), size_range[1])
        parameters['size_range'] = size_range

        self.Parameters.setValue(parameters, check_changed=False)

        foundAllArcs = False;
        new_max_nearest_neighbors = max ([maxNearestNeighbors-1,1])
        maxObjOK = True
        parameters['max_nearest_neighbors'] = maxNearestNeighbors
        while not foundAllArcs and maxObjOK and new_max_nearest_neighbors<10:
            new_max_nearest_neighbors += 1
            logger.info("new_max_nearest_neighbors: {}".format(new_max_nearest_neighbors))

            time_range = range (0,self.LabelImage.meta.shape[0])

            parameters['max_nearest_neighbors'] = new_max_nearest_neighbors
            self.Parameters.setValue(parameters, check_changed=False)

            hypothesesGraph = self._createHypothesesGraph()
            if hypothesesGraph.countNodes() == 0:
                raise DatasetConstraintError('Structured Learning', 'Can not track frames with 0 objects, abort.')

            hypothesesGraph.insertEnergies()
            # trackingGraph = hypothesesGraph.toTrackingGraph()
            # import pprint
            # pprint.pprint(trackingGraph.model)

            maxDist = 200
            sizeDependent = False
            divThreshold = float(0.5)

            logger.info("Structured Learning: Adding Training Annotations to Hypotheses Graph")

            mergeMsgStr = "Your tracking annotations contradict this model assumptions! All tracks must be continuous, tracks of length one are not allowed, and mergers may merge or split but all tracks in a merger appear/disappear together."
            foundAllArcs = True;
            numAllAnnotatedDivisions = 0

            self.features = self.ObjectFeatures(range(0,self.LabelImage.meta.shape[0])).wait()

            for cropKey in self.Crops.value.keys():
                if foundAllArcs:

                    if not cropKey in self.Annotations.value.keys():
                        if not withBatchProcessing:
                            gui._criticalMessage("You have not trained or saved your training for " + str(cropKey) + \
                                              ". \nGo back to the Training applet and save all your training!")
                        return [self.DetectionWeight.value, self.DivisionWeight.value, self.TransitionWeight.value, self.AppearanceWeight.value, self.DisappearanceWeight.value]

                    crop = self.Annotations.value[cropKey]
                    timeRange = self.Crops.value[cropKey]['time']

                    if "labels" in crop.keys():

                        labels = crop["labels"]

                        for time in labels.keys():
                            if time in range(timeRange[0],timeRange[1]+1):

                                if not foundAllArcs:
                                    break

                                for label in labels[time].keys():

                                    if not foundAllArcs:
                                        break

                                    trackSet = labels[time][label]
                                    center = self.features[time][default_features_key]['RegionCenter'][label]
                                    trackCount = len(trackSet)

                                    if trackCount > maxObj:
                                        logger.info("Your track count for object {} in time frame {} is {} =| {} |, which is greater than maximum object number {} defined by object count classifier!".format(label,time,trackCount,trackSet,maxObj))
                                        logger.info("Either remove track(s) from this object or train the object count classifier with more labels!")
                                        maxObjOK = False
                                        raise DatasetConstraintError('Structured Learning', "Your track count for object "+str(label)+" in time frame " +str(time)+ " equals "+str(trackCount)+"=|"+str(trackSet)+"|," + \
                                                " which is greater than the maximum object number "+str(maxObj)+" defined by object count classifier! " + \
                                                "Either remove track(s) from this object or train the object count classifier with more labels!")

                                    for track in trackSet:

                                        if not foundAllArcs:
                                            logger.info("[structuredTrackingGui] Increasing max nearest neighbors!")
                                            break

                                        # is this a FIRST, INTERMEDIATE, LAST, SINGLETON(FIRST_LAST) object of a track (or FALSE_DETECTION)
                                        type = self._type(cropKey, time, track) # returns [type, previous_label] if type=="LAST" or "INTERMEDIATE" (else [type])
                                        if type == None:
                                            raise DatasetConstraintError('Structured Learning', mergeMsgStr)

                                        elif type[0] in ["LAST", "INTERMEDIATE", "SINGLETON(FIRST_LAST)"]:
                                            if type[0] == "SINGLETON(FIRST_LAST)":
                                                trackCountIntersection = len(trackSet)
                                            else:
                                                previous_label = int(type[1])
                                                previousTrackSet = labels[time-1][previous_label]
                                                intersectionSet = trackSet.intersection(previousTrackSet)
                                                trackCountIntersection = len(intersectionSet)
                                            print "trackCountIntersection",trackCountIntersection

                                            if trackCountIntersection > maxObj:
                                                logger.info("Your track count for transition ( {},{} ) ---> ( {},{} ) is {} =| {} |, which is greater than maximum object number {} defined by object count classifier!".format(previous_label,time-1,label,time,trackCountIntersection,intersectionSet,maxObj))
                                                logger.info("Either remove track(s) from these objects or train the object count classifier with more labels!")
                                                maxObjOK = False
                                                raise DatasetConstraintError('Structured Learning', "Your track count for transition ("+str(previous_label)+","+str(time-1)+") ---> ("+str(label)+","+str(time)+") is "+str(trackCountIntersection)+"=|"+str(intersectionSet)+"|, " + \
                                                        "which is greater than maximum object number "+str(maxObj)+" defined by object count classifier!" + \
                                                        "Either remove track(s) from these objects or train the object count classifier with more labels!")


                                            sink = (time, int(label))
                                            foundAllArcs = False
                                            for edge in hypothesesGraph._graph.in_edges(sink): # an edge is a tuple of source and target nodes
                                                logger.info("Looking at in edge {} of node {}, searching for ({},{})".format(edge, sink, time-1, previous_label))
                                                if edge[0][0] == time-1 and edge[0][1] == int(previous_label): # every node 'id' is a tuple (timestep, label), so we need the in-edge coming from previous_label
                                                    foundAllArcs = True
                                                    hypothesesGraph._graph.edge[edge[0]][edge[1]]['value'] = int(trackCountIntersection)
                                                    print "[structuredTrackingGui] EDGE: ({},{})--->({},{})".format(time-1, int(previous_label), time,int(label))
                                                    break

                                            if not foundAllArcs:
                                                logger.info("[structuredTrackingGui] Increasing max nearest neighbors! LABELS/MERGERS {} {}".format(time-1, int(previous_label)))
                                                logger.info("[structuredTrackingGui] Increasing max nearest neighbors! LABELS/MERGERS {} {}".format(time, int(label)))
                                                break

                                    if type == None:
                                        raise DatasetConstraintError('Structured Learning', mergeMsgStr)

                                    elif type[0] in ["FIRST", "LAST", "INTERMEDIATE", "SINGLETON(FIRST_LAST)"]:
                                        if (time, int(label)) in hypothesesGraph._graph.node.keys():
                                            hypothesesGraph._graph.node[(time, int(label))]['value'] = trackCount
                                            logger.info("[structuredTrackingGui] NODE: {} {}".format(time, int(label)))
                                            print "[structuredTrackingGui] NODE: {} {} {}".format(time, int(label), int(trackCount))
                                        else:
                                            logger.info("[structuredTrackingGui] NODE: {} {} NOT found".format(time, int(label)))

                                            foundAllArcs = False
                                            break

                    if foundAllArcs and "divisions" in crop.keys():
                        divisions = crop["divisions"]

                        numAllAnnotatedDivisions = numAllAnnotatedDivisions + len(divisions)
                        for track in divisions.keys():
                            if not foundAllArcs:
                                break

                            division = divisions[track]
                            time = int(division[1])

                            parent = int(self.getLabelInCrop(cropKey, time, track))

                            if parent >=0:
                                children = [int(self.getLabelInCrop(cropKey, time+1, division[0][i])) for i in [0, 1]]
                                parentNode = (time, parent)
                                hypothesesGraph._graph.node[parentNode]['divisionValue'] = 1
                                foundAllArcs = False
                                for child in children:
                                    for edge in hypothesesGraph._graph.out_edges(parentNode): # an edge is a tuple of source and target nodes
                                        if edge[1][0] == time+1 and edge[1][1] == int(child): # every node 'id' is a tuple (timestep, label), so we need the in-edge coming from previous_label
                                            foundAllArcs = True
                                            hypothesesGraph._graph.edge[edge[0]][edge[1]]['value'] = 1
                                            break
                                    if not foundAllArcs:
                                        break

                                if not foundAllArcs:
                                    logger.info("[structuredTrackingGui] Increasing max nearest neighbors! DIVISION {} {}".format(time, parent))
                                    break
        logger.info("max nearest neighbors= {}".format(new_max_nearest_neighbors))

        if new_max_nearest_neighbors > maxNearestNeighbors:
            maxNearestNeighbors = new_max_nearest_neighbors
            parameters['maxNearestNeighbors'] = maxNearestNeighbors
            if not withBatchProcessing:
                gui._drawer.maxNearestNeighborsSpinBox.setValue(maxNearestNeighbors)

        detectionWeight = self.DetectionWeight.value
        divisionWeight = self.DivisionWeight.value
        transitionWeight = self.TransitionWeight.value
        disappearanceWeight = self.DisappearanceWeight.value
        appearanceWeight = self.AppearanceWeight.value

        if not foundAllArcs:
            logger.info("[structuredTracking] Increasing max nearest neighbors did not result in finding all training arcs!")
            return [transitionWeight, detectionWeight, divisionWeight, appearanceWeight, disappearanceWeight]

        hypothesesGraph.insertEnergies()

        # crops away everything (arcs and nodes) that doesn't have 'value' set
        prunedGraph = hypothesesGraph.pruneGraphToSolution(distanceToSolution=0) # width of non-annotated border needed for negative training examples

        trackingGraph = prunedGraph.toTrackingGraph()

        # trackingGraph.convexifyCosts()
        model = trackingGraph.model
        model['settings']['optimizerEpGap'] = 0.005
        gt = prunedGraph.getSolutionDictionary()

        initialWeights = trackingGraph.weightsListToDict([transitionWeight, detectionWeight, divisionWeight, appearanceWeight, disappearanceWeight])

        mht.trainWithWeightInitialization(model,gt, initialWeights)
        weightsDict = mht.train(model, gt)

        weights = trackingGraph.weightsDictToList(weightsDict)


        if not withBatchProcessing and withDivisions and numAllAnnotatedDivisions == 0 and not weights[2] == 0.0:
            gui._informationMessage("Divisible objects are checked, but you did not annotate any divisions in your tracking training. " + \
                                 "The resulting division weight might be arbitrarily and if there are divisions present in the dataset, " +\
                                 "they might not be present in the tracking solution.")

        norm = 0
        for i in range(len(weights)):
            norm += weights[i]*weights[i]
        norm = math.sqrt(norm)

        if norm > 0.0000001:
            self.TransitionWeight.setValue(weights[0]/norm)
            self.DetectionWeight.setValue(weights[1]/norm)
            self.DivisionWeight.setValue(weights[2]/norm)
            self.AppearanceWeight.setValue(weights[3]/norm)
            self.DisappearanceWeight.setValue(weights[4]/norm)

        if not withBatchProcessing:
            gui._drawer.detWeightBox.setValue(self.DetectionWeight.value)
            gui._drawer.divWeightBox.setValue(self.DivisionWeight.value)
            gui._drawer.transWeightBox.setValue(self.TransitionWeight.value)
            gui._drawer.appearanceBox.setValue(self.AppearanceWeight.value)
            gui._drawer.disappearanceBox.setValue(self.DisappearanceWeight.value)

        if not withBatchProcessing:
            if self.DetectionWeight.value < 0.0:
                gui._informationMessage ("Detection weight calculated was negative. Tracking solution will be re-calculated with non-negativity constraints for learning weights. " + \
                    "Furthermore, you should add more training and recalculate the learning weights in order to improve your tracking solution.")
            elif self.DivisionWeight.value < 0.0:
                gui._informationMessage ("Division weight calculated was negative. Tracking solution will be re-calculated with non-negativity constraints for learning weights. " + \
                    "Furthermore, you should add more division cells to your training and recalculate the learning weights in order to improve your tracking solution.")
            elif self.TransitionWeight.value < 0.0:
                gui._informationMessage ("Transition weight calculated was negative. Tracking solution will be re-calculated with non-negativity constraints for learning weights. " + \
                    "Furthermore, you should add more transitions to your training and recalculate the learning weights in order to improve your tracking solution.")
            elif self.AppearanceWeight.value < 0.0:
                gui._informationMessage ("Appearance weight calculated was negative. Tracking solution will be re-calculated with non-negativity constraints for learning weights. " + \
                    "Furthermore, you should add more appearances to your training and recalculate the learning weights in order to improve your tracking solution.")
            elif self.DisappearanceWeight.value < 0.0:
                gui._informationMessage ("Disappearance weight calculated was negative. Tracking solution will be re-calculated with non-negativity constraints for learning weights. " + \
                    "Furthermore, you should add more disappearances to your training and recalculate the learning weights in order to improve your tracking solution.")

        if self.DetectionWeight.value < 0.0 or self.DivisionWeight.value < 0.0 or self.TransitionWeight.value < 0.0 or \
            self.AppearanceWeight.value < 0.0 or self.DisappearanceWeight.value < 0.0:

            model['settings']['nonNegativeWeightsOnly'] = True
            weightsDict = mht.train(model, gt)

            weights = trackingGraph.weightsDictToList(weightsDict)

            norm = 0
            for i in range(len(weights)):
                norm += weights[i]*weights[i]
            norm = math.sqrt(norm)

            if norm > 0.0000001:
                self.TransitionWeight.setValue(weights[0]/norm)
                self.DetectionWeight.setValue(weights[1]/norm)
                self.DivisionWeight.setValue(weights[2]/norm)
                self.AppearanceWeight.setValue(weights[3]/norm)
                self.DisappearanceWeight.setValue(weights[4]/norm)

            if not withBatchProcessing:
                gui._drawer.detWeightBox.setValue(self.DetectionWeight.value)
                gui._drawer.divWeightBox.setValue(self.DivisionWeight.value)
                gui._drawer.transWeightBox.setValue(self.TransitionWeight.value)
                gui._drawer.appearanceBox.setValue(self.AppearanceWeight.value)
                gui._drawer.disappearanceBox.setValue(self.DisappearanceWeight.value)

        logger.info("Structured Learning Tracking Weights (normalized):")
        logger.info("   detection weight     = {}".format(self.DetectionWeight.value))
        logger.info("   division weight     = {}".format(self.DivisionWeight.value))
        logger.info("   transition weight     = {}".format(self.TransitionWeight.value))
        logger.info("   appearance weight     = {}".format(self.AppearanceWeight.value))
        logger.info("   disappearance weight     = {}".format(self.DisappearanceWeight.value))

        parameters['detWeight'] = self.DetectionWeight.value
        parameters['divWeight'] = self.DivisionWeight.value
        parameters['transWeight'] = self.TransitionWeight.value
        parameters['appearanceCost'] = self.AppearanceWeight.value
        parameters['disappearanceCost'] = self.DisappearanceWeight.value

        self.Parameters.setValue(parameters)

        return [self.DetectionWeight.value, self.DivisionWeight.value, self.TransitionWeight.value, self.AppearanceWeight.value, self.DisappearanceWeight.value]

    def getLabelInCrop(self, cropKey, time, track):
        labels = self.Annotations.value[cropKey]["labels"][time]
        for label in labels.keys():
            if self.Annotations.value[cropKey]["labels"][time][label] == set([track]):
                return label
        return -1

    def _type(self, cropKey, time, track):
        # returns [type, previous_label] (if type=="LAST" or "INTERMEDIATE" else [type])
        type = None
        if track == -1:
            return ["FALSE_DETECTION"]
        elif time == 0:
            type = "FIRST"

        labels = self.Annotations.value[cropKey]["labels"]
        crop = self._crops[cropKey]
        lastTime = -1
        lastLabel = -1
        for t in range(crop["time"][0],time):
            for label in labels[t]:
                if track in labels[t][label]:
                    lastTime = t
                    lastLabel = label
        if lastTime == -1:
            type = "FIRST"
        elif lastTime < time-1:
            logger.info("ERROR: Your annotations are not complete. See time frame {}.".format(time-1))
        elif lastTime == time-1:
            type =  "INTERMEDIATE"

        firstTime = -1
        for t in range(crop["time"][1],time,-1):
            if t in labels.keys():
                for label in labels[t]:
                    if track in labels[t][label]:
                        firstTime = t
        if firstTime == -1:
            if type == "FIRST":
                return ["SINGLETON(FIRST_LAST)"]
            else:
                return ["LAST", lastLabel]
        elif firstTime > time+1:
            logger.info("ERROR: Your annotations are not complete. See time frame {}.".format(time+1))
        elif firstTime == time+1:
            if type ==  "INTERMEDIATE":
                return ["INTERMEDIATE",lastLabel]
            elif type != None:
                return [type]


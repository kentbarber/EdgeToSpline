"""
MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import c4d
from c4d import utils

ID_EDGETOSPLINE = 1054844

ID_EDGETOSPLINE_EDGESELECTION = 1000
ID_EDGETOSPLINE_INPUTLINK = 1001
ID_EDGETOSPLINE_SPLINETYPE = 1002
ID_EDGETOSPLINE_LINEAR = 0
ID_EDGETOSPLINE_AKIMA = 1
ID_EDGETOSPLINE_BSPLINE = 2
ID_EDGETOSPLINE_SUBDIVISIONS = 1003
ID_EDGETOSPLINE_OVERRIDETYPE = 1004

def CheckSelfReferencing(startObject, op):
    objectStack = []
    objectStack.append(startObject)

    firstObject = True

    while objectStack:
        currentObject = objectStack.pop()
        if currentObject == op:
            return True

        downObject = currentObject.GetDown()
        if downObject is not None:
            objectStack.append(downObject)

        if not firstObject:
            nextObject = currentObject.GetNext()
            if nextObject is not None:
                objectStack.append(nextObject)
        
        firstObject = False
        
    return False

def CollectPolygonObjects(startObject, op, ignoreFirst):
    polyList = []
    objectStack = []
    objectStack.append(startObject)

    firstObject = True

    while objectStack:
        currentObject = objectStack.pop()

        downObject = currentObject.GetDown()
        if downObject is not None and downObject != op:
            objectStack.append(downObject)

        if not firstObject:
            nextObject = currentObject.GetNext()
            if nextObject is not None and nextObject != op:
                objectStack.append(nextObject)

        if ignoreFirst and firstObject:
            firstObject = False
            continue

        if currentObject.GetCache():
            objectStack.append(currentObject.GetCache())

        if currentObject.IsInstanceOf(c4d.Opolygon):
            if currentObject.GetDeformCache() is not None:
                currentObject = currentObject.GetDeformCache()

            if not currentObject.GetBit(c4d.BIT_CONTROLOBJECT) and currentObject.GetPolygonCount() > 0:
                objectCopy = currentObject.GetClone(c4d.COPYFLAGS_NO_HIERARCHY | c4d.COPYFLAGS_NO_ANIMATION | c4d.COPYFLAGS_NO_BITS)
                objectCopy.SetMg(currentObject.GetMg())
                polyList.append(objectCopy)

        firstObject = False
        
    return polyList

def ProcessEdgeSelection(polyObj, edgeSelectionName):

    if edgeSelectionName is not None and edgeSelectionName != "":
        tagObj = polyObj.GetFirstTag()

        while tagObj:
            if tagObj.IsInstanceOf(c4d.Tedgeselection):
                if tagObj.GetName() == edgeSelectionName:
                    baseSelectNew = tagObj.GetBaseSelect()
                    sel = baseSelectNew.GetAll(polyObj.GetPolygonCount() * 4)
                    targetEdgeSel = polyObj.GetEdgeS()
                    targetEdgeSel.DeselectAll()
                    for index, selected in enumerate(sel):
                        if not selected: continue
                        targetEdgeSel.Select(index)
                    break
            tagObj = tagObj.GetNext()
    else:
        # select all edges. this includes hidden ngon edges
        edgeSelection = polyObj.GetEdgeS()
        edgeSelection.SelectAll(polyObj.GetPolygonCount() * 4 - 1)

        if polyObj.GetNgonCount() > 0:
            # remove all internal ngon edges
            ngonEdges = polyObj.GetNgonEdgesCompact()
            for polyIndex, entry in enumerate(ngonEdges):
                if entry == 0:
                    continue
                else:
                    for edgeIndex in range(4): 
                        if entry & (1 << edgeIndex) != 0:
                            edgeSelection.Deselect(polyIndex * 4 + edgeIndex)

def TransferSplineMode(targetSpline, op):
    type = op[ID_EDGETOSPLINE_SPLINETYPE]
    subdivisions = op[ID_EDGETOSPLINE_SUBDIVISIONS]

    if type == ID_EDGETOSPLINE_LINEAR:
        targetSpline[c4d.SPLINEOBJECT_TYPE] = c4d.SPLINEOBJECT_TYPE_LINEAR
    elif type == ID_EDGETOSPLINE_AKIMA:
        targetSpline[c4d.SPLINEOBJECT_TYPE] = c4d.SPLINEOBJECT_TYPE_AKIMA
    elif type == ID_EDGETOSPLINE_BSPLINE:
        targetSpline[c4d.SPLINEOBJECT_TYPE] = c4d.SPLINEOBJECT_TYPE_BSPLINE

    targetSpline[c4d.SPLINEOBJECT_INTERPOLATION] = c4d.SPLINEOBJECT_INTERPOLATION_UNIFORM
    targetSpline[c4d.SPLINEOBJECT_SUB] = subdivisions

class EdgeToSplineObjectData(c4d.plugins.ObjectData):

    def __init__(self):
        self.isDirty = False
        self.inputLinkMatrixDirty = 0
        self.selfDirtyCount = 0

    def Init(self, node):
        node[ID_EDGETOSPLINE_EDGESELECTION] = ""
        node[ID_EDGETOSPLINE_SPLINETYPE] = ID_EDGETOSPLINE_LINEAR
        node[ID_EDGETOSPLINE_SUBDIVISIONS] = 0
        node[ID_EDGETOSPLINE_OVERRIDETYPE] = False
        return True

    def CreateSplineFromPolyEdges(self, startObject, edgeSelectionName, op, ignoreFirst):

        polyObjectList = CollectPolygonObjects(startObject, op, ignoreFirst)

        if len(polyObjectList) == 0:
            return None

        splineOutputs = []
        settings = c4d.BaseContainer()

        # call edge to spline modeling command
        for polyObj in polyObjectList:
            ProcessEdgeSelection(polyObj, edgeSelectionName)

            res = utils.SendModelingCommand(command=c4d.MCOMMAND_EDGE_TO_SPLINE,
                                list=[polyObj],
                                mode=c4d.MODELINGCOMMANDMODE_EDGESELECTION,
                                bc=settings,
                                doc=None)
            if res is True:
                splineObj = polyObj.GetDown()
                if splineObj != None:
                    splineObj.Remove()
                    splineObj.SetMg(polyObj.GetMg())
                    splineOutputs.append(splineObj)

        if len(splineOutputs) == 0:
            return None

        returnObject = None

        # join the splines if multiple input objects were found
        if len(splineOutputs) > 1:
            doc = op.GetDocument()
            tempdoc = c4d.documents.BaseDocument()
            
            for spline in splineOutputs:
                tempdoc.InsertObject(spline)

            settings[c4d.MDATA_JOIN_MERGE_SELTAGS] = True
            res = utils.SendModelingCommand(command=c4d.MCOMMAND_JOIN,
                                list=splineOutputs,
                                mode=1032176,
                                bc=settings,
                                doc=tempdoc)

            if isinstance(res, list):
                res[0].SetMg(c4d.Matrix())
                returnObject = res[0]

        if len(splineOutputs) == 1:
            returnObject = splineOutputs[0]

        # transform the spline points into generator space. Otherwise cloner has issues cloning
        if returnObject is not None:
            matrix = ~op.GetMg() * returnObject.GetMg()
            pointCount = returnObject.GetPointCount()
            for pointIndex in range(0, pointCount):
                returnObject.SetPoint(pointIndex, matrix * returnObject.GetPoint(pointIndex))

            returnObject.SetMg(c4d.Matrix())

        if op[ID_EDGETOSPLINE_OVERRIDETYPE]:
            TransferSplineMode(returnObject, op)

        return returnObject

    def GetDEnabling(self, node, id, t_data, flags, itemdesc):
        
        if id[0].id == ID_EDGETOSPLINE_SPLINETYPE or id[0].id == ID_EDGETOSPLINE_SUBDIVISIONS:
            override = node[ID_EDGETOSPLINE_OVERRIDETYPE]
            if override == 1:
                return True
            else:
                return False

        return True

    def CheckDirty(self, op, doc):
        if self.isDirty:
            self.isDirty = False
            op.SetDirty(c4d.DIRTYFLAGS_DATA)
            self.selfDirtyCount =  self.selfDirtyCount + 1

    def GetVirtualObjects(self, op, hh):

        inputLink = op[ID_EDGETOSPLINE_INPUTLINK]
        edgeSelectionName = op[ID_EDGETOSPLINE_EDGESELECTION]

        useInputLink = inputLink is not None

        if inputLink is not None and inputLink.IsInstanceOf(c4d.Tbase):
            if inputLink.IsInstanceOf(c4d.Tedgeselection):
                edgeSelectionName = inputLink.GetName()
            inputLink = inputLink.GetObject()

        settingsDirty = False

        newDirty = 0
        if not useInputLink:
            newDirty = op.GetDirty(c4d.DIRTYFLAGS_DATA)
        else:
            newDirty = op.GetDirty(c4d.DIRTYFLAGS_DATA | c4d.DIRTYFLAGS_MATRIX)

        if newDirty != self.selfDirtyCount:
            self.selfDirtyCount = newDirty
            settingsDirty = True

        inputDirty = False

        op.NewDependenceList()

        if not useInputLink:    
            for child in op.GetChildren():
                op.GetHierarchyClone(hh, child, c4d.HIERARCHYCLONEFLAGS_ASPOLY, inputDirty, None, c4d.DIRTYFLAGS_DATA | c4d.DIRTYFLAGS_MATRIX)
        else:
            selfReferencing = CheckSelfReferencing(inputLink, op)
            if not selfReferencing:
                op.GetHierarchyClone(hh, inputLink, c4d.HIERARCHYCLONEFLAGS_ASPOLY, inputDirty, None, c4d.DIRTYFLAGS_DATA | c4d.DIRTYFLAGS_MATRIX)
                if not inputDirty:
                    inputLinkMatrixDirtyNew = inputLink.GetDirty(c4d.DIRTYFLAGS_MATRIX) + inputLink.GetHDirty(c4d.HDIRTYFLAGS_OBJECT_MATRIX)
                    if inputLinkMatrixDirtyNew != self.inputLinkMatrixDirty:
                        inputDirty = True
                        self.inputLinkMatrixDirty = inputLinkMatrixDirtyNew
        
        if not inputDirty:
            inputDirty = not op.CompareDependenceList()

        if not settingsDirty and not inputDirty:
            return op.GetCache(hh)

        firstChild = op.GetDown()

        if firstChild is None and inputLink is None: 
            return c4d.BaseObject(c4d.Onull);

        usingInputLink = inputLink is not None
        if usingInputLink:
            firstChild = inputLink
        else:
            firstChild = op

        returnObject = self.CreateSplineFromPolyEdges(firstChild, edgeSelectionName, op, not usingInputLink)
        self.isDirty = True

        if returnObject is not None:
            return returnObject

        # nothing was done. Output a dummy nullobj
        return c4d.BaseObject(c4d.Onull)

    def GetContour(self, op, doc, lod, bt):
        if op.GetDeformMode() == False:
            return None

        inputLink = op[ID_EDGETOSPLINE_INPUTLINK]
        edgeSelectionName = op[ID_EDGETOSPLINE_EDGESELECTION]

        if inputLink is not None and inputLink.IsInstanceOf(c4d.Tbase):
            if inputLink.IsInstanceOf(c4d.Tedgeselection):
                edgeSelectionName = inputLink.GetName()
            inputLink = inputLink.GetObject()

        firstChild = op.GetDown()

        if firstChild is None and inputLink is None: 
            return None;

        usingInputLink = inputLink is not None
        if usingInputLink:
            firstChild = inputLink
        else:
            firstChild = op

        returnObject = self.CreateSplineFromPolyEdges(firstChild, edgeSelectionName, op, not usingInputLink)
        if returnObject is not None:
            returnObject.SetName(op.GetName())
        return returnObject

    def GetBubbleHelp(self, node):
        return "Convert Edges to Spline Objects"


if __name__ == "__main__":
    c4d.plugins.RegisterObjectPlugin(id=ID_EDGETOSPLINE,
                                     str="Edge To Spline",
                                     g=EdgeToSplineObjectData,
                                     description="opyedgetosplineobject",
                                     icon=c4d.bitmaps.InitResourceBitmap(1009671),
                                     info=c4d.OBJECT_GENERATOR | c4d.OBJECT_ISSPLINE)

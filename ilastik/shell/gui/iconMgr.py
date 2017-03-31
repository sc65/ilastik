#!/usr/bin/env python

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
# -*- coding: utf-8 -*-

#    Copyright 2010 C Sommer, C Straehle, U Koethe, FA Hamprecht. All rights reserved.
#    
#    Redistribution and use in source and binary forms, with or without modification, are
#    permitted provided that the following conditions are met:
#    
#       1. Redistributions of source code must retain the above copyright notice, this list of
#          conditions and the following disclaimer.
#    
#       2. Redistributions in binary form must reproduce the above copyright notice, this list
#          of conditions and the following disclaimer in the documentation and/or other materials
#          provided with the distribution.
#    
#    THIS SOFTWARE IS PROVIDED BY THE ABOVE COPYRIGHT HOLDERS ``AS IS'' AND ANY EXPRESS OR IMPLIED
#    WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND
#    FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE ABOVE COPYRIGHT HOLDERS OR
#    CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
#    CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
#    SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
#    ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
#    NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
#    ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#    
#    The views and conclusions contained in the software and documentation are those of the
#    authors and should not be interpreted as representing official policies, either expressed
#    or implied, of their employers.

import os
import ilastik

#*******************************************************************************
# i l a s t i k I c o n s                                                      *
#*******************************************************************************

class ilastikIcons(object):
    #get the absolute path of the 'ilastik' module
    ilastikPath = os.path.dirname(__file__)
    
    iconPath = ilastikPath+'/icons/32x32/'
    
    Brush = iconPath + 'actions/edit-clear.png'
    Clear = iconPath + 'actions/edit-clear.png'
    Play = iconPath + "actions/media-playback-start.png"
    Pause = iconPath + "actions/media-playback-pause.png"
    Stop = iconPath + "actions/media-playback-stop.png"
    Record = iconPath + "actions/media-record.png"
    ProcessStop = iconPath + "actions/process-stop.png"
    View = iconPath + 'emotes/face-glasses.png'
    Segment = iconPath + "actions/my-segment.png" 
    Undo = iconPath + 'actions/edit-undo.png'
    Redo = iconPath + 'actions/edit-redo.png'
    DoubleArrow = iconPath + 'actions/media-seek-forward.png'
    DoubleArrowBack = iconPath + 'actions/media-seek-backward.png'
    Preferences = iconPath + 'categories/preferences-system.png'
    New = iconPath + "actions/document-new.png" 
    Open = iconPath + "actions/document-open.png" 
    OpenFolder = iconPath + "status/folder-open.png" 
    GoNext = iconPath + "actions/go-next.png" 
    Save = iconPath + "actions/document-save.png" 
    SaveAs = iconPath + "actions/document-save-as.png"
    Edit = iconPath + "actions/document-properties.png" 
    System = iconPath + "categories/applications-system.png"
    Dialog = iconPath + "status/dialog-information.png"
    Select = iconPath + "actions/edit-select-all.png"
    Erase = iconPath + "actions/my_erase.png"
    Edit2 = iconPath + "actions/edit-find-replace.png"
    AddSel = iconPath + "actions/list-add.png"
    RemSel = iconPath + "actions/list-remove.png"
    Python = iconPath + ilastikPath +"/gui/pyc.ico"
    Help = iconPath + "status/weather-storm.png"
    ZoomIn = iconPath + 'actions/zoom-in.png'
    ZoomOut = iconPath + 'actions/zoom-out.png'
    Cut = iconPath + 'actions/edit-cut.png'
    Find = iconPath + 'actions/edit-find.png'
    Refresh = iconPath + 'actions/view-refresh.png'
    
    Ilastik = iconPath + 'ilastik-icon.png'
    
    #22x22
    iconPath = ilastikPath+'/gui/icons/22x22/'
    AddSelx22 = iconPath + "actions/list-add.png"
    RemSelx22 = iconPath + "actions/list-remove.png"
    
    #16x16
    iconPath = ilastikPath+'/gui/icons/16x16/'
    AddSelx16 = iconPath + "actions/list-add.png"
    RemSelx16 = iconPath + "actions/list-remove.png"
    
    #10x10
    iconPath = ilastikPath+'/gui/icons/10x10/'
    ArrowUpx10   = iconPath + "actions/arrow_up.png"
    ArrowDownx10 = iconPath + "actions/arrow_down.png"
    Maximizex10  = iconPath + "actions/maximize.png"
    
    
    

#===============================================================================
#
#  License: GPL
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License 2
#  as published by the Free Software Foundation.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
#
#===============================================================================
import os
import sys
import traceback
import time
import multiprocessing as mp
import pickle
import datetime
import json

import logging
logging.basicConfig(level=logging.DEBUG)
#logging.getLogger('MosaicPlanner').addHandler(logging.NullHandler())

import wx
import numpy as np
import wx.lib.intctrl
import faulthandler
from pyqtgraph.Qt import QtCore, QtGui

from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg as FigureCanvas
from matplotlib.figure import Figure

import LiveMode
from PositionList import PosList
from MyLasso import MyLasso
from MosaicImage import MosaicImage
from ImageCollection import ImageCollection
from Transform import Transform,ChangeTransform

try:
    # these all require MMCore.py
    # might need non-uM versions of these for demo mode?
    from MMPropertyBrowser import MMPropertyBrowser
    from ASI_Control import ASI_AutoFocus
    from FocusCorrectionPlaneWindow import FocusCorrectionPlaneWindow
    from Snap import SnapView
    from Retake import RetakeView
except ImportError:
    logging.warning("Couldn't import MMCorePy. Defaulting to demo mode.")

from NavigationToolBarImproved import NavigationToolbar2Wx_improved as NavBarImproved
from Settings import (MosaicSettings, CameraSettings,SiftSettings,ChangeCameraSettings, ImageSettings,
                       ChangeImageMetadata, SmartSEMSettings, ChangeSEMSettings, ChannelSettings,
                       ChangeChannelSettings, ChangeSiftSettings, CorrSettings,ChangeCorrSettings,
                      ChangeZstackSettings, ZstackSettings, DirectorySettings, ChangeDirectorySettings, RibbonNumberDialog, MultiRibbonSettings, MapSettingsDialog,
                      SessionSettings)

from widgets import ProgressDialog
#########################
# Deps to ask FC about
# LXML
# marshmallow
# pyyaml
# configobj
# validate
# 
from configobj import ConfigObj
from validate import Validator
#########################

#########################
# Might not be needed?
#
import cv2 # SW autofocus
#########################


from LeicaAFCView import LeicaAFCView
from LeicaDMI import LeicaDMI

#########################
# Slacker lets us sent slack messages
# TODO: fix slack integration, seems hacked in, hardcoded
#
try:
    from slacker import Slacker
except ImportError:
    Slacker = None
    logging.warning("Couldn't import slacker. No slack messages will be posted.")

from SaveThread import file_save_process
from imgprocessing import make_thumbnail
import scipy.optimize as opt #softwarea-autofocus

from Tokens import STOP_TOKEN,BUBBLE_TOKEN
DEFAULT_SETTINGS_FILE = 'MosaicPlannerSettings.default.cfg'
SETTINGS_FILE = 'MosaicPlannerSettings.cfg'
SETTINGS_MODEL_FILE = 'MosaicPlannerSettingsModel.cfg'



class MosaicToolbar(NavBarImproved):
    """A custom toolbar which adds buttons and to interact with a MosaicPanel

    current installed buttons which, along with zoom/pan
    are in "at most one of group can be selected mode":
    selectnear: a cursor point
    select: a lasso like icon
    add: a cursor with a plus sign
    selectone: a cursor with a number 1
    selecttwo: a cursor with a number 2

    installed Simple tool buttons:
    deleteTool) calls self.canvas.OnDeleteSelected ID=ON_DELETE_SELECTED
    corrTool: a button that calls self.canvas.on_corr_tool ID=ON_CORR
    stepTool: a button that calls self.canvas.on_step_tool ID=ON_STEP
    ffTool: a button that calls on_fastforward_tool ID=ON_FF

    installed Toggle tool buttons:
    gridTool: a toggled button that calls self.canvas.on_grid_tool with the ID=ON_GRID
    rotateTool: a toggled button that calls self.canvas.on_rotate_tool with the ID=ON_ROTATE
    THESE SHOULD PROBABLY BE CHANGED TO BE MORE MODULAR IN ITS EFFECT AND NOT ASSUME SOMETHING
    ABOUT THE STRUCTURE OF self.canvas

    a set of controls for setting the parameters of a mosaic (see class MosaicSettings)
    the function getMosaicSettings will return an instance of MosaicSettings with the current settings from the controls
    the function self.canvas.posList.set_mosaic_settings(self.getMosaicSettings) will be called when the mosaic settings are changed
    the function self.canvas.posList.set_mosaic_visible(visible) will be called when the show? checkmark is click/unclick
    THIS SHOULD BE CHANGED TO BE MORE MODULAR IN ITS EFFECT

    note this will also call self.canvas.on_home_tool when the home button is pressed
    """
    # Set up class attributes
    ON_FIND = wx.NewId()
    ON_SELECT  = wx.NewId()
    ON_NEWPOINT = wx.NewId()
    ON_DELETE_SELECTED = wx.NewId()
    #ON_CORR_LEFT = wx.NewId()
    ON_STEP = wx.NewId()
    ON_FF = wx.NewId()
    ON_CORR = wx.NewId()
    ON_FINETUNE = wx.NewId()
    ON_GRID = wx.NewId()
    ON_ROTATE = wx.NewId()
    ON_REDRAW = wx.NewId()
    ON_LIVE_MODE = wx.NewId()
    MAGCHOICE = wx.NewId()
    SHOWMAG = wx.NewId()
    ON_ACQGRID = wx.NewId()
    ON_RUN = wx.NewId()
    ON_SNAP = wx.NewId()
    ON_CROP = wx.NewId()
    #ON_RUN_MULTI = wx.NewId() #MultiRibbons
    ON_SOFTWARE_AF = wx.NewId()



    def __init__(self, plotCanvas):
        """
        plotCanvas: an instance of MosaicPanel which has the correct features (see class doc)

        """
        # call the init function of the class we inheriting from
        NavBarImproved.__init__(self, plotCanvas)
        wx.Log.SetLogLevel(0) # batman?

        #import the icons
        leftcorrBmp   = wx.ArtProvider.GetBitmap(wx.ART_GO_BACK, wx.ART_TOOLBAR)
        selectBmp     = wx.Image('icons/lasso-icon.png',   wx.BITMAP_TYPE_PNG).ConvertToBitmap()
        addpointBmp   = wx.Image('icons/add-icon.bmp',     wx.BITMAP_TYPE_BMP).ConvertToBitmap()
        trashBmp      = wx.Image('icons/delete-icon.png',  wx.BITMAP_TYPE_PNG).ConvertToBitmap()
        selectnearBmp = wx.Image('icons/cursor2-icon.png', wx.BITMAP_TYPE_PNG).ConvertToBitmap()
        oneBmp        = wx.Image('icons/one-icon.bmp',     wx.BITMAP_TYPE_BMP).ConvertToBitmap()
        twoBmp        = wx.Image('icons/two-icon.bmp',     wx.BITMAP_TYPE_BMP).ConvertToBitmap()
        stepBmp       = wx.Image('icons/step-icon.png',    wx.BITMAP_TYPE_PNG).ConvertToBitmap()
        corrBmp       = wx.Image('icons/target-icon.png',  wx.BITMAP_TYPE_PNG).ConvertToBitmap()
        ffBmp         = wx.Image('icons/ff-icon.png',      wx.BITMAP_TYPE_PNG).ConvertToBitmap()
        rotateBmp     = wx.Image('icons/rotate-icon.png',  wx.BITMAP_TYPE_PNG).ConvertToBitmap()
        gridBmp       = wx.Image('icons/grid-icon.png',    wx.BITMAP_TYPE_PNG).ConvertToBitmap()
        softwareAFbmp = wx.Image('icons/new/1446777567_Ironman.png', wx.BITMAP_TYPE_PNG).ConvertToBitmap()
        cameraBmp     = wx.Image('icons/camera-icon.png',  wx.BITMAP_TYPE_PNG).ConvertToBitmap()
        mosaicBmp     = wx.Image('icons/mosaic-icon.png',  wx.BITMAP_TYPE_PNG).ConvertToBitmap()
        carBmp        = wx.Image('icons/car-icon.png',     wx.BITMAP_TYPE_PNG).ConvertToBitmap()
        cropBmp       = wx.Image('icons/new/crop.png',     wx.BITMAP_TYPE_PNG).ConvertToBitmap()
        snapBmp       = wx.Image('icons/new/snap.png',     wx.BITMAP_TYPE_PNG).ConvertToBitmap()
        cameraBmp     = wx.Image('icons/new/camera.png',   wx.BITMAP_TYPE_PNG).ConvertToBitmap()
        liveBmp       = wx.Image('icons/new/livemode.png', wx.BITMAP_TYPE_PNG).ConvertToBitmap()
        batmanBmp     = wx.Image('icons/new/batman.png',   wx.BITMAP_TYPE_PNG).ConvertToBitmap()
        activateBmp   = wx.Image('icons/activate-icon.png',wx.BITMAP_TYPE_PNG).ConvertToBitmap()
        #mosaicBmp     = wx.Image('icons/new/mosaic_camera.png', wx.BITMAP_TYPE_PNG).ConvertToBitmap()
        #checkBmp     = wx.Image('icons/new/1446777170_Check.png',wx.BITMAP_TYPE_PNG).ConvertToBitmap() #MultiRibbons

        self.DeleteTool(self.wx_ids['Subplots']) # batman - what is this? add comment above it?

        #add the mutually exclusive/toggleable tools to the toolbar, see superclass for details on how function works
        self.moveHereTool    = self.add_user_tool('movehere',6,carBmp,True,'move scope here')
        self.snapHereTool    = self.add_user_tool('snaphere',7,cameraBmp,True,'move scope and snap image here')
        self.snapPictureTool = self.add_user_tool('snappic',8,mosaicBmp,True,'take 3x3 mosaic on click')
        self.selectNear      = self.add_user_tool('selectnear',9,selectnearBmp,True,'Add Nearest Point to selection')
        self.activateNear    = self.add_user_tool('toggleactivate',10,activateBmp,True,'Toggle Activation of nearest point to selection, \n'
                                                                                       'Hold shift to activate/deactivate frame,\n'
                                                                                       'Hold T to activate/deactivate all frames,\n'
                                                                                       'Hold R to acttivate/deactivate same frame in all sections,\n'
                                                                                       'Hold F to toggle software autofocus on frame,\n'
                                                                                       'Hold C to toggle software autofocus on same frame in all sections,\n'
                                                                                       'Hold I to set inital frame in all sections,\n'
                                                                                       'Hold L to designate initial frame')
        self.addTool         = self.add_user_tool('add', 11, addpointBmp, True, 'Add a Point')
        self.oneTool         = self.add_user_tool('selectone', 12, oneBmp, True, 'Choose pointLine2D 1')
        self.twoTool         = self.add_user_tool('selecttwo', 13, twoBmp, True, 'Choose pointLine2D 2')


        self.AddSeparator()
        self.AddSeparator() # batman - why called twice, why called at all!, maybe add comment?

        #add the simple button click tools
        self.liveModeTool = self.AddSimpleTool(self.ON_LIVE_MODE,liveBmp,'Enter Live Mode','liveMode')
        self.softwareAFTool  = self.AddSimpleTool(self.ON_SOFTWARE_AF, softwareAFbmp, 'Execute Software AutoFocus','softwareAF')
        self.deleteTool   = self.AddSimpleTool(self.ON_DELETE_SELECTED,trashBmp,'Delete selected points','delete points')
        self.corrTool     = self.AddSimpleTool(self.ON_CORR,corrBmp,'Ajdust pointLine2D 2 with correlation','corrTool')
        self.stepTool     = self.AddSimpleTool(self.ON_STEP,stepBmp,'Take one step using points 1+2','stepTool')
        self.ffTool       = self.AddSimpleTool(self.ON_FF,ffBmp,'Auto-take steps till C<.3 or off image','fastforwardTool')
        self.snapNowTool  = self.AddSimpleTool(self.ON_SNAP,snapBmp,'Take a snap now','snapHereTool')
        self.onCropTool   = self.AddSimpleTool(self.ON_CROP,cropBmp,'Crop field of view','cropTool')

        #add the toggleable tools
        self.gridTool=self.AddCheckTool(self.ON_GRID,gridBmp,wx.NullBitmap,'toggle show frames')
        self.rotateTool=self.AddCheckTool(self.ON_ROTATE,rotateBmp,wx.NullBitmap,'toggle rotate boxes')
        self.runAcqTool=self.AddSimpleTool(self.ON_RUN,batmanBmp,'Acquire AT Data','run_tool')
        #self.runMultiAcqTool=self.AddSimpleTool(self.ON_RUN_MULTI,checkBmp,'MultiRibbons','run_multi_tool') #MultiRibbons

        #setup the controls for the mosaic
        self.showMosaicCheck = wx.CheckBox(self)
        self.showMosaicCheck.SetValue(True)
        self.magChoiceCtrl = wx.lib.agw.floatspin.FloatSpin(self,
                                                            size=(65, -1 ),
                                                            value=self.canvas.posList.mosaic_settings.mag,
                                                            min_val=0,
                                                            increment=.1,
                                                            digits=2,
                                                            name='magnification')
        self.mosaicXCtrl = wx.lib.intctrl.IntCtrl(self, value=1, size=(20, -1))
        self.mosaicYCtrl = wx.lib.intctrl.IntCtrl(self, value=1, size=(20, -1))
        self.overlapCtrl = wx.lib.intctrl.IntCtrl(self, value=20, size=(25, -1))

        #setup the controls for the min/max slider
        minstart=0
        maxstart=500
        self.slider = wx.Slider(self,value=250,minValue=minstart,maxValue=maxstart,size=( 180, -1),style = wx.SL_SELRANGE)
        self.sliderMaxCtrl = wx.lib.intctrl.IntCtrl( self, value=maxstart,size=( 60, -1 ))

        #add the control for the mosaic
        self.AddControl(wx.StaticText(self,label="Show Mosaic"))
        self.AddControl(self.showMosaicCheck)
        self.AddControl(wx.StaticText(self,label="Mag"))
        self.AddControl( self.magChoiceCtrl)
        self.AddControl(wx.StaticText(self,label="MosaicX"))
        self.AddControl(self.mosaicXCtrl)
        self.AddControl(wx.StaticText(self,label="MosaicY"))
        self.AddControl(self.mosaicYCtrl)
        self.AddControl(wx.StaticText(self,label="%Overlap"))
        self.AddControl(self.overlapCtrl)
        self.AddSeparator()
        self.AddControl(self.slider)
        self.AddControl(self.sliderMaxCtrl)

        #bind event handles for the various tools
        #this one i think is inherited... the zoom_tool function (- batman, resolution to thinking?)
        self.Bind(wx.EVT_TOOL, self.on_toggle_pan_zoom, self.zoom_tool)
        self.Bind(wx.EVT_CHECKBOX,self.toggle_mosaic_visible,self.showMosaicCheck)
        self.Bind( wx.lib.agw.floatspin.EVT_FLOATSPIN,self.update_mosaic_settings, self.magChoiceCtrl)
        self.Bind(wx.lib.intctrl.EVT_INT,self.update_mosaic_settings, self.mosaicXCtrl)
        self.Bind(wx.lib.intctrl.EVT_INT,self.update_mosaic_settings, self.mosaicYCtrl)
        self.Bind(wx.lib.intctrl.EVT_INT,self.update_mosaic_settings, self.overlapCtrl)

        #event binding for slider
        self.Bind(wx.EVT_SCROLL_THUMBRELEASE,self.canvas.on_slider_change,self.slider)
        self.Bind(wx.lib.intctrl.EVT_INT,self.updateSliderRange, self.sliderMaxCtrl)

        wx.EVT_TOOL(self, self.ON_LIVE_MODE, self.canvas.on_live_mode)
        wx.EVT_TOOL(self, self.ON_DELETE_SELECTED, self.canvas.on_delete_points)
        wx.EVT_TOOL(self, self.ON_CORR, self.canvas.on_corr_tool)
        wx.EVT_TOOL(self, self.ON_STEP, self.canvas.on_step_tool)
        wx.EVT_TOOL(self, self.ON_RUN, self.canvas.setup_complete)
        wx.EVT_TOOL(self, self.ON_FF, self.canvas.on_fastforward_tool)
        wx.EVT_TOOL(self, self.ON_GRID, self.canvas.on_grid_tool)
        wx.EVT_TOOL(self, self.ON_ROTATE, self.canvas.on_rotate_tool)
        wx.EVT_TOOL(self, self.ON_SNAP, self.canvas.on_snap_tool)
        wx.EVT_TOOL(self, self.ON_CROP, self.canvas.on_crop_tool)
        #wx.EVT_TOOL(self, self.ON_RUN_MULTI, self.canvas.on_run_multi_acq)
        wx.EVT_TOOL(self, self.ON_SOFTWARE_AF, self.canvas.on_software_af_tool)

        self.Realize()

    def update_mosaic_settings(self, evt=""):
        """"update the mosaic_settings variables of the canvas and the posList of the canvas and redraw
        set_mosaic_settings should take care of what is necessary to replot the mosaic"""
        self.canvas.posList.set_mosaic_settings(self.get_mosaic_parameters())
        self.canvas.mosaic_settings = self.get_mosaic_parameters()
        self.canvas.draw()

    def updateSliderRange(self, evt=""):
        #self.set_slider_min(self.sliderMinCtrl.GetValue())
        self.set_slider_max(self.sliderMaxCtrl.GetValue())

    def toggle_mosaic_visible(self, evt=""):
        """call the set_mosaic_visible function of self.canvas.posList to initiate what is necessary to hide the mosaic box"""
        self.canvas.posList.set_mosaic_visible(self.showMosaicCheck.IsChecked())
        self.canvas.draw()


    def get_mosaic_parameters(self):
        """extract out an instance of MosaicSettings from the current controls with the proper values"""
        return MosaicSettings(mag=self.magChoiceCtrl.GetValue(),
                              show_box=self.showMosaicCheck.IsChecked(),
                              mx=self.mosaicXCtrl.GetValue(),
                              my=self.mosaicYCtrl.GetValue(),
                              overlap=self.overlapCtrl.GetValue())

    def set_mosaic_parameters(self,mosaic_settings):
        self.magChoiceCtrl.SetValue(mosaic_settings.mag)
        self.mosaicXCtrl.SetValue(mosaic_settings.mx)
        self.mosaicYCtrl.SetValue(mosaic_settings.my)
        self.overlapCtrl.SetValue(mosaic_settings.overlap)
        self.showMosaicCheck.SetValue(mosaic_settings.show_box)

    #unused # batman - should we kill it if unused?
    def cross_cursor(self, event):
        self.canvas.SetCursor(wx.StockCursor(wx.CURSOR_ARROW))

    #overrides the default
    def home(self, event):
        """calls self.canvas.on_home_tool(), should be triggered by the hometool press.. overrides default behavior"""
        self.canvas.on_home_tool()

    def set_slider_min(self, min=0):
        self.slider.SetMin(min)

    def set_slider_max(self, max=500):
        self.slider.SetMax(max)

class MosaicPanel(FigureCanvas):
    """A panel that extends the matplotlib class FigureCanvas for plotting all the plots, and handling all the GUI interface events
    """
    def __init__(self, parent, config, **kwargs):
        """keyword the same as standard init function for a FigureCanvas"""
        self.parent = parent
        
        self.figure = Figure(figsize=(5, 9))
        FigureCanvas.__init__(self, parent, -1, self.figure, **kwargs)
        self.canvas = self.figure.canvas

        #format the appearance
        self.figure.set_facecolor((1, 1, 1))
        self.figure.set_edgecolor((1, 1, 1))
        self.canvas.SetBackgroundColour('white')

        #add subplots for various things
        self.subplot     = self.figure.add_axes([.05, .5, .92, .5])
        self.posone_plot = self.figure.add_axes([.1, .05, .2, .4])
        self.postwo_plot = self.figure.add_axes([.37, .05, .2, .4])
        self.corrplot    = self.figure.add_axes([.65, .05, .25, .4])

        #initialize the camera settings and mosaic settings
        self.cfg = config
        self.camera_settings = CameraSettings()
        self.camera_settings.load_settings(config)
        mosaic_settings = MosaicSettings()
        mosaic_settings.load_settings(config)
        self.MM_config_file = self.cfg['MosaicPlanner']['MM_config_file']
        print(self.MM_config_file)

        #setup the image source
        self.imgSrc=None
        while self.imgSrc is None:
            try:
                self.load_micromanager_config(self.MM_config_file)
            except:
                traceback.print_exc(file=sys.stdout)
                dlg = wx.MessageBox("Error Loading Micromanager\n check scope and re-select config file","MM Error")
                self.edit_MManager_config()

        # DW: WHAT IS GOING ON HERE??
        channels=self.imgSrc.get_channels()
        self.channel_settings=ChannelSettings(channels)
        self.channel_settings.load_settings(config)
        self.imgSrc.set_channel(self.channel_settings.map_chan)
        map_chan=self.channel_settings.map_chan
        if map_chan not in channels: #if the saved settings don't match, call up dialog
            self.edit_channels()
            map_chan=self.channel_settings.map_chan
        self.imgSrc.set_channel(map_chan)
        self.imgSrc.set_exposure(self.channel_settings.exposure_times[map_chan])

        #load the SIFT settings

        self.SiftSettings = SiftSettings()
        self.SiftSettings.load_settings(config)

        self.CorrSettings = CorrSettings()
        self.CorrSettings.load_settings(config)

        # load directory settings

        self.outdirdict = {}
        self.mapdict = {}

        self.Ribbon_Num = 1
        self.directory_settings = DirectorySettings()
        self.directory_settings.load_settings(config)

        # Acquiring flag so remote control can know if we're in
        # an acquisition
        self._is_acquiring = False
        self._frame_count = 0

        # DW, we don't want to do this unless we have to.
        # self.edit_Directory_settings()
        # dictvalue = self.get_output_dir(self.directory_settings)
        # if dictvalue == None:
        #     goahead = False
        #     while goahead == False:
        #         self.edit_Directory_settings()
        #         dictvalue = self.get_output_dir(self.directory_settings)
        #         if dictvalue != None:
        #             goahead = True

        print('Sample_ID:', self.directory_settings.Sample_ID)
        print('Ribbon_ID:', self.directory_settings.Ribbon_ID)
        print('Session_ID:', self.directory_settings.Session_ID)
        print('Map Number:', self.directory_settings.Map_num)
        #self.directory_settings.save_settings(config)
        
        # print self.directory_settings
        # load Zstack settings
        self.zstack_settings = ZstackSettings()
        self.zstack_settings.load_settings(config)
        self.snapView = None
        self.retakeView = None

        #setup a blank position list
        self.posList=PosList(self.subplot,mosaic_settings,self.camera_settings)
        #start with no MosaicImage
        self.mosaicImage=None
        #start with relative_motion on, so that keypress calls shift_selected_curved() of posList
        self.relative_motion = True

        self.focusCorrectionList = PosList(self.subplot)

        #read saved position list from configuration file
        pos_list_string = self.cfg['MosaicPlanner']['focal_pos_list_pickle']
        #if the saved list is not default blank.. add it to current list
        print("pos_list",pos_list_string)
        if len(pos_list_string)>0:
            print("loading saved position list")
            pl = pickle.loads(pos_list_string)
            self.focusCorrectionList.add_from_posList(pl)
        x,y,z = self.focusCorrectionList.getXYZ()
        if len(x)>2:
            XYZ = np.column_stack((x,y,z))
            self.imgSrc.define_focal_plane(np.transpose(XYZ))


        #start with no toolbar and no lasso tool
        self.navtoolbar = None
        self.lasso = None
        self.lassoLock=False

        self.canvas.mpl_connect('button_press_event', self.on_press)
        self.canvas.mpl_connect('button_release_event', self.on_release)
        self.canvas.mpl_connect('key_press_event', self.on_key)

        if len(self.cfg['LeicaDMI']['port']) > 0:
            self.dmi = LeicaDMI(self.cfg['LeicaDMI']['port'])
        else:
            self.dmi = None

        self._setup_slack_integration()
        self._setup_remote_control()

    def _setup_remote_control(self):
        """ Sets up a remote control interface. See remote.py for
                available commands.  Will process one request every
                200 ms.
        """
        try:
            # TODO: support for other remote control libraries
            from remote import RemoteInterface
            self.interface = RemoteInterface(rep_port=7777, pub_port=7778, parent=self)
            self.timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, self._check_sock, self.timer)
            self.timer.Start(200)
        except Exception as e:
            logging.exception("Failed to set up remote control interface.")
            self.interface = None

    def _setup_slack_integration(self):
        """ Sets up integration with Slack.
        # TODO: Move Slack shit out of here.
        """
        self.slacker = None
        if not Slacker:
            return
        if self.cfg['Slack']['slack_token'] is not None:
            self.slacker = Slacker(self.cfg['Slack']['slack_token'])

    def _check_sock(self, event):
        """ Checks for commands from remote control interface. Called every 200ms.
        """
        try:
            self.interface._check_rep()
        except Exception as e:
            #import traceback; traceback.print_exc()  #UNCOMMENT IF MP STOPS COMMUNICATING
            pass

    def setZPosition(self, position, wait=True):
        """ Sets objective height.
        """
        obj = self.imgSrc.objective
        starting_pos = self.getZPosition()
        self.imgSrc.mmc.setPosition(obj, position)

        if wait:
            # waits for the objective to reach the target position
            # also shows a fancy progress bar
            self.setup_objective_progress_bar(starting_pos, position)
            total_distance = abs(position - starting_pos)
            while self.imgSrc.mmc.deviceBusy(obj):
                current = self.getZPosition()
                travelled = abs(current - starting_pos)
                self.obj_progress.update(travelled, "Current: {} / {}".format(current, position))
            self.imgSrc.mmc.waitForDevice(obj)  # just in case
            self.obj_progress.destroy()
        

    def getZPosition(self):
        return self.imgSrc.mmc.getPosition(self.imgSrc.objective)

    def grabGrid(self,pos=None,folder="",n=3):
        """ Grabs a nxn grid of images around `xytuple` and saves them to
                filepath.
        """
        assert(n%2==1)
        pos = pos or self.getStagePosition()
        if folder=="":
            folder = "C:/tmp"
        elif not os.path.isdir(folder):
            os.makedirs(folder)

        self.imgSrc.set_binning(1)
        ch = self.channel_settings.map_chan
        #self.imgSrc.set_exposure(self.cfg['Software Autofocus']['focus_exp_time'])
        self.imgSrc.set_channel(ch)

        collection = ImageCollection(rootpath=folder, imageSource=self.imgSrc, axis=self.subplot)
        (fw, fh)=self.mosaicImage.imgCollection.get_image_size_um()
        x, y = pos
        for i in range(-(n-1)/2, (n-1)/2+1):
            for j in range(-(n-1)/2, (n-1)/2+1):
                filename = "%03d_%03d.tif"%(i,j)
                mypath = os.path.join(folder,filename)
                img = collection.add_image_to_path(x+(j*fw), y+(i*fh), mypath)

                # if we have a remote interface, publish subsampled image
                if self.interface:
                    t0 = time.clock()
                    self.interface.publish({'image': make_thumbnail(img)})
                    print(time.clock()-t0)


    def handle_close(self,evt=None):
        print("handling close")
        self.imgSrc.stopSequenceAcquisition()
        self.imgSrc.shutdown()

    def load_micromanager_config(self, config_path):
        """ Loads a micromanager config file.  Releases current MM instance
                if necessary.
        """
        if self.imgSrc:
            self.imgSrc.shutdown()
        if self.cfg['MosaicPlanner']['demo_mode']:
            from imageSourceDemo import ImageSource
            logging.info("Loading MM config @ {} in demo mode.".format(config_path))
        else:
            from imageSourceMM import ImageSource
            logging.info("Loading MM config @ {}".format(config_path))

        self.imgSrc=ImageSource(config_path,
                                MasterArduinoPort=self.cfg['MMArduino']['port'],
                                interframe_time=self.cfg['MMArduino']['interframe_time'],
                                filtswitch = self.cfg['MosaicPlanner']['filter_switch'])
        logging.debug("Image Source loaded successfully!")
        # DO WE NEED TO FIDDLE WITH CHANNEL SETTINGS HERE LIKE THEY DO IN THE INIT?

    def on_load(self,rootPath):
        """ Called when a user loads a map.  Creates a new MosaicImage instance and
                using the map and populates it.
        """
        self.rootPath = rootPath
        #print("transpose toggle state",self.imgSrc.transpose_xy)
        if self.mosaicImage != None:
            self.clear_position_list()
            self.mosaicImage = None
        logging.info("Loading map images @ {}".format(self.rootPath))
        self.setup_map_progress_bar(rootPath)
        self.mosaicImage=MosaicImage(self.subplot,
                                     self.posone_plot,
                                     self.postwo_plot,
                                     self.corrplot,
                                     self.imgSrc,
                                     rootPath,
                                     figure=self.figure,
                                     load_callback=self._map_load_callback)
        self.map_progress.destroy()
        self.on_crop_tool()
        self.draw()
        logging.info("Finished loading map!")

    def _map_load_callback(self, index):
        """ Callback for map image load. Currently just used to update
                map load progress bar.
        """
        total_frames = self.map_progress.max_val
        (goahead, skip) = self.map_progress.update(index, 
            "Loaded: {} / {} images".format(index+1, total_frames))
        wx.Yield()

    def write_slice_metadata(self,filename,ch,xpos,ypos,zpos):
        f = open(filename, 'w')
        channelname=self.channel_settings.prot_names[ch]
        (height,width)=self.imgSrc.get_sensor_size()
        ScaleFactorX=self.imgSrc.get_pixel_size()
        ScaleFactorY=self.imgSrc.get_pixel_size()
        exp_time=self.channel_settings.exposure_times[ch]

        f.write("Channel\tWidth\tHeight\tMosaicX\tMosaicY\tScaleX\tScaleY\tExposureTime\n")
        f.write("%s\t%d\t%d\t%d\t%d\t%f\t%f\t%f\n" % \
        (channelname, width, height, 1, 1, ScaleFactorX, ScaleFactorY, exp_time))
        f.write("XPositions\tYPositions\tFocusPositions\n")
        f.write("%s\t%s\t%s\n" %(xpos, ypos, zpos))
        f.close()

    def write_session_metadata(self,outdir):
        filename=os.path.join(outdir,'session_metadata.txt')
        f = open(filename, 'w')

        (height,width)=self.imgSrc.get_sensor_size()
        Nch=0
        for k,ch in enumerate(self.channel_settings.channels):
            if self.channel_settings.usechannels[ch]:
                Nch+=1

        f.write("Width\tHeight\t#chan\tMosaicX\tMosaicY\tScaleX\tScaleY\n")
        f.write("%d\t%d\t%d\t%d\t%d\t%f\t%f\n" % (width,height, Nch,self.posList.mosaic_settings.mx, self.posList.mosaic_settings.my, self.imgSrc.get_pixel_size(), self.imgSrc.get_pixel_size()))
        f.write("Channel\tExposure Times (msec)\tRLPosition\n")
        for k,ch in enumerate(self.channel_settings.channels):
            if self.channel_settings.usechannels[ch]:
                f.write(self.channel_settings.prot_names[ch] + "\t" + "%f\t%s\n" % (self.channel_settings.exposure_times[ch],ch))

        f.write("Meta Experiment name:\t%s" %(self.cfg['Directories']['meta_experiment_name']))

        f.write("Imaged on:" + "\t" + self.cfg['MosaicPlanner']['microscope_name'])
        f.close()


    def autofocus_loop(self,hold_focus,wait,sleep):
        attempts=0
        if self.imgSrc.has_hardware_autofocus():
            #wait till autofocus settles
            time.sleep(wait)
            while not self.imgSrc.is_hardware_autofocus_done():
                time.sleep(sleep)
                attempts+=1
                if attempts>50:
                    print "not auto-focusing correctly.. giving up after 10 seconds"
                    break

            if not hold_focus:
                self.imgSrc.set_hardware_autofocus_state(False) #turn off autofocus

        else:
            score=self.imgSrc.image_based_autofocus(chan=self.channel_settings.map_chan)
            print score

    def multiDacq(self,success,outdir,chrome_correction,autofocus_trigger,triggerflag,x,y,current_z,slice_index,frame_index=0,hold_focus = False):

        #print datetime.datetime.now().time()," starting multiDAcq, autofocus on"
        if not hold_focus:
            if self.imgSrc.has_hardware_autofocus():
                self.imgSrc.set_hardware_autofocus_state(True)
        #print datetime.datetime.now().time()," starting stage move"
        self.imgSrc.move_stage(x,y)
        if autofocus_trigger:
            self.software_autofocus(acquisition_boolean=True)
        stagexy = self.imgSrc.get_xy()
        wx.Yield()
        self.autofocus_loop(hold_focus,self.cfg['MosaicPlanner']['autofocus_wait'],self.cfg['MosaicPlanner']['autofocus_sleep'])
        if self.cfg['MosaicPlanner']['do_second_autofocus_wait']:
            self.autofocus_loop(hold_focus,self.cfg['MosaicPlanner']['second_autofocus_wait'],self.cfg['MosaicPlanner']['autofocus_sleep'])

        if (self.dmi is not None) & (self.cfg['LeicaDMI']['take_afc_image']):
            afc_image = self.dmi.get_AFC_image()
            self.dmi.set_AFC_hold(True)
        else:
            afc_image = None

        #print datetime.datetime.now().time()," starting multichannel acq"
        current_z = self.imgSrc.get_z()
        presentZ = current_z
        #print 'flag is,',self.zstack_settings.zstack_flag

        if self.zstack_settings.zstack_flag:
            furthest_distance = self.zstack_settings.zstack_delta * (self.zstack_settings.zstack_number-1)/2
            #furthest_distance =0
            zplanes_to_visit = [(current_z-furthest_distance) + i*self.zstack_settings.zstack_delta for i in range(self.zstack_settings.zstack_number)]

        else:
            zplanes_to_visit = [current_z]
        #print 'zplanes_to_visit : ',zplanes_to_visit

        # num_chan, chrom_correction = self.summarize_channel_settings()

        for k,ch in enumerate(self.channel_settings.channels):
            if self.channel_settings.usechannels[ch]:
                last_channel = ch

        def software_acquire(z=presentZ):
            # currZ=self.imgSrc.get_z()
            # presentZ = currZ
            for z_index, zplane in enumerate(zplanes_to_visit):
                for k,ch in enumerate(self.channel_settings.channels):
                    #print datetime.datetime.now().time()," start channel",ch, " zplane", zplane
                    prot_name=self.channel_settings.prot_names[ch]
                    path=os.path.join(outdir, prot_name)
                    if self.channel_settings.usechannels[ch]:
                        #ti = time.clock()*1000
                        #print time.clock(),'start'
                        if not hold_focus:
                            z = zplane + self.channel_settings.zoffsets[ch]
                            if not z == presentZ:
                                self.imgSrc.set_z(z)
                                presentZ = z
                        self.imgSrc.set_exposure(self.channel_settings.exposure_times[ch])
                        self.imgSrc.set_channel(ch)
                        #t2 = time.clock()*1000
                        #print time.clock(),t2-ti, 'ms to get to snap image from start'

                        data=self.imgSrc.snap_image()
                        #t3 = time.clock()*1000
                        #print time.clock(),t3-t2, 'ms to snap image'
                        if ch == self.cfg['ChannelSettings']['focusscore_chan']:
                            calcFocus = True
                        else:
                            calcFocus = False
                        if ch is not last_channel:
                            self.dataQueue.put((slice_index,frame_index, z_index, prot_name,path,data,ch,stagexy[0],stagexy[1],z,False,calcFocus,None))
                        else:
                            self.dataQueue.put((slice_index,frame_index, z_index, prot_name,path,data,ch,stagexy[0],stagexy[1],z,triggerflag,calcFocus,afc_image))

        def hardware_acquire(z=presentZ):
            # currZ=self.imgSrc.get_z()
            # presentZ = currZ
            for z_index, zplane in enumerate(zplanes_to_visit):
                z = zplane
                if not hold_focus:
                    if not z == presentZ:
                        self.imgSrc.set_z(z)
                        presentZ = z
                self.imgSrc.startHardwareSequence()
                for k,ch in enumerate(self.channel_settings.channels):
                    #print datetime.datetime.now().time()," start channel",ch, " zplane", zplane
                    prot_name=self.channel_settings.prot_names[ch]
                    path=os.path.join(outdir,prot_name)
                    if self.channel_settings.usechannels[ch]:
                        data = self.imgSrc.get_image()

                        if ch == self.cfg['ChannelSettings']['focusscore_chan']:
                            calcFocus = True
                        else:
                            calcFocus = False
                        if ch is not last_channel:
                            self.dataQueue.put((slice_index,frame_index, z_index, prot_name,path,data,ch,stagexy[0],stagexy[1],z,False,calcFocus,None))
                        else:
                            self.dataQueue.put((slice_index,frame_index, z_index, prot_name,path,data,ch,stagexy[0],stagexy[1],z,triggerflag,calcFocus,afc_image))


        if self.cfg['MosaicPlanner']['autofocus_toggle']:
            print 'toggle autofocus'
            self.imgSrc.set_hardware_autofocus_state(False,False)

        if (self.cfg['MosaicPlanner']['hardware_trigger'] == True) and (chrome_correction == False) and (success != False):
            hardware_acquire()
        else:
            software_acquire()

        if self.cfg['MosaicPlanner']['autofocus_toggle']:
            self.imgSrc.set_hardware_autofocus_state(True,True)
        if not hold_focus:
            self.imgSrc.set_z(current_z)
            if self.imgSrc.has_hardware_autofocus():
                self.imgSrc.set_hardware_autofocus_state(True)
        #self.imgSrc.set_hardware_autofocus_state(True)

    def ResetPiezo(self):
        do_stage_reset=self.cfg['StageResetSettings']['enableStageReset']
        if do_stage_reset:
            self.imgSrc.reset_piezo(self.cfg['StageResetSettings'])


    def summarize_stage_settings(self):
        do_stage_reset = self.cfg['StageResetSettings']['enableStageReset']
        comp_stage = self.cfg['StageResetSettings']['compensationStage']
        reset_stage = self.cfg['StageResetSettings']['resetStage']
        min_threshold = self.cfg['StageResetSettings']['minThreshold']
        max_threshold = self.cfg['StageResetSettings']['maxThreshold']
        reset_position = self.cfg['StageResetSettings']['resetPosition']
        invert_compensation = self.cfg['StageResetSettings']['invertCompensation']

        Stage_Settings_Summary = {'Reset_enabled?' : do_stage_reset,
                                  'Compensation Stage' : comp_stage,
                                  'Reset Stage' : reset_stage,
                                  'Reset Pos' : reset_position,
                                  'Min' : min_threshold,
                                  'Max' : max_threshold,
                                  'Invert Comp' : invert_compensation}

        return Stage_Settings_Summary

    def summarize_channel_settings(self):
        """ Gets number of active channels and total exposure time.
        """
        numchan = 0
        exposure_time = 0.0
        for ch in self.channel_settings.channels:
            if self.channel_settings.usechannels[ch]:
                numchan+=1
                exposure_time += self.channel_settings.exposure_times[ch]
        return numchan, exposure_time

    def load_channel_settings(self, settings):
        """ Loads channel settings from ChannelSettings object,
            a dict, or a file path.

            #Once I figure out which of these is most
                relevant i should eliminate the other
                options.

            args:
                settings (ChannelSettings, dict, str): settings to load.
        """
        if isinstance(settings, ChannelSettings):
            pass
        elif isinstance(settings, dict):
            settings = ChannelSettings(**settings)
        elif isinstance(settings, str):
            with open(settings, 'r') as f:
                settings_dict = yaml.load(f)
                settings = ChannelSettings(**settings_dict)
        else:
            raise NotImplementedError("Only dict, path or ChannelSettings for now.")
        self.channel_settings = settings
        # DO WE NEED TO SET EXPOSURES HERE?
        return self.channel_settings

    def load_directory_settings(self, settings=None):
        """ Loads directory settings from DirectorySettings object,
            a dict, or a file path.

            #Once I figure out which of these is most
                relevant i should eliminate the other
                options.

            args:
                settings (DirectorySettings, dict, str): settings to load.
        """
        if isinstance(settings, DirectorySettings):
            pass
        elif isinstance(settings, dict):
            settings = DirectorySettings(**settings)
        elif isinstance(settings, str):
            with open(settings, 'r') as f:
                settings_dict = yaml.load(f)
                settings = DirectorySettings(**settings_dict)
        elif settings is None:
            #load from config
            settings = DirectorySettings()
            settings.load_settings(self.cfg)
        else:
            raise NotImplementedError("Only dict, path or DirectorySettings for now.")
        self.directory_settings = settings
        print(settings.__dict__)
        # DO WE NEED TO SET EXPOSURES HERE?
        map_folder = settings.create_directory(self.cfg, "map")
        self.set_map_folder(map_folder)
        # pos_list_map#.json
        map_num = settings.Map_num
        parent_dir = os.path.dirname(map_folder)
        default_pos_list_path = os.path.join(parent_dir, "pos_list_map{}.json".format(map_num))
        self.set_position_file(default_pos_list_path)

        data_folder = settings.create_directory(self.cfg, "data")

        return self.directory_settings

    @property
    def map_folder(self):
        """ Returns the current GUI position list path
        """
        return self.parent.imgCollectDirPicker.GetPath()

    @map_folder.setter
    def map_folder(self, folder):
        # DW: put this into dir settings as well
        if not os.path.isdir(folder):
            os.makedirs(folder)
        self.parent.imgCollectDirPicker.SetPath(folder)

    def set_map_folder(self, folder):
        """ Sets the current map folder in the GUI.

            #DW: get rid of this?

            args:
                folder (str): the map folder which contains a bunch of images and their
                    text files.
        """
        self.map_folder = folder

    def load_map(self, folder=None):
        """ Loads the map at the specified folder.
                If it is not provided, we attempt to load the whatever folder
                was previous loaded.

            args:
                folder (Optional[None]): a map folder
        """
        if folder:
            self.map_folder = folder
        else:
            folder = self.map_folder
        self.on_load(folder)
        return folder

    @property
    def position_list_path(self):
        """ Returns the current GUI position list path.
        """
        return self.parent.array_filepicker.GetPath()

    @position_list_path.setter
    def position_list_path(self, path):
        self.parent.array_filepicker.SetPath(path)

    def set_position_file(self, position_file):
        """ Sets the current array position file in the GUI.

            args:
                position_file (str): file path to position list.
        """
        # do we need to check if the file exists?  I think not.
        self.position_list_path = position_file

    def load_position_list(self, position_file=""):
        """ Loads a specific position list file.
                If not provided, it will load the one currently specified in the
                GUI.
            args:
                position_file (Optional[str]): position file path (.json)
        """
        if position_file:
            self.set_position_file(position_file)
        self.parent.on_array_load()

    def save_position_list(self, path=""):
        """ Saves the position list to a specified path.

            args:
                path (str): path to save position list (.json)
        """
        if not path:
            path = self.position_list_path
        #I'm not sure what this transfromed stuff does but 
        # i'm keeping it until i know
        if self.parent.save_transformed.IsChecked():
            trans=self.parent.Transform
        else:
            trans=None
        self.posList.save_position_list_JSON(path,trans=trans)

    def get_current_acquisition_settings(self):
        """ Gets all the data required to re-create this acquisition.

            Returns:
                dict: all settings required to re-create this acquisition
        """
        dir_settings = self.directory_settings.__dict__
        return {
            "position_list_path": self.position_list_path,
            "map_folder": self.map_folder,
            "channel_settings": self.channel_settings.__dict__,
            "directory_settings": dir_settings,
            "datetime": str(datetime.datetime.now()),
            "micromanager_config": self.MM_config_file,
            "objective_height": self.getZPosition(),
            "autofocus_offset": self.imgSrc.get_autofocus_offset(),
        }

    def save_acquisition_settings(self, path):
        """ Saves the acquisition settings to a specified yaml path.

            Args:
                path (str): path to output file (.yaml)

            Returns:
                dict: the settings that were saved.
        """
        self.save_position_list()
        settings = self.get_current_acquisition_settings()
        import yaml  #DW should i move this import to top?
        with open(path, 'w') as f:
            yaml.dump(settings, f, default_flow_style=False)
        return settings

    def load_acquisition_settings(self, settings):
        """ Applies acquisition settings from a specified yaml path or
                pre-loaded dict.

            Args:
                path (str, dict): path to settings file (.yaml) or settings dict

            Returns:
                dict: the settings that were loaded.
        """
        if isinstance(settings, (str, unicode)):
            import yaml
            with open(settings, 'r') as f:
                settings = yaml.load(f)
        print(settings)
        self.load_map(settings['map_folder'])
        self.load_position_list(settings['position_list_path'])
        self.load_directory_settings(settings['directory_settings'])
        self.load_channel_settings(settings['channel_settings'])
        # load MM config?  probably shouldn't
        return settings

    def setup_complete(self, event=None):
        """ Callback for batman button (used to start acquisition)
        """
        settings = {
            "acquisition": self.get_current_acquisition_settings(),
        }
        print(settings)
        if self.interface:
            self.interface.publish(settings)
        # what else do?

    def clear_position_list(self):
        """ Clears the current position list.
        """
        self.posList.select_all()
        self.posList.delete_selected()
        self.subplot.clear()
        #self.canvas.clear()
        self.posone_plot.clear()
        self.postwo_plot.clear()

    def move_to_cassette(self, cassette_index=0):
        """ Moves to a specific cassette slot.

            Args:
                cassette_index (int): cassette slot to move to

            Returns:
                2-tuple: (x, y) position of target cassette
        """
        slot_positions = self.cfg['Stage_Settings']['slot_positions']
        try:
            pos = slot_positions[cassette_index]
        except IndexError:
            raise IndexError("No position for cassette index {} defined.".format(
                cassette_index))
        self.setStagePosition(*pos)
        return pos

    def move_to_oil_position(self, index=None):
        """ Moves to a specific oil position.  If None specified,
                moves to the closest.

            args:
                index (Optional[int]): index of target oil position.

            returns:
                2-tuple: (x,y) for chosen stage position
        """

        def dist2d(p0, p1):
            """ Distance between two 2d points. """
            x0, y0 = p0
            x1, y1 = p1
            return np.sqrt((x1-x0)**2 + (y1-y0)**2)

        def get_nearest(source, pos_list):
            """ Finds nearest point in position list to source position."""
            distances = [dist2d(source, pos) for pos in pos_list]
            val, i = min((val, i) for (i, val) in enumerate(distances))
            return pos_list[i]

        pos_list = self.cfg['Stage_Settings']['oiling_positions']
        if not pos_list:
            raise ValueError("No oiling positions configured.")
        if index is None:
            source = self.getStagePosition()
            pos = get_nearest(source, pos_list)
        else:
            pos = pos_list[index]

        self.setStagePosition(*pos)
        return pos

    def move_to_setup_height(self):
        """ Moves the objective to a configured height for starting mosaic
                plan setup.
        """
        height = self.cfg['Stage_Settings']['objective_setup_height']
        self.setZPosition(height)

    def unload_arduino(self):
        # DW: basically something about the arduino is fucking up
        #   and this could let me manually unload it
        self.imgSrc.mmc.unloadDevice("LaserArduino")

    def summarize_autofocus_settings(self):
        auto_sleep = self.cfg['Mosaic Planner']['autofocus_sleep']
        auto_wait = self.cfg['Mosaic Planner']['autofocus_wait']

        Autofocus_settings = {'Sleep' : auto_sleep,
                              'Wait' : auto_wait}

        return Autofocus_settings

    def move_safe_to_start(self):
        #step the stage back to the first position, position by position
        #so as to not lose the immersion oil
        (x,y)=self.imgSrc.get_xy()
        currpos=self.posList.get_position_nearest(x,y)

        #turn on autofocus
        self.imgSrc.set_hardware_autofocus_state(True)
        while currpos is not None:
            self.ResetPiezo()
            self.imgSrc.move_stage(currpos.x,currpos.y)
            currpos=self.posList.get_prev_pos(currpos)
            if currpos is not None:
                if not currpos.activated:
                    break
            wx.Yield()

    def setup_acquisition_progress_bar(self):
        hasFrameList = self.posList.slicePositions[0].frameList is not None
        numSections = len(self.posList.slicePositions)
        if hasFrameList:
            numFrames = len(self.posList.slicePositions[0].frameList.slicePositions)
        else:
            numFrames = 1
        maxProgress = numSections*numFrames

        self.acq_progress = ProgressDialog("Acquisition Progress",
                                           'Acquiring {} sectionts'.format(numSections),
                                           maxProgress)

        return numFrames,numSections

    def setup_map_progress_bar(self, img_folder):
        metafiles=[os.path.join(img_folder, f) for f in os.listdir(img_folder) if f.endswith('.txt') ]
        map_img_count = len(metafiles)
        self.map_progress = ProgressDialog('Map Loading',
                                           'Loading {} images'.format(map_img_count),
                                           map_img_count)

    def setup_objective_progress_bar(self, start, end):
        self.obj_progress = ProgressDialog('Objective Moving',
                                           'Moving from {} to {}'.format(start, end),
                                           abs(end-start))

    def get_remaining_frames(self):
        """ Gets number of frames remaining in the acquisition.
        """
        current_frame_count = self._frame_count
        
        total_sections = len(self.posList.slicePositions)
        if not total_sections:
            # nothing loaded yet
            return 0

        frames_per_section = len(self.posList.slicePositions[0].frameList.slicePositions)
        total_frames = total_sections * frames_per_section

        if not self._is_acquiring:
            return total_frames

        return total_frames - current_frame_count

    def get_remaining_time(self):
        """ Gets time remaining in the acquisition with the current settings.
        """
        _, exposure_time = self.summarize_channel_settings()
        remaining_frames = self.get_remaining_frames()
        stage_step = 200 #ms
        return (stage_step + exposure_time) / 1000.0 * remaining_frames

    def get_output_dir(self,directory_settings):
        assert(isinstance(directory_settings, DirectorySettings))
        #gets output directory for session

        cfg = self.cfg
        path = directory_settings.create_directory(cfg,kind='data')
        if path is not None:
            dlg=wx.DirDialog(self, message="Pick output directory", defaultPath=path)
            button_pressed = dlg.ShowModal()
            if button_pressed == wx.ID_CANCEL:
                wx.MessageBox("You didn't enter a save directory... \n Aborting acquisition")
                return None
            outdir = dlg.GetPath()
            dlg.Destroy()
            return outdir
        else:
            return None

    def make_channel_directories(self,outdir):
        #setup output directories
        for k,ch in enumerate(self.channel_settings.channels):
            if self.channel_settings.usechannels[ch]:
                thedir=os.path.join(outdir,self.channel_settings.prot_names[ch])
                if not os.path.isdir(thedir):
                    os.makedirs(thedir)


    # def show_summary_dialog(self):
    #     binning=self.imgSrc.get_binning()
    #     caption = "about to capture %d sections, binning is %dx%d, numchannel is %d"%(len(self.posList.slicePositions),binning,binning,numchan)
    #     dlg = wx.MessageDialog(self,message=caption, style = wx.OK|wx.CANCEL)
    #     button_pressed = dlg.ShowModal()
    #     if button_pressed == wx.ID_CANCEL:
    #         return False

    # def execute_imaging(self,pos_list,numFrames,numSections,channel_settings,chrome_correction,sample_information,mosaic_settings,zstack_settings,acquisition_settings,
    #                     stage_reset_settings,autofocus_settings):
    #     """ DW: This appears to be an old version of on_run_acq.  I don't think it is used and
    #             could probably be deleted...
    #     """

    #     assert(isinstance(zstack_settings, ZstackSettings))
    #     assert(isinstance(channel_settings, ChannelSettings))
    #     assert(isinstance(pos_list,PosList))
    #     assert(type(autofocus_settings == dict))
    #     assert(type(acquisition_settings == dict))
    #     outdir = self.outdirdict[sample_information.Ribbon_ID]

    #     binning = acquisition_settings['Binning']

    #     numFrames,numSections = self.setup_progress_bar()
    #     hold_focus = not (zstack_settings.zstack_flag or chrome_correction)

    #     # starting with cycling through positions
    #     goahead = True
    #     #loop over positions
    #     for i,pos in enumerate(pos_list.slicePositions):
    #         if pos.activated:
    #             if not goahead:
    #                 break
    #             if not self.imgSrc.get_hardware_autofocus_state():
    #                 print "autofocus not enabled when moving between sections.. "
    #                 goahead=False
    #                 break
    #             (goahead, skip) = self.progress.Update(i*numFrames,'section %d of %d'%(i,numSections-1))
    #             #turn on autofocus
    #             self.ResetPiezo()
    #             current_z = self.imgSrc.get_z()
    #             if pos.frameList is None:
    #                 self.multiDacq(outdir,chrome_correction,pos.x,pos.y,current_z,i,hold_focus=hold_focus)
    #             else:
    #                 for j,fpos in enumerate(pos.frameList.slicePositions):
    #                     if not goahead:
    #                         print("breaking out!")
    #                         break
    #                     if not self.imgSrc.get_hardware_autofocus_state():
    #                         print("autofocus no longer enabled while moving between frames.. quiting")
    #                         goahead = False
    #                         break
    #                     self.multiDacq(outdir,chrome_correction,fpos.x,fpos.y,current_z,i,j,hold_focus)
    #                     self.ResetPiezo()
    #                     (goahead, skip)=self.progress.Update((i*numFrames) + j+1,'section %d of %d, frame %d'%(i,numSections-1,j))

    #             wx.Yield()
    #     if not goahead:
    #         print("acquisition stopped prematurely")
    #         print("section %d"%(i))
    #         if pos.frameList is not None:
    #             print("frame %d"%(j))

    #     self.dataQueue.put(STOP_TOKEN)
    #     self.saveProcess.join()
    #     print("save process ended")
    #     self.progress.Destroy()
    #     #self.progress.Close()
    #     self.imgSrc.set_binning(2)
    #     if self.cfg['MosaicPlanner']['hardware_trigger']:
    #         self.imgSrc.stop_hardware_triggering()



    def slack_notify(self,message,notify=False):
        """ TODO: move this out of here, remove hard-coded scope names...
        """
        if self.slacker is not None:
            microscope = self.cfg['MosaicPlanner']['microscope_name']
            if 'Jarvis'in microscope:
                message="Ironman be aware: "+message
            if 'Rosie' in microscope:
                message="George!: "+message
            if 'Igor' in microscope:
                message="mmm Dr. Frankenstein...: "+message
            if notify:
                message=self.cfg['Slack']['notify_list']
            self.slacker.chat.post_message(self.cfg['Slack']['slack_room'],'{} says: {}'.format(microscope,message))

    def lookup_mountpoint(self, outdir):
        drive,tail = os.path.splitdrive(outdir)
        mountfile = os.path.join(drive,'mountpoint','mountpoint.json')
        with open(mountfile,'r') as fp:
            d=json.load(fp)
        return d['mountpoint']

    def get_initial_position(self,position):
        for i in range(len(position.frameList.slicePositions)):
            framepos = position.frameList.slicePositions[i]
            if framepos.initial_trigger == True:
                frameposx = framepos.x
                frameposy = framepos.y
                return [frameposx, frameposy]

            elif i == (len(position.frameList.slicePositions)-1):
                return None
            else:
                pass

    def move_to_xy_and_focus(self,x,y):
        """ Move to specific stage pos and initiate
            software autofocus.

        DW: changed name to reflect functionality a
            bit better.
        """
        self.imgSrc.move_stage(x,y)
        stg = self.imgSrc.mmc.stage
        self.imgSrc.mmc.waitForDevice(stg)
        # self.imgSrc.stop_hardware_triggering()
        self.software_autofocus(acquisition_boolean=True)
        # self.imgSrc.setup_hardware_triggering(channels,exp_times)

    def move_to_slice(self, slice_index=0):
        """ Moves to a specific slice (section) on the
            current ribbon.
        """
        slice_pos = self.posList.slicePositions[slice_index]
        pos = slice_pos.x, slice_pos.y
        self.setStagePosition(*pos)
        return pos

    def on_run_acq(self, outdir=None, event="none"):
        """ Main acquisition loop.
        """
        print("running")

        self.imgSrc.set_binning(1)
        binning=self.imgSrc.get_binning()
        numchan, _ = self.summarize_channel_settings()
        chrom_correction = False  # can we get rid of this?

        if not outdir:
            outdir = self.directory_settings.get_data_folder()

        self.make_channel_directories(outdir)

        self.write_session_metadata(outdir)

        self.move_safe_to_start()

        self.dataQueue = mp.Queue()
        self.messageQueue = mp.Queue()

        metadata_dictionary = {
        'channelname'    : self.channel_settings.prot_names,
        '(height,width)' : self.imgSrc.get_sensor_size(),
        'ScaleFactorX'   : self.imgSrc.get_pixel_size(),
        'ScaleFactorY'   : self.imgSrc.get_pixel_size(),
        'exp_time'       : self.channel_settings.exposure_times,
        }
        # DW: lets remove hard-coded SSH stuff
        #ssh_opts = dict(self.cfg['SSH'])
        #ssh_opts['mount_point']=self.lookup_mountpoint(outdir)
        self.saveProcess =  mp.Process(target=file_save_process,args=(self.dataQueue, self.messageQueue, metadata_dictionary))
        self.saveProcess.start()


        numFrames,numSections = self.setup_acquisition_progress_bar()

        hold_focus = not (self.zstack_settings.zstack_flag or chrom_correction)


        if self.cfg['MosaicPlanner']['hardware_trigger']:
            #iterates over channels/exposure times in appropriate order
            channels = [ch for ch in self.channel_settings.channels if self.channel_settings.usechannels[ch]]
            exp_times = [self.channel_settings.exposure_times[ch] for ch in self.channel_settings.channels if self.channel_settings.usechannels[ch]]
            print(channels)
            print (exp_times)
            success=self.imgSrc.setup_hardware_triggering(channels,exp_times)
        else:
            success = False

        goahead = True

        if not self.imgSrc.get_hardware_autofocus_state():
            self.slack_notify('HELP! lost autofocus on way to first position',notify=True)
            print('HELP! lost autofocus on way to first position')
            goahead=False


        #loop over positions
        self._is_acquiring = True
        for i,pos in enumerate(self.posList.slicePositions):
            if pos.activated:
                if not goahead:
                    break
                if not self.imgSrc.get_hardware_autofocus_state():
                    self.slack_notify('HELP! lost autofocus between sections',notify=True)
                    goahead=False
                    break
                (goahead, skip) = self.acq_progress.update(i*numFrames,'section %d of %d'%(i,numSections-1))
                #turn on autofocus
                self.ResetPiezo()
                current_z = self.imgSrc.get_z()
                if pos.frameList is None:
                    triggerflag = False
                    autofocus_trigger = False
                    self.multiDacq(success,outdir,chrom_correction,autofocus_trigger,triggerflag,pos.x,pos.y,current_z,i,hold_focus=hold_focus)
                else:

                    triggerflag = False
                    initial_position = self.get_initial_position(pos)
                    if initial_position is not None:
                        print('moving to initial position to focus')
                        initx = initial_position[0]
                        inity = initial_position[1]
                        self.move_to_xy_and_focus(initx,inity)

                    #move to initial position and focus function goes here
                    for j,fpos in enumerate(pos.frameList.slicePositions):
                        if j == (len(pos.frameList.slicePositions) - 1):
                            triggerflag = True

                        if not goahead:
                            print "breaking out!"
                            break
                        if not self.imgSrc.get_hardware_autofocus_state():
                            self.slack_notify('HELP! lost autofocus between frames',notify=True)
                            print("autofocus no longer enabled while moving between frames.. quiting")
                            goahead = False
                            break
                        if not self.messageQueue.empty():
                            token,message = self.messageQueue.get()
                            self.slack_notify('HELP! save process failed: %s'%message)
                            if (token == STOP_TOKEN):
                                goahead = False
                                break
                        if pos.frameList.slicePositions[j].activated:
                            autofocus_trigger = pos.frameList.slicePositions[j].autofocus_trigger
                            #print autofocus_trigger
                            self.multiDacq(success,outdir,chrom_correction,autofocus_trigger,triggerflag,fpos.x,fpos.y,current_z,i,j,hold_focus)
                        else:
                            # print 'moving on'
                            pass
                        self.ResetPiezo()
                        if i==(len(self.posList.slicePositions)-1):
                            if j == (len(pos.frameList.slicePositions) - 1):
                                self.slack_notify('Done Imaging!')
                        (goahead, skip)=self.acq_progress.update((i*numFrames) + j+1,'section %d of %d, frame %d'%(i,numSections-1,j))
                        #======================================================
                        if self.interface and self.interface.pause == True:
                            while self.interface.pause == True:
                                self._check_sock(True)
                                (goahead, skip)=self.acq_progress.update((i*numFrames) + j+1,'REMOTELY PAUSED -- section %d of %d, frame %d'%(i,numSections-1,j))
                                #time.sleep(0.1)
                                wx.Yield()
                        #======================================================
                        self._frame_count += 1

                wx.Yield()
        if not goahead:
            self.slack_notify('Imaging stopped prematurely')
            self.slack_notify('on section %d'%i)
            if pos.frameList is not None:
                self.slack_notify("frame %d"%(j))

            print("acquisition stopped prematurely")
            print("section %d"%(i))
            if pos.frameList is not None:
                print("frame %d"%(j))

        self.dataQueue.put(STOP_TOKEN)
        self.saveProcess.join()

        self.acq_progress.destroy()
        self.imgSrc.set_binning(2)
        if (self.cfg['MosaicPlanner']['hardware_trigger']):
            self.imgSrc.stop_hardware_triggering()

        self._is_acquiring = False
        self._frame_count = 0
        logging.info("Imaging Complete! Data saved to: {}".format(outdir))

    def edit_channels(self,event="none"):
        dlg = ChangeChannelSettings(None, -1, title = "Channel Settings", settings = self.channel_settings,style=wx.OK)
        ret=dlg.ShowModal()
        if ret == wx.ID_OK:
            self.channel_settings=dlg.GetSettings()
            self.channel_settings.save_settings(self.cfg)
            map_chan=self.channel_settings.map_chan
            self.imgSrc.set_channel(map_chan)
            self.imgSrc.set_exposure(self.channel_settings.exposure_times[map_chan])
            #print "should be changed" ##DW WAT

        dlg.Destroy()

    def on_live_mode(self,evt="none"):
        expTimes=LiveMode.launchLive(self.imgSrc,exposure_times=self.channel_settings.exposure_times)
        self.channel_settings.exposure_times=expTimes
        self.channel_settings.save_settings(self.cfg)
        #reset the current channel to the mapping channel, and it's exposure
        map_chan=self.channel_settings.map_chan
        self.imgSrc.set_channel(map_chan)
        self.imgSrc.set_exposure(self.channel_settings.exposure_times[map_chan])

    def edit_SIFT_settings(self, event="none"):
        dlg = ChangeSiftSettings(None, -1, title= "Edit SIFT Settings", settings = self.SiftSettings, style = wx.OK)
        ret=dlg.ShowModal()
        if ret == wx.ID_OK:
            self.SiftSettings = dlg.GetSettings()
            self.SiftSettings.save_settings(self.cfg)
        dlg.Destroy()

    def edit_corr_settings(self, event="none"):
        dlg = ChangeCorrSettings(None, -1, title= "Edit Corr Settings", settings = self.CorrSettings, style = wx.OK)
        ret=dlg.ShowModal()
        if ret == wx.ID_OK:
            self.CorrSettings = dlg.GetSettings()
            self.CorrSettings.save_settings(self.cfg)
        dlg.Destroy()

    def edit_MManager_config(self, event = "none"):

        fullpath=self.MM_config_file
        if fullpath is None:
            fullpath = ""

        (dir,file)=os.path.split(fullpath)
        dlg = wx.FileDialog(self,"select configuration file",dir,file,"*.cfg")

        dlg.ShowModal()
        self.MM_config_file = str(dlg.GetPath())
        self.cfg['MosaicPlanner']['MM_config_file'] = self.MM_config_file
        self.cfg.write()

        dlg.Destroy()

    def edit_Directory_settings(self,event="none"):
        dlg = ChangeDirectorySettings(None,-1,title = u"Enter Sample Information",style = wx.OK,settings=self.directory_settings)
        ret = dlg.ShowModal()
        if ret == wx.ID_OK:
            self.directory_settings = dlg.get_settings()
            self.directory_settings.save_settings(self.cfg)
        if ret == wx.ID_CANCEL:
            self.edit_Directory_settings()
        dlg.Destroy()


    def edit_Zstack_settings(self,event = "none"):
        dlg = ChangeZstackSettings(None, -1, title= "Edit Ztack Settings", settings = self.zstack_settings, style = wx.OK)
        ret=dlg.ShowModal()
        if ret == wx.ID_OK:
            self.zstack_settings = dlg.GetSettings()
            self.zstack_settings.save_settings(self.cfg)
        dlg.Destroy()

    def edit_focus_correction_plane(self, event=None):
        global win
        win = FocusCorrectionPlaneWindow(self.focusCorrectionList,self.imgSrc)
        win.show()

    def launch_MManager_browser(self, event=None):
        global win
        win = MMPropertyBrowser(self.imgSrc.mmc)
        win.show()

    def launch_retake(self,event=None):
        if self.retakeView is None:
            self.retakeView = RetakeView(self)
        self.retakeView.show()

    def launch_LeicaAFC(self,event=None):
        if self.LeicaAFCView is None:
            self.LeicaAFCView = LeicaAFCView(self.imgSrc,self.cfg['LeicaDMI']['port'])

    def launch_snap(self, event=None):
        if self.snapView is None:
            print 'Binning is', self.imgSrc.get_binning()
            self.snapView = SnapView(self.imgSrc,exposure_times=self.channel_settings.exposure_times)
            self.snapView.changedExposureTimes.connect(self.getSnapExposures)
        self.imgSrc.set_binning(1)
        self.snapView.show()

    def getSnapExposures(self, event=None):
        self.channel_settings.exposure_times = self.snapView.getExposureTimes()

    def launch_ASI(self, event=None):
         global win
         win = ASI_AutoFocus(self.imgSrc.mmc)
         win.show()

    def repaint_image(self, evt):
        """event handler used when the slider bar changes and you want to repaint the MosaicImage with a different color scale"""
        if not self.mosaicImage==None:
            self.mosaicImage.repaint()
            self.draw()

    def lasso_callback(self, verts):
        """callback function for handling the lasso event, called from on_release"""
        #select the points inside the vertices listed
        self.posList.select_points_inside(verts)
        #redraw the plot
        self.canvas.draw_idle()
        #release the widgetlock and remove the lasso
        self.canvas.widgetlock.release(self.lasso)
        self.lassoLock=False
        del self.lasso

    def on_key(self,evt):
        if (evt.inaxes == self.mosaicImage.axis):
            if (evt.key == 'a'):
                self.posList.select_all()
                self.draw()
            if (evt.key == 'd'):
                self.posList.delete_selected()

    def on_press(self, evt):
        """canvas mousedown handler
        """
        #on a left click
        if evt.button == 1:
            #if something hasn't locked the widget
            if self.canvas.widgetlock.locked():
                return
            #if the click is inside the axis
            if evt.inaxes is None:
                return
            #if we have a toolbar
            if (self.navtoolbar):
                #figure out which of the mutually exclusive toolbar buttons are active
                mode = self.navtoolbar.get_mode()
                #call the appropriate function
                if (evt.inaxes == self.mosaicImage.one_axis):
                    self.posList.pos1.setPosition(evt.xdata,evt.ydata)
                    self.mosaicImage.paintPointsOneTwo(self.posList.pos1.getPosition(),self.posList.pos2.getPosition())
                elif (evt.inaxes == self.mosaicImage.two_axis):
                    self.posList.pos2.setPosition(evt.xdata,evt.ydata)
                    self.mosaicImage.paintPointsOneTwo(self.posList.pos1.getPosition(),self.posList.pos2.getPosition())
                else:
                    if (mode == 'movehere'):
                        self.imgSrc.set_xy(evt.xdata,evt.ydata,self.imgSrc.use_focus_plane)
                    if (mode == 'selectone'):
                        self.posList.set_pos1_near(evt.xdata,evt.ydata)
                        if not (self.posList.pos2 == None):
                            self.mosaicImage.paintPointsOneTwo(self.posList.pos1.getPosition(),self.posList.pos2.getPosition())
                    if (mode == 'selecttwo'):
                        self.posList.set_pos2_near(evt.xdata,evt.ydata)
                        if not (self.posList.pos1 == None):
                            self.mosaicImage.paintPointsOneTwo(self.posList.pos1.getPosition(),self.posList.pos2.getPosition())
                    if (mode == 'selectnear'):
                        pos=self.posList.get_position_nearest(evt.xdata,evt.ydata)

                        if not evt.key=='shift':
                            self.posList.set_select_all(False)
                        pos.set_selected(True)
                    if (mode == 'toggleactivate'):
                        pos=self.posList.get_position_nearest(evt.xdata,evt.ydata)

                        if evt.key is None:
                            pos.set_activated((not pos.activated))
                        elif evt.key=='shift':

                            framepos = pos.frameList.get_position_nearest(evt.xdata,evt.ydata)

                            framepos.set_activated((not framepos.activated),'frame')

                        elif evt.key == 'r':

                            frameindex = pos.frameList.get_nearest_position_index(evt.xdata,evt.ydata)
                            for position in self.posList.slicePositions:
                                framepos = position.frameList.slicePositions[frameindex]
                                framepos.set_activated((not framepos.activated), 'frame')

                        elif evt.key == 't':
                            for position in self.posList.slicePositions:
                                for i in range(len(position.frameList.slicePositions)):
                                    framepos = position.frameList.slicePositions[i]
                                    framepos.set_activated((not framepos.activated),'frame')

                        elif evt.key == 'f':
                            framepos = pos.frameList.get_position_nearest(evt.xdata,evt.ydata)


                            framepos.set_autofocus_trigger((not framepos.autofocus_trigger))

                        elif evt.key == 'c':
                            frameindex = pos.frameList.get_nearest_position_index(evt.xdata,evt.ydata)
                            for position in self.posList.slicePositions:
                                framepos = position.frameList.slicePositions[frameindex]
                                framepos.set_autofocus_trigger((not framepos.autofocus_trigger))

                        elif evt.key == 'l':
                            frameindex = pos.frameList.get_nearest_position_index(evt.xdata,evt.ydata)
                            for i,frame in enumerate(pos.frameList.slicePositions):
                                if i != frameindex:
                                    frame.set_autofocus_trigger(False, 'Initial')
                                else:
                                    frame.set_autofocus_trigger((not frame.initial_trigger),'Initial')



                        elif evt.key == 'i':
                            frameindex = pos.frameList.get_nearest_position_index(evt.xdata,evt.ydata)
                            for position in self.posList.slicePositions:
                                for i in range(len(position.frameList.slicePositions)):
                                    if i != frameindex:
                                        framepos = position.frameList.slicePositions[i]
                                        framepos.set_autofocus_trigger(False,'Initial')
                                    else:
                                        framepos = position.frameList.slicePositions[i]
                                        framepos.set_autofocus_trigger((not framepos.initial_trigger),'Initial')
                                        #
                                        # else:
                                        #     framepos.set_autofocus_trigger(False,'Initial')







                    elif (mode == 'add'):
                        print ('add point at',evt.xdata,evt.ydata)
                        self.posList.add_position(evt.xdata,evt.ydata)
                        self.mosaicImage.imgCollection.add_covered_point(evt.xdata,evt.ydata)

                    elif (mode  == 'select' ):
                        self.lasso = MyLasso(evt.inaxes, (evt.xdata, evt.ydata), self.lasso_callback,linecolor='white')
                        self.lassoLock=True
                        self.canvas.widgetlock(self.lasso)
                    elif (mode == 'snappic' ):
                        (fw,fh)=self.mosaicImage.imgCollection.get_image_size_um()
                        for i in range(-1,2):
                            for j in range(-1,2):
                                self.mosaicImage.imgCollection.add_image_at(evt.xdata+(j*fw),evt.ydata+(i*fh))
                                self.draw()
                                self.on_crop_tool()
                                wx.Yield()
                    elif (mode == 'snaphere'):
                        self.mosaicImage.imgCollection.add_image_at(evt.xdata,evt.ydata)

                self.draw()

    def on_release(self, evt):
        """canvas mouseup handler
        """
        # Note: lasso_callback is not called on click without drag so we release
        #   the lock here to handle this case as well.
        if evt.button == 1:
            if self.lassoLock:
                self.canvas.widgetlock.release(self.lasso)
                self.lassoLock=False
        else:
            #this would be for handling right click release, and call up a popup menu, this is not implemented so it gives an error
            self.show_popup_menu((evt.x, self.canvas.GetSize()[1]-evt.y), None)

    def get_toolbar(self):
        """"return the toolbar, make one if neccessary"""
        if not self.navtoolbar:
            self.navtoolbar = MosaicToolbar(self.canvas)
            self.navtoolbar.Realize()
        return self.navtoolbar

    def on_slider_change(self, evt):
        """handler for when the maximum value slider changes"""
        if not self.mosaicImage==None:
            self.mosaicImage.set_maxval(self.get_toolbar().slider.GetValue())
            self.draw()

    def on_grid_tool(self, evt):
        """handler for when the grid tool is toggled"""
        #returns whether the toggle is True or False
        visible=self.navtoolbar.GetToolState(self.navtoolbar.ON_GRID)
        #make the frames grid visible/invisible accordingly
        self.posList.set_frames_visible(visible)
        self.draw()

    def on_delete_points(self,event="none"):
        """handlier for handling the Delete tool press"""
        self.posList.delete_selected()
        self.draw()

    def on_rotate_tool(self,evt):
        """handler for handling when the Rotate tool is toggled"""
        if self.navtoolbar.GetToolState(self.navtoolbar.ON_ROTATE):
            self.posList.rotate_boxes()
        else:
            self.posList.unrotate_boxes()
        self.draw()

    def on_step_tool(self,evt=""):
        """handler for when the step_tool is pressed"""
        #we call another steptool function so that the fast forward tool can use the same function
        goahead=self.step_tool()
        self.on_crop_tool()
        self.draw()

    def on_corr_tool(self,evt=""):
        """handler for when the corr_tool is pressed"""
        #we call another function so the step tool can use the same function
        passed=self.corr_tool()
        #inliers=self.sift_corr_tool(window=70)
        self.draw()

    def on_snap_tool(self,evt=""):
        #takes snap straight away
        img = self.mosaicImage.imgCollection.oh_snap()
        print(img.shape)
        print(img.dtype)
        if self.mosaicImage.imgCollection.imgCount == 1:
            self.on_crop_tool()
        self.draw()

    def on_home_tool(self):
        """handler which overrides the usual behavior of the home button, just resets the zoom on the main subplot for the mosaicImage"""
        self.mosaicImage.set_view_home()
        self.draw()

    def on_crop_tool(self,evt=""):
        self.mosaicImage.crop_to_images(evt)
        self.draw()

    def on_software_af_tool(self,evt=""):
        self.software_autofocus(buttonpress=True)

    def on_fine_tune_tool(self,evt=""):
        print "fine tune tool not yet implemented, should do something to make fine adjustments to current position list"
        #this is a list of positions which we forbid from being point 1, our anchor points
        badpositions = []
        badstreak=0
        if ((self.posList.pos1 != None) & (self.posList.pos2 != None)):
            #start with point 1 where it is, and make point 2 the next point
            #self.posList.set_pos2(self.posList.get_next_pos(self.posList.pos1))
            #we are going to loop through until point 2 reaches the end
            #while (self.posList.pos2 != None):
            if badstreak>2:
                return
            #adjust the position of point 2 using a fine scale alignment with a small search radius
            corrval=self.corr_tool()
            #each time through the loop we are going to move point 2 but not point 1, but after awhile
            #we expect the correlation to fall off, at which point we will move point 1 to be closer
            # so first lets try moving point 1 to be the closest point to pos2 that we have fixed (which hasn't been marked "bad")
            if (corrval<.3):
                #lets make point 1 the point just before this one which is still a "good one"
                newp1=self.posList.get_prev_pos(self.posList.pos2)
                #if its marked bad, lets try the one before it
                while (newp1 in badpositions):
                    newp1=self.posList.get_prev_pos(newp1)
                self.posList.set_pos1(newp1)
                #try again
                corrval2=self.corr_tool()
                if (corrval2<.3):
                    badstreak=badstreak+1
                    #if this fails a second time, lets assume that this point 2 is a messed up one and skip it
                    #we just want to make sure that we don't use it as a point 1 in the future
                    badpositions.append(self.posList.pos2)
            else:
                badstreak=0
            #select pos2 as the next point in line
            self.posList.set_pos2(self.posList.get_next_pos(self.posList.pos2))
            self.draw()

    #===========================================================================
    # def PreviewTool(self,evt):
    #    """handler for handling the make preview stack tool.... not fully implemented"""
    #    (h_um,w_um)=self.calcMosaicSize()
    #    mypf=pointFinder(self.positionarray,self.tif_filename,self.extent,self.originalfactor)
    #    mypf.make_preview_stack(w_um, h_um)
    #===========================================================================
    def on_redraw(self,evt=""):
        self.mosaicImage.paintPointsOneTwo((self.posList.pos1.x,self.posList.pos1.y),
                                           (self.posList.pos2.x,self.posList.pos2.y),
                                                               100)
        self.draw()

    def on_fastforward_tool(self,event):

        goahead=True
        numsections = 0

        ffprogress = wx.ProgressDialog("A progress box", "Time elapsed", 100 ,
        style=wx.PD_CAN_ABORT | wx.PD_ELAPSED_TIME  )

        #keep doing this till the step_tool says it shouldn't go forward anymore

        while (goahead):
            wx.Yield()
            goahead=self.step_tool()
            self.on_crop_tool()
            self.draw()
            numsections += 1
            if goahead:
                #check if the progress bar has been cancelled and update it
               (goahead, skip) = ffprogress.Update(numsections,'section %d'%(numsections))

        #call up a box and make a beep alerting the user for help
        wx.MessageBox('Fast Forward Aborted, Help me','Info')
        ffprogress.Destroy()

    def step_tool(self):
        """function for performing a step, assuming point1 and point2 have been selected

        keywords:
        window)size of the patch to cut out
        delta)size of shifts in +/- x,y to look for correlation
        skip)the number of positions in pixels to skip over when sampling shifts

        """
        newpos=self.posList.new_position_after_step()
        #if the new postiion was not created, or if it wasn't on the array stop and return False
        if newpos == None:
            return False
        #if not self.is_pos_on_array(newpos):
        #    return False
        #if things were fine, fine adjust the position
        #corrval=self.corr_tool(window,delta,skip)
        #return self.sift_corr_tool(window)
        return self.corr_tool()

    def sift_corr_tool(self,window=70):
        """function for performing the correction of moving point2 to match the image shown around point1

        keywords)
        window)radious of the patch to cut out in microns
        return inliers
        inliers is the number of inliers in the best transformation obtained by this operation

        """
        (dxy_um,inliers)=self.mosaicImage.align_by_sift((self.posList.pos1.x,self.posList.pos1.y),(self.posList.pos2.x,self.posList.pos2.y),window = window,SiftSettings=self.SiftSettings)
        (dx_um,dy_um)=dxy_um
        self.posList.pos2.shiftPosition(-dx_um,-dy_um)
        return len(inliers)>self.SiftSettings.inlier_thresh

    def corr_tool(self):
        """function for performing the correlation correction of two points, identified as point1 and point2

        keywords)
        window)size of the patch to cut out
        delta)size of shifts in +/- x,y to look for correlation
        skip)the number of positions in pixels to skip over when sampling shifts

        """

        (corrval,dxy_um)=self.mosaicImage.align_by_correlation((self.posList.pos1.x,self.posList.pos1.y),(self.posList.pos2.x,self.posList.pos2.y),CorrSettings=self.CorrSettings)

        (dx_um,dy_um)=dxy_um
        self.posList.pos2.shiftPosition(-dx_um,-dy_um)
        #self.draw()
        return corrval>self.CorrSettings.corr_thresh

    def do_shift(self,event):
        #pull out the current bounds
        #(minx,maxx)=self.subplot.get_xbound()
        (miny,maxy)=self.subplot.get_ybound()

        #make the jump a size dependant on the y extent of the bounds, and depending on whether you are holding down shift
        if event.ShiftDown():
            jump=(maxy-miny)/20
        else:
            jump=(maxy-miny)/100
        #initialize the jump to be zero
        dx=dy=0


        keycode=event.GetKeyCode()

        #if keycode in (wx.WXK_DELETE,wx.WXK_BACK,wx.WXK_NUMPAD_DELETE):
        #    self.posList.delete_selected()
        #    self.draw()
        #    return
        #handle arrow key presses
        if keycode == wx.WXK_DOWN:
            dy=-jump
        elif keycode == wx.WXK_UP:
            dy=jump
        elif keycode == wx.WXK_LEFT:
            dx=-jump
        elif keycode == wx.WXK_RIGHT:
            dx=jump
        #skip the event if not handled above
        else:
            event.Skip()
        #if we have a jump move accomplish it depending on whether you have relative_motion on/off
        if not (dx==0 and dy==0):
            if self.relative_motion:
                self.posList.shift_selected_curve(dx, dy)
            else:
                self.posList.shift_selected(dx,dy)
            self.draw()

    def do_angle_shift(self,event):
        keycode=event.GetKeyCode()
        jump=.01
        if event.ShiftDown():
            jump=10*jump
        if keycode == wx.WXK_LEFT:
            dtheta=-jump
        elif keycode == wx.WXK_RIGHT:
            dtheta=jump
        self.posList.rotate_selected(dtheta)
        self.draw()

    def toggle_sliceframe(self,event):
        keycode = event.GetKeyCode()
        return keycode

        #
        #
        #
        # else:
        #     pass #will just toggle that single frame index within that particular slice to turn off




    def on_key_press(self,event="none"):
        """function for handling key press events"""
        keycode=event.GetKeyCode()
        if event.AltDown():
            if keycode in [wx.WXK_LEFT,wx.WXK_RIGHT]:
                self.do_angle_shift(event)
        # elif event.ContolDown():
        #     self.toggle_sliceframe(event)
        else:
            self.do_shift(event)



    def software_autofocus(self, acquisition_boolean=False, buttonpress=False):
        """ Olga's autofocus routine.

        TODO: read through this and see if i can get rid of some of it.
        """
        if buttonpress:
            self.imgSrc.set_binning(1)
        print("software autofocus")
        if (acquisition_boolean) and (self.cfg['MosaicPlanner']['hardware_trigger']):
            self.imgSrc.stop_hardware_triggering()
        self.imgSrc.set_hardware_autofocus_state(False) #turn off autofocus
        ch = self.channel_settings.map_chan
        self.imgSrc.set_exposure(self.cfg['Software Autofocus']['focus_exp_time'])
        self.imgSrc.set_channel(ch)
        (height,width) = self.imgSrc.get_sensor_size()
        zstack_step = self.cfg['Software Autofocus']['stepsize'] #z step between images(microns)
        if acquisition_boolean:
            zstack_number = self.cfg['Software Autofocus']['acquisition']
        else:
            zstack_number = self.cfg['Software Autofocus']['nonacquisition'] #number of images to take
        print(zstack_step, zstack_number)
        stack = np.zeros((height,width,zstack_number))
        offsets = []
        current_z = self.imgSrc.get_z()
        print("current_z: ", current_z)
        print("autofocus offset: ", self.imgSrc.get_autofocus_offset())
        furthest_distance = zstack_step * (zstack_number-1)/2
        zplanes_to_visit = [(current_z-furthest_distance) + i*zstack_step for i in range(zstack_number)]
        print("z_planes:", zplanes_to_visit)

        for z_index, zplane in enumerate(zplanes_to_visit):
            self.imgSrc.set_z(zplane)
            stack[:,:,z_index]=self.imgSrc.snap_image()
            self.imgSrc.set_autofocus_offset(-1)
            time.sleep(2*self.cfg['MosaicPlanner']['autofocus_wait'])
            offsets.append(self.imgSrc.get_autofocus_offset())

        #calculate best z
        print("calculating focus")
        print("offsets: ", offsets)
        #using Laplacian
        score_med = np.zeros(zstack_number)
        score_std = np.zeros(zstack_number)
        for i in range(len(zplanes_to_visit)):
            score = cv2.Laplacian(stack[:,:,i],cv2.CV_16U, ksize = 5)
            score_med[i] = np.median(score)
            score_std[i] = np.std(score)
        zscore = (score_med - np.median(score_med))/np.median(score_std)
        select = np.ones(len(offsets))
        for i in range(len(offsets)-1):
            if offsets[i]>=offsets[i+1] or offsets[i]==0:
                select[i] = 0
        idx = np.nonzero(select)
        zscore = zscore[idx]
        offsets1 = np.array(offsets)
        offsets1 = offsets1[idx]
        par_init = np.max(zscore)-np.min(zscore), np.min(zscore), offsets1[np.argmax(zscore)],\
                   offsets1[int((zstack_number-1)/2)+1]-offsets1[int((zstack_number-1)/2)-1]
        def gauss_1d(x, amp, offset, x0, sigma_x):
            z = offset + amp*np.exp(-((x-x0)/sigma_x)**2)
            return z
        print("zscore", zscore)
        popt, pcov = opt.curve_fit(gauss_1d, offsets1, zscore, p0=par_init)
        best_offset = popt[2]
        print("best_offset: ", best_offset)
        self.imgSrc.set_autofocus_offset(best_offset) #reset autofocus offset
        time.sleep(2*self.cfg['MosaicPlanner']['autofocus_wait'])
        self.imgSrc.set_hardware_autofocus_state(True) #turn on autofocus
        self.imgSrc.set_exposure(self.channel_settings.exposure_times[ch])
        if (acquisition_boolean) and (self.cfg['MosaicPlanner']['hardware_trigger']):
            channels = [ch for ch in self.channel_settings.channels if self.channel_settings.usechannels[ch]]
            exp_times = [self.channel_settings.exposure_times[ch] for ch in self.channel_settings.channels if self.channel_settings.usechannels[ch]]
            self.imgSrc.setup_hardware_triggering(channels,exp_times)
        if buttonpress:
            self.imgSrc.set_binning(2)
        return best_offset

    def getStagePosition(self):
        stagePosition = self.imgSrc.get_xy()
        return stagePosition

    def setStagePosition(self, newXPos, newYPos):
        self.imgSrc.move_stage(newXPos, newYPos)

    def remoteSavePositionListJSON(self, trans=None):
        if self.cfg['MosaicPlanner']['default_arraypath']:
            jsonfilepath = self.cfg['MosaicPlanner']['default_arraypath']
        else:
            map_path = self.cfg['MosaicPlanner']['default_imagepath']
            pathlist = map_path.rsplit('\\',1)
            jsonfilepath = pathlist[0] + '\\' + pathlist[1] + '_%sx%sat%s.json' % (self.cfg['MosaicSettings']['mosaic_mx'],self.cfg['MosaicSettings']['mosaic_my'],
                                                                                   self.cfg['MosaicSettings']['mosaic_overlap'])

        if trans:
            self.posList.save_position_list_JSON(jsonfilepath,trans=self.Transform)
        else:
            self.posList.save_position_list_JSON(jsonfilepath,trans=None)
        self.posList.save_frame_list(jsonfilepath)

    def remoteLoadPositionListJSON(self, filename):
        self.posList.add_from_file_JSON(filename)

class ZVISelectFrame(wx.Frame):
    """class extending wx.Frame for highest level handling of GUI components
    
        This is the main frame that instantiates a "MosaicPannel" and configures it.  It also houses many
            configuration methods.
    
    """
    ID_RELATIVEMOTION = wx.NewId()
    ID_EDIT_CAMERA_SETTINGS = wx.NewId()
    ID_EDIT_SMARTSEM_SETTINGS = wx.NewId()
    ID_SORTPOINTS = wx.NewId()
    ID_SHOWNUMBERS = wx.NewId()
    ID_SAVETRANSFORM = wx.NewId()
    ID_EDITTRANSFORM = wx.NewId()
    ID_FLIPVERT = wx.NewId()
    #ID_FULLRES = wx.NewId()
    ID_SAVE_SETTINGS = wx.NewId()
    ID_EDIT_CHANNELS = wx.NewId()
    ID_EDIT_MM_CONFIG = wx.NewId()
    ID_EDIT_SIFT = wx.NewId()
    ID_MM_PROP_BROWSER = wx.NewId()
    ID_EDIT_CORR = wx.NewId()
    ID_EDIT_FOCUS_CORRECTION = wx.NewId()
    ID_USE_FOCUS_CORRECTION = wx.NewId()
    ID_TRANSPOSE_XY = wx.NewId()
    ID_EDIT_ZSTACK = wx.NewId()
    ID_ASIAUTOFOCUS = wx.NewId()
    ID_SNAPCONTROL = wx.NewId()
    ID_RETAKECONTROL = wx.NewId()
    ID_LEICAAFC = wx.NewId()
    ID_NEWMAP = wx.NewId()

    # ID_Alfred = wx.NewId()

    def __init__(self, parent, title):
        """default init function for a wx.Frame

        keywords:
        parent)parent window to associate it with
        title) title of the

        """
        #default metadata info and image file, remove for release
        #default_meta=""
        #default_image=""

        #recursively call old init function
        wx.Frame.__init__(self, parent, title=title, size=(1900,885),pos=(5,5))
        #self.cfg = wx.Config('settings')
        if not os.path.isfile(SETTINGS_FILE):
            from shutil import copyfile
            copyfile(DEFAULT_SETTINGS_FILE,SETTINGS_FILE)
        self.cfg = ConfigObj(SETTINGS_FILE,unrepr=True,configspec=SETTINGS_MODEL_FILE)
        vdt = Validator()
        self.cfg.validate(vdt,copy=True)
        #setup a mosaic panel
        self.mosaicCanvas=MosaicPanel(self,config=self.cfg)

        #setup menu
        menubar = wx.MenuBar()
        options = wx.Menu()
        transformMenu = wx.Menu()
        Platform_Menu = wx.Menu()
        Imaging_Menu = wx.Menu()

        #OPTIONS MENU
        self.relative_motion = options.Append(self.ID_RELATIVEMOTION, 'Relative motion?', 'Move points in the ribbon relative to the apparent curvature, else in absolution coordinates',kind=wx.ITEM_CHECK)
        self.sort_points = options.Append(self.ID_SORTPOINTS,'Sort positions?','Should the program automatically sort the positions by their X coordinate from right to left?',kind=wx.ITEM_CHECK)
        self.show_numbers = options.Append(self.ID_SHOWNUMBERS,'Show numbers?','Display a number next to each position to show the ordering',kind=wx.ITEM_CHECK)
        self.flipvert = options.Append(self.ID_FLIPVERT,'Flip Image Vertically?','Display the image flipped vertically relative to the way it was meant to be displayed',kind=wx.ITEM_CHECK)
        #self.fullResOpt = options.Append(self.ID_FULLRES,'Load full resolution (speed vs memory)','Rather than loading a 10x downsampled ',kind=wx.ITEM_CHECK)
        self.saveSettings = options.Append(self.ID_SAVE_SETTINGS,'Save Settings','Saves current configuration settings to config file that will be loaded automatically',kind=wx.ITEM_NORMAL)
        self.transpose_xy = options.Append(self.ID_TRANSPOSE_XY,'Transpose XY','Flips the x,y display so the vertical ribbons run horizontally',kind=wx.ITEM_CHECK)


        #options.Check(self.ID_FULLRES,self.cfg.ReadBool('fullres',False))

        self.edit_transform_option = options.Append(self.ID_EDIT_CAMERA_SETTINGS,'Edit Camera Properties...','Edit the size of the camera chip and the pixel size',kind=wx.ITEM_NORMAL)

        #SETUP THE CALLBACKS
        self.Bind(wx.EVT_MENU, self.save_settings, id=self.ID_SAVE_SETTINGS)
        self.Bind(wx.EVT_MENU, self.toggle_relative_motion, id=self.ID_RELATIVEMOTION)
        self.Bind(wx.EVT_MENU, self.toggle_sort_option, id=self.ID_SORTPOINTS)
        self.Bind(wx.EVT_MENU, self.toggle_show_numbers,id=self.ID_SHOWNUMBERS)
        self.Bind(wx.EVT_MENU, self.edit_camera_settings, id=self.ID_EDIT_CAMERA_SETTINGS)
        self.Bind(wx.EVT_MENU, self.toggle_transpose_xy, id = self.ID_TRANSPOSE_XY)


        #SET THE INTIAL SETTINGS
        options.Check(self.ID_RELATIVEMOTION,self.cfg['MosaicPlanner']['relativemotion'])
        options.Check(self.ID_SORTPOINTS,True)
        options.Check(self.ID_SHOWNUMBERS,False)
        options.Check(self.ID_FLIPVERT,self.cfg['MosaicPlanner']['flipvert'])
        options.Check(self.ID_TRANSPOSE_XY,self.cfg['MosaicPlanner']['transposexy'])
        self.toggle_transpose_xy()
        #TRANSFORM MENU
        self.save_transformed = transformMenu.Append(self.ID_SAVETRANSFORM,'Save Transformed?',\
        'Rather than save the coordinates in the original space, save a transformed set of coordinates according to transform configured in set_transform...',kind=wx.ITEM_CHECK)
        transformMenu.Check(self.ID_SAVETRANSFORM,self.cfg['MosaicPlanner']['savetransform'])

        self.edit_camera_settings = transformMenu.Append(self.ID_EDITTRANSFORM,'Edit Transform...',\
        'Edit the transform used to save transformed coordinates, by setting corresponding points and fitting a model',kind=wx.ITEM_NORMAL)

        self.Bind(wx.EVT_MENU, self.edit_transform, id=self.ID_EDITTRANSFORM)
        self.Transform = Transform()
        self.Transform.load_settings(self.cfg)

        #PLATFORM MENU
        self.edit_smartsem_settings = Platform_Menu.Append(self.ID_EDIT_SMARTSEM_SETTINGS,'Edit SmartSEMSettings',\
        'Edit the settings used to set the magnification, rotation,tilt, Z position, and working distance of SEM software in position list',kind=wx.ITEM_NORMAL)
        self.Bind(wx.EVT_MENU, self.edit_smart_SEM_settings, id=self.ID_EDIT_SMARTSEM_SETTINGS)

        #IMAGING SETTINGS MENU
        self.edit_micromanager_config = Imaging_Menu.Append(self.ID_EDIT_MM_CONFIG,'Set MicroManager Configuration',kind=wx.ITEM_NORMAL)
        self.edit_zstack_settings = Imaging_Menu.Append(self.ID_EDIT_ZSTACK,'Edit Zstack settings', kind = wx.ITEM_NORMAL)
        self.edit_channels = Imaging_Menu.Append(self.ID_EDIT_CHANNELS,'Edit Channels',kind=wx.ITEM_NORMAL)
        self.edit_SIFT_settings = Imaging_Menu.Append(self.ID_EDIT_SIFT, 'Edit SIFT settings',kind=wx.ITEM_NORMAL)
        self.edit_CORR_settings = Imaging_Menu.Append(self.ID_EDIT_CORR,'Edit corr_tool settings',kind=wx.ITEM_NORMAL)
        self.launch_MM_PropBrowser = Imaging_Menu.Append(self.ID_MM_PROP_BROWSER,'Open MicroManager Property Browser',kind = wx.ITEM_NORMAL)
        self.focus_correction_plane = Imaging_Menu.Append(self.ID_EDIT_FOCUS_CORRECTION,'Edit Focus Correction Plane',kind = wx.ITEM_NORMAL)
        self.use_focus_correction = Imaging_Menu.Append(self.ID_USE_FOCUS_CORRECTION,'Use Focus Correction?','Use Focus Correction For Mapping',kind=wx.ITEM_CHECK)
        self.launch_ASIControl = Imaging_Menu.Append(self.ID_ASIAUTOFOCUS, 'Allen ASI AutoFocus Control', kind= wx.ITEM_NORMAL)
        self.launch_Snap = Imaging_Menu.Append(self.ID_SNAPCONTROL,'Snap single channel images',kind = wx.ITEM_NORMAL)
        self.launch_Retake = Imaging_Menu.Append(self.ID_RETAKECONTROL,'Retake dialog',kind = wx.ITEM_NORMAL)
        # self.new_map = Imaging_Menu.Append(self.ID_NEWMAP,'Launch New Map', kind= wx.Button)
        if len(self.cfg['LeicaDMI']['port'])>0:
            self.launch_Leica = Imaging_Menu.Append(self.ID_LEICAAFC,'Leica AFC dialog',kind= wx.ITEM_NORMAL)

        self.Bind(wx.EVT_MENU, self.toggle_use_focus_correction,id=self.ID_USE_FOCUS_CORRECTION)
        self.Bind(wx.EVT_MENU, self.mosaicCanvas.edit_Zstack_settings,id=self.ID_EDIT_ZSTACK)
        self.Bind(wx.EVT_MENU, self.mosaicCanvas.edit_MManager_config, id = self.ID_EDIT_MM_CONFIG)
        self.Bind(wx.EVT_MENU, self.mosaicCanvas.edit_channels, id = self.ID_EDIT_CHANNELS)
        self.Bind(wx.EVT_MENU, self.mosaicCanvas.edit_SIFT_settings, id = self.ID_EDIT_SIFT)
        self.Bind(wx.EVT_MENU, self.mosaicCanvas.edit_corr_settings, id = self.ID_EDIT_CORR)
        self.Bind(wx.EVT_MENU, self.mosaicCanvas.launch_MManager_browser, id = self.ID_MM_PROP_BROWSER)
        self.Bind(wx.EVT_MENU, self.mosaicCanvas.edit_focus_correction_plane, id = self.ID_EDIT_FOCUS_CORRECTION)
        self.Bind(wx.EVT_MENU, self.mosaicCanvas.launch_ASI,id = self.ID_ASIAUTOFOCUS)
        self.Bind(wx.EVT_MENU, self.mosaicCanvas.launch_snap,id = self.ID_SNAPCONTROL)
        self.Bind(wx.EVT_MENU, self.mosaicCanvas.launch_retake,id = self.ID_RETAKECONTROL)
        self.Bind(wx.EVT_MENU, self.mosaicCanvas.launch_LeicaAFC, id= self.ID_LEICAAFC)
        # self.Bind(wx.EVT_BUTTON, self.on_new_map(), id = self.ID_NEWMAP)


        Imaging_Menu.Check(self.ID_USE_FOCUS_CORRECTION,self.cfg['MosaicPlanner']['use_focus_correction'])

        menubar.Append(options, '&Options')
        menubar.Append(transformMenu,'&Transform')
        menubar.Append(Platform_Menu,'&Platform Options')
        menubar.Append(Imaging_Menu,'&Imaging Settings')
        self.SetMenuBar(menubar)

        #setup a file picker for the metadata selector
        #self.meta_label=wx.StaticText(self,id=wx.ID_ANY,label="metadata file")
        #self.meta_filepicker=wx.FilePickerCtrl(self,message='Select a metadata file',\
        #path="",name='metadataFilePickerCtrl1',\
        #style=wx.FLP_USE_TEXTCTRL, size=wx.Size(300,20),wildcard='*.*')
        #self.meta_filepicker.SetPath(self.cfg.Read('default_metadatapath',""))
        #self.meta_formatBox=wx.ComboBox(self,id=wx.ID_ANY,value='ZeissXML',\
        #size=wx.DefaultSize,choices=['ZVI','ZeissXML','SimpleCSV','ZeissCZI'], name='File Format For Meta Data')
        #self.meta_formatBox.SetEditable(False)
        #self.meta_load_button=wx.Button(self,id=wx.ID_ANY,label="Load",name="metadata load")
        #self.meta_enter_button=wx.Button(self,id=wx.ID_ANY,label="Edit",name="manual meta")

        #define the image file picker components
        self.imgCollectLabel=wx.StaticText(self,id=wx.ID_ANY,label="image collection directory")
        self.imgCollectDirPicker=wx.DirPickerCtrl(self,message='Select a directory to store images',\
        path="",name='imgCollectPickerCtrl1',\
        style=wx.FLP_USE_TEXTCTRL, size=wx.Size(300,20))
        self.imgCollectDirPicker.SetPath(self.cfg['MosaicPlanner']['default_imagepath'])
        self.imgCollect_load_button=wx.Button(self,id=wx.ID_ANY,label="Load",name="imgCollect load")
        self.new_map_button = wx.Button(self,id=wx.ID_ANY, label = "New Map", name="newmap button")
        self.Bind(wx.EVT_BUTTON,self.start_newmap,self.new_map_button)

        #wire up the button to the "on_load" button
        self.Bind(wx.EVT_BUTTON, self.on_image_collect_load,self.imgCollect_load_button)
        #self.Bind(wx.EVT_BUTTON, self.OnMetaLoad,self.meta_load_button)
        #self.Bind(wx.EVT_BUTTON, self.OnEditImageMetadata,self.meta_enter_button)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        #define the array picker components
        self.array_label=wx.StaticText(self,id=wx.ID_ANY,label="array file")
        self.array_filepicker=wx.FilePickerCtrl(self,message='Select an array file',\
        path="",name='arrayFilePickerCtrl1',\
        style=wx.FLP_USE_TEXTCTRL, size=wx.Size(300,20),wildcard='*.*')
        self.array_filepicker.SetPath(self.cfg['MosaicPlanner']['default_arraypath'])

        self.array_load_button=wx.Button(self,id=wx.ID_ANY,label="Load",name="load button")
        self.array_formatBox=wx.ComboBox(self,id=wx.ID_ANY,value='JSON',\
        size=wx.DefaultSize,choices=['uManager','AxioVision','SmartSEM','OMX','ZEN','JSON'], name='File Format For Position List')
        self.array_formatBox.SetEditable(False)
        self.array_save_button=wx.Button(self,id=wx.ID_ANY,label="Save",name="save button")
        self.array_saveframes_button=wx.Button(self,id=wx.ID_ANY,label="Save Frames",name="save-frames button")

        #wire up the button to the "on_load" button
        self.Bind(wx.EVT_BUTTON, self.on_array_load,self.array_load_button)
        self.Bind(wx.EVT_BUTTON, self.on_array_save,self.array_save_button)
        self.Bind(wx.EVT_BUTTON, self.on_array_save_frames,self.array_saveframes_button)

        #define a horizontal sizer for them and place the file picker components in there
        #self.meta_filepickersizer=wx.BoxSizer(wx.HORIZONTAL)
        #self.meta_filepickersizer.Add(self.meta_label,0,wx.EXPAND)
        #self.meta_filepickersizer.Add(self.meta_filepicker,1,wx.EXPAND)
        #self.meta_filepickersizer.Add(wx.StaticText(self,id=wx.ID_ANY,label="Metadata Format:"))
        #self.meta_filepickersizer.Add(self.meta_formatBox,0,wx.EXPAND)
        #self.meta_filepickersizer.Add(self.meta_load_button,0,wx.EXPAND)
        #self.meta_filepickersizer.Add(self.meta_enter_button,0,wx.EXPAND)

        #define a horizontal sizer for them and place the file picker components in there
        self.imgCollect_filepickersizer=wx.BoxSizer(wx.HORIZONTAL)
        self.imgCollect_filepickersizer.Add(self.imgCollectLabel,0,wx.EXPAND)
        self.imgCollect_filepickersizer.Add(self.imgCollectDirPicker,1,wx.EXPAND)
        self.imgCollect_filepickersizer.Add(self.imgCollect_load_button,0,wx.EXPAND)
        self.imgCollect_filepickersizer.Add(self.new_map_button,0,wx.EXPAND)

        #define a horizontal sizer for them and place the file picker components in there
        self.array_filepickersizer=wx.BoxSizer(wx.HORIZONTAL)
        self.array_filepickersizer.Add(self.array_label,0,wx.EXPAND)
        self.array_filepickersizer.Add(self.array_filepicker,1,wx.EXPAND)
        self.array_filepickersizer.Add(wx.StaticText(self,id=wx.ID_ANY,label="Format:"))
        self.array_filepickersizer.Add(self.array_formatBox,0,wx.EXPAND)
        self.array_filepickersizer.Add(self.array_load_button,0,wx.EXPAND)
        self.array_filepickersizer.Add(self.array_save_button,0,wx.EXPAND)
        self.array_filepickersizer.Add(self.array_saveframes_button,0,wx.EXPAND)

        #define the overall vertical sizer for the frame
        self.sizer = wx.BoxSizer(wx.VERTICAL)
        #place the filepickersizer into the vertical arrangement
        self.sizer.Add(self.imgCollect_filepickersizer,0,wx.EXPAND)
        #self.sizer.Add(self.meta_filepickersizer,0,wx.EXPAND)
        self.sizer.Add(self.array_filepickersizer,0,wx.EXPAND)
        self.sizer.Add(self.mosaicCanvas.get_toolbar(), 0, wx.LEFT | wx.EXPAND)
        self.sizer.Add(self.mosaicCanvas, 0, wx.EXPAND)

        #self.poslist_set=False
        #set the overall sizer and autofit everything
        self.SetSizer(self.sizer)
        self.SetAutoLayout(1)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key_press)

        #self.sizer.Fit(self)
        self.Show(True)

        self.SmartSEMSettings=SmartSEMSettings()
        self.app = QtGui.QApplication([])


        #self.app.exec_()

        #self.OnImageLoad()
        #self.on_array_load()
        #self.mosaicCanvas.draw()

    def start_newmap(self,evt=None):
        self.mosaicCanvas.What_toMap()
        self.imgCollectDirPicker.SetPath(self.cfg['MosaicPlanner']['default_imagepath'])
        self.array_filepicker.SetPath(self.cfg['MosaicPlanner']['default_arraypath'])

    def toggle_transpose_xy(self,evt=None):
        print "toggle called",self.transpose_xy.IsChecked()

        self.mosaicCanvas.imgSrc.transpose_xy = self.transpose_xy.IsChecked()


    def save_settings(self,event="none"):


        self.Transform.save_settings(self.cfg)

        #save the menu options
        self.cfg['MosaicPlanner']['relativemotion']=self.relative_motion.IsChecked()
        #self.cfg.WriteBool('flipvert',self.flipvert.IsChecked())
        #self.cfg.WriteBool('fullres',self.fullResOpt.IsChecked())
        self.cfg['MosaicPlanner']['savetransform']=self.save_transformed.IsChecked()
        self.cfg['MosaicPlanner']['transposexy']=self.transpose_xy.IsChecked()
        #save the camera settings
        self.mosaicCanvas.posList.camera_settings.save_settings(self.cfg)

        #save the mosaic options
        self.mosaicCanvas.posList.mosaic_settings.save_settings(self.cfg)

        #save the SEMSettings
        self.SmartSEMSettings.save_settings(self.cfg)

        self.cfg['MosaicPlanner']['default_imagepath']=self.imgCollectDirPicker.GetPath()

        self.cfg['MosaicPlanner']['default_arraypath']=self.array_filepicker.GetPath()

        focal_pos_lis_string = self.mosaicCanvas.focusCorrectionList.to_json()
        #jsonpickle.encode(self.mosaicPanel.focusCorrectionList)
        self.cfg['MosaicPlanner']["focal_pos_list_pickle"]=focal_pos_lis_string
        self.cfg.write()
        #with open(SETTINGS_FILE,'wb') as configfile:
        #    self.cfg.write(configfile)

    def on_key_press(self,event="none"):
        """forward the key press event to the mosaicCanvas handler"""
        mpos=wx.GetMousePosition()
        mcrect=self.mosaicCanvas.GetScreenRect()
        if mcrect.Contains(mpos):
            self.mosaicCanvas.on_key_press(event)
        else:
            event.Skip()

    def on_array_load(self,event="none"):
        """event handler for the array load button"""
        # DW: If they've loaded a json file, then lets do that regardless of the array
        #   type box.
        # 
        array_file_path = self.array_filepicker.GetPath()
        if array_file_path.lower().endswith(".json"):
            self.mosaicCanvas.posList.add_from_file_JSON(array_file_path)

        # Might as well still allow old method
        elif self.array_formatBox.GetValue()=='AxioVision':
            self.mosaicCanvas.posList.add_from_file(array_file_path)
        elif self.array_formatBox.GetValue()=='OMX':
            raise NotImplementedError("No OMX yet.")
        elif self.array_formatBox.GetValue()=='SmartSEM':
            SEMsetting=self.mosaicCanvas.posList.add_from_file_SmartSEM(array_file_path)
            self.SmartSEMSettings=SEMsetting
        elif self.array_formatBox.GetValue()=='ZEN':
            self.mosaicCanvas.posList.add_from_file_ZEN(array_file_path)
        elif self.array_formatBox.GetValue()=='JSON':
            self.mosaicCanvas.posList.add_from_file_JSON(array_file_path)

        self.mosaicCanvas.navtoolbar.set_mosaic_parameters(self.mosaicCanvas.posList.mosaic_settings)
        self.mosaicCanvas.draw()

        logging.info("Loaded array file @ {}".format(array_file_path))


    def on_array_save(self,event):
        """event handler for the array save button"""
        if self.save_transformed.IsChecked():
            trans=self.Transform
        else:
            trans=None
        if self.array_formatBox.GetValue()=='AxioVision':
                self.mosaicCanvas.posList.save_position_list(self.array_filepicker.GetPath(),trans=trans)
        elif self.array_formatBox.GetValue()=='OMX':
                self.mosaicCanvas.posList.save_position_list_OMX(self.array_filepicker.GetPath(),trans=trans);
        elif self.array_formatBox.GetValue()=='SmartSEM':
                self.mosaicCanvas.posList.save_position_list_SmartSEM(self.array_filepicker.GetPath(),SEMS=self.SmartSEMSettings,trans=trans)
        elif self.array_formatBox.GetValue()=='ZEN':
                self.mosaicCanvas.posList.save_position_list_ZENczsh(self.array_filepicker.GetPath(),trans=trans,planePoints=self.planePoints)
        elif self.array_formatBox.GetValue()=='uManager':
                self.mosaicCanvas.posList.save_position_list_uM(self.array_filepicker.GetPath(),trans=trans)
        elif self.array_formatBox.GetValue()=='JSON':
                self.mosaicCanvas.posList.save_position_list_JSON(self.array_filepicker.GetPath(),trans=trans)
        
        if self.mosaicCanvas.cfg['MosaicPlanner']['frame_state_save']:
            self.mosaicCanvas.posList.on_save_frame_state_table(self.array_filepicker.GetPath())

    def on_image_collect_load(self,event):
        path=self.imgCollectDirPicker.GetPath()
        self.mosaicCanvas.on_load(path)

    def on_array_save_frames(self,event):
        if self.array_formatBox.GetValue()=='AxioVision':
            if self.save_transformed.IsChecked():
                self.mosaicCanvas.posList.save_frame_list(self.array_filepicker.GetPath(),trans=self.Transform)
            else:
                self.mosaicCanvas.posList.save_frame_list(self.array_filepicker.GetPath())
        elif self.array_formatBox.GetValue()=='OMX':
            if self.save_transformed.IsChecked():
                self.mosaicCanvas.posList.save_frame_list_OMX(self.array_filepicker.GetPath(),trans=self.Transform);
            else:
                self.mosaicCanvas.posList.save_frame_list_OMX(self.array_filepicker.GetPath(),trans=None);
        elif self.array_formatBox.GetValue()=='SmartSEM':
            if self.save_transformed.IsChecked():
                self.mosaicCanvas.posList.save_frame_list_SmartSEM(self.array_filepicker.GetPath(),SEMS=self.SmartSEMSettings,trans=self.Transform)
            else:
                self.mosaicCanvas.posList.save_frame_list_SmartSEM(self.array_filepicker.GetPath(),SEMS=self.SmartSEMSettings,trans=None)
        elif self.array_formatBox.GetValue()=='JSON': #MultiRibbons
            print "not yet implement"

    def toggle_relative_motion(self,event):
        """event handler for handling the toggling of the relative motion"""
        if self.relative_motion.IsChecked():
            self.mosaicCanvas.relative_motion=(True)
        else:
            self.mosaicCanvas.relative_motion=(False)

    def toggle_sort_option(self,event):
        """event handler for handling the toggling of the relative motion"""
        if self.sort_points.IsChecked():
            self.mosaicCanvas.posList.dosort=(True)
        else:
            self.mosaicCanvas.posList.dosort=(False)

    def toggle_use_focus_correction(self,event):
        """event handler for handling the toggling of using focus correction plane"""
        if self.use_focus_correction.IsChecked():
            "print use focus correction"
            self.mosaicCanvas.imgSrc.use_focus_plane = True
        else:
            "print do not use focus correction"
            self.mosaicCanvas.imgSrc.use_focus_plane = False

    def toggle_show_numbers(self,event):
        if self.show_numbers.IsChecked():
            self.mosaicCanvas.posList.setNumberVisibility(True)
        else:
            self.mosaicCanvas.posList.setNumberVisibility(False)
        self.mosaicCanvas.draw()

    def edit_camera_settings(self,event):
        """event handler for clicking the camera setting menu button"""
        dlg = ChangeCameraSettings(None, -1,
                                   title="Camera Settings",
                                   settings=self.mosaicCanvas.camera_settings)
        dlg.ShowModal()
        #del self.posList.camera_settings
        #passes the settings to the position list
        self.mosaicCanvas.camera_settings=dlg.GetSettings()
        self.mosaicCanvas.posList.set_camera_settings(dlg.GetSettings())
        dlg.Destroy()

    def edit_smart_SEM_settings(self,event):
        dlg = ChangeSEMSettings(None, -1,
                                   title="Smart SEM Settings",
                                   settings=self.SmartSEMSettings)
        dlg.ShowModal()
        del self.SmartSEMSettings
        #passes the settings to the position list
        self.SmartSEMSettings=dlg.GetSettings()
        dlg.Destroy()

    def edit_transform(self,event):
        """event handler for clicking the edit transform menu button"""
        dlg = ChangeTransform(None, -1,title="Adjust Transform")
        dlg.ShowModal()
        #passes the settings to the position list
        #(pts_from,pts_to,transformType,flipVert,flipHoriz)=dlg.GetTransformInfo()
        #print transformType

        self.Transform=dlg.getTransform()
        #for index,pt in enumerate(pts_from):
        #    (xp,yp)=self.Transform.transform(pt.x,pt.y)
        #    print("%5.5f,%5.5f -> %5.5f,%5.5f (%5.5f, %5.5f)"%(pt.x,pt.y,xp,yp,pts_to[index].x,pts_to[index].y))
        dlg.Destroy()

    def on_close(self,event):
        print("closing")

        self.mosaicCanvas.handle_close()
        self.Destroy()

if __name__ == '__main__':
    #dirname=sys.argv[1]
    #print dirname
    faulthandler.enable()
    app = wx.App(False)
    # Create a new app, don't redirect stdout/stderr to a window.
    frame = ZVISelectFrame(None,"Mosaic Planner")
    # A Frame is a top-level window.
    app.MainLoop()
    QtGui.QApplication.quit()

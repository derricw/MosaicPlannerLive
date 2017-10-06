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
"""
remote.py

Remote Interface for Mosaic Planner.

Here we expose any Mosaic Planner functionality that we'd like to be able to access from other
    software.  Any function or attribute added to RemoteInterface will be automatically callable
    using:

    >>> from zro import Proxy
    >>> mp = Proxy("<host_computer_name>:<rep_port>")

    For example:
    >>> pos = mp.get_stage_pos()
    >>> pos
    (3000, 4000)

It should be possible to re-use this code with other remote object systems like Pyro4.
"""
import os
import time
import logging

from zro import RemoteObject, Publisher

from imgprocessing import make_thumbnail

class RemoteInterface(Publisher):
    """ Allows remote control of certain Mosaic Planner features.

        All public attributes and methods of this class can be called
            remotely by connecting:

        >>> from zro import Proxy
        >>> mp = Proxy("<host_computer_name>:<rep_port>")
        >>> pos = mp.get_stage_pos()

        Args:
            rep_port (int): reply socket
            parent (MosaicPlanner): reference to MosaicPlanner

    """
    def __init__(self, rep_port, pub_port, parent):
        super(RemoteInterface, self).__init__(rep_port=rep_port, pub_port=pub_port)
        logging.info("Opening Remote Interface on port:{}".format(rep_port))
        self.parent = parent
        self._pause = False

        self._current_map = None
        self._current_position_list = None
        self._current_channel_settings = None

    @property
    def pause(self):
        return self._pause

    @pause.setter
    def pause(self, value):
        self._pause = value

    def _check_rep(self):
        """ Checks replay socket.  Mosaic Planner calls this periodically to process
            requests.
        """
        super(RemoteInterface, self)._check_rep()

    def get_stage_pos(self):
        """ Returns the current xy stage position.

            Returns:
                tuple: current (x, y) stage position.
        """
        stagePosition = self.parent.getStagePosition()
        return stagePosition

    def set_stage_pos(self, pos):
        """ Sets the current xy stage position.

            Args:
                pos (iterable): x and y position for stage
        """
        self.parent.setStagePosition(*pos)
        logging.info("Set new stage position to x:{}, y:{}".format(*pos))

    def get_objective_z(self):
        """ Returns the current Z height of objective.

        """
        pos_z = self.parent.getZPosition()
        return pos_z

    def set_objective_z(self, pos_z, speed=None):
        """ Sets the Z position of the objective.

            args:
                pos_z (float): target Z position
                speed (Optional[float]): custom speed for the move
        """
        if speed:
            old_speed = self.get_objective_property("Speed")
            self.set_objective_property("Speed", speed)
        t0 = time.clock()
        self.parent.setZPosition(pos_z)
        # make sure it got there
        timeout = self.parent.imgSrc.mmc.getTimeoutMs() / 1000.0
        while time.clock()-t0 < timeout:
            if not (pos_z-0.5 < self.get_objective_z() < pos_z+0.5):
                time.sleep(0.1)
            else:
                break
        else:
            raise Exception("Failed to reach target position before timeout.")

        logging.info("Set Z Position to z: {}".format(pos_z))
        if speed:
            self.set_objective_property("Speed", old_speed)

    def get_objective_property_names(self):
        """ Gets a list of objective property names.
        """
        # check that it has that property
        objective = self.parent.imgSrc.objective
        return self.parent.imgSrc.mmc.getDevicePropertyNames(objective)

    def get_objective_property(self, property):
        objective = self.parent.imgSrc.objective
        return self.parent.imgSrc.mmc.getProperty(objective, property)

    def set_objective_property(self, property, value):
        objective = self.parent.imgSrc.objective
        return self.parent.imgSrc.mmc.setProperty(objective, str(property), value)

    def set_objective_vel(self, vel):
        """ Sets objective move speed
        """

    def get_objective_vel(self):
        """ Get objective speed
        """

    def set_mm_timeout(self, sec):
        """ Sets MicroManager timeout
        """
        ms = int(sec*1000)
        self.parent.imgSrc.mmc.setTimeoutMs(ms)
        logging.info("MicroManager timeout set to: {} ms".format(ms))

    def get_remaining_time(self):
        """ Returns remaining acquisition time.
        """
        return self.parent.get_remaining_time()

    def get_current_acquisition_settings(self):
        """ Gets the current imaging session metadata.

        Returns:
            dict: session data
        """
        return self.parent.get_current_acquisition_settings()

    def load_channel_settings(self, settings):
        """ Load channel settings.
        """
        self.parent.load_channel_settings(settings)

    def load_map(self, folder=None):
        """ Loads the map at the specified folder
                or at the one currently specified in the GUI.
        """
        folder = self.parent.load_map(folder)
        self._current_map = folder
        return folder

    def set_position_file(self, position_file):
        """ Sets the current array position file in the GUI.

            args:
                position_file (str): file path to position list.
        """
        self.parent.set_position_file(position_file)

    def load_position_list(self, position_file=None):
        """ Loads a specific position list file.
                If not provided, it will load the one currently specified in the
                GUI.
        """
        self.parent.load_position_list(position_file)

    def clear_position_list(self):
        """ Clears the current position list.
        """
        self.parent.clear_position_list()

    def set_directory_settings(self, root_dir, sample_id, ribbon_id, session_id):
        """ Sets directory settings exactly how Mosiac planner likes them.
        """
        settings = {
            "default_path": root_dir,
            "Sample_ID": sample_id,
            "Ribbon_ID": ribbon_id,
            "Session_ID": session_id,
            "Map_num": 0, # ??
            "Slot_num": 0,  #DW: what should i do with this?
            "meta_experiment_name": "mpe_automated",
        }
        self.parent.load_directory_settings(settings)

    def get_directory_settings(self):
        settings = self.parent.directory_settings.__dict__
        return {
            "sample_id": settings['Sample_ID'],
            "ribbon_id": settings['Ribbon_ID'],
            "session_id": settings['Session_ID'],
            "root_dir": settings['default_path'],
            # Include map#?
        }

    def save_acquisition_settings(self, path=""):
        if not path:
            path = self.acquisition_data_path
        return self.parent.save_acquisition_settings(path), path

    @property
    def acquisition_data_path(self):
        dir_settings = self.get_directory_settings()
        return os.path.join(dir_settings['root_dir'],
                            dir_settings['sample_id'],
                            "{}_{}.yaml".format(dir_settings['ribbon_id'],
                                                dir_settings['session_id']))

    def load_acquisition_settings(self, settings):
        self.parent.load_acquisition_settings(settings)

    def sample_nearby(self, pos=None, folder="", size=3):
        """ Samples a grid of images and saves them to a specified folder.

        args:
            pos (tuple): position of center image, defaults to current position
            folder (str): folder to save images to
            size (int): rows and columns in each direction (total images are (2*size+1)^2)
        """
        self.parent.grabGrid(pos, folder, size)
        logging.info("Grid grabbed @ {}".format(folder))

    def grab_image(self):
        """ Returns the current image from the camera.

        Returns:
            numpy.ndarray: the current image data
        """
        data = self.parent.imgSrc.snap_image()
        thumb = make_thumbnail(data, autoscale=True)
        self.publish(thumb)
        return data

    def unload_arduino(self):
        self.parent.unload_arduino()

    def move_to_cassette(self, cassette_index=0):
        """ Moves to the specified cassette.

            #TODO: Should we disconnect objective?

        """
        return self.parent.move_to_cassette(cassette_index)

    def move_to_oil_position(self, index=None):
        """ Moves stage to specified oiling location.  If none,
            moves to closest.
        """
        return self.parent.move_to_oil_position(index)

    def move_to_z_and_focus(self, z=None):
        if z is not None:
            self.set_objective_z(z)
        self.parent.software_autofocus()

    def move_to_setup_height(self):
        """ Moves to default height for montage setup.
        """
        self.parent.move_to_setup_height()

    def connect_objective(self, pos_z, speed=300000):
        """ Connects the objective, moves to pos_z
        """
        approach_offset = 4000.0 # configurable?
        # go to approach offset first
        self.set_objective_z(approach_offset)
        # then go to objective slowly if desired
        self.set_objective_z(pos_z, speed=speed)


    def disconnect_objective(self, pos_z=None, speed=300000):
        approach_offset = 4000.0 #configurable?
        if pos_z is None:
            pos_z = approach_offset
        self.set_objective_z(approach_offset, speed)
        self.set_objective_z(pos_z)


    def autofocus(self, search_range=320, step=20, settle_time=1.0, attempts=3):
        """ Triggers autofocus.
        """
        z_pos = self.parent.imgSrc.focus_search(search_range=search_range,
                                                step=step,
                                                settle_time=settle_time,
                                                attempts=attempts)
        logging.info("Autofocus completed @ objective height: {}".format(z_pos))
        return z_pos

    @property
    def is_acquiring(self):
        """ Returns whether or not MP is acquiring
        """
        #return self.parent.acquiring
        return self.parent._is_acquiring

    def start_acquisition(self, data_dir=""):
        self._rep_sock.send_json(True)
        self.parent._is_acquiring = True
        self.parent.on_run_acq(data_dir)

    def check_bubbles(self, img_folder):
        """ Checks for bubbles in the images in specified folder.

        args:
            folder (str): folder of images

        Returns:
            list: list of images containing detected bubbles
        """
        import cv2
        import numpy as np
        import tifffile
        data_files = []
        for file in os.listdir(img_folder):
            data_files.append(os.path.join(img_folder, file))

        params = cv2.SimpleBlobDetector_Params()

        # Change thresholds
        params.minThreshold = 0
        params.maxThreshold = 15
        params.thresholdStep = 1

        # Filter by Area.
        params.filterByArea = True
        params.maxArea = 1e7
        params.minArea = 5e4 #5e4

        # Filter by Circularity
        params.filterByCircularity = False
        params.minCircularity = 0.5

        # Filter by Convexity
        params.filterByConvexity = True
        params.minConvexity = 0.97

        # Filter by Inertia
        params.filterByInertia = False
        params.minInertiaRatio = 0.4

        # Find bubbles
        score = np.zeros((len(data_files),),dtype='uint8')
        x = np.zeros((len(data_files),))
        y = np.zeros((len(data_files),))
        s = np.zeros((len(data_files),))

        blobReport = []

        for i, filename in enumerate(data_files):
            img = tifffile.imread(filename)
            img = cv2.blur(img, (50,50))
            a = 255.0/(np.max(img) - np.min(img))
            b = np.min(img)*(-255.0)/(np.max(img)-np.min(img))
            img = cv2.convertScaleAbs(img,alpha=a,beta=b)
            params.maxThreshold = int(round(np.min(img) + (np.min(img) + np.median(img))/4))
            img[0:2,:]=img[-2:,:]=img[:,0:2]=img[:,-2:]=np.median(img)

            # Create a detector with the parameters
            detector = cv2.SimpleBlobDetector(params)

            keypoints = detector.detect(img)
            if keypoints:
                score[i] = 1
                x[i] = keypoints[0].pt[0]
                y[i] = keypoints[0].pt[1]
                s[i] = keypoints[0].size
                logging.info("found %d blobs" % len(keypoints))
                blobReport.append(filename)
            else:
                score[i] = 0

        logging.info("blobReport:{}".format(blobReport))
        return blobReport

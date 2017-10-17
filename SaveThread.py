""" SaveThread.py

Multiprocessing Queue to save images and potentially do some preprocessing / publishing.

#TODO: DW make a "ImageSaver" class that more cleanly allows us to set up signalling
    and post-processing

"""
import os
from tifffile import imsave
import pandas as pd
import cv2
import numpy as np
import sys
import traceback
from Tokens import STOP_TOKEN,BUBBLE_TOKEN
import json
import logging
import time

from imgprocessing import make_thumbnail, get_focus_score



def file_save_process(queue, message_queue, metadata_dict):

    logging.basicConfig(level=logging.DEBUG)

    try:
        from zro import Publisher
        publisher = Publisher(pub_port=7779)
    except Exception as e:
        publisher = None
        logging.warning("Save thread failed to init publisher. Data will not be published.")

    while True:
        token = queue.get()
        if token == STOP_TOKEN:
            return
        else:
            try:
                t0_t = time.clock()
                (slice_index,frame_index, z_index, prot_name, path, data, ch, x, y, z,triggerflag,calcfocus,afc_image) = token
                tif_filepath = os.path.join(path, prot_name + "_S%04d_F%04d_Z%02d.tif" % (slice_index, frame_index, z_index))
                metadata_filepath = os.path.join(path, prot_name + "_S%04d_F%04d_Z%02d_metadata.txt"%(slice_index, frame_index, z_index))
                write_img(tif_filepath, data)
                if publisher:
                    t0_p = time.clock()
                    thumb = {'image': make_thumbnail(data, bin=2)}
                    publisher.publish(thumb)
                    #logging.debug("Publishing took: {} seconds".format(time.clock()-t0_p))
                write_slice_metadata(metadata_filepath, ch, x, y, z, slice_index, triggerflag, metadata_dict)
                if calcfocus:
                    focus_filepath = os.path.join(path, prot_name + "_S%04d_F%04d_Z%02d_focus.csv"%(slice_index, frame_index, z_index))
                    write_focus_score(focus_filepath, data,ch,x,y,slice_index,frame_index,prot_name)
                if afc_image is not None:
                    afc_image_filepath = os.path.join(path, prot_name + "_S%04d_F%04d_Z%02d_afc.json"%(slice_index, frame_index, z_index))
                    #np.savetxt(afc_image_filepath, afc_image)
                    write_afc_image(afc_image_filepath, afc_image,x,y,slice_index,frame_index)
                #logging.debug("Entire save operation took: {} seconds".format(time.clock()-t0_t))
            except:
                message_queue.put((STOP_TOKEN,traceback.print_exc()))

def write_img(path, img):
    """ Writes a numpy image as a tif file.

    args:
        path (str): file path to save img to
        img (numpy.ndarray): img data
    """
    imsave(path, img)


def write_focus_score(filename, data, ch,xpos,ypos,slide_index,frame_index,prot_name):
    df = pd.DataFrame(columns = ['score1_mean','score1_median','score1_std',
                                 'ch','xpos','ypos','slide_index','frame_index','prot_name'])
    score1_mean,score1_median,score1_std = get_focus_score(data)
    d = {
            'score1_mean':score1_mean,
            'score1_median':score1_median,
            'score1_std':score1_std,
            'ch':ch,
            'xpos':xpos,
            'ypos':ypos,
            'slide_index':slide_index,
            'frame_index':frame_index,
            'prot_name':prot_name
        }
    df = df.append(d,ignore_index=True)
    df.to_csv(filename)

def write_afc_image(filename, afc_image, xpos, ypos, slice_index, frame_index):
    dict = {'afc_image': afc_image.tolist(),'xpos': xpos,'ypos': ypos, 'slice_index': slice_index, 'frame_index': frame_index}
    thestring = json.JSONEncoder().encode(dict)
    file = open(filename, 'w')
    file.write(thestring)
    file.close()

def write_slice_metadata(filename, ch, xpos, ypos, zpos, slice_index,triggerflag, meta_dict):
    channelname    = meta_dict['channelname'][ch]
    (height,width) = meta_dict['(height,width)']
    ScaleFactorX   = meta_dict['ScaleFactorX']
    ScaleFactorY   = meta_dict['ScaleFactorY']
    exp_time       = meta_dict['exp_time'][ch]

    f = open(filename, 'w')
    f.write("Channel\tWidth\tHeight\tMosaicX\tMosaicY\tScaleX\tScaleY\tExposureTime\n")
    f.write("%s\t%d\t%d\t%d\t%d\t%f\t%f\t%f\n" % \
    (channelname, width, height, 1, 1, ScaleFactorX, ScaleFactorY, exp_time))
    f.write("XPositions\tYPositions\tFocusPositions\n")
    f.write("%s\t%s\t%s\n" %(xpos, ypos, zpos))

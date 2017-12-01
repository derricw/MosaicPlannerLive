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
widgets.py

Misc reusable widgets.

@author: derricw

"""
import time
import wx
import numpy as np


class ProgressDialog(object):
    """
    """
    def __init__(self,
                 title="Progress",
                 message="",
                 max_val=100,
                 publisher=None):
        
        self.max_val = max_val
        self.current_val = 0
        self.title = title
        self.message = message
        self.publisher = publisher
        
        self._update_times = []

        self.dialog = wx.ProgressDialog(title,
                                        message, 
                                        max_val,
                                        style=(wx.PD_CAN_ABORT | 
                                               wx.PD_ELAPSED_TIME | 
                                               wx.PD_REMAINING_TIME | 
                                               wx.PD_AUTO_HIDE)
        )
        self.update(self.current_val)
        wx.Yield() # do i need this?

    def update(self, value, text=""):
        if text:
            self.message = text
        self.current_val = value
        self._update_times.append(time.clock())
        self.publish_status()
        if self.current_val == self.max_val:
            self.destroy()
        try:
            return self.dialog.Update(value, self.message)
        except Exception:
            self.destroy()
        
    @property
    def remaining_time(self):
        average_time = np.mean(np.diff(self._update_times))
        return max( 0.0, average_time * (1 - self.current_val / self.max_val))

    @property
    def percent_complete(self):
        return (1 - self.current_val / self.max_val) * 100.0

    def destroy(self):
        self.dialog.Destroy()
        wx.Yield()

    @property
    def status(self):
        return {
            'remaining_time': self.remaining_time,
            'percent_complete': self.percent_complete,
            'current_val': self.current_val,
            'max_val': self.max_val,
            'current_message': self.message,
            'title': self.title,
        }

    def publish_status(self):
        if self.publisher:
            self.publisher.publish(self.status)
            print(self.status)
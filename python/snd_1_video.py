# sender2.py
import sys
import os

import gi
gi.require_version('Gst', '1.0') 
from gi.repository import Gst, GLib
import time
import hashlib


# Path configurations
current_dir = os.path.dirname(os.path.abspath(__file__))
python_driver_path = "/home/ivm/ivm-proto/driver/python/cleaned"
sys.path.append(python_driver_path)

gen_python_path = "/home/ivm/ivm-proto/gen/python/ivm_backend"
sys.path.append(gen_python_path)

import camera_pb2 as camera_pb2

Gst.init(None)

# Generator pipeline
pipeline_gen = """
videotestsrc pattern=ball ! video/x-raw,format=RGB,width=320,height=240,framerate=4/1 ! appsink name=sink emit-signals=true
"""
gen = Gst.parse_launch(pipeline_gen)

# Sender pipeline

transport = "tcpserversink host=0.0.0.0 port=6010"
#transport = "srtclientsink uri=srt://0.0.0.0:6010?mode=listener"

# Add second appsrc for KLV
pipeline_snd = f'''
 appsrc name=videosrc is-live=true do-timestamp=true format=time
 caps="video/x-raw,format=RGB,width=320,height=240,framerate=4/1" !
 videoconvert ! openjpegenc qos=true ! jpeg2000parse !
 capsfilter caps="image/x-jpc,alignment=(string)frame" !
 queue leaky=2 max-size-buffers=5 ! mpegtsmux name=mux !
{transport}
 appsrc name=klvsrc is-live=true do-timestamp=true format=time 
 caps="meta/x-klv,parsed=(boolean)true" ! queue ! mux.
'''

print("gst-launch-1.0", ' '.join(pipeline_snd.split('\n')))

snd = Gst.parse_launch(pipeline_snd)

# Modify get_frame to push KLV data
frame_counter = 0
def get_frame(sink, src):
    global frame_counter
    sample = sink.emit('pull-sample')
    if not sample:
        return Gst.FlowReturn.OK

    # Handle video
    buffer = sample.get_buffer()
    videosrc = src.get_by_name('videosrc')
    video_caps = Gst.Caps.from_string('video/x-raw,format=RGB,width=320,height=240,framerate=4/1')
    sample_video = Gst.Sample.new(buffer, video_caps, None, None)
    videosrc.emit('push-sample', sample_video)

    # Create and serialize protobuf
    image_info = camera_pb2.ImageInfo()
    image_info.trig_id = frame_counter
    image_info.device_id = "HYDRO-LRR"
    image_info.channel = "lrr"
    image_info.filename = "filename.jpg"
    image_info.session_name = "session"
    image_info.gain=1.0
    serialized = image_info.SerializeToString()

    # Create KLV
    key = hashlib.md5(b'ImageInfo').digest()  # 16 bytes
    length = len(serialized).to_bytes(4, 'big')
    klv_data = key + length + serialized

    # Push KLV
    klvsrc = src.get_by_name('klvsrc')
    klv_buffer = Gst.Buffer.new_allocate(None, len(klv_data), None)
    klv_buffer.fill(0, klv_data)
    klv_caps = Gst.Caps.from_string('meta/x-klv,parsed=(boolean)true')
    klv_sample = Gst.Sample.new(klv_buffer, klv_caps, None, None)
    klvsrc.emit('push-sample', klv_sample)
    
    frame_counter += 1
    return Gst.FlowReturn.OK

sink = gen.get_by_name('sink')
sink.connect('new-sample', get_frame, snd)

snd.set_state(Gst.State.PLAYING)
gen.set_state(Gst.State.PLAYING)

try:
   GLib.MainLoop().run()
except KeyboardInterrupt:
   gen.set_state(Gst.State.NULL)
   snd.set_state(Gst.State.NULL)

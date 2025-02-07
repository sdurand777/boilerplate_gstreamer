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

# Generator pipelines - one for each video source
pipeline_gen1 = """
videotestsrc pattern=ball ! video/x-raw,format=RGB,width=320,height=240,framerate=4/1 ! appsink name=sink1 emit-signals=true
"""
pipeline_gen2 = """
videotestsrc pattern=ball ! video/x-raw,format=RGB,width=320,height=240,framerate=4/1 ! appsink name=sink2 emit-signals=true
"""

gen1 = Gst.parse_launch(pipeline_gen1)
gen2 = Gst.parse_launch(pipeline_gen2)

# Single sender pipeline with two video inputs and one KLV
transport = "tcpserversink host=0.0.0.0 port=6010"

pipeline_snd = f'''
 appsrc name=videosrc1 is-live=true do-timestamp=true format=time
 caps="video/x-raw,format=RGB,width=320,height=240,framerate=4/1" !
 videoconvert ! openjpegenc qos=true ! jpeg2000parse !
 capsfilter caps="image/x-jpc,alignment=(string)frame" !
 queue leaky=2 max-size-buffers=5 ! mpegtsmux name=mux !
{transport}

 appsrc name=videosrc2 is-live=true do-timestamp=true format=time
 caps="video/x-raw,format=RGB,width=320,height=240,framerate=4/1" !
 videoconvert ! openjpegenc qos=true ! jpeg2000parse !
 capsfilter caps="image/x-jpc,alignment=(string)frame" !
 queue leaky=2 max-size-buffers=5 ! mux.

 appsrc name=klvsrc is-live=true do-timestamp=true format=time 
 caps="meta/x-klv,parsed=(boolean)true" ! queue ! mux.
'''

print("gst-launch-1.0", ' '.join(pipeline_snd.split('\n')))

snd = Gst.parse_launch(pipeline_snd)

# Frame counters for each video stream
frame_counter1 = 0
frame_counter2 = 0

def get_frame1(sink, src):
    global frame_counter1
    sample = sink.emit('pull-sample')
    if not sample:
        return Gst.FlowReturn.OK
        
    # Handle video 1
    buffer = sample.get_buffer()
    videosrc = src.get_by_name('videosrc1')
    video_caps = Gst.Caps.from_string('video/x-raw,format=RGB,width=320,height=240,framerate=4/1')
    sample_video = Gst.Sample.new(buffer, video_caps, None, None)
    videosrc.emit('push-sample', sample_video)
    
    # Create and serialize protobuf for video 1
    image_info = camera_pb2.ImageInfo()
    image_info.trig_id = frame_counter1
    image_info.device_id = "HYDRO-LRR-1"
    image_info.channel = "lrr1"
    image_info.filename = "filename1.jpg"
    image_info.session_name = "session1"
    image_info.gain = 1.0
    serialized = image_info.SerializeToString()
    
    # Create KLV
    key = hashlib.md5(b'ImageInfo').digest()
    length = len(serialized).to_bytes(4, 'big')
    klv_data = key + length + serialized
    
    # Push KLV
    klvsrc = src.get_by_name('klvsrc')
    klv_buffer = Gst.Buffer.new_allocate(None, len(klv_data), None)
    klv_buffer.fill(0, klv_data)
    klv_caps = Gst.Caps.from_string('meta/x-klv,parsed=(boolean)true')
    klv_sample = Gst.Sample.new(klv_buffer, klv_caps, None, None)
    klvsrc.emit('push-sample', klv_sample)
    
    frame_counter1 += 1
    return Gst.FlowReturn.OK

def get_frame2(sink, src):
    global frame_counter2
    sample = sink.emit('pull-sample')
    if not sample:
        return Gst.FlowReturn.OK
        
    # Handle video 2
    buffer = sample.get_buffer()
    videosrc = src.get_by_name('videosrc2')
    video_caps = Gst.Caps.from_string('video/x-raw,format=RGB,width=320,height=240,framerate=4/1')
    sample_video = Gst.Sample.new(buffer, video_caps, None, None)
    videosrc.emit('push-sample', sample_video)
    
    frame_counter2 += 1
    return Gst.FlowReturn.OK

# Connect sinks to callbacks
sink1 = gen1.get_by_name('sink1')
sink2 = gen2.get_by_name('sink2')
sink1.connect('new-sample', get_frame1, snd)
sink2.connect('new-sample', get_frame2, snd)

# Start all pipelines
snd.set_state(Gst.State.PLAYING)
gen1.set_state(Gst.State.PLAYING)
gen2.set_state(Gst.State.PLAYING)

try:
    GLib.MainLoop().run()
except KeyboardInterrupt:
    gen1.set_state(Gst.State.NULL)
    gen2.set_state(Gst.State.NULL)
    snd.set_state(Gst.State.NULL)

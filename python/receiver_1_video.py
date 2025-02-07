import sys
import os
import queue
import time
import cv2
import numpy as np
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib

# Path configurations
current_dir = os.path.dirname(os.path.abspath(__file__))
python_driver_path = "/home/ivm/ivm-proto/driver/python/cleaned"
sys.path.append(python_driver_path)

gen_python_path = "/home/ivm/ivm-proto/gen/python/ivm_backend"
sys.path.append(gen_python_path)

import camera_pb2

# Initialize GStreamer
Gst.init(None)

# Frame queue for thread-safe frame passing
frame_queue = queue.Queue()

# GStreamer pipeline configuration
transport = "tcpclientsrc host=127.0.0.1 port=6010 ! "
pipeline = f'''
{transport}
tsdemux name=demux
demux. ! queue ! jpeg2000parse ! openjpegdec ! videoconvert ! video/x-raw,format=RGB ! appsink name=video1_sink emit-signals=true
demux. ! queue ! appsink name=klvsink emit-signals=true
'''

# Frame counting for FPS calculation
frame_right_count = 0
last_right_time = time.time()
frame_left_count = 0
last_left_time = time.time()


def extract_frame(sample, frame_count, last_time):
    # Video1 processing
    caps = sample.get_caps()
    buffer = sample.get_buffer()
    
    caps_format = caps.get_structure(0)
    width = caps_format.get_value("width")
    height = caps_format.get_value("height")
    pixel_format = caps_format.get_value("format")

    # Map the buffer to memory
    success, map_info = buffer.map(Gst.MapFlags.READ)
    if success:
        # Extract the data into a numpy array
        frame_data = np.ndarray(
            (height, width, 3),
            dtype=np.uint8,
            buffer=map_info.data
        )
        
        # Convert to BGR for OpenCV
        frame = cv2.cvtColor(frame_data, cv2.COLOR_RGB2BGR)
        
        # Push the frame to the queue
        frame_queue.put(frame)

        # Unmap the buffer
        buffer.unmap(map_info)

        # FPS Calculation
        frame_count += 1
        current_time = time.time()
        elapsed_time = current_time - last_time

        if elapsed_time >= 1:
            fps = frame_count / elapsed_time
            print(f"FPS: {fps:.2f}")
            last_time = current_time
            frame_count = 0




# def on_combined_data(v1_sink, v2_sink, klv_sink):
#     global frame_right_count, last_right_time, frame_left_count, last_left_time
#
#     # Pull samples from all sinks
#     v1_sample = v1_sink.emit('pull-sample')
#     v2_sample = v2_sink.emit('pull-sample')
#     klv_sample = klv_sink.emit('pull-sample')
#     
#     if not all([v1_sample, v2_sample, klv_sample]):
#         return Gst.FlowReturn.OK
#         
#     
#     extract_frame(v1_sample, frame_right_count, last_right_time)
#
#
#     # Get caps and buffer info for video2
#     v2_caps = v2_sample.get_caps()
#     v2_buffer = v2_sample.get_buffer()
#     print("\nVideo2 caps:", v2_caps.to_string())
#     print("Video2 buffer size:", v2_buffer.get_size())
#     
#     # Process KLV data
#     klv_buffer = klv_sample.get_buffer()
#     klv_data = klv_buffer.extract_dup(0, klv_buffer.get_size())
#     klv_caps = klv_sample.get_caps()
#     print("\nKLV caps:", klv_caps.to_string())
#     print("KLV buffer size:", klv_buffer.get_size())
#     
#     # Parse KLV using klv_data instead of data
#     key = klv_data[:16]
#     length = int.from_bytes(klv_data[16:20], 'big')
#     value = klv_data[20:20+length]
#     
#     # Decode protobuf
#     image_info = camera_pb2.ImageInfo()
#     image_info.ParseFromString(value)
#     print("KLV content:", image_info)
 

def on_combined_data(v1_sink, klv_sink):
    global frame_right_count, last_right_time, frame_left_count, last_left_time

    # Pull samples from all sinks
    v1_sample = v1_sink.emit('pull-sample')
    klv_sample = klv_sink.emit('pull-sample')
    
    if not all([v1_sample, klv_sample]):
        return Gst.FlowReturn.OK
        
    
    extract_frame(v1_sample, frame_right_count, last_right_time)

    # Process KLV data
    klv_buffer = klv_sample.get_buffer()
    klv_data = klv_buffer.extract_dup(0, klv_buffer.get_size())
    klv_caps = klv_sample.get_caps()
    print("\nKLV caps:", klv_caps.to_string())
    print("KLV buffer size:", klv_buffer.get_size())
    
    # Parse KLV using klv_data instead of data
    key = klv_data[:16]
    length = int.from_bytes(klv_data[16:20], 'big')
    value = klv_data[20:20+length]
    
    # Decode protobuf
    image_info = camera_pb2.ImageInfo()
    image_info.ParseFromString(value)
    print("KLV content:", image_info)
    return Gst.FlowReturn.OK


def display_frame(user_data):
    try:
        if not frame_queue.empty():
            frame = frame_queue.get()
            cv2.imshow("Frame", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                GLib.idle_remove_by_data(user_data)
                cv2.destroyAllWindows()
                return False
        return True
    except Exception as e:
        print(f"Error in display_frame: {e}")
        return False



def main():
    # Create and configure pipeline
    pipeline_obj = Gst.parse_launch(pipeline)
    v1_sink = pipeline_obj.get_by_name('video1_sink')
    klv_sink = pipeline_obj.get_by_name('klvsink')
 
    # Connect the callback
    v1_sink.connect('new-sample', on_combined_data, klv_sink)
 
    # Error handling
    pipeline_obj.get_bus().add_signal_watch()
    def on_message(bus, message):
        t = message.type
        if t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print("Error:", err, debug)
            pipeline_obj.set_state(Gst.State.NULL)
    
    pipeline_obj.get_bus().connect("message", on_message)
    pipeline_obj.set_state(Gst.State.PLAYING)

    # Set up GLib main loop
    main_loop = GLib.MainLoop()
    
    # Add idle callback for frame display
    idle_id = GLib.idle_add(display_frame, main_loop)

    try:
        main_loop.run()
    except KeyboardInterrupt:
        pass
    finally:
        pipeline_obj.set_state(Gst.State.NULL)
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()


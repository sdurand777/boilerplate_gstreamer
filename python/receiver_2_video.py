import sys
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib, GObject
import numpy as np
import cv2

Gst.init(None)

# Pipeline de réception corrigée
pipeline_str = '''
    tcpclientsrc host=127.0.0.1 port=6010 ! 
    tsdemux name=demux
    
    demux. ! queue ! jpeg2000parse ! openjpegdec ! videoconvert ! 
    video/x-raw,format=RGB ! appsink name=video1_sink emit-signals=true
    
    demux. ! queue ! jpeg2000parse ! openjpegdec ! videoconvert ! 
    video/x-raw,format=RGB ! appsink name=video2_sink emit-signals=true
    
    demux. ! queue ! appsink name=klvsink emit-signals=true
'''

# Créer le pipeline
pipeline = Gst.parse_launch(pipeline_str)

# Obtenir les références des sinks
video1_sink = pipeline.get_by_name('video1_sink')
video2_sink = pipeline.get_by_name('video2_sink')
klv_sink = pipeline.get_by_name('klvsink')

from threading import Lock

lock = Lock()

def show_frame(title, array):
    with lock:  # Éviter les conflits d'accès
        cv2.imshow(title, array)
        cv2.waitKey(1)

def on_new_video1_sample(sink):
    sample = sink.emit('pull-sample')
    if sample:
        buffer = sample.get_buffer()
        caps = sample.get_caps()
        structure = caps.get_structure(0)
        width = structure.get_value('width')
        height = structure.get_value('height')

        buffer_size = buffer.get_size()
        array = np.ndarray(
            shape=(height, width, 3),
            dtype=np.uint8,
            buffer=buffer.extract_dup(0, buffer_size)
        )

        GLib.idle_add(show_frame, "Video 1", array)  # Déplacer dans le thread principal

    return Gst.FlowReturn.OK

def on_new_video2_sample(sink):
    sample = sink.emit('pull-sample')
    if sample:
        buffer = sample.get_buffer()
        caps = sample.get_caps()
        structure = caps.get_structure(0)
        width = structure.get_value('width')
        height = structure.get_value('height')

        buffer_size = buffer.get_size()
        array = np.ndarray(
            shape=(height, width, 3),
            dtype=np.uint8,
            buffer=buffer.extract_dup(0, buffer_size)
        )

        GLib.idle_add(show_frame, "Video 2", array)  # Déplacer dans le thread principal

    return Gst.FlowReturn.OK


# Callback pour les données KLV
def on_new_klv_sample(sink):
    sample = sink.emit('pull-sample')
    if sample:
        buffer = sample.get_buffer()
        data = buffer.extract_dup(0, buffer.get_size())
        # Ici vous pouvez traiter les données KLV si nécessaire
        print(f"Reçu données KLV de taille: {len(data)}")
    
    return Gst.FlowReturn.OK

# Connecter les callbacks
video1_sink.connect('new-sample', on_new_video1_sample)
video2_sink.connect('new-sample', on_new_video2_sample)
klv_sink.connect('new-sample', on_new_klv_sample)

# Fonction de gestion des messages de bus
def on_bus_message(bus, message, loop):
    message_type = message.type
    
    if message_type == Gst.MessageType.EOS:
        print("Fin du flux")
        loop.quit()
    elif message_type == Gst.MessageType.ERROR:
        err, debug = message.parse_error()
        print(f"Erreur: {err}, {debug}")
        loop.quit()
    
    return True

# Configurer le bus
bus = pipeline.get_bus()
loop = GLib.MainLoop()
bus.add_watch(0, on_bus_message, loop)

# Démarrer le pipeline
pipeline.set_state(Gst.State.PLAYING)

print("Réception en cours... Appuyez sur Ctrl+C pour arrêter.")

try:
    loop.run()
except KeyboardInterrupt:
    print("Arrêt du récepteur...")
finally:
    pipeline.set_state(Gst.State.NULL)
    cv2.destroyAllWindows()


#include <gst/gst.h>

/* Structure pour contenir les éléments du pipeline */
typedef struct _CustomData {
  GstElement *pipeline;
  GstElement *source;
  GstElement *video_convert;
  GstElement *video_sink;
  GstElement *audio_convert;
  GstElement *audio_resample;
  GstElement *audio_sink;
} CustomData;

/* Handler pour la gestion des nouveaux pads */
static void pad_added_handler (GstElement *src, GstPad *new_pad, CustomData *data);

int main(int argc, char *argv[]) {
  CustomData data;
  GstBus *bus;
  GstMessage *msg;
  GstStateChangeReturn ret;
  gboolean terminate = FALSE;

  /* Initialisation de GStreamer */
  gst_init (&argc, &argv);

  /* Création des éléments */
  data.source = gst_element_factory_make ("uridecodebin", "source");

  /* Éléments pour la vidéo */
  data.video_convert = gst_element_factory_make ("videoconvert", "video_convert");
  data.video_sink = gst_element_factory_make ("autovideosink", "video_sink");

  /* Éléments pour l'audio */
  data.audio_convert = gst_element_factory_make ("audioconvert", "audio_convert");
  data.audio_resample = gst_element_factory_make ("audioresample", "audio_resample");
  data.audio_sink = gst_element_factory_make ("autoaudiosink", "audio_sink");

  /* Création du pipeline */
  data.pipeline = gst_pipeline_new ("test-pipeline");

  if (!data.pipeline || !data.source || !data.video_convert || !data.video_sink ||
      !data.audio_convert || !data.audio_resample || !data.audio_sink) {
    g_printerr ("Erreur : Un ou plusieurs éléments n'ont pas pu être créés.\n");
    return -1;
  }

  /* Ajout des éléments au pipeline */
  gst_bin_add_many (GST_BIN (data.pipeline),
                    data.source,
                    data.video_convert, data.video_sink,
                    data.audio_convert, data.audio_resample, data.audio_sink, NULL);

  /* Lien des éléments vidéo */
  if (!gst_element_link_many (data.video_convert, data.video_sink, NULL)) {
    g_printerr ("Erreur lors du lien des éléments vidéo.\n");
    gst_object_unref (data.pipeline);
    return -1;
  }

  /* Lien des éléments audio */
  if (!gst_element_link_many (data.audio_convert, data.audio_resample, data.audio_sink, NULL)) {
    g_printerr ("Erreur lors du lien des éléments audio.\n");
    gst_object_unref (data.pipeline);
    return -1;
  }

  /* Définition de l'URI de la source */
  g_object_set (data.source, "uri", "https://gstreamer.freedesktop.org/data/media/sintel_trailer-480p.webm", NULL);

  /* Connexion au signal "pad-added" */
  g_signal_connect (data.source, "pad-added", G_CALLBACK (pad_added_handler), &data);

  /* Lancement du pipeline */
  ret = gst_element_set_state (data.pipeline, GST_STATE_PLAYING);
  if (ret == GST_STATE_CHANGE_FAILURE) {
    g_printerr ("Impossible de passer en mode lecture.\n");
    gst_object_unref (data.pipeline);
    return -1;
  }

  /* Gestion des messages du bus */
  bus = gst_element_get_bus (data.pipeline);
  do {
    msg = gst_bus_timed_pop_filtered (bus, GST_CLOCK_TIME_NONE,
        GST_MESSAGE_STATE_CHANGED | GST_MESSAGE_ERROR | GST_MESSAGE_EOS);

    /* Traitement des messages */
    if (msg != NULL) {
      GError *err;
      gchar *debug_info;

      switch (GST_MESSAGE_TYPE (msg)) {
        case GST_MESSAGE_ERROR:
          gst_message_parse_error (msg, &err, &debug_info);
          g_printerr ("Erreur : %s\n", err->message);
          g_clear_error (&err);
          g_free (debug_info);
          terminate = TRUE;
          break;
        case GST_MESSAGE_EOS:
          g_print ("Fin du flux.\n");
          terminate = TRUE;
          break;
        case GST_MESSAGE_STATE_CHANGED:
          if (GST_MESSAGE_SRC (msg) == GST_OBJECT (data.pipeline)) {
            GstState old_state, new_state;
            gst_message_parse_state_changed (msg, &old_state, &new_state, NULL);
            g_print ("État du pipeline : %s -> %s\n",
                     gst_element_state_get_name (old_state),
                     gst_element_state_get_name (new_state));
          }
          break;
        default:
          g_printerr ("Message inattendu reçu.\n");
          break;
      }
      gst_message_unref (msg);
    }
  } while (!terminate);

  /* Libération des ressources */
  gst_object_unref (bus);
  gst_element_set_state (data.pipeline, GST_STATE_NULL);
  gst_object_unref (data.pipeline);
  return 0;
}

/* Gestion de l'ajout dynamique de pads */
static void pad_added_handler (GstElement *src, GstPad *new_pad, CustomData *data) {
  GstPad *sink_pad;
  GstPadLinkReturn ret;
  GstCaps *new_pad_caps = NULL;
  GstStructure *new_pad_struct = NULL;
  const gchar *new_pad_type = NULL;

  g_print ("Nouveau pad détecté : '%s' de l'élément '%s'\n", GST_PAD_NAME (new_pad), GST_ELEMENT_NAME (src));

  /* Récupération des caps du pad */
  new_pad_caps = gst_pad_query_caps (new_pad, NULL);
  new_pad_struct = gst_caps_get_structure (new_pad_caps, 0);
  new_pad_type = gst_structure_get_name (new_pad_struct);

  /* Lien du pad en fonction du type */
  if (g_str_has_prefix (new_pad_type, "audio/x-raw")) {
    sink_pad = gst_element_get_static_pad (data->audio_convert, "sink");
  } else if (g_str_has_prefix (new_pad_type, "video/x-raw")) {
    sink_pad = gst_element_get_static_pad (data->video_convert, "sink");
  } else {
    g_print ("Type non supporté : '%s'\n", new_pad_type);
    goto exit;
  }

  /* Vérifier si le pad est déjà lié */
  if (gst_pad_is_linked (sink_pad)) {
    g_print ("Le pad est déjà lié.\n");
    goto exit;
  }

  /* Lier le pad */
  ret = gst_pad_link (new_pad, sink_pad);
  if (GST_PAD_LINK_FAILED (ret)) {
    g_print ("Échec du lien pour le type '%s'.\n", new_pad_type);
  } else {
    g_print ("Lien réussi pour le type '%s'.\n", new_pad_type);
  }

exit:
  if (new_pad_caps != NULL)
    gst_caps_unref (new_pad_caps);
  gst_object_unref (sink_pad);
}

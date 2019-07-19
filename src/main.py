#!/usr/bin/env python3

from gst import gstc
from gi.repository import GObject, Gst, GLib
import logging
import gi
import sys
import time
import json
gi.require_version('Gst', '1.0')
gi.require_version('GObject', '2.0')

# Read Tinyyolo Labels
tinyyolo_labels_file = open("tinyyolov2_labels.txt", "r")
tinyyolo_labels = tinyyolo_labels_file.read()
tinyyolo_labels_file.close()

# Absolute Path where models are found
models_path = "/home/nvidia/gst-inference-demo/src/"

# Pipelines definitions

webrtc_base_pipeline = " rrwebrtcbin start-call=true signaler=GstOwrSignaler signaler::server_url=https://webrtc.ridgerun.com:8443 "
rstp_source_pipeline = " rtspsrc debug=true async-handling=true location=rtsp://"
camera_source_pipeline = " nvarguscamerasrc sensor-id=0 ! nvvidconv ! capsfilter caps=video/x-raw,width=752,height=480 "
video_decode_pipeline = " rtpvp8depay ! omxvp8dec ! nvvidconv ! capsfilter caps=video/x-raw(memory:NVMM) ! nvvidconv "
interpipesink_pipeline = " interpipesink enable-last-sample=false forward-eos=true forward-events=true async=false name="
interpipesrc_pipeline = " interpipesrc name=src format=3 listen-to="
video_encode_pipeline = " queue max-size-buffers=1 leaky=downstream ! omxvp8enc ! rtpvp8pay"
tee_pipeline = " tee name="
jpeg_base_pipeline = " nvjpegenc name="
multifilesink_pipeline = " identity name=identity silent=false ! multifilesink location=/tmp/output.jpeg"

# Inference (Tinyyolov2)
tinyyolov2_format_pipeline = " capsfilter caps=video/x-raw,width=752,height=480 "
tinyyolov2_base_pipeline = """ tinyyolov2 model-location=""" + models_path + \
    """graph_tinyyolov2_tensorflow.pb backend=tensorflow backend::input-layer=input/Placeholder backend::output-layer=add_8 name=net """
tinyyolov2_net_pipeline = " queue max-size-buffers=1 leaky=downstream ! nvvidconv ! capsfilter caps=video/x-raw(memory:NVMM) ! nvvidconv ! net.sink_model "
tinyyolov2_bypass_pipeline = " queue max-size-buffers=1 leaky=downstream ! net.sink_bypass "
tinyyolov2_overlay_pipeline = """ net.src_bypass ! nvvidconv ! capsfilter caps=video/x-raw(memory:NVMM) ! nvvidconv ! detectionoverlay labels=\"""" + tinyyolo_labels + \
    """\" ! inferencealert name=person-alert label-index=14 ! queue max-size-buffers=1 leaky=downstream ! nvvidconv ! capsfilter caps=video/x-raw(memory:NVMM)  ! nvvidconv ! capsfilter caps=video/x-raw """


def logger_setup():
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    root.addHandler(handler)


def create_pipeline(gstd_client, name, pipeline):
    global pipeline_counter
    ret = gstd_client.pipeline_create(name, pipeline)
    if (ret != 0):
        print("Error creating the pipeline: " + str(ret))
        return


def play_pipeline(gstd_client, name):
    ret = gstd_client.pipeline_play(name)
    if (ret != 0):
        print("Error playing the pipeline: " + str(ret))
        return


def set_element_prop(gstd_client, name, element, prop, value):
    ret = gstd_client.element_set(name, element, prop, value)
    if (ret != 0):
        print("Error setting element property: " + str(ret))
        return


def stop_pipeline(gstd_client, name):
    ret = gstd_client.pipeline_stop(name)
    if (ret != 0):
        print("Error stopping the pipeline: " + str(ret))
        return


def build_test_0(gstd_client, test_name, default_data):
    session_id = default_data[test_name]["session_id"]
    rtsp_ip_address = default_data[test_name]["rtsp_ip_address"]
    rtsp_port = default_data[test_name]["rtsp_port"]

    # Create Pipelines
    webrtc_name = test_name + ".video_sink"
    webrtc = webrtc_base_pipeline + "signaler::session_id=" + session_id
    webrtc += " name=" + test_name

    rtsp = rstp_source_pipeline + rtsp_ip_address + ":" + rtsp_port + "/test"

    interpipesink0_name = test_name + "_camera"
    interpipesink1_name = test_name + "_decodesink"

    video_receive0 = interpipesink_pipeline + interpipesink0_name

    video_receive1 = video_decode_pipeline + \
        " ! " + tinyyolov2_format_pipeline + " ! "
    video_receive1 += interpipesink_pipeline + interpipesink1_name

    inference = tinyyolov2_base_pipeline
    inference += interpipesrc_pipeline + interpipesink1_name + " ! " + tee_pipeline + "t0"
    inference += " t0. ! " + tinyyolov2_net_pipeline
    inference += " t0. ! " + tinyyolov2_bypass_pipeline
    inference += tinyyolov2_overlay_pipeline

    video_send = inference + " ! " + tee_pipeline + "t1"
    video_send += " t1. ! " + video_encode_pipeline
    
    jpeg = " t1. ! " + jpeg_base_pipeline + test_name + "_jpeg_sink ! "
    jpeg += multifilesink_pipeline

    full_pipe = webrtc + "  " + camera_source_pipeline + " ! " + video_receive0 + \
        rtsp + " ! " + video_receive1 + video_send + " ! " + webrtc_name + jpeg

    logging.info(" Test name: " + test_name)
    logging.info(
        " Description: RTSP + GstInterpipe + GstInference Detection + GstWebRTC on GStreamer Daemon")
    logging.info(" Pipeline: " + full_pipe)
    create_pipeline(gstd_client, "p0", full_pipe)
    play_pipeline(gstd_client, "p0")


def main(args=None):
    gstd_client = gstc.client(loglevel='DEBUG')

    # Load the JSON default parameters as a dictionary
    with open('./pipe_config.json') as json_file:
        default_params = json.load(json_file)

    # Logger Setup
    logger_setup()

    logging.info("This is a demo application...")
    build_test_0(gstd_client, "Test0", default_params)

    time.sleep(1)
    while True:
        choice = input(
            "    ** Menu **\n 1) Camera source\n 2) RTSP source\n 3) Exit\n > ")
        choice = choice.lower()  # Convert input to "lowercase"

        if choice == '1':
            set_element_prop(
                gstd_client,
                "p0",
                "src",
                "listen-to",
                "Test0_camera")
            print("--> Camera source selected\n")
        if choice == '2':
            set_element_prop(
                gstd_client,
                "p0",
                "src",
                "listen-to",
                "Test0_decodesink")
            print("--> RTSP source selected\n")
        if choice == '3':
            print("--> Exit\n")
            break

    stop_pipeline(gstd_client, "p0")


if __name__ == "__main__":
    main(None)

# camera_capture.py
# Refactored from china_cam.py for single image capture as a module function

import sys
import threading
import os
import termios
import fcntl # Import fcntl for non-blocking stdin
from datetime import datetime
import time

from ctypes import c_ubyte, byref, memset, sizeof, cast, create_string_buffer, POINTER, c_char

# Ensure the MvImport directory is in your Python path.
# This path should point to the directory containing MvCameraControl_class.py
# IMPORTANT: Adjust this path if your MvImport directory is located elsewhere.
sys.path.append("/opt/MVS/Samples/aarch64/Python/MvImport")
try:
    from MvCameraControl_class import *
except ImportError:
    print("Error: MvCameraControl_class.py not found or cannot be imported.", file=sys.stderr)
    print("Please ensure the path in sys.path.append() is correct and the MvImport directory contains the necessary files.", file=sys.stderr)
    sys.exit(1)


# Define a common RGB pixel type for conversion target.
# This value (0x02180014) is a widely used representation for MV_Gvsp_RGB8_Packed.
# If your SDK's PixelType_const.py defines a different value for RGB8_Packed,
# you might need to adjust this.
MV_Gvsp_RGB8_Packed = 0x02180014

# Global flags/events for internal control of the capture thread
# These are internal to the module and should not be directly accessed from outside.
_g_bExit_internal = False
_capture_event_internal = threading.Event()
_captured_image_path_internal = None # To store the path of the saved image


def _get_char_internal():
    """
    Internal helper to read a single character non-blockingly from stdin.
    This function is Unix-specific due to the use of termios and fcntl.
    It temporarily sets stdin to non-blocking mode.
    """
    fd = sys.stdin.fileno()
    old_ttyinfo = termios.tcgetattr(fd)
    new_ttyinfo = old_ttyinfo[:]
    new_ttyinfo[3] &= ~termios.ICANON  # Disable canonical mode (line buffering)
    new_ttyinfo[3] &= ~termios.ECHO    # Disable echoing of characters
    termios.tcsetattr(fd, termios.TCSANOW, new_ttyinfo)

    # Set stdin to non-blocking mode
    old_flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, old_flags | os.O_NONBLOCK)

    ch = ''
    try:
        ch = os.read(fd, 1).decode()
    except BlockingIOError:
        ch = '' # No character available
    except Exception as e:
        sys.stderr.write(f"Error reading character in _get_char_internal: {e}\n") # Use stderr for internal errors
        ch = '' # Return empty string on other errors
    finally:
        # Restore old stdin flags and tty settings
        fcntl.fcntl(fd, fcntl.F_SETFL, old_flags)
        termios.tcsetattr(fd, termios.TCSANOW, old_ttyinfo)
    return ch

# Internal work thread that performs the actual image capture and saving
def _work_thread_internal(cam, output_dir, capture_done_event):
    """
    Internal thread to capture and save a single image upon signal.
    It runs in a loop, waiting for _capture_event_internal to be set.
    Once an image is captured and saved (or an error occurs), it clears
    _capture_event_internal and sets capture_done_event to signal completion.
    """
    global _g_bExit_internal
    global _capture_event_internal
    global _captured_image_path_internal

    stOutFrame = MV_FRAME_OUT()
    memset(byref(stOutFrame), 0, sizeof(stOutFrame))

    while not _g_bExit_internal:
        _capture_event_internal.wait(timeout=0.1)

        if _g_bExit_internal:
            break

        if _capture_event_internal.is_set():
            # print("Attempting to get image buffer...") # Avoid verbose output in module
            ret = cam.MV_CC_GetImageBuffer(stOutFrame, 5000)
            if ret == 0:
                print(f"Captured frame: W={stOutFrame.stFrameInfo.nWidth}, H={stOutFrame.stFrameInfo.nHeight}, PixelType=0x{stOutFrame.stFrameInfo.enPixelType:x}, FrameNum={stOutFrame.stFrameInfo.nFrameNum}")

                image_data_to_save = stOutFrame.pBufAddr
                image_data_len_to_save = stOutFrame.stFrameInfo.nFrameLen
                image_pixel_type_to_save = stOutFrame.stFrameInfo.enPixelType

                is_bayer_format = (stOutFrame.stFrameInfo.enPixelType & 0xFF000000) == 0x01000000

                if is_bayer_format:
                    expected_len_8bit = stOutFrame.stFrameInfo.nWidth * stOutFrame.stFrameInfo.nHeight
                    print(f"Detected Bayer pixel type. nFrameLen={stOutFrame.stFrameInfo.nFrameLen}, "
                          f"width*height={expected_len_8bit} (diff={stOutFrame.stFrameInfo.nFrameLen - expected_len_8bit}). "
                          f"Attempting conversion to RGB8_Packed...")
                    stConvertParam = MV_CC_PIXEL_CONVERT_PARAM()
                    memset(byref(stConvertParam), 0, sizeof(stConvertParam))

                    stConvertParam.nWidth = stOutFrame.stFrameInfo.nWidth
                    stConvertParam.nHeight = stOutFrame.stFrameInfo.nHeight
                    stConvertParam.enSrcPixelType = stOutFrame.stFrameInfo.enPixelType
                    stConvertParam.pSrcData = stOutFrame.pBufAddr
                    stConvertParam.nSrcDataLen = stOutFrame.stFrameInfo.nFrameLen
                    stConvertParam.enDstPixelType = MV_Gvsp_RGB8_Packed
                    nDstBufSize = stOutFrame.stFrameInfo.nWidth * stOutFrame.stFrameInfo.nHeight * 3
                    pDstBuf = (c_ubyte * nDstBufSize)()
                    stConvertParam.pDstBuffer = cast(pDstBuf, POINTER(c_ubyte))
                    stConvertParam.nDstBufferSize = nDstBufSize

                    ret_convert = cam.MV_CC_ConvertPixelType(stConvertParam)
                    if ret_convert == 0:
                        print("Pixel format converted successfully.")
                        image_data_to_save = stConvertParam.pDstBuffer
                        image_data_len_to_save = stConvertParam.nDstLen
                        image_pixel_type_to_save = stConvertParam.enDstPixelType
                    else:
                        print(f"Failed to convert pixel format! Return code: [0x%x]" % ret_convert, file=sys.stderr)
                        print("Attempting to save original raw image, but it might fail.", file=sys.stderr)

                stSaveParam = MV_SAVE_IMAGE_TO_FILE_PARAM_EX()
                memset(byref(stSaveParam), 0, sizeof(stSaveParam))

                stSaveParam.pData = image_data_to_save
                stSaveParam.nDataLen = image_data_len_to_save
                stSaveParam.enPixelType = image_pixel_type_to_save
                stSaveParam.nWidth = stOutFrame.stFrameInfo.nWidth
                stSaveParam.nHeight = stOutFrame.stFrameInfo.nHeight
                stSaveParam.enImageType = MV_Image_Jpeg
                stSaveParam.nQuality = 80

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = os.path.join(output_dir, f"captured_image_{timestamp}.jpg")
                filename_bytes = filename.encode('ascii')

                c_filename_buffer = create_string_buffer(filename_bytes, 256)
                stSaveParam.pcImagePath = cast(c_filename_buffer, POINTER(c_char))

                print(f"Saving image to {filename}...")
                ret_save = cam.MV_CC_SaveImageToFileEx(stSaveParam)
                if ret_save == 0:
                    print(f"Image saved successfully as {filename}")
                    _captured_image_path_internal = filename
                else:
                    print(f"Failed to save image! Return code: [0x%x]" % ret_save, file=sys.stderr)
                    _captured_image_path_internal = None

                cam.MV_CC_FreeImageBuffer(stOutFrame)
            else:
                print(f"No data [0x{ret:x}] or failed to get image buffer within timeout.", file=sys.stderr)
                _captured_image_path_internal = None

            _capture_event_internal.clear()
            capture_done_event.set() # Signal that capture/save attempt is done

    # print("Internal work thread exiting.") # Avoid verbose output in module


def capture_and_save_single_image(output_dir='.', camera_index=0):
    """
    Captures a single image from the camera and saves it to the specified directory.
    Initializes and cleans up camera resources for a single shot.

    Args:
        output_dir (str): Directory where the image will be saved.
        camera_index (int): The index of the camera to connect to.

    Returns:
        str: The path to the saved image, or None if capture fails.
    """
    global _g_bExit_internal
    global _capture_event_internal
    global _captured_image_path_internal

    _g_bExit_internal = False
    _captured_image_path_internal = None
    _capture_event_internal.clear()

    capture_done_event = threading.Event()

    os.makedirs(output_dir, exist_ok=True)

    print(f"Attempting to capture image to directory: {output_dir}")

    ret_sdk_init = MvCamera.MV_CC_Initialize()
    if ret_sdk_init != 0:
        print(f"Failed to initialize SDK! Return code: [0x{ret_sdk_init:x}]", file=sys.stderr)
        return None

    print (f"SDKVersion[0x{MvCamera.MV_CC_GetSDKVersion():x}]")

    deviceList = MV_CC_DEVICE_INFO_LIST()
    tlayerType = MV_GIGE_DEVICE | MV_USB_DEVICE

    ret_enum = MvCamera.MV_CC_EnumDevices(tlayerType, deviceList)
    if ret_enum != 0:
        print (f"Enum devices fail! Return code: [0x{ret_enum:x}]", file=sys.stderr)
        MvCamera.MV_CC_Finalize()
        return None

    if deviceList.nDeviceNum == 0:
        print ("Find no device!", file=sys.stderr)
        MvCamera.MV_CC_Finalize()
        return None

    print (f"Find {deviceList.nDeviceNum} devices!")

    for i in range(0, deviceList.nDeviceNum):
        mvcc_dev_info = cast(deviceList.pDeviceInfo[i], POINTER(MV_CC_DEVICE_INFO)).contents
        if mvcc_dev_info.nTLayerType == MV_GIGE_DEVICE:
            model_name = "".join(chr(per) for per in mvcc_dev_info.SpecialInfo.stGigEInfo.chModelName if per != 0)
            ip_address = ".".join(str(((mvcc_dev_info.SpecialInfo.stGigEInfo.nCurrentIp >> (8 * (3-j))) & 0xFF)) for j in range(4))
            print(f"  Gige device: [{i}] Model: {model_name}, IP: {ip_address}")
        elif mvcc_dev_info.nTLayerType == MV_USB_DEVICE:
            model_name = "".join(chr(per) for per in mvcc_dev_info.SpecialInfo.stUsb3VInfo.chModelName if per != 0)
            serial_number = "".join(chr(per) for per in mvcc_dev_info.SpecialInfo.stUsb3VInfo.chSerialNumber if per != 0)
            print(f"  U3V device: [{i}] Model: {model_name}, S/N: {serial_number}")

    nConnectionNum = camera_index

    if int(nConnectionNum) >= deviceList.nDeviceNum or int(nConnectionNum) < 0:
        print (f"Input error! Configured device index {nConnectionNum} is out of range (0-{deviceList.nDeviceNum-1}).", file=sys.stderr)
        MvCamera.MV_CC_Finalize()
        return None

    cam = MvCamera()
    stDeviceList = cast(deviceList.pDeviceInfo[int(nConnectionNum)], POINTER(MV_CC_DEVICE_INFO)).contents
    
    ret_handle = cam.MV_CC_CreateHandle(stDeviceList)
    if ret_handle != 0:
        print (f"Create handle fail! Return code: [0x{ret_handle:x}]", file=sys.stderr)
        MvCamera.MV_CC_Finalize()
        return None

    ret_open = cam.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0)
    if ret_open != 0:
        print (f"Open device fail! Return code: [0x{ret_open:x}]", file=sys.stderr)
        cam.MV_CC_DestroyHandle()
        MvCamera.MV_CC_Finalize()
        return None
        
    # Set exposure settings **after device is open** TO SMO DODALI!!!!!!!
    ret_auto = cam.MV_CC_SetEnumValue("ExposureAuto", 0)  # 0 = off/manual
    if ret_auto != 0:
        print(f"Failed to disable auto exposure! Return code: [0x{ret_auto:x}]", file=sys.stderr)

    exposure_time_us = 60000
    ret_exp = cam.MV_CC_SetFloatValue("ExposureTime", exposure_time_us)
    if ret_exp != 0:
        print(f"Failed to set exposure time! Return code: [0x{ret_exp:x}]", file=sys.stderr)

    if stDeviceList.nTLayerType == MV_GIGE_DEVICE:
        nPacketSize = cam.MV_CC_GetOptimalPacketSize()
        if int(nPacketSize) > 0:
            ret_packet_size = cam.MV_CC_SetIntValue("GevSCPSPacketSize",nPacketSize)
            if ret_packet_size != 0:
                print (f"Warning: Set Packet Size fail! Return code: [0x{ret_packet_size:x}]", file=sys.stderr)
        else:
            print (f"Warning: Get Packet Size fail! Return code: [0x{nPacketSize:x}]", file=sys.stderr)

    ret_trigger_mode = cam.MV_CC_SetEnumValue("TriggerMode", MV_TRIGGER_MODE_OFF)
    if ret_trigger_mode != 0:
        print (f"Set trigger mode fail! Return code: [0x{ret_trigger_mode:x}]", file=sys.stderr)
        cam.MV_CC_CloseDevice()
        cam.MV_CC_DestroyHandle()
        MvCamera.MV_CC_Finalize()
        return None

    stParam = MVCC_INTVALUE()
    memset(byref(stParam), 0, sizeof(MVCC_INTVALUE))
    ret_payload = cam.MV_CC_GetIntValue("PayloadSize", stParam)
    if ret_payload != 0:
        print (f"Get payload size fail! Return code: [0x{ret_payload:x}]", file=sys.stderr)
        cam.MV_CC_CloseDevice()
        cam.MV_CC_DestroyHandle()
        MvCamera.MV_CC_Finalize()
        return None
    nPayloadSize = stParam.nCurValue
    


    ret_grabbing = cam.MV_CC_StartGrabbing()
    if ret_grabbing != 0:
        print (f"Start grabbing fail! Return code: [0x{ret_grabbing:x}]", file=sys.stderr)
        cam.MV_CC_CloseDevice()
        cam.MV_CC_DestroyHandle()
        MvCamera.MV_CC_Finalize()
        return None

    data_buf = (c_ubyte * nPayloadSize)()

    try:
        hThreadHandle = threading.Thread(target=_work_thread_internal, args=(cam, output_dir, capture_done_event))
        hThreadHandle.daemon = True
        hThreadHandle.start()
    except Exception as e:
        print (f"Error: unable to start capture thread: {e}", file=sys.stderr)
        cam.MV_CC_StopGrabbing()
        cam.MV_CC_CloseDevice()
        cam.MV_CC_DestroyHandle()
        MvCamera.MV_CC_Finalize()
        return None

    print ("Camera ready. Triggering single image capture...")
    _capture_event_internal.set() # Signal the internal thread to capture one image

    if not capture_done_event.wait(timeout=15):
        print("Image capture timed out or failed to complete saving.", file=sys.stderr)
        _g_bExit_internal = True
        _capture_event_internal.set()
        hThreadHandle.join(timeout=1)
        _captured_image_path_internal = None
    else:
        if _captured_image_path_internal:
            print(f"Image capture process signaled completion. Captured image path: {_captured_image_path_internal}")
        else:
            print("Image capture process signaled completion, but no image path was stored (likely due to save failure).", file=sys.stderr)


    _g_bExit_internal = True
    _capture_event_internal.set()
    hThreadHandle.join(timeout=2)

    ret_stop = cam.MV_CC_StopGrabbing()
    if ret_stop != 0:
        print (f"Stop grabbing fail! Return code: [0x{ret_stop:x}]", file=sys.stderr)
    ret_close = cam.MV_CC_CloseDevice()
    if ret_close != 0:
        print (f"Close device fail! Return code: [0x{ret_close:x}]", file=sys.stderr)
    ret_destroy = cam.MV_CC_DestroyHandle()
    if ret_destroy != 0:
        print (f"Destroy handle fail! Return code: [0x{ret_destroy:x}]", file=sys.stderr)
    MvCamera.MV_CC_Finalize()
    print("Camera resources cleaned up.")

    del data_buf

    return _captured_image_path_internal

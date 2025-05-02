import cv2
import time


def start_webcam(camera_index = 0) -> cv2.VideoCapture|None:
    """Startup the webcam and try to read a frame from it.

    Make sure to release it when unused for longer period.
    It will give the webcam a second to focus itself."""
    print(f"[Webcam] Loading webcam at index {camera_index}...")
    cap = cv2.VideoCapture(camera_index)

    # Check if the camera opened successfully
    if not cap.isOpened():
        print(f"[Webcam] Error: Could not open video device {camera_index}")
        return None

    # Configure properties
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    # Allow the camera to warm up and adjust exposure
    print("[Webcam] Allowing webcam to focus...")
    time.sleep(1)

    # Read a frame, shouldn't fail.
    ret, frame = cap.read()
    if not ret:
        print(f"[Webcam] Error: Failed to read frame: ${ret}")
        return None

    # All good!
    return cap


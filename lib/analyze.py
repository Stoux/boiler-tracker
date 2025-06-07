import datetime
import time
from dataclasses import dataclass
import cv2
import numpy as np
import collections
from loguru import logger
from typing import List, Tuple, Union, Optional

from lib.errors import generate_error_image_path

# --- Configuration

# Region of Interest = ROI

# Number of frames to check with a given interval between each frame. Should allow us to detect blinking & rule out any anomalies.
NUMBER_OF_FRAMES = 30
TIME_BETWEEN_FRAMES = 0.2

# ROI for detecting if the general light is on
GENERAL_LIGHT_ROI = [425, 115, 460, 275]
# Average brightness of the GENERAL_LIGHT_ROI to be counted as on
GENERAL_LIGHT_BRIGHTNESS_THRESHOLD = 100 # Example value (0-255 range)

# ROI for detecting whether the button is pressed (lights will be extra bright, shining on the button(s))
IS_PRESSED_ROI = [240, 165, 270, 190]
# Percentage of pixels in the ROI that should be green to be counted as on
PRESSED_REQUIRED_PERCENTAGE_GREEN = 25

# ROIs for each light (0-indexed) and the areas we should check for green light
# If the webcam ever moves, we're fucked :)
LIGHT_ROIS = [
    [
        # Light 1
        [ 110, 122, 128, 226 ],
        [ 128, 122, 164, 151 ],
    ],
    [
        # Light 2
        [ 183, 139, 221, 168 ],
        [ 207, 168, 230, 216]
    ],
    [
        # Light 3,
        [ 221, 245, 236, 296 ],
        [ 174, 306, 237, 328 ],
    ],
    [
        # Light 4
        [ 113, 230, 142, 335 ],
        [ 142, 314, 173, 330]
    ]
]
# Percentage of pixels each ROI should be green to be counted as on
LIGHT_REQUIRED_PERCENTAGE_GREEN = 50

# -- Tuned green bounds for detecting

# [1] Detect PRESSED state. If pressed, can also be used to detect all lights, in both light & dark scenario's.
PRESSED_LOWER_GREEN = np.array([45, 50, 45])
PRESSED_UPPER_GREEN = np.array([95, 255, 255])

# [2] Light scenario & not PRESSED
LIGHT_LOWER_GREEN = np.array([45, 40, 70])
LIGHT_UPPER_GREEN = np.array([95, 255, 255])

# [3] Dark scenario & not PRESSED
DARK_LOWER_GREEN = np.array([45, 40, 30])
DARK_UPPER_GREEN = np.array([95, 255, 255])


# -- Data class for return status

@dataclass
class FrameData:
    """Data for a single frame with its analysis results."""
    original_frame: cv2.typing.MatLike
    annotated_frame: cv2.typing.MatLike
    light_value: Union[str, int]

@dataclass
class BoilerStatus:
    """The current boiler status."""
    # Whether the boiler is currently heating
    heating: bool
    # The number of lights that are currently on (1-4)
    lights_on: int
    # Whether the general (room) light is currently on
    general_light_on: bool
    # List of frames with their annotated versions showing light values
    frames: List[FrameData]
    # List of frames with frequency annotations
    frequency_frames: List[FrameData] = None
    # Lower green HSV threshold used for detection
    lower_green: np.ndarray = None
    # Upper green HSV threshold used for detection
    upper_green: np.ndarray = None

@dataclass
class BoilerErrorStatus:
    """The current boiler error status."""
    # List of frames with their annotated versions showing light values
    frames: List[FrameData]
    # List of frames with frequency annotations
    frequency_frames: List[FrameData] = None

# -- Internal functions

def is_percentage_reached(total, count, percentage) -> bool:
    return count > (total * (percentage / 100))


def determine_general_light(frame: cv2.typing.MatLike) -> bool:
    # Extract the ROI from the image
    (x1, y1, x2, y2) = GENERAL_LIGHT_ROI
    img = frame[y1:y2, x1:x2]

    # Convert it to gray scale
    gray_img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Get the average brightness of the ROI
    avg_brightness = cv2.mean(gray_img)[0]

    # Should be higher than our threshold to be counted as on / off
    return avg_brightness > GENERAL_LIGHT_BRIGHTNESS_THRESHOLD

def determine_pressed_state(frame: cv2.typing.MatLike) -> bool:
    # Convert the image to HSV for proper green detection
    hsv_img = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    # Extract the ROI from the image
    (x1, y1, x2, y2) = IS_PRESSED_ROI
    roi_hsv_img = hsv_img[y1:y2, x1:x2]

    # Create mask for green
    roi_hsv_mask = cv2.inRange(roi_hsv_img, PRESSED_LOWER_GREEN, PRESSED_UPPER_GREEN)

    # Count the number of green pixels in that ROI
    total_size = (x2 - x1) * (y2 - y1)
    green_pixels = cv2.countNonZero(roi_hsv_mask)

    return is_percentage_reached(total_size, green_pixels, PRESSED_REQUIRED_PERCENTAGE_GREEN)

def determine_number_of_lights_in_frame(frame: cv2.typing.MatLike, lower_green, upper_green) -> int|None:
    # Convert the image to HSV for proper green detection
    hsv_img = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    # Assume none of the lights are on
    lights_on = 0

    # Loop through each light
    for light_index, light_rois in enumerate(LIGHT_ROIS):
        # Each light has a set of ROIs. Count total pixels of all those ROIs & total that are green
        total_pixels = 0
        green_pixels = 0

        # Loop trough each ROI for that light and attempt to fetch the number of green pixels
        for (x1, y1, x2, y2) in light_rois:
            # Add total size of this block to total pixels
            roi_size = (x2 - x1) * (y2 - y1)
            total_pixels += roi_size

            # Extract ROI
            roi_hsv = hsv_img[y1:y2, x1:x2]
            if roi_hsv.size == 0:
                logger.error(f"ROI {light_index} is empty or invalid. {x1} {y1} {x2} {y2}")
                return None

            # Create mask for green
            roi_mask = cv2.inRange(roi_hsv, lower_green, upper_green)

            # Count green pixels
            roi_active = cv2.countNonZero(roi_mask)
            green_pixels += roi_active


        # Assume the light is on when threshold is reached
        light_is_on = is_percentage_reached(total_pixels, green_pixels, LIGHT_REQUIRED_PERCENTAGE_GREEN)
        if light_is_on:
            # Up the number of lights on.
            if lights_on != light_index:
                logger.warning(f"Previous light {light_index} was not detected as on while the current is {light_index + 1}. Invalid result!")
                return None
            lights_on = light_index + 1

    return lights_on


# -- Public function

def analyze( cap: cv2.VideoCapture ) -> BoilerStatus|None:
    # Fetch an initial image for general flags
    logger.info("[CHECK] Getting initial image to be used for general checks")
    ret, frame = cap.read()
    if not ret:
        logger.error("[CHECK] Error: Failed to capture frame")
        return None

    # Use that initial image to check the general (room) light
    logger.info("[CHECK] Checking general light status")
    general_light_on = determine_general_light(frame)

    # Use that initial image to determine the "Pressed" state of the boiler button (which heavily increases the brightness of the LEDs; requiring different green thresholds)
    logger.info(f"[CHECK] Starting analysis over {NUMBER_OF_FRAMES} frames with {TIME_BETWEEN_FRAMES} between frames.")
    is_pressed = determine_pressed_state(frame)

    # Determine the green bounds based on the previous variables
    if is_pressed:
        lower_green = PRESSED_LOWER_GREEN
        upper_green = PRESSED_UPPER_GREEN
    elif general_light_on:
        lower_green = LIGHT_LOWER_GREEN
        upper_green = LIGHT_UPPER_GREEN
    else:
        lower_green = DARK_LOWER_GREEN
        upper_green = DARK_UPPER_GREEN

    # Starting looping for the given number of frames
    determined_light_values: List[int] = []
    failed_frames: int = 0
    stored_frames: List[FrameData] = []  # Store frames with their light values

    for frame_index in range(NUMBER_OF_FRAMES):
        # Read a frame
        ret, frame = cap.read()
        if not ret:
            logger.error("[CHECK] Error: Failed to capture frame")
            return None

        # Determine the number of lights
        lights_on = determine_number_of_lights_in_frame(frame, lower_green, upper_green)
        if lights_on is None:
            # Invalid value, our upper/lower green bounds configuration is wrong!
            failed_frames += 1
            # Enable for debugging
            error_image = generate_error_image_path()
            cv2.imwrite(error_image, frame)
            logger.warning(f"Invalid frame #{frame_index} ({failed_frames}/{NUMBER_OF_FRAMES}): {error_image}")

            # Create a copy with error text
            annotated_frame = frame.copy()
            cv2.putText(annotated_frame, "ERROR", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            stored_frames.append(FrameData(original_frame=frame, annotated_frame=annotated_frame, light_value="ERROR"))
            continue

        # Add to the list of values
        determined_light_values.append(lights_on)

        # Create a copy with light value text
        annotated_frame = frame.copy()
        cv2.putText(annotated_frame, f"Lights: {lights_on}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        stored_frames.append(FrameData(original_frame=frame, annotated_frame=annotated_frame, light_value=lights_on))

        # Wait a bit (except on last frame)
        if frame_index != (NUMBER_OF_FRAMES - 1):
            time.sleep(TIME_BETWEEN_FRAMES)

    # Check if not too many failed values
    if failed_frames > (NUMBER_OF_FRAMES / 4):
        logger.warning("[CHECK] Error: Failed to resolve too many frames?")
        return None

    # Count the number of identical values in the unit
    top_values = collections.Counter(determined_light_values)
    top_two_values = top_values.most_common(2)
    if not top_two_values:
        logger.error("[CHECK] Error: Failed to determine top two values?")
        return None

    # Determine the state
    heating = False
    lights_on = 0

    if len(top_two_values) == 1:
        # If there's only one value: all frames resulted in the same number of lights on.
        value1, count1 = top_two_values[0]
        lights_on = value1
    else:
        # Multiple values. Determine if we're blinking or if was just some error
        value1, count1 = top_two_values[0]
        value2, count2 = top_two_values[1]

        # Determine the highest light count of those two
        lights_on = value1 if value1 > value2 else value2

        # More than 25% of the time that we detected a different value? Assume it's blinking.
        if count2 > (NUMBER_OF_FRAMES / 4):
            heating = True

            # Those two values should be right next to each other tho.
            if not ( value1 == value2 - 1 ) and not (value1 - 1 == value2):
                logger.warning("[CHECK] Error: Top two determined 'lights on' values are not next to each other. Faulty values?")
                return None

    # Assume is fully empty when only 1 light on & not heating
    if lights_on == 1 and not heating:
        lights_on = 0

    # Create frequency-annotated frames
    frequency_frames = []
    for light_value, count in top_values.items():
        # Find the first frame with this light value
        for frame_data in stored_frames:
            if frame_data.light_value == light_value:
                # Create a copy of the frame with frequency annotation
                frequency_frame = frame_data.annotated_frame.copy()
                # Add text in the top right corner
                cv2.putText(frequency_frame, f"{count}x", (frame_data.original_frame.shape[1] - 80, 30), 
                           cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                # Add to the list
                frequency_frames.append(FrameData(
                    original_frame=frame_data.original_frame,
                    annotated_frame=frequency_frame,
                    light_value=light_value
                ))
                break

    return BoilerStatus(heating, lights_on, general_light_on, stored_frames, frequency_frames, lower_green, upper_green)

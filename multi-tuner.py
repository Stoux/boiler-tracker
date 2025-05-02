import cv2
import numpy as np
import os
import glob
import math

# Absolutely hacked together & heavily copied garbage this

# --- Configuration ---
IMAGE_FOLDER = "images/errors"
DISPLAY_ITEM_WIDTH = 640 # Resize the images if ya want. This fucks with the ROIs tho.

# --- Helper Functions ---
def nothing(x):
    # Dummy callback function for trackbars
    pass

def load_images_from_folder(folder):
    """Loads images from a folder, filtering by common extensions."""
    images = []
    filenames = []
    supported_extensions = ["*.png", "*.jpg", "*.jpeg"]
    print(f"Loading images from: {os.path.abspath(folder)}")
    if not os.path.isdir(folder):
        print(f"Error: Folder not found at '{folder}'")
        return images, filenames

    for ext in supported_extensions:
        for filepath in glob.glob(os.path.join(folder, ext)):
            img = cv2.imread(filepath)
            if img is not None:
                images.append(img)
                filenames.append(os.path.basename(filepath))
            else:
                print(f"Warning: Could not read image '{filepath}'")
    print(f"Loaded {len(images)} images.")
    return images, filenames

# - Load Images
frames, filenames = load_images_from_folder(IMAGE_FOLDER)
if not frames:
    print("No images loaded. Exiting.")
    exit()

# - Pre-process Images (Get dimensions, Convert to HSV)
hsv_images = []
original_height, original_width = frames[0].shape[:2] # Get dimensions from first image
aspect_ratio = original_height / original_width
display_item_height = int(DISPLAY_ITEM_WIDTH * aspect_ratio) # Calculate height for display items

print(f"Display item size: {DISPLAY_ITEM_WIDTH}x{display_item_height}")

for frame in frames:
    # Optional: Check if images have different sizes - resizing originals for consistency might be needed
    if frame.shape[0] != original_height or frame.shape[1] != original_width:
        print(f"Warning: Image {filenames[len(hsv_images)]} has different dimensions ({frame.shape[1]}x{frame.shape[0]}).")

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    hsv_images.append(hsv)


# 3. Setup GUI Windows and Trackbars
cv2.namedWindow("Trackbars")
cv2.namedWindow("Originals and Masks") # Window to display interleaved images

# ==== Configured tuning

# [1] Detect PRESSED state. If pressed, can also be used to detect all lights, in both light & dark scenario's.
# LOWER_GREEN = np.array([45, 50, 90])
# UPPER_GREEN = np.array([95, 255, 255])

# [2] Light scenario & not PRESSED
# LOWER_GREEN = np.array([45, 40, 70])
# UPPER_GREEN = np.array([95, 255, 255])

# [3] Dark scenario & not PRESSED
# LOWER_GREEN = np.array([45, 40, 30])
# UPPER_GREEN = np.array([95, 255, 255])


# Create trackbars (set initial values based on previous tuning if available)
cv2.createTrackbar("L - H", "Trackbars", 45, 179, nothing) # Hue 0-179
cv2.createTrackbar("L - S", "Trackbars", 50, 255, nothing)
cv2.createTrackbar("L - V", "Trackbars", 90, 255, nothing)
cv2.createTrackbar("U - H", "Trackbars", 95, 179, nothing)
cv2.createTrackbar("U - S", "Trackbars", 255, 255, nothing)
cv2.createTrackbar("U - V", "Trackbars", 255, 255, nothing)

# 4. Calculate Grid Layout for Displaying Image Pairs
num_images = len(frames)
# Calculate layout based on the number of pairs (Original+Mask)
cols = int(math.ceil(math.sqrt(num_images)))
rows = int(math.ceil(num_images / cols))
print(f"Displaying {num_images} pairs in a {rows}x{cols} grid layout.")

# Create a blank canvas (3-channel BGR) to tile the images onto
# Width accommodates 'cols' number of pairs, each pair is 2 items wide
canvas_width = cols * 2 * DISPLAY_ITEM_WIDTH
canvas_height = rows * display_item_height
# Initialize with a mid-gray value (128, 128, 128)
canvas = np.full((canvas_height, canvas_width, 3), (128, 128, 128), dtype=np.uint8)


print("\nAdjust sliders to isolate the desired color across all images.")
print("Compare Original (left) with Mask (right) for each pair.")
print("Press 'q' to quit and print the final values.")

# ROI for detecting if the general light is on
GENERAL_LIGHT_ROI = [425, 115, 460, 275]
# Average brightness of the GENERAL_LIGHT_ROI to be counted as on
BRIGHTNESS_THRESHOLD = 100 # Example value (0-255 range)

# ROI for detecting whether the button is pressed (lights will be extra bright, shining on the button(s))
IS_PRESSED_ROI = [240, 165, 270, 190]
PRESSED_REQUIRED_PERCENTAGE_GREEN = 25

# ROIs for each light (0-indexed) and the areas we should check for green light
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

# The required percentage of pixels each ROI should be green to be counted as on
# TODO: Implement
LIGHT_REQUIRED_PERCENTAGE_GREEN = 50

# 5. Main Loop for Interactive Tuning
while True:
    # Get current positions from trackbars
    l_h = cv2.getTrackbarPos("L - H", "Trackbars")
    l_s = cv2.getTrackbarPos("L - S", "Trackbars")
    l_v = cv2.getTrackbarPos("L - V", "Trackbars")
    u_h = cv2.getTrackbarPos("U - H", "Trackbars")
    u_s = cv2.getTrackbarPos("U - S", "Trackbars")
    u_v = cv2.getTrackbarPos("U - V", "Trackbars")

    lower_bound = np.array([l_h, l_s, l_v])
    upper_bound = np.array([u_h, u_s, u_v])

    # Clear the canvas (or re-initialize)
    canvas.fill(128) # Fill with gray again

    # Process each image and update the canvas
    for i, (frame, hsv_img) in enumerate(zip(frames, hsv_images)):
        # Create the mask
        mask = cv2.inRange(hsv_img, lower_bound, upper_bound)

        # Resize original and mask for display
        display_original = cv2.resize(frame, (DISPLAY_ITEM_WIDTH, display_item_height))
        display_mask_gray = cv2.resize(mask, (DISPLAY_ITEM_WIDTH, display_item_height), interpolation=cv2.INTER_NEAREST)

        # Convert single-channel mask to 3-channel BGR to place on canvas
        display_mask_bgr = cv2.cvtColor(display_mask_gray, cv2.COLOR_GRAY2BGR)


        # Determine whether the general light is on
        if GENERAL_LIGHT_ROI is not None:
            # Extract the ROI from the image
            (x1, y1, x2, y2) = GENERAL_LIGHT_ROI
            gen_light_img = frame[y1:y2, x1:x2]
            # Convert it to gray scale
            gen_light_gray = cv2.cvtColor(gen_light_img, cv2.COLOR_BGR2GRAY)
            # Get the average brightness of the ROI
            gen_light_avg_brightness = cv2.mean(gen_light_gray)[0]
            # Should be higher than our threshold to be counted as on / off
            gen_light_is_on = gen_light_avg_brightness > BRIGHTNESS_THRESHOLD

            # Show in picture
            display_mask_bgr = cv2.putText(display_mask_bgr, "Light" if gen_light_is_on else "Dark", (10, 100), cv2.FONT_HERSHEY_TRIPLEX, 2.2,
                                           (0, 255, 0) if gen_light_is_on else  (0, 0, 255), 2)


        # Determine whether the button is pressed & lights are extra bright
        if IS_PRESSED_ROI is not None:
            # Extract the ROI from the image
            (x1, y1, x2, y2) = IS_PRESSED_ROI
            pressed_hsv_img = hsv_img[y1:y2, x1:x2]
            pressed_roi_size = (x2 - x1) * (y2 - y1)

            # Create mask for green
            pressed_hsv_mask = cv2.inRange(pressed_hsv_img, lower_bound, upper_bound)

            # Count the number of green pixels in that ROI
            pressed_green_pixels = cv2.countNonZero(pressed_hsv_mask)
            # Should be minimum percentage
            pressed_active = pressed_green_pixels > (pressed_roi_size * ( PRESSED_REQUIRED_PERCENTAGE_GREEN / 100 ) )

            if pressed_active:

                display_mask_bgr = cv2.putText(display_mask_bgr, "Pressed", (10, 370),
                                               cv2.FONT_HERSHEY_TRIPLEX, 2,
                                               (0, 255, 0), 2)


        # Draw rectangles & calculate
        light_statuses = []
        for light_index, light_rois in enumerate(LIGHT_ROIS):
            total_pixels = 0
            light_green_pixels = 0
            for (x1, y1, x2, y2) in light_rois:
                # Add total size of this block to total pixels
                roi_size = (x2 - x1) * (y2 - y1)
                total_pixels += roi_size

                # Extract ROI
                roi_hsv = hsv_img[y1:y2, x1:x2]

                if roi_hsv.size == 0:
                    print(f"Warning: ROI {light_index} is empty or invalid. {x1} {y1} {x2} {y2}")
                    continue

                # Convert ROI to HSV
                # roi_hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)

                # Create mask for green
                roi_mask = cv2.inRange(roi_hsv, lower_bound, upper_bound)

                # Count green pixels
                roi_active = cv2.countNonZero(roi_mask)
                light_green_pixels += roi_active

                roi_is_on = roi_active > (roi_size / 2)

                # Draw a rectangle on the debug
                cv2.rectangle(display_mask_bgr, (x1, y1), (x2, y2), (0, 255, 0), 1)

            # Assume the light is on with minimum 50%
            light_is_on = light_green_pixels > ( total_pixels / 2 )
            light_status = f"{light_index + 1} @ {'ON' if light_is_on else 'OFF'}"
            # light_statuses.append(f"Light {light_index + 1} @ {light_green_pixels} pixels: {'ON' if light_is_on else 'OFF'}")
            display_mask_bgr = cv2.putText(display_mask_bgr, light_status, (350, 50 + (light_index * 100)), cv2.FONT_HERSHEY_TRIPLEX, 2.2,
                                           (0, 255, 0) if light_is_on else  (0, 0, 255), 2)

        # Show the image status inside the image
        # image_status = "\n".join(light_statuses)
        # display_mask_bgr = cv2.putText(display_mask_bgr, image_status, ( 10, 50 ), cv2.FONT_HERSHEY_TRIPLEX, 1, (255, 255, 255), 1)

        # Calculate position in the grid for the i-th pair
        row = i // cols
        col = i % cols

        # Calculate pixel offsets for pasting
        y_offset = row * display_item_height
        x_offset_orig = col * 2 * DISPLAY_ITEM_WIDTH
        x_offset_mask = x_offset_orig + DISPLAY_ITEM_WIDTH

        # Place the original image onto the canvas
        if y_offset + display_item_height <= canvas_height and x_offset_orig + DISPLAY_ITEM_WIDTH <= canvas_width:
             canvas[y_offset : y_offset + display_item_height, x_offset_orig : x_offset_orig + DISPLAY_ITEM_WIDTH] = display_original
        else:
             print(f"Warning: Original image {i} position exceeds canvas bounds.")

        # Place the mask image onto the canvas next to the original
        if y_offset + display_item_height <= canvas_height and x_offset_mask + DISPLAY_ITEM_WIDTH <= canvas_width:
             canvas[y_offset : y_offset + display_item_height, x_offset_mask : x_offset_mask + DISPLAY_ITEM_WIDTH] = display_mask_bgr
        else:
             print(f"Warning: Mask {i} position exceeds canvas bounds.")


    # Display the combined originals and masks
    cv2.imshow("Originals and Masks", canvas)

    # Exit loop if 'q' is pressed
    key = cv2.waitKey(1) & 0xFF
    if key == ord('q'):
        break

# 6. Print Final Values and Cleanup
print("\n--- Final Tuned Values ---")
print(f"LOWER_BOUND = np.array([{l_h}, {l_s}, {l_v}])")
print(f"UPPER_BOUND = np.array([{u_h}, {u_s}, {u_v}])")

cv2.destroyAllWindows()
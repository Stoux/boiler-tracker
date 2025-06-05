import threading
import time
import os
import sys
import json
from dotenv import load_dotenv
import paho.mqtt.client as paho
from loguru import logger
from datetime import datetime, timezone


from lib.analyze import analyze
from lib.errors import run_cleanup
from lib.mqtt import create_mqtt_client, publish
from lib.webcam import start_webcam
from lib.http_server import start_http_server, update_status, get_image_urls

# Load .env variables
load_dotenv()

WATCHER_SLEEP_SECONDS=int(os.getenv('WATCHER_SLEEP_SECONDS', "60"))
LOG_DIR=os.getenv('LOG_DIR', "./logs")

# Configure Loguru
logger.remove() # Remove default handler to avoid duplicate console output if any
logger.add(sys.stderr, level="INFO", format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>") # Console output
logger.add(LOG_DIR + "/app_{time:YYYY-MM-DD}.log", rotation="10 MB", retention="7 days", level="DEBUG", format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}") # File output

# Topics
GENERAL_LIGHT_STATE_TOPIC = "homeassistant/binary_sensor/storage_room/light/state"
HEATING_STATE_TOPIC = "homeassistant/binary_sensor/boiler/heating/state"
PERCENTAGE_STATE_TOPIC = "homeassistant/sensor/boiler/percentage/state"
ERROR_STATE_TOPIC = "homeassistant/binary_sensor/boiler/error/state"
LAST_FORCE_CHECK_TOPIC = "homeassistant/sensor/boiler/last_force_check/state"
FRAMES_URLS_TOPIC = "homeassistant/sensor/boiler/frames_urls/state"
FREQUENCY_FRAMES_URLS_TOPIC = "homeassistant/sensor/boiler/frequency_frames_urls/state"

# HTTP server settings
HTTP_SERVER_PORT = 8800
BASE_URL = os.getenv('HTTP_URL_PREFIX', f"http://localhost:{HTTP_SERVER_PORT}")

# Create interrupt event to allow MQTT to force an instant check
force_check_event = threading.Event()
# Keep track of when to publish the last force check
should_publish_force_checked = False
# Custom waiting interval (generally used when action is currently happening around the boiler)
custom_waiting_interval: int = WATCHER_SLEEP_SECONDS
# Debug mode state
debug_mode_enabled = False

def bool_to_state( state: bool ) -> str:
    return "ON" if state else "OFF"

def lights_to_percentage( lights: int, heating: bool ) -> str:
    if lights == 0:
        return "0"
    if lights == 1:
        if heating:
            return "13"
        return "25"
    if lights == 2:
        if heating:
            return "38"
        return "50"
    if lights == 3:
        if heating:
            return "63"
        return "75"
    if lights == 4:
        if heating:
            return "88"
        return "100"

    logger.info(f"Unsupported number of lights: {lights}")
    exit(1)


def on_force_check_callback():
    """Callback when MQTT receives a message to force check"""
    logger.info("On force check callback")
    global force_check_event, should_publish_force_checked
    should_publish_force_checked = True
    force_check_event.set()

def on_custom_interval_callback(interval: str):
    """Callback when MQTT receives a message to change the waiting interval"""
    global custom_waiting_interval

    # Parse the message
    _interval = int(interval.strip() or "0")
    if _interval <= 0:
        logger.info(f"Restoring waiting interval to default ({WATCHER_SLEEP_SECONDS}s)")
        custom_waiting_interval = WATCHER_SLEEP_SECONDS
    else:
        logger.info(f"Custom waiting interval set to {_interval}")
        custom_waiting_interval = _interval

    # Instantly force a check
    on_force_check_callback()

def on_debug_mode_callback(enabled: bool):
    """Callback when MQTT receives a message to enable/disable debug mode"""
    global debug_mode_enabled, force_check_event

    # Update the debug mode state
    previous_state = debug_mode_enabled
    debug_mode_enabled = enabled

    logger.info(f"[Debug] Debug mode {'enabled' if enabled else 'disabled'}")

    # If debug mode is being disabled, interrupt any waiting thread
    if previous_state and not enabled:
        logger.info("[Debug] Interrupting wait due to debug mode being disabled")
        force_check_event.set()



def main_loop(client: paho.Client):
    # Use the global Thread event
    global force_check_event, should_publish_force_checked, custom_waiting_interval, debug_mode_enabled, status_history

    logger.info(f"[Main] Watch loop started. Checking every {custom_waiting_interval} seconds...")


    # Loop indefinitely
    while True:
        # Don't waste resources if we're not connected
        if not client.is_connected():
            logger.warning("[Check] MQTT client is not connected. Skipping analysis.")
            time.sleep(5)
            continue

        # Check if we're in debug mode and should wait indefinitely
        if debug_mode_enabled and not should_publish_force_checked:
            logger.info("[Check] Debug mode enabled and no force check requested. Waiting indefinitely...")
            # Wait indefinitely for a thread interrupt
            force_check_event.wait()
            logger.info("[Check] Wait interrupted by MQTT event!")
            # Reset the event flag
            force_check_event.clear()
            # Skip to the next iteration if this was just a debug mode toggle
            if not should_publish_force_checked:
                continue

        # Load the camera
        logger.info("[Check] Starting check: Loading camera")
        cap = start_webcam()
        if cap is None:
            logger.warning("[Check] Failed to start camera...")
            return False

        # Analyze the result
        status = analyze(cap)

        # TODO: Check if we have had a big change compared to last run
        # TODO: If yes: run again to verify before pushing it out.
        # TODO: [NTH] Dump images if we big jump (i.e. 100 -> 0).
        # // Mostly to combat random

        # Release the camera
        cap.release()

        # Check if we're still connected
        if not client.is_connected():
            logger.warning("[Check] MQTT client is not connected. Cannot publish.")
            time.sleep(5)
            continue

        # Publish error if we failed to analyse
        if status is None:
            logger.warning("[Check] Failed to analyze status...")
            publish(client, ERROR_STATE_TOPIC, bool_to_state(True))
            continue

        # Reset the threading event if a force was called while we were busy
        force_check_event.clear()

        # Update the HTTP server status
        logger.info("[Check] Updating HTTP server status")
        status_changed = update_status(status, BASE_URL)

        # Get image URLs
        image_urls = get_image_urls()

        # Publish image URLs
        if image_urls["frames"]:
            publish(client, FRAMES_URLS_TOPIC, json.dumps(image_urls["frames"]))
        if image_urls["frequency_frames"]:
            publish(client, FREQUENCY_FRAMES_URLS_TOPIC, json.dumps(image_urls["frequency_frames"]))

        # Check if we've hit a different result than last time
        if status_changed:
            # Different! We've got to be 100% sure this it the output. Instantly run again.
            logger.info('[Check] Status is different from last check. Instantly run again to double check!.')
            continue

        # We've confirmed the same status at least two times in a row.
        logger.info("[Check] Status is confirmed at least twice. Update MQTT.")

        # Otherwise publish the state
        logger.info("[Check] Publishing status")
        publish(client, HEATING_STATE_TOPIC, bool_to_state(status.heating))
        publish(client, GENERAL_LIGHT_STATE_TOPIC, bool_to_state(status.general_light_on))
        publish(client, PERCENTAGE_STATE_TOPIC, lights_to_percentage(status.lights_on, status.heating))
        publish(client, ERROR_STATE_TOPIC, bool_to_state(False))

        # Possibly publish the last check state
        if should_publish_force_checked:
            publish(client, LAST_FORCE_CHECK_TOPIC, datetime.now(timezone.utc).isoformat())
            should_publish_force_checked = False

        # Wait for the next round (or an interrupt)
        logger.info(f"[Check] Finished. Sleeping for {custom_waiting_interval} seconds...")
        thread_event_is_set = force_check_event.wait(timeout = custom_waiting_interval)
        if thread_event_is_set:
            logger.info("[Check] Wait interrupted by MQTT event!")

    return True


# Main execution!
if __name__ == '__main__':
    logger.info("[BOOT] === Starting boiler monitor ===")

    # Make sure the webcam is connected & accessible
    logger.info("[BOOT] => Checking webcam")
    camera = start_webcam()
    if camera is None:
        exit(1)
    # => Instantly release that camera as we don't currently need it
    camera.release()
    camera = None

    # Open a connection with the MQTT broker
    logger.info("[BOOT] => Connecting to MQTT broker")
    mqtt_client = create_mqtt_client(
        force_check_callback = on_force_check_callback,
        custom_interval_callback = on_custom_interval_callback,
        debug_mode_callback = on_debug_mode_callback,
    )

    # Start the error image dir clean up thread
    logger.info("[BOOT] => Starting error image dir cleaner")
    error_image_cleanup_event = threading.Event()
    error_image_cleanup_thread = threading.Thread(
        target=run_cleanup,
        args=(error_image_cleanup_event, ),
        daemon=True
    )
    error_image_cleanup_thread.start()

    # Start the HTTP server
    logger.info("[BOOT] => Starting HTTP server on port %d", HTTP_SERVER_PORT)
    http_server = start_http_server(HTTP_SERVER_PORT)
    logger.info(f"[BOOT] => HTTP server started at {BASE_URL}")

    # We've reached a workable state, enter the main loop
    try:
        success = main_loop(mqtt_client)
    except KeyboardInterrupt:
        logger.info("[SHUTDOWN] Interrupted by user.")
        success = False
    finally:
        logger.info("[SHUTDOWN] Exiting: Disconnect MQTT")
        mqtt_client.loop_stop()
        mqtt_client.disconnect()

        logger.info(f"[SHUTDOWN] Stopping image dir cleaner")
        error_image_cleanup_event.set()

        logger.info("[SHUTDOWN] Stopping HTTP server")
        http_server.shutdown()



    if success:
        logger.info("[SHUTDOWN] Goodbye!")
    else:
        logger.error("[SHUTDOWN] Exiting with error...")
        exit(1)

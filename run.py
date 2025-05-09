import threading
import time
import os
import sys
from dotenv import load_dotenv
import paho.mqtt.client as paho
from loguru import logger
from datetime import datetime, timezone


from lib.analyze import analyze
from lib.errors import run_cleanup
from lib.mqtt import create_mqtt_client, publish
from lib.webcam import start_webcam


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

# Create interrupt event to allow MQTT to force an instant check
force_check_event = threading.Event()
# Keep track of when to publish the last force check
should_publish_force_checked = False
# Custom waiting interval (generally used when action is currently happening around the boiler)
custom_waiting_interval: int = WATCHER_SLEEP_SECONDS

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



def main_loop(client: paho.Client):
    # Use the global Thread event
    global force_check_event, should_publish_force_checked, custom_waiting_interval

    logger.info(f"[Main] Watch loop started. Checking every {custom_waiting_interval} seconds...")


    # Loop indefinitely
    while True:
        # Don't waste resources if we're not connected
        if not client.is_connected():
            logger.warning("[Check] MQTT client is not connected. Skipping analysis.")
            time.sleep(5)
            continue

        # Load the camera
        logger.info("[Check] Starting check: Loading camera")
        cap = start_webcam()
        if cap is None:
            logger.warning("[Check] Failed to start camera...")
            return False

        # Analyze the result
        status = analyze(cap)

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



    if success:
        logger.info("[SHUTDOWN] Goodbye!")
    else:
        logger.error("[SHUTDOWN] Exiting with error...")
        exit(1)


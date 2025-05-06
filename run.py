import time
import os
import sys
from dotenv import load_dotenv
import paho.mqtt.client as paho
from loguru import logger
from datetime import datetime


from lib.analyze import analyze
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


def main_loop(client: paho.Client):
    logger.info(f"[Main] Watch loop started. Checking every {WATCHER_SLEEP_SECONDS} seconds...")

    has_published_config = False

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

        # Otherwise publish the state
        logger.info("[Check] Publishing status")
        publish(client, HEATING_STATE_TOPIC, bool_to_state(status.heating))
        publish(client, GENERAL_LIGHT_STATE_TOPIC, bool_to_state(status.general_light_on))
        publish(client, PERCENTAGE_STATE_TOPIC, lights_to_percentage(status.lights_on, status.heating))
        publish(client, ERROR_STATE_TOPIC, bool_to_state(False))

        print(f"[Check] Finished. Sleeping for {WATCHER_SLEEP_SECONDS} seconds...")
        time.sleep(WATCHER_SLEEP_SECONDS)

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
    print("[BOOT] => Connecting to MQTT broker")
    mqtt_client = create_mqtt_client()

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

    if success:
        logger.info("[SHUTDOWN] Goodbye!")
    else:
        logger.error("[SHUTDOWN] Exiting with error...")
        exit(1)


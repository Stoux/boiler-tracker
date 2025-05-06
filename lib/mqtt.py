import threading
from typing import Callable

import paho.mqtt.client as paho
import os
import json
from loguru import logger

has_published_config = False
_on_force_check_callback: Callable[[], None]|None = None

# Topic called by Home Assistant to force an update
FORCE_CHECK_TOPIC = "boiler_tracker/action/force_check"

# --- MQTT Callbacks ---
def on_connect(client, userdata, flags, rc, properties=None):

    broker = os.environ['MQTT_BROKER_ADDRESS']
    if rc == 0:
        logger.info(f"[MQTT] Connected to {broker}!")

        global has_published_config
        if not has_published_config:
            has_published_config = True
            publish_config(client)

    else:
        logger.error(f"[MQTT] Failed to connect to {broker}: return code {rc}")

def on_disconnect(client, userdata, rc, properties=None):
     logger.warning(f"[MQTT] Disconnected from {os.environ['MQTT_BROKER_ADDRESS']} with code {rc}")

def on_message(client, userdata, msg):
    #logger.info(f"[MQTT] Received message from {msg.topic}: {msg.payload}")
    # Check if topic is a force check
    if msg.topic == FORCE_CHECK_TOPIC and _on_force_check_callback is not None:
        logger.info(f"[MQTT] Force check command received")
        _on_force_check_callback()

    # Genuinely don't care about anything else.

# -- Main create function -->
def create_mqtt_client( force_check_callback: Callable[[], None] ) -> paho.Client:
    # Resolve env variables
    mqtt_broker_address = os.environ['MQTT_BROKER_ADDRESS']
    mqtt_port = int(os.environ['MQTT_PORT'])
    mqtt_username = os.environ['MQTT_USERNAME']
    mqtt_password = os.environ['MQTT_PASSWORD']
    mqtt_client_id = os.environ['MQTT_CLIENT_ID']

    # => Set the Threading event
    global _on_force_check_callback
    _on_force_check_callback = force_check_callback

    # Create MQTT client instance
    client = paho.Client(client_id=mqtt_client_id, protocol=paho.MQTTv5)

    # Assign callbacks
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    # Enable MQTT logging (optional - useful for debugging)
    client.enable_logger()

    # Set username and password if required
    client.username_pw_set(mqtt_username, mqtt_password)

    # Use TLS to connect
    client.tls_set()

    try:
        # Connect to the broker
        logger.info(f"[MQTT] Connecting to Broker: {mqtt_broker_address}:{mqtt_port}...")
        client.connect(mqtt_broker_address, mqtt_port, keepalive=60)

        # Subscribe to required events
        client.subscribe(FORCE_CHECK_TOPIC, qos=1)

        # Start the network loop in a separate thread. This handles reconnects.
        logger.info("[MQTT] Starting main background loop")
        client.loop_start()
    except Exception as e:
        # Exit if connection fails initially
        logger.error(f"[MQTT] Error connecting to Broker: {e}")
        exit(1)

    return client

# -- Helpers
def publish( mqtt_client: paho.Client, mqtt_topic: str, message: str ) -> None:
    r = mqtt_client.publish(mqtt_topic, payload=message, qos=0)
    r.wait_for_publish(5)
    if r.rc == paho.MQTT_ERR_SUCCESS:
        logger.info(f"[MQTT] Published to {mqtt_topic}: {message}")
    else:
        logger.warning(f"[MQTT] Failed to publish charging state, return code {r.rc}")

def publish_discovery_config(client, component, object_id, device_name, config_payload):
    """Publishes MQTT Discovery config payload with retain=True."""
    config_topic = f"homeassistant/{component}/{device_name}/{object_id}/config"
    try:
        payload_json = json.dumps(config_payload)
        logger.info(f"[MQTT] Publishing discovery config to {config_topic}")
        # print(f"Payload: {payload_json}") # Uncomment for debugging
        result = client.publish(config_topic, payload=payload_json, qos=1, retain=True)
        result.wait_for_publish(timeout=5) # Wait for publish confirmation
        if result.rc != paho.MQTT_ERR_SUCCESS:
             logger.warning(f"Failed to publish discovery config for {object_id}, error code: {result.rc}")
        # else:
        #      print(f"Successfully published discovery for {object_id}")
    except Exception as e:
        logger.warning(f"Error publishing discovery config for {object_id}: {e}")


def publish_config( client: paho.Client ) -> None:
    manufacturer = "Pi Boiler Tracker"

    boiler_device = {
        "identifiers": ["boiler_mqtt"],  # Unique identifier for this device
        "name": "Boiler",
        "manufacturer": manufacturer,
        "model": "Boiler v1"
    }

    light_device = {
        "identifiers": ["storage_room_light_mqtt_01"],
        "name": "Storage Room Light",
        "manufacturer": manufacturer,
        "model": "Basic Light v1"
    }

    discovery_prefix = "homeassistant"

    # --- Define Availability Topics ---
    boiler_availability_topic = f"{discovery_prefix}/device/boiler/availability"
    light_availability_topic = f"{discovery_prefix}/device/storage_room_light/availability"
    availability_online = "online"
    availability_offline = "offline"

    # --- Publish Discovery for Boiler Entities ---
    # 1. Boiler Heating (binary_sensor)
    heating_object_id = "boiler_heating"
    heating_state_topic = f"{discovery_prefix}/binary_sensor/boiler/heating/state"
    heating_config = {
        "name": "Boiler Heating",  # Friendly Name
        "unique_id": f"{heating_object_id}_mqtt_auto_01",  # Unique ID
        "state_topic": heating_state_topic,  # Topic for state updates
        "payload_on": "ON",
        "payload_off": "OFF",
        "device_class": "heat",
        "availability_topic": boiler_availability_topic,
        "payload_available": availability_online,
        "payload_not_available": availability_offline,
        "device": boiler_device
    }
    publish_discovery_config(client, "binary_sensor", heating_object_id, "boiler", heating_config)

    # 2. Boiler Percentage (sensor)
    percentage_object_id = "boiler_percentage"
    percentage_state_topic = f"{discovery_prefix}/sensor/boiler/percentage/state"
    percentage_config = {
        "name": "Boiler Percentage",
        "unique_id": f"{percentage_object_id}_mqtt_auto_01",
        "state_topic": percentage_state_topic,
        "unit_of_measurement": "%",
        "device_class": "battery",
        "state_class": "measurement",
        "availability_topic": boiler_availability_topic,
        "payload_available": availability_online,
        "payload_not_available": availability_offline,
        "device": boiler_device
    }
    publish_discovery_config(client, "sensor", percentage_object_id, "boiler", percentage_config)

    # 3. Boiler Error (binary_sensor)
    error_object_id = "boiler_error"
    error_state_topic = f"{discovery_prefix}/binary_sensor/boiler/error/state"
    error_config = {
        "name": "Boiler Error",
        "unique_id": f"{error_object_id}_mqtt_auto_01",
        "state_topic": error_state_topic,
        "payload_on": "ON",
        "payload_off": "OFF",
        "device_class": "problem",  # Indicates an error state
        "availability_topic": boiler_availability_topic,
        "payload_available": availability_online,
        "payload_not_available": availability_offline,
        "device": boiler_device  # Link to the Boiler device
    }
    publish_discovery_config(client, "binary_sensor", error_object_id, "boiler", error_config)

    # 2. Boiler Percentage (sensor)
    force_check_object_id = "boiler_last_force_check"
    force_check_state_topic = f"{discovery_prefix}/sensor/boiler/last_force_check/state"
    force_check_config = {
        "name": "Boiler Last Force Check",
        "unique_id": f"{force_check_object_id}_mqtt_auto_01",
        "state_topic": force_check_state_topic,
        "device_class": "timestamp",
        "availability_topic": boiler_availability_topic,
        "payload_available": availability_online,
        "payload_not_available": availability_offline,
        "device": boiler_device
    }
    publish_discovery_config(client, "sensor", force_check_object_id, "boiler", force_check_config)

    # --- Publish Discovery for Storage Room Light (light) ---
    light_object_id = "storage_room_light"
    light_state_topic = f"{discovery_prefix}/binary_sensor/storage_room/light/state"
    light_config = {
        "name": "Storage Room Light",
        "unique_id": f"{light_object_id}_mqtt_auto_01",
        "state_topic": light_state_topic,
        "payload_on": "ON",
        "payload_off": "OFF",
        "schema": "basic",  # Use 'basic' for simple ON/OFF lights
        "availability_topic": light_availability_topic,
        "payload_available": availability_online,
        "payload_not_available": availability_offline,
        "device": light_device  # Link to the Light device
    }
    publish_discovery_config(client, "binary_sensor", light_object_id, "storage_room", light_config)

    # --- Publish initial online status ---
    # Use retain=True so HA sees availability immediately if it restarts
    client.publish(boiler_availability_topic, payload=availability_online, qos=1, retain=True)
    client.publish(light_availability_topic, payload=availability_online, qos=1, retain=True)
    logger.info("[MQTT] Published initial 'online' availability status.")

    return
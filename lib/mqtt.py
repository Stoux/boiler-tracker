import paho.mqtt.client as paho
import os
import json

has_published_config = False

# --- MQTT Callbacks ---
def on_connect(client, userdata, flags, rc, properties=None):

    broker = os.environ['MQTT_BROKER_ADDRESS']
    if rc == 0:
        print(f"[MQTT] Connected to {broker}!")

        global has_published_config
        if not has_published_config:
            has_published_config = True
            publish_config(client)

    else:
        print(f"[MQTT] Failed to connect to {broker}: return code {rc}")

def on_disconnect(client, userdata, rc, properties=None):
     print(f"[MQTT] Disconnected from {os.environ['MQTT_BROKER_ADDRESS']} with code {rc}")

# -- Main create function -->
def create_mqtt_client() -> paho.Client:
    # Resolve env variables
    mqtt_broker_address = os.environ['MQTT_BROKER_ADDRESS']
    mqtt_port = int(os.environ['MQTT_PORT'])
    mqtt_username = os.environ['MQTT_USERNAME']
    mqtt_password = os.environ['MQTT_PASSWORD']
    mqtt_client_id = os.environ['MQTT_CLIENT_ID']


    # Create MQTT client instance
    client = paho.Client(client_id=mqtt_client_id, protocol=paho.MQTTv5)

    # Assign callbacks
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    # Enable MQTT logging (optional - useful for debugging)
    client.enable_logger()

    # Set username and password if required
    client.username_pw_set(mqtt_username, mqtt_password)

    # Use TLS to connect
    client.tls_set()

    try:
        # Connect to the broker
        print(f"[MQTT] Connecting to Broker: {mqtt_broker_address}:{mqtt_port}...")
        client.connect(mqtt_broker_address, mqtt_port, keepalive=60)


        # Start the network loop in a separate thread. This handles reconnects.
        print("[MQTT] Starting main background loop")
        client.loop_start()
    except Exception as e:
        # Exit if connection fails initially
        print(f"[MQTT] Error connecting to Broker: {e}")
        exit(1)

    return client

# -- Helpers
def publish( mqtt_client: paho.Client, mqtt_topic: str, message: str ) -> None:
    r = mqtt_client.publish(mqtt_topic, payload=message, qos=0)
    r.wait_for_publish(5)
    if r.rc == paho.MQTT_ERR_SUCCESS:
        print(f"[MQTT] Published to {mqtt_topic}: {message}")
    else:
        print(f"[MQTT] Failed to publish charging state, return code {r.rc}")

def publish_discovery_config(client, component, object_id, device_name, config_payload):
    """Publishes MQTT Discovery config payload with retain=True."""
    config_topic = f"homeassistant/{component}/{device_name}/{object_id}/config"
    try:
        payload_json = json.dumps(config_payload)
        print(f"[MQTT] Publishing discovery config to {config_topic}")
        # print(f"Payload: {payload_json}") # Uncomment for debugging
        result = client.publish(config_topic, payload=payload_json, qos=1, retain=True)
        result.wait_for_publish(timeout=5) # Wait for publish confirmation
        if result.rc != paho.MQTT_ERR_SUCCESS:
             print(f"Failed to publish discovery config for {object_id}, error code: {result.rc}")
        # else:
        #      print(f"Successfully published discovery for {object_id}")
    except Exception as e:
        print(f"Error publishing discovery config for {object_id}: {e}")


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
    print("[MQTT] Published initial 'online' availability status.")

    return
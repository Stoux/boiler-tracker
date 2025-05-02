# Ghetto Boiler Tracker

Some ghetto code that runs on a little Raspberry Pi with a USB webcam attached watching the status of my dumb boiler.

That boiler also has a couple of Zigbee button pressers attached, allowing an automation to heat the boiler, when it's empty.

- See `states/*.jpg` for some example images of what the webcam expects
- Runs `python run.py` as a daemon
- I sometimes need to run `python multi-tuner.py` to view those images & test green boundaries for light detection

## More info? Wtf is this thing?

Ehh, I guess.

- There's a boiler with 4 lights, indicating 0 - 100% heated.
- When one of the lights is blinking, it indicates it's heating that step.
- Script connects to an MQTT broker (mainly for Home Assistant)
- Checks if the Webcam is connected & is working
- Start loop every X (see .env) seconds to analyse the current state
- 1) Take a frame of the webcam
- 2) Detect if the general light (in the room) is on
- 3) Attempt to detect if the boiler button is pressed (this causes the LEDs to heavily increase their brightness)
- 4) Determine the lower green & upper green color bounds (pixels) we're looking for based on the previous variables 
- 5) Take X (~30) frames every X (0.2) seconds and analyse each light's Region of Interest (ROI), determining whether that light is on or off by masking it to HSV & finding the green pixels
- 6) Publish that result to the MQTT broker
- 7) Wait & repeat

### Dependencies

- `paho-mqtt`
- `python-dotenv`
- `numpy`
- `opencv-python` (with cv installed on the host)

## Disclaimers

I haven't written Python in ages, so excuse the garbage.

License is WTFPL.
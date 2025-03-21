# Govee H613E

This script uses the already reverse engineered Govee H613E bluetooth commands to turn the light on and off.

![Image](./assets/image.png)

As the bluetooth signal from the LED controller is "weak" or the build in bluetooth module on the host is not powerful enough, try scanning for devices first before running the script to determine if the signal is strong enough or you might need a higher gain antenna for the host. Personally my antenna/ signal booster on my PC and Laptop was not strong enough to find the device so i had to get a direct line of sight to connect and control the light. So keep that in mind.

In contrast, on my phone i was able to find the device from further away and connect to it. So put the host near to the light or invest in a higher gain antenna or bluetooth module for the host.

## Usage

Set Govee BLE MAC address in the script.

```python
GOVEE_ADDRESS = "A4:C1:38:xx:xx:xx"
```

To see the available commands, run:

```bash
python govee_control.py
```

To turn the light on, run:

```bash
python govee_control.py on
```

To turn the light off, run:

```bash
python govee_control.py off
```

To scan for devices, run:

```bash
python govee_control.py scan
```

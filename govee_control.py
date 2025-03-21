import asyncio
import sys
from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError, BleakDeviceNotFoundError

# Replace with your Govee device's BLE MAC address (format like "A4:C1:38:xx:xx:xx")
GOVEE_ADDRESS = "A4:C1:38:D3:81:44"

# Govee H613E/H6159 service and characteristic UUIDs
# This is the typical custom service for Govee BLE devices
GOVEE_SERVICE_UUID = "00010203-0405-0607-0809-0a0b0c0d1910"
# This is the characteristic used for control commands (write without response)
GOVEE_CHAR_UUID = "00010203-0405-0607-0809-0a0b0c0d2b11"

# Pre-built command arrays for ON and OFF
# 20 bytes total, last byte is XOR of bytes 0..18
CMD_ON = bytearray([
    0x33, 0x01, 0x01, # 0x33 is header, 0x01 = power command, 3rd byte = ON
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
    0x00, 0x00, 0x00, # fill up to byte 18 with 0x00
    0x33  # checksum = 0x33 ^ 0x01 ^ 0x01 = 0x33
])

CMD_OFF = bytearray([
    0x33, 0x01, 0x00, # 0x33 is header, 0x01 = power command, 3rd byte = OFF
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
    0x00, 0x00, 0x00, # fill up to byte 18 with 0x00
    0x32  # checksum = 0x33 ^ 0x01 ^ 0x00 = 0x32
])

async def scan_for_devices(timeout=5.0):
    """
    Scan for BLE devices and return a list of discovered devices.
    
    Args:
        timeout (float): Time in seconds to scan for devices
        
    Returns:
        list: Discovered BLE devices
    """
    print(f"Scanning for BLE devices (timeout: {timeout}s)...")
    devices = await BleakScanner.discover(timeout=timeout)
    
    if not devices:
        print("No BLE devices found.")
        return []
    
    print(f"Found {len(devices)} BLE devices:")
    for i, device in enumerate(devices, 1):
        name = device.name or "Unknown"
        print(f"{i}. {device.address} - {name}")
    
    return devices

async def toggle_govee_light(power_on: bool, address: str = None):
    """
    Connects to the Govee BLE device via BLE, sends the ON or OFF command,
    then disconnects.
    
    Args:
        power_on (bool): True to turn on, False to turn off
        address (str, optional): Device address to connect to. Defaults to GOVEE_ADDRESS.
    """
    command = CMD_ON if power_on else CMD_OFF
    target_address = address or GOVEE_ADDRESS
    
    try:
        # Create a BleakClient with the Govee address
        print(f"Connecting to {target_address}...")
        async with BleakClient(target_address, timeout=10.0) as client:
            print(f"Connected to {target_address}. Sending command...")

            # Write command to the control characteristic
            # Some Govee devices accept 'without response' only
            await client.write_gatt_char(GOVEE_CHAR_UUID, command, response=False)
            print(f"Command sent! Device {'ON' if power_on else 'OFF'}")
            
    except BleakDeviceNotFoundError:
        print(f"Error: Device with address {target_address} was not found.")
        print("Would you like to scan for available devices? (y/n)")
        if input().lower() == 'y':
            await scan_for_devices()
    except BleakError as e:
        print(f"Bluetooth error: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")

async def select_and_control_device():
    """
    Scan for devices, allow user to select one, and control it.
    """
    devices = await scan_for_devices()
    
    if not devices:
        return
    
    while True:
        print("\nEnter the number of the device to control, or 0 to cancel:")
        try:
            choice = int(input())
            if choice == 0:
                return
            if 1 <= choice <= len(devices):
                selected_device = devices[choice-1]
                print(f"Selected: {selected_device.address} - {selected_device.name or 'Unknown'}")
                
                print("Enter command (on/off):")
                cmd = input().lower()
                if cmd in ["on", "off"]:
                    await toggle_govee_light(cmd == "on", selected_device.address)
                    return
                else:
                    print("Invalid command. Use 'on' or 'off'.")
            else:
                print("Invalid selection.")
        except ValueError:
            print("Please enter a number.")

async def main():
    """
    Main function to parse arguments and execute commands.
    """
    if len(sys.argv) < 2:
        print("Usage: python govee_control.py [on/off/scan]")
        return
    
    cmd = sys.argv[1].lower()
    if cmd == "on":
        await toggle_govee_light(True)
    elif cmd == "off":
        await toggle_govee_light(False)
    elif cmd == "scan":
        await select_and_control_device()
    else:
        print("Invalid argument. Use 'on', 'off', or 'scan'.")

if __name__ == "__main__":
    asyncio.run(main())

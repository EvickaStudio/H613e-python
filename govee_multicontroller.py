import asyncio
import tkinter as tk
from tkinter import ttk, colorchooser, filedialog
import json
import os
import threading
import queue

from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

# ==========================
# Govee BLE Constants
# ==========================
GOVEE_SERVICE_UUID = "00010203-0405-0607-0809-0a0b0c0d1910"
GOVEE_CHAR_UUID =   "00010203-0405-0607-0809-0a0b0c0d2b11"

# Provide your known Govee address here. Or set it via scanning
# e.g. "A4:C1:38:D3:81:44"
DEFAULT_GOVEE_ADDRESS = "A4:C1:38:D3:81:44"

# Commands
def build_checksum(packet_19_bytes):
    """Compute XOR of first 19 bytes."""
    chksum = 0
    for b in packet_19_bytes:
        chksum ^= b
    return chksum

def build_power_command(on: bool):
    """
    Returns 20 bytes for power ON or OFF command
    """
    cmd_type = 0x01
    cmd = bytearray([0x33, cmd_type, 0x01 if on else 0x00] + [0x00]*16)
    checksum = build_checksum(cmd)
    cmd.append(checksum)
    return cmd

def build_brightness_command(brightness: int):
    """
    Brightness ranges from 0..255 (though typically 0..100).
    0 means off, 255 is max.
    """
    cmd_type = 0x04
    if brightness < 0:
        brightness = 0
    if brightness > 255:
        brightness = 255
    cmd = bytearray([0x33, cmd_type, brightness] + [0x00]*16)
    checksum = build_checksum(cmd)
    cmd.append(checksum)
    return cmd

def build_color_command(r: int, g: int, b: int):
    """
    Build a 20-byte command to set static color.
    Typically: 33 05 02 R G B ... + XOR checksum.
    """
    cmd_type = 0x05
    sub_type = 0x02  # 0x02 for static color
    cmd = bytearray([0x33, cmd_type, sub_type, r & 0xFF, g & 0xFF, b & 0xFF] + [0x00]*13)
    checksum = build_checksum(cmd)
    cmd.append(checksum)
    return cmd

def build_scene_command(scene_id: int):
    """
    Basic scene command:
    33 05 04 [scene_id] + zeros + checksum
    E.g. 0x0A = Breathe, 0x08 = Pulse, 0x15 = Rainbow
    """
    cmd_type = 0x05
    sub_type = 0x04  # Scenes
    cmd = bytearray([0x33, cmd_type, sub_type, scene_id] + [0x00]*15)
    checksum = build_checksum(cmd)
    cmd.append(checksum)
    return cmd

# Example scene IDs from known Govee reverse engineering
SCENES = {
    "Breathe (Fade)": 0x0A,
    "Pulse (Blink)":  0x08,
    "Rainbow":        0x15,
    "Candlelight":    0x09
}

# ==============
# BLE Control
# ==============
async def send_command(address, cmd):
    """
    Connect to the Govee device at 'address' and write 'cmd' (20 bytes)
    to the characteristic. Disconnect afterwards.
    """
    try:
        async with BleakClient(address, timeout=10.0) as client:
            if client.is_connected:
                await client.write_gatt_char(GOVEE_CHAR_UUID, cmd, response=False)
                return True
            return False
    except BleakError as e:
        print(f"BleakError: {e}")
        return False
    except Exception as e:
        print(f"Unexpected error: {e}")
        return False

# Thread for running asyncio operations
class AsyncThread:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.queue = queue.Queue()
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()
    
    def _worker(self):
        asyncio.set_event_loop(self.loop)
        while True:
            coro, future = self.queue.get()
            try:
                result = self.loop.run_until_complete(coro)
                if future is not None:
                    future.set_result(result)
            except Exception as e:
                if future is not None:
                    future.set_exception(e)
            finally:
                self.queue.task_done()
    
    def run_coroutine(self, coro, callback=None):
        """Run a coroutine in the asyncio thread and optionally call a callback with the result"""
        if callback:
            future = asyncio.Future(loop=self.loop)
            future.add_done_callback(lambda f: self._callback_wrapper(f, callback))
            self.queue.put((coro, future))
        else:
            self.queue.put((coro, None))
    
    def _callback_wrapper(self, future, callback):
        """Handle the callback in the main thread"""
        try:
            result = future.result()
            # Schedule callback in main thread
            from tkinter import Tk
            Tk().after(0, lambda: callback(result))
        except Exception as e:
            print(f"Callback error: {e}")

# ================
# Tkinter GUI
# ================
class GoveeControllerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Govee Multi-Controller")
        
        # Create async thread for BLE operations
        self.async_thread = AsyncThread()
        
        # Status indicator
        self.status_var = tk.StringVar(value="Ready")
        status_label = tk.Label(root, textvariable=self.status_var, bd=1, relief=tk.SUNKEN, anchor=tk.W)
        status_label.pack(side=tk.BOTTOM, fill=tk.X)
        
        # We'll store the BLE address in a variable (could let user set it).
        self.device_address = tk.StringVar(value=DEFAULT_GOVEE_ADDRESS)

        # Frame for device address input & scanning
        address_frame = tk.Frame(root)
        address_frame.pack(pady=5)
        tk.Label(address_frame, text="Govee BLE Address:").pack(side=tk.LEFT, padx=5)
        tk.Entry(address_frame, textvariable=self.device_address, width=20).pack(side=tk.LEFT, padx=5)
        tk.Button(address_frame, text="Scan", command=self.scan_for_devices).pack(side=tk.LEFT, padx=5)

        # Row for on/off
        power_frame = tk.Frame(root)
        power_frame.pack(pady=5)
        tk.Button(power_frame, text="ON", command=self.turn_on).pack(side=tk.LEFT, padx=10)
        tk.Button(power_frame, text="OFF", command=self.turn_off).pack(side=tk.LEFT, padx=10)

        # Row for brightness
        brightness_frame = tk.Frame(root)
        brightness_frame.pack(pady=5)
        tk.Label(brightness_frame, text="Brightness:").pack(side=tk.LEFT)
        self.brightness_var = tk.IntVar(value=255)
        brightness_scale = tk.Scale(brightness_frame, from_=0, to=255, orient=tk.HORIZONTAL,
                                    variable=self.brightness_var, command=self.on_brightness_change)
        brightness_scale.pack(side=tk.LEFT)

        # Row for color
        color_frame = tk.Frame(root)
        color_frame.pack(pady=5)
        # Sliders for R, G, B
        self.r_var = tk.IntVar(value=255)
        self.g_var = tk.IntVar(value=0)
        self.b_var = tk.IntVar(value=0)
        
        tk.Label(color_frame, text="R").pack(side=tk.LEFT)
        r_scale = tk.Scale(color_frame, from_=0, to=255, orient=tk.HORIZONTAL,
                           variable=self.r_var, command=self.on_color_change, length=100)
        r_scale.pack(side=tk.LEFT)

        tk.Label(color_frame, text="G").pack(side=tk.LEFT)
        g_scale = tk.Scale(color_frame, from_=0, to=255, orient=tk.HORIZONTAL,
                           variable=self.g_var, command=self.on_color_change, length=100)
        g_scale.pack(side=tk.LEFT)

        tk.Label(color_frame, text="B").pack(side=tk.LEFT)
        b_scale = tk.Scale(color_frame, from_=0, to=255, orient=tk.HORIZONTAL,
                           variable=self.b_var, command=self.on_color_change, length=100)
        b_scale.pack(side=tk.LEFT)

        # Button to choose color with a colorchooser
        tk.Button(color_frame, text="Color Picker", command=self.pick_color).pack(side=tk.LEFT, padx=10)

        # Row for Scenes
        scene_frame = tk.Frame(root)
        scene_frame.pack(pady=5)
        tk.Label(scene_frame, text="Scene/Effect:").pack(side=tk.LEFT)
        self.scene_var = tk.StringVar(value="Breathe (Fade)")
        scene_dropdown = ttk.Combobox(scene_frame, textvariable=self.scene_var,
                                      values=list(SCENES.keys()), state="readonly")
        scene_dropdown.pack(side=tk.LEFT, padx=5)
        tk.Button(scene_frame, text="Apply Scene", command=self.on_scene_apply).pack(side=tk.LEFT, padx=5)

        # Row for Presets (save/load)
        preset_frame = tk.Frame(root)
        preset_frame.pack(pady=5)
        tk.Button(preset_frame, text="Save Preset", command=self.save_preset).pack(side=tk.LEFT, padx=5)
        tk.Button(preset_frame, text="Load Preset", command=self.load_preset).pack(side=tk.LEFT, padx=5)

        # For scanning results:
        self.scan_window = None
        
        # Color change debouncing
        self.color_change_id = None

    def update_status(self, message):
        """Update status bar with message"""
        self.status_var.set(message)

    def turn_on(self):
        self.update_status("Turning device ON...")
        self.async_thread.run_coroutine(
            send_command(self.device_address.get(), build_power_command(True)), 
            lambda success: self.update_status("Device turned ON" if success else "Failed to turn ON")
        )

    def turn_off(self):
        self.update_status("Turning device OFF...")
        self.async_thread.run_coroutine(
            send_command(self.device_address.get(), build_power_command(False)), 
            lambda success: self.update_status("Device turned OFF" if success else "Failed to turn OFF")
        )

    def on_brightness_change(self, val):
        # Called when brightness slider changes
        # Using debouncing to avoid too many commands
        if hasattr(self, '_brightness_timer_id') and self._brightness_timer_id:
            self.root.after_cancel(self._brightness_timer_id)
        
        self._brightness_timer_id = self.root.after(200, self._send_brightness)
    
    def _send_brightness(self):
        bright_value = int(self.brightness_var.get())
        self.update_status(f"Setting brightness to {bright_value}...")
        self.async_thread.run_coroutine(
            send_command(self.device_address.get(), build_brightness_command(bright_value)),
            lambda success: self.update_status(f"Brightness set to {bright_value}" if success else "Failed to set brightness")
        )

    def on_color_change(self, val):
        # Using debouncing to avoid too many commands when sliders are moved
        if self.color_change_id:
            self.root.after_cancel(self.color_change_id)
        
        self.color_change_id = self.root.after(200, self._send_color)
    
    def _send_color(self):
        self.color_change_id = None
        r = self.r_var.get()
        g = self.g_var.get()
        b = self.b_var.get()
        self.update_status(f"Setting color to RGB({r},{g},{b})...")
        self.async_thread.run_coroutine(
            send_command(self.device_address.get(), build_color_command(r, g, b)),
            lambda success: self.update_status(f"Color set to RGB({r},{g},{b})" if success else "Failed to set color")
        )

    def on_scene_apply(self):
        scene_name = self.scene_var.get()
        if scene_name in SCENES:
            scene_id = SCENES[scene_name]
            self.update_status(f"Applying scene: {scene_name}...")
            self.async_thread.run_coroutine(
                send_command(self.device_address.get(), build_scene_command(scene_id)),
                lambda success: self.update_status(f"Scene applied: {scene_name}" if success else f"Failed to apply scene: {scene_name}")
            )

    def pick_color(self):
        """Open a color chooser dialog and set R,G,B accordingly."""
        color_code = colorchooser.askcolor(title="Choose Color")
        if color_code and color_code[0] is not None:
            # color_code is ((R, G, B), 'hexstring')
            rgb = color_code[0]
            r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
            self.r_var.set(r)
            self.g_var.set(g)
            self.b_var.set(b)
            self._send_color()

    def save_preset(self):
        """
        Save current power state, brightness, color, and scene to a JSON file.
        For a real device, you'd also want to track power state if we can read it or store locally.
        """
        r = self.r_var.get()
        g = self.g_var.get()
        b = self.b_var.get()
        brightness = self.brightness_var.get()
        scene = self.scene_var.get()
        
        preset_data = {
            "rgb": [r, g, b],
            "brightness": brightness,
            "scene": scene,
        }
        
        # Prompt for file name
        file_path = filedialog.asksaveasfilename(defaultextension=".json", 
                                                 filetypes=[("JSON Files","*.json")])
        if file_path:
            with open(file_path, "w") as f:
                json.dump(preset_data, f, indent=2)
            self.update_status(f"Preset saved to {file_path}")

    def load_preset(self):
        """
        Load a preset JSON file and apply it to the device.
        """
        file_path = filedialog.askopenfilename(defaultextension=".json", 
                                               filetypes=[("JSON Files","*.json")])
        if not file_path or not os.path.exists(file_path):
            return
        
        with open(file_path, "r") as f:
            preset_data = json.load(f)
        
        # Extract data
        r, g, b = preset_data.get("rgb", [255, 255, 255])
        brightness = preset_data.get("brightness", 255)
        scene = preset_data.get("scene", None)

        # Apply to sliders/variables
        self.r_var.set(r)
        self.g_var.set(g)
        self.b_var.set(b)
        self.brightness_var.set(brightness)
        
        # Send commands to device
        self.update_status(f"Loading preset from {file_path}...")
        
        # First set color
        self.async_thread.run_coroutine(
            send_command(self.device_address.get(), build_color_command(r, g, b)),
            lambda success: self._apply_preset_brightness(brightness, scene, success)
        )
    
    def _apply_preset_brightness(self, brightness, scene, prev_success):
        if not prev_success:
            self.update_status("Failed to apply preset color")
            return
            
        self.async_thread.run_coroutine(
            send_command(self.device_address.get(), build_brightness_command(brightness)),
            lambda success: self._apply_preset_scene(scene, success)
        )
    
    def _apply_preset_scene(self, scene, prev_success):
        if not prev_success:
            self.update_status("Failed to apply preset brightness")
            return
            
        if scene and scene in SCENES:
            self.scene_var.set(scene)
            scene_id = SCENES[scene]
            self.async_thread.run_coroutine(
                send_command(self.device_address.get(), build_scene_command(scene_id)),
                lambda success: self.update_status("Preset applied successfully" if success else "Failed to apply preset scene")
            )
        else:
            self.update_status("Preset applied successfully")

    def scan_for_devices(self):
        """
        Perform a BLE scan for devices, show them in a new window, 
        and allow user to select one for controlling.
        """
        if self.scan_window and tk.Toplevel.winfo_exists(self.scan_window):
            self.scan_window.destroy()

        self.scan_window = tk.Toplevel(self.root)
        self.scan_window.title("Scan for Devices")
        self.scan_window.geometry("400x300")
        scan_status = tk.Label(self.scan_window, text="Scanning... Please wait.")
        scan_status.pack(pady=10)
        
        # Create a progress bar
        progress = ttk.Progressbar(self.scan_window, mode='indeterminate')
        progress.pack(fill=tk.X, padx=20, pady=10)
        progress.start()

        async def do_scan():
            try:
                return await BleakScanner.discover(timeout=5.0)
            except Exception as e:
                print(f"Scan error: {e}")
                return []

        def on_scan_done(devices):
            progress.stop()
            for widget in self.scan_window.winfo_children():
                widget.destroy()  # Clear existing

            if not devices:
                tk.Label(self.scan_window, text="No devices found.", font=("Arial", 12)).pack(pady=20)
                tk.Button(self.scan_window, text="Close", command=self.scan_window.destroy).pack()
                return

            tk.Label(self.scan_window, text=f"Found {len(devices)} devices:", font=("Arial", 12)).pack(pady=10)
            
            # Create a frame with scrollbar for the listbox
            frame = tk.Frame(self.scan_window)
            frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
            
            scrollbar = tk.Scrollbar(frame)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            
            lb = tk.Listbox(frame, width=50, height=10, yscrollcommand=scrollbar.set)
            lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            
            scrollbar.config(command=lb.yview)
            
            for d in devices:
                name = d.name or "Unknown"
                lb.insert(tk.END, f"{d.address} - {name}")

            def select_device():
                selection = lb.curselection()
                if selection:
                    idx = selection[0]
                    chosen = devices[idx]
                    self.device_address.set(chosen.address)
                    self.scan_window.destroy()
                    self.update_status(f"Selected device: {chosen.address}")

            button_frame = tk.Frame(self.scan_window)
            button_frame.pack(fill=tk.X, pady=10)
            tk.Button(button_frame, text="Select", command=select_device).pack(side=tk.LEFT, padx=20)
            tk.Button(button_frame, text="Cancel", command=self.scan_window.destroy).pack(side=tk.RIGHT, padx=20)

        # Run the BLE scan in the async thread
        self.update_status("Scanning for devices...")
        self.async_thread.run_coroutine(do_scan(), on_scan_done)

def main():
    root = tk.Tk()
    app = GoveeControllerGUI(root)
    root.geometry("500x350")
    root.mainloop()

if __name__ == "__main__":
    main()

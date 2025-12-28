#!/usr/bin/env python3
"""
Native Instruments Traktor Kontrol Z1 - HID to MIDI Bridge
============================================================
This daemon reads HID reports from the Z1 and translates them to MIDI,
exposing a virtual ALSA MIDI port that applications like BeatportDJ can use.

Based on the Mixxx HID mapping by djantti.

Author: Generated for Colby's Z1 Linux integration project
License: GPL-3.0
"""

import os
import sys
import time
import struct
import signal
import argparse
from dataclasses import dataclass
from typing import Optional, Callable

# We'll use rtmidi for virtual MIDI port creation
try:
    import rtmidi
except ImportError:
    print("ERROR: python-rtmidi not installed.")
    print("Install with: pip install python-rtmidi --break-system-packages")
    print("Or: pipx install python-rtmidi")
    sys.exit(1)


# =============================================================================
# Z1 HID Protocol Constants (from Mixxx mapping)
# =============================================================================

Z1_VENDOR_ID = 0x17cc
Z1_PRODUCT_ID = 0x1210

# HID Report IDs
INPUT_REPORT_ID = 0x01
OUTPUT_REPORT_ID = 0x80

# LED brightness values
LED_OFF = 0x00
LED_DIM = 0x0A
LED_FULL = 0x7F

# Input Report byte offsets (16-bit little-endian values, 12-bit resolution 0-4095)
# Format: (byte_offset, name, midi_cc)
INPUT_CONTROLS = [
    # Channel 1 (Left side)
    (0x01, "ch1_gain", 16),       # Gain knob
    (0x03, "ch1_eq_hi", 17),      # EQ High
    (0x05, "ch1_eq_mid", 18),     # EQ Mid
    (0x07, "ch1_eq_lo", 19),      # EQ Low
    (0x09, "ch1_fx", 20),         # Filter/FX knob
    (0x17, "ch1_volume", 21),     # Volume fader
    
    # Channel 2 (Right side)
    (0x0B, "ch2_gain", 24),       # Gain knob
    (0x0D, "ch2_eq_hi", 25),      # EQ High
    (0x0F, "ch2_eq_mid", 26),     # EQ Mid
    (0x11, "ch2_eq_lo", 27),      # EQ Low
    (0x13, "ch2_fx", 28),         # Filter/FX knob
    (0x19, "ch2_volume", 29),     # Volume fader
    
    # Master section
    (0x15, "headphone_mix", 22),  # Cue Mix knob
    (0x1B, "crossfader", 23),     # Crossfader
]

# Button byte (offset 0x1D) bitmasks
BUTTON_MODE = 0x02      # Mode button
BUTTON_CUE_A = 0x10     # Headphone Cue A (Channel 1)
BUTTON_CUE_B = 0x01     # Headphone Cue B (Channel 2)
BUTTON_FX_A = 0x04      # FX On A (Channel 1)
BUTTON_FX_B = 0x08      # FX On B (Channel 2)

# Button MIDI note assignments
BUTTON_NOTES = {
    "mode": 1,
    "cue_a": 2,
    "cue_b": 3,
    "fx_a": 4,
    "fx_b": 5,
}

# Output Report LED offsets (for OutputReport 0x80)
# The report is 22 bytes: report_id (0x80) + 21 data bytes
LED_OFFSETS = {
    # VU meters Channel 1 (offsets 0x01-0x07)
    "ch1_vu_30": 0x01,
    "ch1_vu_15": 0x02,
    "ch1_vu_6": 0x03,
    "ch1_vu_3": 0x04,
    "ch1_vu_0": 0x05,
    "ch1_vu_3p": 0x06,
    "ch1_vu_6p": 0x07,
    
    # VU meters Channel 2 (offsets 0x08-0x0E)
    "ch2_vu_30": 0x08,
    "ch2_vu_15": 0x09,
    "ch2_vu_6": 0x0A,
    "ch2_vu_3": 0x0B,
    "ch2_vu_0": 0x0C,
    "ch2_vu_3p": 0x0D,
    "ch2_vu_6p": 0x0E,
    
    # Button LEDs
    "cue_a": 0x0F,          # Headphone Cue A
    "cue_b": 0x10,          # Headphone Cue B
    "fx_a": 0x11,           # FX On A (also play indicator)
    "fx_b_enabled": 0x12,   # FX B enabled indicator
    "mode": 0x13,           # Mode button
    "fx_b": 0x14,           # FX On B (also play indicator)
    "fx_a_enabled": 0x15,   # FX A enabled indicator (this might be swapped)
}


# =============================================================================
# Z1 HID Device Interface
# =============================================================================

class Z1HIDDevice:
    """Low-level HID interface to the Z1 controller."""
    
    def __init__(self, device_path: str = None):
        self.device_path = device_path
        self.fd = None
        self._last_input = None
        self._led_state = bytearray(22)  # Output report buffer
        self._led_state[0] = OUTPUT_REPORT_ID
        
    def find_device(self) -> Optional[str]:
        """Find the Z1 hidraw device by checking vendor/product IDs."""
        for i in range(10):
            path = f"/dev/hidraw{i}"
            if not os.path.exists(path):
                continue
            try:
                # Check via sysfs
                sysfs_path = f"/sys/class/hidraw/hidraw{i}/device/uevent"
                if os.path.exists(sysfs_path):
                    with open(sysfs_path, 'r') as f:
                        content = f.read()
                        # Look for our vendor:product ID
                        if "17CC" in content.upper() and "1210" in content.upper():
                            return path
            except (IOError, PermissionError):
                continue
        return None
    
    def open(self) -> bool:
        """Open the HID device."""
        if self.device_path is None:
            self.device_path = self.find_device()
            if self.device_path is None:
                print("ERROR: Z1 device not found. Is it connected?")
                return False
        
        try:
            self.fd = os.open(self.device_path, os.O_RDWR | os.O_NONBLOCK)
            print(f"Opened Z1 at {self.device_path}")
            return True
        except (IOError, PermissionError) as e:
            print(f"ERROR: Cannot open {self.device_path}: {e}")
            print("Check permissions. You may need to run as root or set up udev rules.")
            return False
    
    def close(self):
        """Close the HID device."""
        if self.fd is not None:
            try:
                os.close(self.fd)
            except:
                pass
            self.fd = None
    
    def read_input(self) -> Optional[bytes]:
        """Read an input report from the device (non-blocking)."""
        if self.fd is None:
            return None
        try:
            data = os.read(self.fd, 64)
            if len(data) > 0:
                return data
        except BlockingIOError:
            pass  # No data available
        except Exception as e:
            print(f"Read error: {e}")
        return None
    
    def send_output(self, data: bytes) -> bool:
        """Send an output report to the device."""
        if self.fd is None:
            return False
        try:
            os.write(self.fd, data)
            return True
        except Exception as e:
            print(f"Write error: {e}")
            return False
    
    def set_led(self, name: str, brightness: int):
        """Set an LED brightness (0x00=off, 0x0A=dim, 0x7F=full)."""
        if name in LED_OFFSETS:
            offset = LED_OFFSETS[name]
            self._led_state[offset] = brightness & 0x7F
    
    def update_leds(self):
        """Send the current LED state to the device."""
        return self.send_output(bytes(self._led_state))
    
    def initialize_leds(self, dim: bool = True):
        """Initialize all LEDs to dim or off state."""
        brightness = LED_DIM if dim else LED_OFF
        
        # Set all button LEDs to dim
        for name in ["mode", "cue_a", "cue_b", "fx_a", "fx_b", "fx_a_enabled", "fx_b_enabled"]:
            self.set_led(name, brightness)
        
        # VU meters off
        for ch in ["ch1", "ch2"]:
            for level in ["vu_30", "vu_15", "vu_6", "vu_3", "vu_0", "vu_3p", "vu_6p"]:
                self.set_led(f"{ch}_{level}", LED_OFF)
        
        return self.update_leds()


# =============================================================================
# MIDI Output Handler
# =============================================================================

class MIDIOutput:
    """Virtual MIDI output port."""
    
    def __init__(self, port_name: str = "Z1 Bridge"):
        self.port_name = port_name
        self.midi_out = None
        
    def open(self) -> bool:
        """Create and open a virtual MIDI output port."""
        try:
            self.midi_out = rtmidi.MidiOut()
            self.midi_out.open_virtual_port(self.port_name)
            print(f"Created virtual MIDI port: {self.port_name}")
            return True
        except Exception as e:
            print(f"ERROR: Cannot create MIDI port: {e}")
            return False
    
    def close(self):
        """Close the MIDI port."""
        if self.midi_out:
            self.midi_out.close_port()
            self.midi_out = None
    
    def send_cc(self, channel: int, cc: int, value: int):
        """Send a MIDI Control Change message."""
        if self.midi_out:
            # CC message: 0xB0 + channel, cc number, value
            msg = [0xB0 + (channel & 0x0F), cc & 0x7F, value & 0x7F]
            self.midi_out.send_message(msg)
    
    def send_note_on(self, channel: int, note: int, velocity: int = 127):
        """Send a MIDI Note On message."""
        if self.midi_out:
            msg = [0x90 + (channel & 0x0F), note & 0x7F, velocity & 0x7F]
            self.midi_out.send_message(msg)
    
    def send_note_off(self, channel: int, note: int):
        """Send a MIDI Note Off message."""
        if self.midi_out:
            msg = [0x80 + (channel & 0x0F), note & 0x7F, 0]
            self.midi_out.send_message(msg)


# =============================================================================
# Z1 Bridge - Main Controller
# =============================================================================

class Z1Bridge:
    """Main bridge controller that ties everything together."""
    
    def __init__(self, device_path: str = None, midi_channel: int = 0):
        self.hid = Z1HIDDevice(device_path)
        self.midi = MIDIOutput("Traktor Kontrol Z1")
        self.midi_channel = midi_channel
        self.running = False
        
        # State tracking for delta detection
        self._last_values = {}
        self._last_buttons = 0
        
    def start(self) -> bool:
        """Initialize and start the bridge."""
        # Open HID device
        if not self.hid.open():
            return False
        
        # Open MIDI port
        if not self.midi.open():
            self.hid.close()
            return False
        
        # Initialize LEDs (this "wakes up" the device)
        print("Initializing Z1 LEDs...")
        if self.hid.initialize_leds(dim=True):
            print("Z1 LEDs initialized - device should be lit!")
        else:
            print("WARNING: Could not initialize LEDs")
        
        self.running = True
        return True
    
    def stop(self):
        """Stop the bridge and clean up."""
        self.running = False
        
        # Turn off all LEDs
        if self.hid.fd:
            self.hid.initialize_leds(dim=False)  # All off
        
        self.midi.close()
        self.hid.close()
        print("Z1 Bridge stopped.")
    
    def process_input(self, data: bytes):
        """Process an HID input report and generate MIDI messages."""
        if len(data) < 30:
            return
        
        # Process analog controls (knobs and faders)
        for offset, name, cc in INPUT_CONTROLS:
            # Read 16-bit little-endian value
            raw_value = struct.unpack_from('<H', data, offset)[0]
            # Mask to 12 bits (0-4095)
            raw_value &= 0x0FFF
            
            # Check if value changed (with small deadzone for noise)
            last_value = self._last_values.get(name, -1)
            if abs(raw_value - last_value) > 8:  # ~0.2% deadzone
                self._last_values[name] = raw_value
                
                # Convert to 7-bit MIDI value (0-127)
                midi_value = int((raw_value / 4095) * 127)
                
                # Send CC
                self.midi.send_cc(self.midi_channel, cc, midi_value)
        
        # Process buttons (byte at offset 0x1D)
        buttons = data[0x1D]
        last_buttons = self._last_buttons
        self._last_buttons = buttons
        
        # Check each button for changes
        button_map = [
            (BUTTON_MODE, "mode"),
            (BUTTON_CUE_A, "cue_a"),
            (BUTTON_CUE_B, "cue_b"),
            (BUTTON_FX_A, "fx_a"),
            (BUTTON_FX_B, "fx_b"),
        ]
        
        for mask, name in button_map:
            was_pressed = (last_buttons & mask) != 0
            is_pressed = (buttons & mask) != 0
            
            if is_pressed and not was_pressed:
                # Button pressed
                note = BUTTON_NOTES[name]
                self.midi.send_note_on(self.midi_channel, note, 127)
                # Update LED to full brightness
                if name in LED_OFFSETS:
                    self.hid.set_led(name, LED_FULL)
            elif not is_pressed and was_pressed:
                # Button released
                note = BUTTON_NOTES[name]
                self.midi.send_note_off(self.midi_channel, note)
                # Update LED to dim
                if name in LED_OFFSETS:
                    self.hid.set_led(name, LED_DIM)
        
        # Update LEDs if any button state changed
        if buttons != last_buttons:
            self.hid.update_leds()
    
    def run(self):
        """Main loop - process HID input and generate MIDI."""
        print("Z1 Bridge running. Press Ctrl+C to stop.")
        print(f"MIDI output on channel {self.midi_channel + 1}")
        print("")
        print("Control mappings:")
        print("  CC 16-21: Channel 1 (Gain, EQ Hi/Mid/Lo, FX, Volume)")
        print("  CC 22-23: Headphone Mix, Crossfader")
        print("  CC 24-29: Channel 2 (Gain, EQ Hi/Mid/Lo, FX, Volume)")
        print("  Note 1-5: Mode, Cue A, Cue B, FX A, FX B")
        print("")
        
        try:
            while self.running:
                data = self.hid.read_input()
                if data:
                    self.process_input(data)
                else:
                    # No data, sleep briefly to avoid CPU spinning
                    time.sleep(0.001)
        except KeyboardInterrupt:
            print("\nInterrupted.")
        finally:
            self.stop()


# =============================================================================
# Signal Handlers
# =============================================================================

bridge_instance = None

def signal_handler(signum, frame):
    """Handle termination signals gracefully."""
    global bridge_instance
    if bridge_instance:
        bridge_instance.running = False


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    global bridge_instance
    
    parser = argparse.ArgumentParser(
        description="Native Instruments Traktor Kontrol Z1 - HID to MIDI Bridge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                    # Auto-detect Z1 device
  %(prog)s -d /dev/hidraw5    # Use specific device
  %(prog)s -c 2               # Output on MIDI channel 2

The bridge creates a virtual ALSA MIDI port named "Traktor Kontrol Z1"
that can be connected to any MIDI-capable application.

Use 'aconnect -l' to see available MIDI ports.
"""
    )
    
    parser.add_argument('-d', '--device', type=str, default=None,
                        help='HID device path (default: auto-detect)')
    parser.add_argument('-c', '--channel', type=int, default=1,
                        help='MIDI channel 1-16 (default: 1)')
    parser.add_argument('--init-only', action='store_true',
                        help='Just initialize LEDs and exit (for testing)')
    
    args = parser.parse_args()
    
    # Validate channel
    if not 1 <= args.channel <= 16:
        print("ERROR: MIDI channel must be 1-16")
        sys.exit(1)
    
    # Create bridge
    bridge_instance = Z1Bridge(
        device_path=args.device,
        midi_channel=args.channel - 1  # Convert to 0-indexed
    )
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start the bridge
    if not bridge_instance.start():
        sys.exit(1)
    
    if args.init_only:
        print("LEDs initialized. Waiting 3 seconds before exit...")
        time.sleep(3)
        bridge_instance.stop()
    else:
        bridge_instance.run()


if __name__ == "__main__":
    main()

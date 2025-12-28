#!/usr/bin/env python3
"""
Native Instruments Traktor Kontrol X1 MK2 - HID to MIDI Bridge (Corrected)
==========================================================================
Based on Mixxx community mapping by infiniteloop

Fixes:
- Correct byte offsets matching Mixxx HID mapping
- All buttons including Shift, Load, FX Select
- Proper encoder handling (relative 4-bit values)
- Correct touch strip offsets
- All 8 FX knobs

Author: Colby's NI Linux Bridge Project
License: GPL-3.0
"""

import os
import sys
import time
import argparse
from dataclasses import dataclass
from typing import Optional

try:
    import rtmidi
except ImportError:
    print("ERROR: python-rtmidi not installed.")
    print("Install with: pip install python-rtmidi --break-system-packages")
    sys.exit(1)


# =============================================================================
# X1 MK2 HID Protocol Constants (from Mixxx mapping by infiniteloop)
# =============================================================================

X1_VENDOR_ID = 0x17cc
X1_PRODUCT_ID = 0x1220

# Report IDs
INPUT_REPORT_ID = 0x01
OUTPUT_REPORT_BUTTONS = 0x80
OUTPUT_REPORT_DISPLAY = 0x81

# LED brightness values
LED_OFF = 0x00
LED_DIM = 0x10
LED_FULL = 0x7F


# =============================================================================
# Input Report Structure (Report 0x01, 31 bytes total)
# =============================================================================
# Byte offsets are from start of report (byte 0 = report ID)

# Knobs: 12-bit Little Endian values (0x0FFF mask)
# Format: (byte_offset, name, midi_cc)
KNOBS = [
    # Effect Unit 1 (Left side)
    (0x01, "fx1_mix", 10),      # FX Mix/Dry-Wet
    (0x03, "fx1_knob1", 11),    # FX Parameter 1
    (0x05, "fx1_knob2", 12),    # FX Parameter 2
    (0x07, "fx1_knob3", 13),    # FX Parameter 3
    
    # Effect Unit 2 (Right side)
    (0x09, "fx2_mix", 14),      # FX Mix/Dry-Wet
    (0x0B, "fx2_knob1", 15),    # FX Parameter 1
    (0x0D, "fx2_knob2", 16),    # FX Parameter 2
    (0x0F, "fx2_knob3", 17),    # FX Parameter 3
]


# Buttons: (byte_offset, bitmask, name, midi_note)
@dataclass(frozen=True)
class ButtonDef:
    byte_offset: int
    mask: int
    name: str
    note: int

BUTTONS = [
    # Byte 0x13: FX Buttons (active low? check your data)
    ButtonDef(0x13, 0x80, "fx1_focus", 40),      # Effect Focus Unit 1
    ButtonDef(0x13, 0x40, "fx1_btn1", 41),       # FX1 Button 1
    ButtonDef(0x13, 0x20, "fx1_btn2", 42),       # FX1 Button 2
    ButtonDef(0x13, 0x10, "fx1_btn3", 43),       # FX1 Button 3
    ButtonDef(0x13, 0x08, "fx2_focus", 44),      # Effect Focus Unit 2
    ButtonDef(0x13, 0x04, "fx2_btn1", 45),       # FX2 Button 1
    ButtonDef(0x13, 0x02, "fx2_btn2", 46),       # FX2 Button 2
    ButtonDef(0x13, 0x01, "fx2_btn3", 47),       # FX2 Button 3
    
    # Byte 0x14: Shift, Load, FX Assign buttons
    ButtonDef(0x14, 0x80, "fx1_to_ch1", 48),     # FX1 → Channel 1
    ButtonDef(0x14, 0x40, "fx2_to_ch1", 49),     # FX2 → Channel 1
    ButtonDef(0x14, 0x20, "fx1_to_ch2", 50),     # FX1 → Channel 2
    ButtonDef(0x14, 0x10, "fx2_to_ch2", 51),     # FX2 → Channel 2
    ButtonDef(0x14, 0x08, "load_left", 52),      # Load Track Left (Ch1)
    ButtonDef(0x14, 0x04, "shift", 53),          # SHIFT button
    ButtonDef(0x14, 0x02, "load_right", 54),     # Load Track Right (Ch2)
    ButtonDef(0x14, 0x01, "loop_r_press", 55),   # Right Loop Encoder Press
    
    # Byte 0x15: Channel 2 (Right deck) transport + hotcues
    ButtonDef(0x15, 0x80, "hotcue1_r", 56),      # Hotcue 1 Right
    ButtonDef(0x15, 0x40, "hotcue2_r", 57),      # Hotcue 2 Right
    ButtonDef(0x15, 0x20, "hotcue3_r", 58),      # Hotcue 3 Right
    ButtonDef(0x15, 0x10, "hotcue4_r", 59),      # Hotcue 4 Right
    ButtonDef(0x15, 0x08, "flux_r", 60),         # Flux/Slip Right
    ButtonDef(0x15, 0x04, "sync_r", 61),         # Sync Right
    ButtonDef(0x15, 0x02, "cue_r", 62),          # Cue Right
    ButtonDef(0x15, 0x01, "play_r", 63),         # Play Right
    
    # Byte 0x16: Channel 1 (Left deck) transport + hotcues
    ButtonDef(0x16, 0x80, "hotcue1_l", 64),      # Hotcue 1 Left
    ButtonDef(0x16, 0x40, "hotcue2_l", 65),      # Hotcue 2 Left
    ButtonDef(0x16, 0x20, "hotcue3_l", 66),      # Hotcue 3 Left
    ButtonDef(0x16, 0x10, "hotcue4_l", 67),      # Hotcue 4 Left
    ButtonDef(0x16, 0x08, "flux_l", 68),         # Flux/Slip Left
    ButtonDef(0x16, 0x04, "sync_l", 69),         # Sync Left
    ButtonDef(0x16, 0x02, "cue_l", 70),          # Cue Left
    ButtonDef(0x16, 0x01, "play_l", 71),         # Play Left
    
    # Byte 0x17: Encoder presses
    ButtonDef(0x17, 0x02, "browse_press", 72),   # Browse Encoder Press
    ButtonDef(0x17, 0x01, "loop_l_press", 73),   # Left Loop Encoder Press
]

# Encoder CC assignments
CC_BROWSE = 80      # Browse encoder rotation
CC_LOOP_L = 81      # Left deck encoder rotation
CC_LOOP_R = 82      # Right deck encoder rotation
CC_TOUCH = 83       # Touch strip position


# =============================================================================
# LED Output Report Structure (Report 0x80)
# =============================================================================

LED_OFFSETS = {
    # FX buttons
    "fx1_focus": 0x01,
    "fx1_btn1": 0x02,
    "fx1_btn2": 0x03,
    "fx1_btn3": 0x04,
    "fx2_focus": 0x05,
    "fx2_btn1": 0x06,
    "fx2_btn2": 0x07,
    "fx2_btn3": 0x08,
    
    # FX assign
    "fx1_to_ch1": 0x09,
    "fx2_to_ch1": 0x0A,
    "fx1_arrow_l": 0x0B,
    "fx1_arrow_r": 0x0C,
    "fx2_arrow_l": 0x0D,
    "fx2_arrow_r": 0x0E,
    "fx1_to_ch2": 0x0F,
    "fx2_to_ch2": 0x10,
    
    # Track loaded
    "load_left": 0x11,
    "shift": 0x12,
    "load_right": 0x13,
    
    # Hotcue pads Left (RGB)
    "hc1_l_r": 0x14, "hc1_l_g": 0x15, "hc1_l_b": 0x16,
    "hc2_l_r": 0x17, "hc2_l_g": 0x18, "hc2_l_b": 0x19,
    
    # Hotcue pads Right (RGB)
    "hc1_r_r": 0x1A, "hc1_r_g": 0x1B, "hc1_r_b": 0x1C,
    "hc2_r_r": 0x1D, "hc2_r_g": 0x1E, "hc2_r_b": 0x1F,
    
    # More hotcue pads Left
    "hc3_l_r": 0x20, "hc3_l_g": 0x21, "hc3_l_b": 0x22,
    "hc4_l_r": 0x23, "hc4_l_g": 0x24, "hc4_l_b": 0x25,
    
    # More hotcue pads Right
    "hc3_r_r": 0x26, "hc3_r_g": 0x27, "hc3_r_b": 0x28,
    "hc4_r_r": 0x29, "hc4_r_g": 0x2A, "hc4_r_b": 0x2B,
    
    # Transport Left
    "flux_l": 0x2C,
    "sync_l": 0x2D,
    
    # Transport Right
    "flux_r": 0x2E,
    "sync_r": 0x2F,
    
    # More transport
    "cue_l": 0x30,
    "play_l": 0x31,
    "cue_r": 0x32,
    "play_r": 0x33,
}


# =============================================================================
# X1 MK2 Bridge Class
# =============================================================================

class X1MK2Bridge:
    """HID to MIDI bridge for Traktor Kontrol X1 MK2."""
    
    def __init__(self, device_path: str = None, midi_channel: int = 1):
        self.device_path = device_path
        self.fd = None
        self.midi_out = None
        self.midi_channel = midi_channel  # 0-indexed (0 = Ch1, 1 = Ch2)
        
        # State tracking
        self.last_knobs = {}
        self.last_buttons = {}
        self.last_encoders = {"browse": None, "loop_l": None, "loop_r": None}
        self.last_touch = None
        
        # LED state buffer (report 0x80 is ~52 bytes, we use first 52)
        self.led_state = bytearray([OUTPUT_REPORT_BUTTONS] + [0x00] * 51)
        
    def find_device(self) -> Optional[str]:
        """Find the X1 MK2 hidraw device."""
        for i in range(20):
            path = f"/dev/hidraw{i}"
            if not os.path.exists(path):
                continue
            try:
                sysfs_path = f"/sys/class/hidraw/hidraw{i}/device/uevent"
                if os.path.exists(sysfs_path):
                    with open(sysfs_path, 'r') as f:
                        content = f.read().upper()
                        if "17CC" in content and "1220" in content:
                            return path
            except (IOError, PermissionError):
                continue
        return None
    
    def open(self) -> bool:
        """Open HID device and MIDI port."""
        # Find device if not specified
        if self.device_path is None:
            self.device_path = self.find_device()
            if self.device_path is None:
                print("ERROR: X1 MK2 not found. Is it connected?")
                return False
        
        # Open HID device
        try:
            self.fd = os.open(self.device_path, os.O_RDWR | os.O_NONBLOCK)
            print(f"Opened X1 MK2 at {self.device_path}")
        except (IOError, PermissionError) as e:
            print(f"ERROR: Cannot open {self.device_path}: {e}")
            return False
        
        # Open MIDI port
        try:
            self.midi_out = rtmidi.MidiOut()
            self.midi_out.open_virtual_port("Traktor Kontrol X1 MK2")
            print("Created MIDI port: Traktor Kontrol X1 MK2")
        except Exception as e:
            print(f"ERROR: Cannot create MIDI port: {e}")
            os.close(self.fd)
            return False
        
        return True
    
    def close(self):
        """Clean up resources."""
        if self.midi_out:
            self.midi_out.close_port()
        if self.fd:
            os.close(self.fd)
    
    def initialize_leds(self):
        """Send LED initialization to wake up the device."""
        # Set all button LEDs to dim
        for name, offset in LED_OFFSETS.items():
            if offset < len(self.led_state):
                # Dim for most, off for RGB components
                if '_r' in name or '_g' in name or '_b' in name:
                    self.led_state[offset] = LED_OFF
                else:
                    self.led_state[offset] = LED_DIM
        
        self._send_led_report()
        print("LEDs initialized")
    
    def _send_led_report(self):
        """Send current LED state to device."""
        if self.fd:
            try:
                os.write(self.fd, bytes(self.led_state))
            except Exception as e:
                print(f"LED write error: {e}")
    
    def set_led(self, name: str, brightness: int):
        """Set a single LED brightness."""
        if name in LED_OFFSETS:
            offset = LED_OFFSETS[name]
            if offset < len(self.led_state):
                self.led_state[offset] = brightness & 0x7F
    
    def send_cc(self, cc: int, value: int):
        """Send MIDI CC message."""
        if self.midi_out:
            msg = [0xB0 | (self.midi_channel & 0x0F), cc & 0x7F, value & 0x7F]
            self.midi_out.send_message(msg)
    
    def send_note(self, note: int, velocity: int):
        """Send MIDI Note On/Off message."""
        if self.midi_out:
            status = 0x90 if velocity > 0 else 0x80
            msg = [status | (self.midi_channel & 0x0F), note & 0x7F, velocity & 0x7F]
            self.midi_out.send_message(msg)
    
    def process_report(self, data: bytes):
        """Process an HID input report."""
        if len(data) < 31:
            return
        if data[0] != INPUT_REPORT_ID:
            return
        
        # Process knobs (12-bit values)
        for offset, name, cc in KNOBS:
            if offset + 1 < len(data):
                # Little-endian 16-bit, masked to 12-bit
                raw = data[offset] | (data[offset + 1] << 8)
                raw &= 0x0FFF
                
                # Convert to 7-bit MIDI (0-127)
                midi_val = raw >> 5  # Divide by 32 (4096/128)
                
                # Only send if changed (with small deadzone)
                last = self.last_knobs.get(name, -1)
                if abs(midi_val - last) > 0:
                    self.last_knobs[name] = midi_val
                    self.send_cc(cc, midi_val)
        
        # Process buttons
        for btn in BUTTONS:
            if btn.byte_offset < len(data):
                pressed = (data[btn.byte_offset] & btn.mask) != 0
                last_pressed = self.last_buttons.get(btn.name, False)
                
                if pressed != last_pressed:
                    self.last_buttons[btn.name] = pressed
                    self.send_note(btn.note, 127 if pressed else 0)
                    
                    # Update LED if applicable
                    led_name = btn.name
                    if led_name in LED_OFFSETS:
                        self.set_led(led_name, LED_FULL if pressed else LED_DIM)
                    
                    if pressed:
                        print(f"Button: {btn.name} (Note {btn.note})")
        
        # Process encoders (4-bit relative values, 0-15 wrapping)
        # Browse encoder: byte 0x11 high nibble
        browse_val = (data[0x11] >> 4) & 0x0F
        if self.last_encoders["browse"] is not None:
            delta = self._calc_encoder_delta(browse_val, self.last_encoders["browse"])
            if delta != 0:
                # Send relative: 1 = CW, 127 = CCW (standard relative mode)
                self.send_cc(CC_BROWSE, 1 if delta > 0 else 127)
        self.last_encoders["browse"] = browse_val
        
        # Left deck encoder: byte 0x11 low nibble
        loop_l_val = data[0x11] & 0x0F
        if self.last_encoders["loop_l"] is not None:
            delta = self._calc_encoder_delta(loop_l_val, self.last_encoders["loop_l"])
            if delta != 0:
                self.send_cc(CC_LOOP_L, 1 if delta > 0 else 127)
        self.last_encoders["loop_l"] = loop_l_val
        
        # Right deck encoder: byte 0x12 low nibble
        loop_r_val = data[0x12] & 0x0F
        if self.last_encoders["loop_r"] is not None:
            delta = self._calc_encoder_delta(loop_r_val, self.last_encoders["loop_r"])
            if delta != 0:
                self.send_cc(CC_LOOP_R, 1 if delta > 0 else 127)
        self.last_encoders["loop_r"] = loop_r_val
        
        # Process touch strip
        # Touch positions at 0x1B and 0x1D (11-bit values, mask 0x07FF)
        touch0 = (data[0x1B] | (data[0x1C] << 8)) & 0x07FF
        touch1 = (data[0x1D] | (data[0x1E] << 8)) & 0x07FF
        
        # Use touch0 if valid (non-zero typically means touched)
        if touch0 > 0:
            # Scale 0-2047 to 0-127
            midi_val = min(127, touch0 >> 4)
            if self.last_touch != midi_val:
                self.last_touch = midi_val
                self.send_cc(CC_TOUCH, midi_val)
        
        # Update LEDs periodically (not every report to reduce USB traffic)
        self._send_led_report()
    
    def _calc_encoder_delta(self, current: int, previous: int) -> int:
        """Calculate encoder delta with wraparound handling."""
        delta = current - previous
        # Handle wraparound (0-15 range)
        if delta > 8:
            delta -= 16
        elif delta < -8:
            delta += 16
        return delta
    
    def run(self):
        """Main loop."""
        print(f"X1 MK2 Bridge running on MIDI Channel {self.midi_channel + 1}")
        print("Press Ctrl+C to stop")
        print("")
        print("Knob CCs: 10-17 (FX knobs)")
        print("Encoder CCs: 80 (Browse), 81 (Loop L), 82 (Loop R)")
        print("Touch Strip CC: 83")
        print("Button Notes: 40-73")
        print("")
        
        try:
            while True:
                try:
                    data = os.read(self.fd, 64)
                    if data:
                        self.process_report(data)
                except BlockingIOError:
                    time.sleep(0.001)
        except KeyboardInterrupt:
            print("\nStopping...")
        finally:
            self.close()


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Traktor Kontrol X1 MK2 HID to MIDI Bridge"
    )
    parser.add_argument('-d', '--device', type=str, default=None,
                        help='HID device path (default: auto-detect)')
    parser.add_argument('-c', '--channel', type=int, default=2,
                        help='MIDI channel 1-16 (default: 2)')
    args = parser.parse_args()
    
    if not 1 <= args.channel <= 16:
        print("ERROR: MIDI channel must be 1-16")
        sys.exit(1)
    
    bridge = X1MK2Bridge(
        device_path=args.device,
        midi_channel=args.channel - 1  # Convert to 0-indexed
    )
    
    if not bridge.open():
        sys.exit(1)
    
    bridge.initialize_leds()
    bridge.run()


if __name__ == "__main__":
    main()

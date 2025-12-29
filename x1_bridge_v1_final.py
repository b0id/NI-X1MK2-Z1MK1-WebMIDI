#!/usr/bin/env python3
"""
Native Instruments Traktor Kontrol X1 MK2 - HID to MIDI Bridge v1.0
====================================================================
Rock-solid DJ-ready implementation with:
- All buttons mapped (30 buttons)
- Shift layer doubles buttons (60 total notes)
- 8 FX knobs (CC 10-17)
- 3 encoders with push (CC 80-82)
- Touch strip full range (CC 83)
- All LEDs including RGB hotcue pads (light purple)

Based on Mixxx community HID mapping by infiniteloop
Author: Colby's NI Linux Bridge Project
License: GPL-3.0
"""

import os
import sys
import time
import argparse
from dataclasses import dataclass
from typing import Optional, Dict

try:
    import rtmidi
except ImportError:
    print("ERROR: python-rtmidi not installed.")
    print("Install with: pip install python-rtmidi --break-system-packages")
    sys.exit(1)


# =============================================================================
# Hardware Constants
# =============================================================================

X1_VENDOR_ID = 0x17cc
X1_PRODUCT_ID = 0x1220

INPUT_REPORT_ID = 0x01
OUTPUT_REPORT_BUTTONS = 0x80

# LED brightness
LED_OFF = 0x00
LED_DIM = 0x10
LED_MED = 0x40
LED_FULL = 0x7F

# =============================================================================
# Touch Strip Calibration (from your hex dump)
# =============================================================================

TOUCH_MIN = 90      # Left edge value
TOUCH_MAX = 1020    # Right edge value
TOUCH_RANGE = TOUCH_MAX - TOUCH_MIN


# =============================================================================
# Button Definitions
# =============================================================================

@dataclass(frozen=True)
class ButtonDef:
    byte_offset: int
    mask: int
    name: str
    note: int           # Normal note
    shift_note: int     # Note when shift held
    led_name: Optional[str] = None  # LED to light (if any)

# All 30 buttons with shift layer
# Normal notes: 40-72
# Shifted notes: 74-106 (normal + 34, no MIDI overflow)

BUTTONS = [
    # === Byte 0x13: FX Buttons (8 buttons) ===
    ButtonDef(0x13, 0x80, "fx1_focus", 40, 74, "fx1_focus"),
    ButtonDef(0x13, 0x40, "fx1_btn1", 41, 75, "fx1_btn1"),
    ButtonDef(0x13, 0x20, "fx1_btn2", 42, 76, "fx1_btn2"),
    ButtonDef(0x13, 0x10, "fx1_btn3", 43, 77, "fx1_btn3"),
    ButtonDef(0x13, 0x08, "fx2_focus", 44, 78, "fx2_focus"),
    ButtonDef(0x13, 0x04, "fx2_btn1", 45, 79, "fx2_btn1"),
    ButtonDef(0x13, 0x02, "fx2_btn2", 46, 80, "fx2_btn2"),
    ButtonDef(0x13, 0x01, "fx2_btn3", 47, 81, "fx2_btn3"),
    
    # === Byte 0x14: FX Assign, Load, Shift (7 buttons + shift) ===
    ButtonDef(0x14, 0x80, "fx1_to_ch1", 48, 82, "fx1_to_ch1"),
    ButtonDef(0x14, 0x40, "fx2_to_ch1", 49, 83, "fx2_to_ch1"),
    ButtonDef(0x14, 0x20, "fx1_to_ch2", 50, 84, "fx1_to_ch2"),
    ButtonDef(0x14, 0x10, "fx2_to_ch2", 51, 85, "fx2_to_ch2"),
    ButtonDef(0x14, 0x08, "load_left", 52, 86, "load_left"),
    # Shift is handled specially - not in this list
    ButtonDef(0x14, 0x02, "load_right", 53, 87, "load_right"),
    ButtonDef(0x14, 0x01, "loop_r_press", 54, 88, None),
    
    # === Byte 0x15: Channel 2 (Right deck) - 8 buttons ===
    # Hotcues use RGB - we'll set all 3 channels in button handler
    ButtonDef(0x15, 0x80, "hotcue1_r", 55, 89, "hotcue1_r"),
    ButtonDef(0x15, 0x40, "hotcue2_r", 56, 90, "hotcue2_r"),
    ButtonDef(0x15, 0x20, "hotcue3_r", 57, 91, "hotcue3_r"),
    ButtonDef(0x15, 0x10, "hotcue4_r", 58, 92, "hotcue4_r"),
    ButtonDef(0x15, 0x08, "flux_r", 59, 93, "flux_r"),
    ButtonDef(0x15, 0x04, "sync_r", 60, 94, "sync_r"),
    ButtonDef(0x15, 0x02, "cue_r", 61, 95, "cue_r"),
    ButtonDef(0x15, 0x01, "play_r", 62, 96, "play_r"),
    
    # === Byte 0x16: Channel 1 (Left deck) - 8 buttons ===
    ButtonDef(0x16, 0x80, "hotcue1_l", 63, 97, "hotcue1_l"),
    ButtonDef(0x16, 0x40, "hotcue2_l", 64, 98, "hotcue2_l"),
    ButtonDef(0x16, 0x20, "hotcue3_l", 65, 99, "hotcue3_l"),
    ButtonDef(0x16, 0x10, "hotcue4_l", 66, 100, "hotcue4_l"),
    ButtonDef(0x16, 0x08, "flux_l", 67, 101, "flux_l"),
    ButtonDef(0x16, 0x04, "sync_l", 68, 102, "sync_l"),
    ButtonDef(0x16, 0x02, "cue_l", 69, 103, "cue_l"),
    ButtonDef(0x16, 0x01, "play_l", 70, 104, "play_l"),
    
    # === Byte 0x17: Encoder presses (2 buttons) ===
    ButtonDef(0x17, 0x02, "browse_press", 71, 105, None),
    ButtonDef(0x17, 0x01, "loop_l_press", 72, 106, None),
]

# Hotcue RGB mapping - maps button name to (R, G, B) LED offset tuple
HOTCUE_RGB = {
    "hotcue1_l": ("hotcue1_l_r", "hotcue1_l_g", "hotcue1_l_b"),
    "hotcue2_l": ("hotcue2_l_r", "hotcue2_l_g", "hotcue2_l_b"),
    "hotcue3_l": ("hotcue3_l_r", "hotcue3_l_g", "hotcue3_l_b"),
    "hotcue4_l": ("hotcue4_l_r", "hotcue4_l_g", "hotcue4_l_b"),
    "hotcue1_r": ("hotcue1_r_r", "hotcue1_r_g", "hotcue1_r_b"),
    "hotcue2_r": ("hotcue2_r_r", "hotcue2_r_g", "hotcue2_r_b"),
    "hotcue3_r": ("hotcue3_r_r", "hotcue3_r_g", "hotcue3_r_b"),
    "hotcue4_r": ("hotcue4_r_r", "hotcue4_r_g", "hotcue4_r_b"),
}

# Default hotcue colors
HOTCUE_COLOR_BRIGHT = (0x50, 0x20, 0x60)  # Bright purple/pink when set
HOTCUE_COLOR_DIM = (0x18, 0x08, 0x1A)     # Dim pink when empty

# Shift button is special - tracked but sends its own note
SHIFT_BYTE = 0x14
SHIFT_MASK = 0x04
SHIFT_NOTE = 73
SHIFT_LED = "shift"


# =============================================================================
# Knob and Encoder CCs
# =============================================================================

KNOBS = [
    (0x01, "fx1_mix", 10),
    (0x03, "fx1_knob1", 11),
    (0x05, "fx1_knob2", 12),
    (0x07, "fx1_knob3", 13),
    (0x09, "fx2_mix", 14),
    (0x0B, "fx2_knob1", 15),
    (0x0D, "fx2_knob2", 16),
    (0x0F, "fx2_knob3", 17),
]

CC_BROWSE = 80
CC_LOOP_L = 81
CC_LOOP_R = 82
CC_TOUCH = 83

# Shifted encoder CCs (when shift held)
CC_BROWSE_SHIFT = 84
CC_LOOP_L_SHIFT = 85
CC_LOOP_R_SHIFT = 86
CC_TOUCH_SHIFT = 87


# =============================================================================
# LED Output Map (Report 0x80) - Definitive from probe
# =============================================================================
# Byte offsets are 0-indexed into the 51-byte data payload (after report ID)

LED_OFFSETS = {
    # FX Mode & Buttons (bytes 0-7)
    "fx1_focus": 0,       # LEFTFXMODE
    "fx1_btn1": 1,        # LEFTFX1
    "fx1_btn2": 2,        # LEFTFX2
    "fx1_btn3": 3,        # LEFTFX3
    "fx2_focus": 4,       # RIGHTFXMODE
    "fx2_btn1": 5,        # RIGHTFX1
    "fx2_btn2": 6,        # RIGHTFX2
    "fx2_btn3": 7,        # RIGHTFX3
    
    # FX Select (bytes 8-15)
    "fx1_to_ch1": 8,      # LEFTFXSELECT1
    "fx2_to_ch1": 9,      # LEFTFXSELECT2
    "fx1_arrow_l": 10,    # LEFT-LEFTARROW
    "fx1_arrow_r": 11,    # LEFT-RIGHTARROW
    "fx2_arrow_l": 12,    # RIGHT-LEFTARROW
    "fx2_arrow_r": 13,    # RIGHT-RIGHTARROW
    "fx1_to_ch2": 14,     # RIGHTFXSELECT1
    "fx2_to_ch2": 15,     # RIGHTFXSELECT2
    
    # Load & Shift (bytes 16-18)
    "load_left": 16,      # LOADLEFT
    "shift": 17,          # SHIFT
    "load_right": 18,     # LOADRIGHT
    
    # Hotcue Pads - RGB (bytes 19-42)
    # Left Deck Hotcue 1
    "hotcue1_l_r": 19,    # LEFTDECKHOTCUE1 R
    "hotcue1_l_g": 20,    # LEFTDECKHOTCUE1 G
    "hotcue1_l_b": 21,    # LEFTDECKHOTCUE1 B
    # Left Deck Hotcue 2
    "hotcue2_l_r": 22,    # LEFTDECKHOTCUE2 R
    "hotcue2_l_g": 23,    # LEFTDECKHOTCUE2 G
    "hotcue2_l_b": 24,    # LEFTDECKHOTCUE2 B
    # Right Deck Hotcue 1
    "hotcue1_r_r": 25,    # RIGHTDECKHOTCUE1 R
    "hotcue1_r_g": 26,    # RIGHTDECKHOTCUE1 G
    "hotcue1_r_b": 27,    # RIGHTDECKHOTCUE1 B
    # Right Deck Hotcue 2
    "hotcue2_r_r": 28,    # RIGHTDECKHOTCUE2 R
    "hotcue2_r_g": 29,    # RIGHTDECKHOTCUE2 G
    "hotcue2_r_b": 30,    # RIGHTDECKHOTCUE2 B
    # Left Deck Hotcue 3
    "hotcue3_l_r": 31,    # LEFTDECKHOTCUE3 R
    "hotcue3_l_g": 32,    # LEFTDECKHOTCUE3 G
    "hotcue3_l_b": 33,    # LEFTDECKHOTCUE3 B
    # Left Deck Hotcue 4
    "hotcue4_l_r": 34,    # LEFTDECKHOTCUE4 R
    "hotcue4_l_g": 35,    # LEFTDECKHOTCUE4 G
    "hotcue4_l_b": 36,    # LEFTDECKHOTCUE4 B
    # Right Deck Hotcue 3
    "hotcue3_r_r": 37,    # RIGHTDECKHOTCUE3 R
    "hotcue3_r_g": 38,    # RIGHTDECKHOTCUE3 G
    "hotcue3_r_b": 39,    # RIGHTDECKHOTCUE3 B
    # Right Deck Hotcue 4
    "hotcue4_r_r": 40,    # RIGHTDECKHOTCUE4 R
    "hotcue4_r_g": 41,    # RIGHTDECKHOTCUE4 G
    "hotcue4_r_b": 42,    # RIGHTDECKHOTCUE4 B
    
    # Transport (bytes 43-50)
    "flux_l": 43,         # LEFT FLUX B
    "sync_l": 44,         # LEFT SYNC B
    "flux_r": 45,         # RIGHT FLUX B
    "sync_r": 46,         # RIGHT SYNC B
    "cue_l": 47,          # LEFT CUE B
    "play_l": 48,         # LEFT PLAY G
    "cue_r": 49,          # RIGHT CUE B
    "play_r": 50,         # RIGHT PLAY G
}

# =============================================================================
# X1 MK2 Bridge Class
# =============================================================================

class X1MK2Bridge:
    """HID to MIDI bridge for Traktor Kontrol X1 MK2 v1.0"""
    
    def __init__(self, device_path: str = None, midi_channel: int = 1, debug: bool = False):
        self.device_path = device_path
        self.fd = None
        self.midi_out = None
        self.midi_channel = midi_channel  # 0-indexed
        self.debug = debug
        
        # State
        self.shift_held = False
        self.last_knobs: Dict[str, int] = {}
        self.last_buttons: Dict[str, bool] = {}
        self.last_encoders = {"browse": None, "loop_l": None, "loop_r": None}
        self.last_touch = None
        
        # LED state buffer (Report 0x80 = 51 data bytes, confirmed from HID descriptor)
        self.led_state = bytearray([OUTPUT_REPORT_BUTTONS] + [0x00] * 51)  # 52 bytes total
        self.led_dirty = True
        
        # Hotcue state tracking (True = hotcue is set, False = empty)
        self.hotcue_set = {name: False for name in HOTCUE_RGB}
        
    def find_device(self) -> Optional[str]:
        """Auto-detect X1 MK2 hidraw device."""
        for i in range(20):
            path = f"/dev/hidraw{i}"
            if not os.path.exists(path):
                continue
            try:
                with open(f"/sys/class/hidraw/hidraw{i}/device/uevent", 'r') as f:
                    content = f.read().upper()
                    if "17CC" in content and "1220" in content:
                        return path
            except:
                continue
        return None
    
    def open(self) -> bool:
        """Open HID device and create MIDI port."""
        if self.device_path is None:
            self.device_path = self.find_device()
            if self.device_path is None:
                print("ERROR: X1 MK2 not found!")
                return False
        
        try:
            self.fd = os.open(self.device_path, os.O_RDWR | os.O_NONBLOCK)
            print(f"✓ Opened X1 MK2: {self.device_path}")
        except Exception as e:
            print(f"ERROR: Cannot open {self.device_path}: {e}")
            return False
        
        try:
            self.midi_out = rtmidi.MidiOut()
            self.midi_out.open_virtual_port("Traktor Kontrol X1 MK2")
            print(f"✓ MIDI port: Traktor Kontrol X1 MK2 (Channel {self.midi_channel + 1})")
        except Exception as e:
            print(f"ERROR: Cannot create MIDI port: {e}")
            os.close(self.fd)
            return False
        
        return True
    
    def close(self):
        """Clean shutdown."""
        if self.midi_out:
            self.midi_out.close_port()
        if self.fd:
            os.close(self.fd)
    
    # =========================================================================
    # LED Control
    # =========================================================================
    
    def set_led(self, name: str, brightness: int):
        """Set single-color LED by name."""
        if name in LED_OFFSETS:
            offset = LED_OFFSETS[name]
            # Offset is into data portion, led_state[0] is report ID
            if offset + 1 < len(self.led_state):
                self.led_state[offset + 1] = brightness & 0x7F
                self.led_dirty = True
    
    def set_hotcue_rgb(self, name: str, r: int, g: int, b: int):
        """Set hotcue pad RGB color."""
        if name in HOTCUE_RGB:
            r_name, g_name, b_name = HOTCUE_RGB[name]
            self.set_led(r_name, r)
            self.set_led(g_name, g)
            self.set_led(b_name, b)
    
    def send_leds(self):
        """Send LED state to device."""
        if self.led_dirty and self.fd:
            try:
                os.write(self.fd, bytes(self.led_state))
                self.led_dirty = False
            except:
                pass
    
    def initialize_leds(self):
        """Set initial LED state - all buttons dim, hotcues dim pink."""
        # Set all single-color LEDs to dim
        for name, offset in LED_OFFSETS.items():
            # Skip RGB components - we'll handle hotcues separately
            if '_r' not in name and '_g' not in name and '_b' not in name:
                self.set_led(name, LED_DIM)
        
        # Set all hotcue RGB to dim pink (empty state)
        for hotcue_name in HOTCUE_RGB:
            self.set_hotcue_rgb(hotcue_name, *HOTCUE_COLOR_DIM)
            self.hotcue_set[hotcue_name] = False
        
        self.send_leds()
        print("✓ LEDs initialized")
    
    # =========================================================================
    # MIDI Output
    # =========================================================================
    
    def send_cc(self, cc: int, value: int):
        """Send MIDI Control Change."""
        if self.midi_out:
            self.midi_out.send_message([0xB0 | self.midi_channel, cc & 0x7F, value & 0x7F])
    
    def send_note_on(self, note: int, velocity: int = 127):
        """Send MIDI Note On."""
        if self.midi_out:
            self.midi_out.send_message([0x90 | self.midi_channel, note & 0x7F, velocity & 0x7F])
    
    def send_note_off(self, note: int):
        """Send MIDI Note Off."""
        if self.midi_out:
            self.midi_out.send_message([0x80 | self.midi_channel, note & 0x7F, 0])
    
    # =========================================================================
    # Input Processing
    # =========================================================================
    
    def process_report(self, data: bytes):
        """Process HID input report."""
        if len(data) < 31 or data[0] != INPUT_REPORT_ID:
            return
        
        # --- Shift Button (internal only - no MIDI output) ---
        shift_pressed = (data[SHIFT_BYTE] & SHIFT_MASK) != 0
        if shift_pressed != self.shift_held:
            self.shift_held = shift_pressed
            if shift_pressed:
                # No MIDI sent - shift only modifies other buttons
                self.set_led(SHIFT_LED, LED_FULL)
                if self.debug:
                    print("SHIFT: ON")
            else:
                self.set_led(SHIFT_LED, LED_DIM)
                if self.debug:
                    print("SHIFT: OFF")
        
        # --- Knobs (12-bit -> 7-bit) ---
        for offset, name, cc in KNOBS:
            if offset + 1 < len(data):
                raw = (data[offset] | (data[offset + 1] << 8)) & 0x0FFF
                midi_val = raw >> 5  # 4096 -> 128
                
                if self.last_knobs.get(name, -1) != midi_val:
                    self.last_knobs[name] = midi_val
                    self.send_cc(cc, midi_val)
        
        # --- Buttons ---
        for btn in BUTTONS:
            if btn.byte_offset < len(data):
                pressed = (data[btn.byte_offset] & btn.mask) != 0
                was_pressed = self.last_buttons.get(btn.name, False)
                
                if pressed != was_pressed:
                    self.last_buttons[btn.name] = pressed
                    
                    # Choose note based on shift state
                    note = btn.shift_note if self.shift_held else btn.note
                    
                    if pressed:
                        self.send_note_on(note)
                        if self.debug:
                            shifted = " [SHIFT]" if self.shift_held else ""
                            print(f"Button: {btn.name} → Note {note}{shifted}")
                        
                        # Update LED - check if it's a hotcue (RGB) or regular LED
                        if btn.led_name:
                            if btn.led_name in HOTCUE_RGB:
                                # Hotcue stateful logic
                                if self.shift_held:
                                    # Shift+press = delete hotcue → dim pink
                                    self.hotcue_set[btn.led_name] = False
                                    self.set_hotcue_rgb(btn.led_name, *HOTCUE_COLOR_DIM)
                                elif not self.hotcue_set[btn.led_name]:
                                    # Press on empty = set hotcue → bright
                                    self.hotcue_set[btn.led_name] = True
                                    self.set_hotcue_rgb(btn.led_name, *HOTCUE_COLOR_BRIGHT)
                                # If already set and no shift, LED stays bright (no change)
                            else:
                                self.set_led(btn.led_name, LED_FULL)
                    else:
                        self.send_note_off(note)
                        
                        # LED off/dim - but NOT for hotcues (they maintain state)
                        if btn.led_name:
                            if btn.led_name not in HOTCUE_RGB:
                                self.set_led(btn.led_name, LED_DIM)
        
        # --- Encoders (4-bit relative) ---
        # Browse: byte 0x11 high nibble
        browse_val = (data[0x11] >> 4) & 0x0F
        if self.last_encoders["browse"] is not None:
            delta = self._encoder_delta(browse_val, self.last_encoders["browse"])
            if delta != 0:
                cc = CC_BROWSE_SHIFT if self.shift_held else CC_BROWSE
                self.send_cc(cc, 1 if delta > 0 else 127)
        self.last_encoders["browse"] = browse_val
        
        # Loop L: byte 0x11 low nibble
        loop_l_val = data[0x11] & 0x0F
        if self.last_encoders["loop_l"] is not None:
            delta = self._encoder_delta(loop_l_val, self.last_encoders["loop_l"])
            if delta != 0:
                cc = CC_LOOP_L_SHIFT if self.shift_held else CC_LOOP_L
                self.send_cc(cc, 1 if delta > 0 else 127)
        self.last_encoders["loop_l"] = loop_l_val
        
        # Loop R: byte 0x12 low nibble
        loop_r_val = data[0x12] & 0x0F
        if self.last_encoders["loop_r"] is not None:
            delta = self._encoder_delta(loop_r_val, self.last_encoders["loop_r"])
            if delta != 0:
                cc = CC_LOOP_R_SHIFT if self.shift_held else CC_LOOP_R
                self.send_cc(cc, 1 if delta > 0 else 127)
        self.last_encoders["loop_r"] = loop_r_val
        
        # --- Touch Strip ---
        # Position at 0x1B-0x1C (little-endian, 11-bit)
        touch_raw = (data[0x1B] | (data[0x1C] << 8)) & 0x07FF
        
        if touch_raw >= TOUCH_MIN:
            # Normalize to 0-127
            normalized = touch_raw - TOUCH_MIN
            midi_val = min(127, max(0, int(normalized * 127 / TOUCH_RANGE)))
            
            if midi_val != self.last_touch:
                self.last_touch = midi_val
                cc = CC_TOUCH_SHIFT if self.shift_held else CC_TOUCH
                self.send_cc(cc, midi_val)
        
        # Send LED updates
        self.send_leds()
    
    def _encoder_delta(self, current: int, previous: int) -> int:
        """Calculate encoder delta with 4-bit wraparound."""
        delta = current - previous
        if delta > 8:
            delta -= 16
        elif delta < -8:
            delta += 16
        return delta
    
    # =========================================================================
    # Main Loop
    # =========================================================================
    
    def run(self):
        """Main processing loop."""
        print("")
        print("=" * 60)
        print("X1 MK2 Bridge v1.0 Running")
        print("=" * 60)
        print(f"MIDI Channel: {self.midi_channel + 1}")
        print("")
        print("CONTROLS:")
        print("  Knobs:    CC 10-17 (FX knobs)")
        print("  Encoders: CC 80-82 (Browse, Loop L, Loop R)")
        print("  Touch:    CC 83")
        print("  Buttons:  Notes 40-72")
        print("")
        print("SHIFT LAYER (hold Shift):")
        print("  Encoders: CC 84-86")
        print("  Touch:    CC 87")
        print("  Buttons:  Notes 74-106")
        print("")
        print("Press Ctrl+C to stop")
        print("=" * 60)
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
            print("\n\nShutting down...")
        finally:
            self.close()
            print("Done.")


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Traktor Kontrol X1 MK2 HID to MIDI Bridge v1.0"
    )
    parser.add_argument('-d', '--device', type=str, default=None,
                        help='HID device path (default: auto-detect)')
    parser.add_argument('-c', '--channel', type=int, default=2,
                        help='MIDI channel 1-16 (default: 2)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Print button presses')
    args = parser.parse_args()
    
    if not 1 <= args.channel <= 16:
        print("ERROR: MIDI channel must be 1-16")
        sys.exit(1)
    
    bridge = X1MK2Bridge(
        device_path=args.device,
        midi_channel=args.channel - 1,
        debug=args.verbose
    )
    
    if not bridge.open():
        sys.exit(1)
    
    bridge.initialize_leds()
    bridge.run()


if __name__ == "__main__":
    main()

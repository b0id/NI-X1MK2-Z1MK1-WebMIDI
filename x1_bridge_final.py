#!/usr/bin/env python3
"""
Native Instruments Traktor Kontrol X1 MK2 – HID to MIDI Bridge (Final - Corrected)
======================================================================
Architecture: Modular Setup
- Defaults to MIDI Channel 2 (to coexist with Z1 on Ch 1)
- Auto-connects to VirMIDI
- Initializes LEDs on startup
- Fixed device detection
"""

import os
import sys
import time
import argparse
from dataclasses import dataclass
try:
    import rtmidi
except ImportError:
    print("ERROR: python-rtmidi not installed.")
    sys.exit(1)

# ============ CONFIGURATION ============

# Button Definitions (Mapped to Channel 2 Notes)
@dataclass(frozen=True)
class ButtonDef:
    name: str
    byte_idx: int
    mask: int
    note: int

# We map X1 buttons to a clean range of notes (10-50)
BUTTONS = [
    # Transport & FX
    ButtonDef("PLAY_RIGHT", 21, 0x01, 10), ButtonDef("CUE_RIGHT", 21, 0x02, 11),
    ButtonDef("SYNC_RIGHT", 21, 0x04, 12), ButtonDef("FLUX_RIGHT", 21, 0x08, 13),
    ButtonDef("PLAY_LEFT",  22, 0x01, 14), ButtonDef("CUE_LEFT",  22, 0x02, 15),
    ButtonDef("SYNC_LEFT",  22, 0x04, 16), ButtonDef("FLUX_LEFT", 22, 0x08, 17),
    
    # FX Buttons
    ButtonDef("FX1_L_ON", 19, 0x40, 18), ButtonDef("FX2_L_ON", 19, 0x20, 19), ButtonDef("FX3_L_ON", 19, 0x10, 20),
    ButtonDef("FX1_R_ON", 19, 0x04, 21), ButtonDef("FX2_R_ON", 19, 0x02, 22), ButtonDef("FX3_R_ON", 19, 0x01, 23),
    
    # Encoder Presses
    ButtonDef("BROWSE_PUSH", 23, 0x02, 24),
    ButtonDef("LOOP_L_PUSH", 23, 0x01, 25),
    ButtonDef("LOOP_R_PUSH", 20, 0x01, 26),
    
    # Hotcues (Right)
    ButtonDef("HC1_R", 21, 0x80, 27), ButtonDef("HC2_R", 21, 0x40, 28),
    ButtonDef("HC3_R", 21, 0x20, 29), ButtonDef("HC4_R", 21, 0x10, 30),
    # Hotcues (Left)
    ButtonDef("HC1_L", 22, 0x80, 31), ButtonDef("HC2_L", 22, 0x40, 32),
    ButtonDef("HC3_L", 22, 0x20, 33), ButtonDef("HC4_L", 22, 0x10, 34),
]

KNOB_START_CC = 10
CC_BROWSE = 50
CC_LOOP_L = 51
CC_LOOP_R = 52
CC_TOUCH = 53

# ============ BRIDGE CLASS ============

class X1Bridge:
    def __init__(self, device_path, port_name, channel):
        self.device_path = device_path
        self.fd = None
        self.midi_out = rtmidi.MidiOut()
        self.midi_out.open_virtual_port(port_name)
        self.channel = channel # 0-15
        
        self.last_knobs = {}
        self.last_buttons = {}
        self.prev_report = None
        self.touch_active = False

    def start(self):
        try:
            self.fd = os.open(self.device_path, os.O_RDWR | os.O_NONBLOCK)
            print(f"Opened HID: {self.device_path}")
            
            # --- LED INITIALIZATION ---
            # Wake up the device LEDs
            init_report = bytearray([0x80] + [0x00] * 31) 
            # Set generic LEDs to DIM
            for i in range(1, 25): 
                init_report[i] = 0x10 
                
            os.write(self.fd, init_report)
            print("Sent LED Initialization sequence.")
            
        except OSError as e:
            print(f"Error: {e}")
            sys.exit(1)

    def send_midi(self, status_base, code, value):
        # Apply Channel Offset
        status = status_base | (self.channel & 0x0F)
        self.midi_out.send_message([status, code & 0x7F, value & 0x7F])

    def process(self, r):
        if len(r) != 31 or r[0] != 0x01: return

        # KNOBS (CC)
        for i in range(8):
            val = (r[1 + i*2] | (r[2 + i*2] << 8)) >> 5 # 12bit -> 7bit fast
            if self.last_knobs.get(i) != val:
                self.last_knobs[i] = val
                self.send_midi(0xB0, KNOB_START_CC + i, val)

        # BUTTONS (NOTE ON/OFF)
        for btn in BUTTONS:
            pressed = (r[btn.byte_idx] & btn.mask) != 0
            if self.last_buttons.get(btn.name) != pressed:
                self.last_buttons[btn.name] = pressed
                velocity = 127 if pressed else 0
                self.send_midi(0x90, btn.note, velocity)
                if pressed: print(f"Ch{self.channel+1} Note {btn.note}: {btn.name}")

        # ENCODERS (Relative CC)
        if self.prev_report:
            def get_delta(idx): return (r[idx] - self.prev_report[idx] + 128) % 256 - 128
            marker = r[23]
            
            if marker & 0x08: # Browse
                d = get_delta(17)
                self.send_midi(0xB0, CC_BROWSE, 1 if d > 0 else 127)
            if marker & 0x04: # Loop L
                d = get_delta(17)
                self.send_midi(0xB0, CC_LOOP_L, 1 if d > 0 else 127)
            if marker & 0x10: # Loop R
                d = get_delta(18)
                self.send_midi(0xB0, CC_LOOP_R, 1 if d > 0 else 127)

        # TOUCH STRIP
        touch_raw = r[25] | (r[26] << 8)
        touched = 21000 < touch_raw < 39000
        if touched:
            val = int((touch_raw - 21000) / 18000 * 127)
            val = max(0, min(127, val))
            self.send_midi(0xB0, CC_TOUCH, val)

        self.prev_report = bytes(r)

    def run(self):
        while True:
            try:
                data = os.read(self.fd, 31)
                if data: self.process(data)
            except BlockingIOError:
                time.sleep(0.001)

# ============ AUTO-CONNECT UTILITY ============

def auto_bridge(source_name, target_name="VirMIDI"):
    """Automatically runs aconnect to bridge the ports"""
    print(f"Bridging '{source_name}' -> '{target_name}'...")
    try:
        # Find client ID for Source
        src_stream = os.popen(f"aconnect -i | grep '{source_name}' | head -n1 | cut -d: -f1 | cut -d' ' -f2")
        src_client = src_stream.read().strip()
        src_stream.close()
        
        # Find client ID for Target (VirMIDI)
        tgt_stream = os.popen(f"aconnect -o | grep '{target_name}' | head -n1 | cut -d: -f1 | cut -d' ' -f2")
        tgt_client = tgt_stream.read().strip()
        tgt_stream.close()
        
        if src_client and tgt_client:
            cmd = f"aconnect {src_client}:0 {tgt_client}:0"
            print(f"Executing: {cmd}")
            os.system(cmd)
            print("SUCCESS: Connection Bridged.")
        else:
            print("WARNING: Could not auto-connect (IDs not found). Check 'aconnect -l'.")
    except Exception as e:
        print(f"Auto-bridge error: {e}")

# ============ MAIN ============

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", type=int, default=2, help="MIDI Channel (1-16)")
    args = parser.parse_args()

    # Find Device (Fixed Logic)
    dev_path = None
    for i in range(64): # Increased search range
        try:
            uevent_path = f"/sys/class/hidraw/hidraw{i}/device/uevent"
            if os.path.exists(uevent_path):
                with open(uevent_path, "r") as f:
                    # Read ONCE, store in variable, then check
                    info = f.read().upper()
                    if "17CC" in info and "1220" in info:
                        dev_path = f"/dev/hidraw{i}"
                        break
        except: pass

    if not dev_path:
        print("X1 MK2 Not Found.")
        sys.exit(1)

    # Convert 1-based channel to 0-based
    ch_idx = max(0, min(15, args.channel - 1))
    
    port_name = "Traktor Kontrol X1 MK2"
    bridge = X1Bridge(dev_path, port_name, ch_idx)
    bridge.start()
    
    # Run the auto-connector
    time.sleep(1) # Wait for port to register
    auto_bridge(port_name, "VirMIDI")

    try:
        bridge.run()
    except KeyboardInterrupt:
        print("\nStopped.")

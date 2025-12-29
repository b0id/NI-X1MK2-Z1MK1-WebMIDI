#!/usr/bin/env python3
"""
X1 MK2 7-Segment Display & Touch Strip LED Probe Tool
======================================================
Report 0x81 = 90 data bytes (confirmed from HID descriptor)
Total write = 91 bytes (report ID + data)

Structure (from Mixxx):
- Bytes 0x00-0x17 (0-23):   Left deck display (3 digits × 8 segments)
- Bytes 0x18-0x2F (24-47):  Right deck display (3 digits × 8 segments)
- Bytes 0x30-0x59 (48-89):  Touch strip LEDs (21 segments × 2 colors?)
"""

import os
import sys
import time

# Find the X1 MK2
def find_x1():
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

def send_display_report(fd, data):
    """Send a 91-byte display report (0x81 + 90 bytes)"""
    report = bytearray([0x81]) + bytearray(data)
    os.write(fd, bytes(report))

def all_on(fd, brightness=0x7F):
    """Turn ALL display segments on"""
    print(f"ALL DISPLAY ON at brightness 0x{brightness:02X}")
    send_display_report(fd, [brightness] * 90)

def all_off(fd):
    """Turn ALL display segments off"""
    print("ALL DISPLAY OFF")
    send_display_report(fd, [0x00] * 90)

def all_dim(fd):
    """All segments dim"""
    print("ALL DISPLAY DIM (0x10)")
    send_display_report(fd, [0x10] * 90)

def single_byte(fd, byte_index, brightness=0x7F):
    """Light up only a single byte position"""
    data = [0x00] * 90
    if 0 <= byte_index < 90:
        data[byte_index] = brightness
    send_display_report(fd, data)

def left_deck_display(fd, brightness=0x7F):
    """Light only left deck display (bytes 0-23)"""
    data = [0x00] * 90
    for i in range(24):
        data[i] = brightness
    send_display_report(fd, data)
    print("LEFT DECK DISPLAY (bytes 0-23)")

def right_deck_display(fd, brightness=0x7F):
    """Light only right deck display (bytes 24-47)"""
    data = [0x00] * 90
    for i in range(24, 48):
        data[i] = brightness
    send_display_report(fd, data)
    print("RIGHT DECK DISPLAY (bytes 24-47)")

def touch_strip_leds(fd, brightness=0x7F):
    """Light only touch strip LEDs (bytes 48-89)"""
    data = [0x00] * 90
    for i in range(48, 90):
        data[i] = brightness
    send_display_report(fd, data)
    print("TOUCH STRIP LEDs (bytes 48-89)")

def single_digit(fd, deck, digit, brightness=0x7F):
    """
    Light a single digit (all 8 segments)
    deck: 0=left, 1=right
    digit: 0, 1, 2 (left to right)
    """
    data = [0x00] * 90
    base = (deck * 24) + (digit * 8)
    for i in range(8):
        data[base + i] = brightness
    send_display_report(fd, data)
    print(f"Deck {deck} Digit {digit} (bytes {base}-{base+7})")

def probe_display_bytes(fd):
    """Iterate through each byte in display report"""
    print("\n" + "="*60)
    print("DISPLAY BYTE-BY-BYTE PROBE (Report 0x81)")
    print("="*60)
    print("Press Enter to advance, 'q' to quit, 's' to skip 10")
    print("="*60 + "\n")
    
    byte_index = 0
    while byte_index < 90:
        single_byte(fd, byte_index, 0x7F)
        
        # Show context
        if byte_index < 24:
            context = f"Left Deck, Digit {byte_index // 8}, Segment {byte_index % 8}"
        elif byte_index < 48:
            adj = byte_index - 24
            context = f"Right Deck, Digit {adj // 8}, Segment {adj % 8}"
        else:
            context = f"Touch Strip LED {byte_index - 48}"
        
        response = input(f"Byte {byte_index} (0x{byte_index:02X}) [{context}]: > ").strip().lower()
        
        if response == 'q':
            break
        elif response == 's':
            byte_index += 10
            continue
        
        byte_index += 1
    
    all_off(fd)
    print("\nProbe complete.")

def interactive_mode(fd):
    """Interactive testing mode"""
    print("\n" + "="*60)
    print("X1 MK2 DISPLAY INTERACTIVE MODE (Report 0x81)")
    print("="*60)
    print("Commands:")
    print("  on [brightness]  - All segments on (0-127, default 127)")
    print("  off              - All segments off")
    print("  dim              - All segments dim (0x10)")
    print("  b <num> [bright] - Single byte on (0-89)")
    print("  left             - Left deck display on")
    print("  right            - Right deck display on")
    print("  strip            - Touch strip LEDs on")
    print("  digit <d> <n>    - Single digit (deck 0-1, digit 0-2)")
    print("  probe            - Step through each byte")
    print("  range <s> <e>    - Light bytes from s to e")
    print("  q                - Quit")
    print("="*60 + "\n")
    
    while True:
        try:
            cmd = input("DISP> ").strip().lower().split()
            if not cmd:
                continue
            
            if cmd[0] == 'q':
                break
            elif cmd[0] == 'on':
                bright = int(cmd[1]) if len(cmd) > 1 else 0x7F
                all_on(fd, bright)
            elif cmd[0] == 'off':
                all_off(fd)
            elif cmd[0] == 'dim':
                all_dim(fd)
            elif cmd[0] == 'b' and len(cmd) >= 2:
                byte_idx = int(cmd[1])
                bright = int(cmd[2]) if len(cmd) > 2 else 0x7F
                single_byte(fd, byte_idx, bright)
                print(f"  Byte {byte_idx} (0x{byte_idx:02X}) = {bright}")
            elif cmd[0] == 'left':
                left_deck_display(fd)
            elif cmd[0] == 'right':
                right_deck_display(fd)
            elif cmd[0] == 'strip':
                touch_strip_leds(fd)
            elif cmd[0] == 'digit' and len(cmd) >= 3:
                deck = int(cmd[1])
                digit = int(cmd[2])
                single_digit(fd, deck, digit)
            elif cmd[0] == 'probe':
                probe_display_bytes(fd)
            elif cmd[0] == 'range' and len(cmd) >= 3:
                start = int(cmd[1])
                end = int(cmd[2])
                data = [0x00] * 90
                for i in range(start, min(end+1, 90)):
                    data[i] = 0x7F
                send_display_report(fd, data)
                print(f"  Bytes {start}-{end} ON")
            else:
                print("  Unknown command")
        except (ValueError, IndexError) as e:
            print(f"  Error: {e}")
        except KeyboardInterrupt:
            break
    
    all_off(fd)
    print("Done.")

def main():
    device_path = find_x1()
    if not device_path:
        print("ERROR: X1 MK2 not found!")
        sys.exit(1)
    
    print(f"Found X1 MK2 at {device_path}")
    
    try:
        fd = os.open(device_path, os.O_RDWR)
        print("Device opened successfully")
        print(f"Report 0x81: 90 data bytes (91 total with report ID)")
        print(f"  Bytes 0-23:  Left deck display")
        print(f"  Bytes 24-47: Right deck display") 
        print(f"  Bytes 48-89: Touch strip LEDs")
    except Exception as e:
        print(f"ERROR: Cannot open device: {e}")
        sys.exit(1)
    
    # Quick initialization test - flash all
    print("\nInitializing: Flash all display elements...")
    all_on(fd, 0x7F)
    time.sleep(0.5)
    all_off(fd)
    time.sleep(0.2)
    
    # Enter interactive mode
    interactive_mode(fd)
    
    os.close(fd)

if __name__ == "__main__":
    main()

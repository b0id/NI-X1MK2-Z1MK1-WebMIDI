#!/usr/bin/env python3
"""
X1 MK2 LED Probe Tool
=====================
Systematically probe each LED byte to create a definitive map.

Report 0x80 = 51 data bytes (confirmed from HID descriptor)
Total write = 52 bytes (report ID + data)
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

def send_led_report(fd, data):
    """Send a 52-byte LED report (0x80 + 51 bytes)"""
    report = bytearray([0x80]) + bytearray(data)
    os.write(fd, bytes(report))

def all_on(fd, brightness=0x7F):
    """Turn ALL LEDs on at specified brightness"""
    print(f"ALL ON at brightness 0x{brightness:02X}")
    send_led_report(fd, [brightness] * 51)

def all_off(fd):
    """Turn ALL LEDs off"""
    print("ALL OFF")
    send_led_report(fd, [0x00] * 51)

def all_dim(fd):
    """Turn ALL LEDs to dim"""
    print("ALL DIM (0x10)")
    send_led_report(fd, [0x10] * 51)

def single_byte(fd, byte_index, brightness=0x7F):
    """Light up only a single byte position"""
    data = [0x00] * 51
    if 0 <= byte_index < 51:
        data[byte_index] = brightness
    send_led_report(fd, data)

def probe_all_bytes(fd):
    """Iterate through each byte, one at a time"""
    print("\n" + "="*60)
    print("BYTE-BY-BYTE LED PROBE")
    print("="*60)
    print("Watch the controller. Press Enter to advance to next byte.")
    print("Note which LED lights up for each byte position.")
    print("Press 'q' then Enter to quit, 's' to skip 10.")
    print("="*60 + "\n")
    
    byte_index = 0
    while byte_index < 51:
        single_byte(fd, byte_index, 0x7F)
        response = input(f"Byte {byte_index} (0x{byte_index:02X}): Which LED? > ").strip().lower()
        
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
    print("X1 MK2 LED INTERACTIVE MODE")
    print("="*60)
    print("Commands:")
    print("  on [brightness]  - All LEDs on (brightness 0-127, default 127)")
    print("  off              - All LEDs off")
    print("  dim              - All LEDs dim (0x10)")
    print("  b <num> [bright] - Single byte on (0-50)")
    print("  probe            - Step through each byte")
    print("  range <s> <e>    - Light bytes from s to e")
    print("  q                - Quit")
    print("="*60 + "\n")
    
    while True:
        try:
            cmd = input("LED> ").strip().lower().split()
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
            elif cmd[0] == 'probe':
                probe_all_bytes(fd)
            elif cmd[0] == 'range' and len(cmd) >= 3:
                start = int(cmd[1])
                end = int(cmd[2])
                data = [0x00] * 51
                for i in range(start, min(end+1, 51)):
                    data[i] = 0x7F
                send_led_report(fd, data)
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
        print(f"Report 0x80: 51 data bytes (52 total with report ID)")
    except Exception as e:
        print(f"ERROR: Cannot open device: {e}")
        sys.exit(1)
    
    # Quick initialization test - flash all then dim
    print("\nInitializing: Flash all LEDs...")
    all_on(fd, 0x7F)
    time.sleep(0.3)
    all_dim(fd)
    time.sleep(0.2)
    
    # Enter interactive mode
    interactive_mode(fd)
    
    os.close(fd)

if __name__ == "__main__":
    main()

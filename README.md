# Native Instruments Traktor Kontrol X1 MK2 - Linux HID Bridge

A complete HID-to-MIDI bridge for using the Traktor Kontrol X1 MK2 on Linux without proprietary drivers. This project provides full hardware support including all buttons, knobs, encoders, touch strip, and LED feedback.

## Project Overview

The X1 MK2 is a DJ controller that communicates via USB HID protocol. On Windows/Mac, Native Instruments provides drivers that expose it as a MIDI device. On Linux, no such driver exists. This bridge reads raw HID reports and translates them to standard MIDI, while also controlling the device's LEDs.

### Features

- **30 buttons** with shift layer (60 total MIDI notes)
- **8 FX knobs** (12-bit resolution → 7-bit MIDI CC)
- **3 rotary encoders** with push buttons
- **Touch strip** with full 0-127 range
- **51 LEDs** including 8 RGB hotcue pads
- **Stateful hotcue LEDs** that track set/empty state
- **7-segment displays** (documented, not yet implemented)
- **Touch strip LEDs** (documented, not yet implemented)

---

## Hardware Protocol Reference

### Device Identification

| Property | Value |
|----------|-------|
| Vendor ID | `0x17CC` (Native Instruments) |
| Product ID | `0x1220` (Traktor Kontrol X1 MK2) |
| HID Interface | 0 |

### HID Reports

The X1 MK2 uses multiple HID reports for different functions:

| Report ID | Direction | Size | Purpose |
|-----------|-----------|------|---------|
| `0x01` | Input | 31 bytes | Buttons, knobs, encoders, touch strip |
| `0x80` | Output | 52 bytes | Button LEDs (51 data + report ID) |
| `0x81` | Output | 91 bytes | 7-segment displays + touch strip LEDs |
| `0xD0-D9` | Feature | 32 bytes | Firmware/configuration |
| `0xF0-F1` | Feature | 8-16 bytes | Device configuration |

---

## Input Report 0x01 (31 bytes)

### Byte Map

```
Offset  Size    Description
------  ----    -----------
0x00    1       Report ID (0x01)
0x01-02 2       FX1 Mix knob (12-bit LE)
0x03-04 2       FX1 Knob 1 (12-bit LE)
0x05-06 2       FX1 Knob 2 (12-bit LE)
0x07-08 2       FX1 Knob 3 (12-bit LE)
0x09-0A 2       FX2 Mix knob (12-bit LE)
0x0B-0C 2       FX2 Knob 1 (12-bit LE)
0x0D-0E 2       FX2 Knob 2 (12-bit LE)
0x0F-10 2       FX2 Knob 3 (12-bit LE)
0x11    1       Encoders: Browse (high nibble), Loop L (low nibble)
0x12    1       Encoder: Loop R (low nibble)
0x13    1       FX buttons bitmask
0x14    1       FX assign, Load, Shift bitmask
0x15    1       Right deck (Ch2) buttons bitmask
0x16    1       Left deck (Ch1) buttons bitmask
0x17    1       Encoder press buttons bitmask
0x18    1       (reserved)
0x19-1A 2       Touch strip timestamp
0x1B-1C 2       Touch strip position (11-bit, range 90-1020)
0x1D-1E 2       Touch strip position 2 (secondary touch point)
```

### Knob Processing

Knobs report 12-bit values (0-4095) in little-endian format:

```python
raw = (data[offset] | (data[offset + 1] << 8)) & 0x0FFF
midi_value = raw >> 5  # Convert to 7-bit (0-127)
```

### Button Bitmasks

**Byte 0x13 - FX Buttons:**
| Bit | Button |
|-----|--------|
| 0x80 | FX1 Focus |
| 0x40 | FX1 Button 1 |
| 0x20 | FX1 Button 2 |
| 0x10 | FX1 Button 3 |
| 0x08 | FX2 Focus |
| 0x04 | FX2 Button 1 |
| 0x02 | FX2 Button 2 |
| 0x01 | FX2 Button 3 |

**Byte 0x14 - FX Assign / Load / Shift:**
| Bit | Button |
|-----|--------|
| 0x80 | FX1 → Channel 1 |
| 0x40 | FX2 → Channel 1 |
| 0x20 | FX1 → Channel 2 |
| 0x10 | FX2 → Channel 2 |
| 0x08 | Load Left |
| 0x04 | **Shift** |
| 0x02 | Load Right |
| 0x01 | Loop R Encoder Press |

**Byte 0x15 - Right Deck (Channel 2):**
| Bit | Button |
|-----|--------|
| 0x80 | Hotcue 1 R |
| 0x40 | Hotcue 2 R |
| 0x20 | Hotcue 3 R |
| 0x10 | Hotcue 4 R |
| 0x08 | Flux R |
| 0x04 | Sync R |
| 0x02 | Cue R |
| 0x01 | Play R |

**Byte 0x16 - Left Deck (Channel 1):**
| Bit | Button |
|-----|--------|
| 0x80 | Hotcue 1 L |
| 0x40 | Hotcue 2 L |
| 0x20 | Hotcue 3 L |
| 0x10 | Hotcue 4 L |
| 0x08 | Flux L |
| 0x04 | Sync L |
| 0x02 | Cue L |
| 0x01 | Play L |

**Byte 0x17 - Encoder Presses:**
| Bit | Button |
|-----|--------|
| 0x02 | Browse Encoder Press |
| 0x01 | Loop L Encoder Press |

### Encoder Processing

Encoders report 4-bit relative values (0-15) that wrap around:

```python
def encoder_delta(current, previous):
    delta = current - previous
    if delta > 8:
        delta -= 16  # Wrapped backwards
    elif delta < -8:
        delta += 16  # Wrapped forwards
    return delta
```

### Touch Strip Calibration

The touch strip reports raw values that need calibration:

| Parameter | Value |
|-----------|-------|
| Minimum (left edge) | ~90 |
| Maximum (right edge) | ~1020 |
| Range | ~930 |

```python
TOUCH_MIN = 90
TOUCH_MAX = 1020
normalized = (raw - TOUCH_MIN) * 127 / (TOUCH_MAX - TOUCH_MIN)
midi_value = max(0, min(127, int(normalized)))
```

---

## Output Report 0x80 - Button LEDs (52 bytes)

**Critical:** This report must be exactly 52 bytes (1 byte report ID + 51 bytes data). Sending incorrect sizes will cause the device to reject the report.

### Complete LED Register Map

Discovered via systematic probing on 2024-12-29:

```
Byte  Offset  LED Name              Type
----  ------  --------              ----
0     0x00    (Report ID 0x80)      -
1     0x00    FX1 Mode/Focus        Single
2     0x01    FX1 Button 1          Single
3     0x02    FX1 Button 2          Single
4     0x03    FX1 Button 3          Single
5     0x04    FX2 Mode/Focus        Single
6     0x05    FX2 Button 1          Single
7     0x06    FX2 Button 2          Single
8     0x07    FX2 Button 3          Single
9     0x08    FX1 Select 1 (→Ch1)   Single
10    0x09    FX1 Select 2 (→Ch1)   Single
11    0x0A    Left Arrow (L deck)   Single
12    0x0B    Right Arrow (L deck)  Single
13    0x0C    Left Arrow (R deck)   Single
14    0x0D    Right Arrow (R deck)  Single
15    0x0E    FX1 Select (→Ch2)     Single
16    0x0F    FX2 Select (→Ch2)     Single
17    0x10    Load Left             Single
18    0x11    Shift                 Single
19    0x12    Load Right            Single
20    0x13    Hotcue 1 L - Red      RGB
21    0x14    Hotcue 1 L - Green    RGB
22    0x15    Hotcue 1 L - Blue     RGB
23    0x16    Hotcue 2 L - Red      RGB
24    0x17    Hotcue 2 L - Green    RGB
25    0x18    Hotcue 2 L - Blue     RGB
26    0x19    Hotcue 1 R - Red      RGB
27    0x1A    Hotcue 1 R - Green    RGB
28    0x1B    Hotcue 1 R - Blue     RGB
29    0x1C    Hotcue 2 R - Red      RGB
30    0x1D    Hotcue 2 R - Green    RGB
31    0x1E    Hotcue 2 R - Blue     RGB
32    0x1F    Hotcue 3 L - Red      RGB
33    0x20    Hotcue 3 L - Green    RGB
34    0x21    Hotcue 3 L - Blue     RGB
35    0x22    Hotcue 4 L - Red      RGB
36    0x23    Hotcue 4 L - Green    RGB
37    0x24    Hotcue 4 L - Blue     RGB
38    0x25    Hotcue 3 R - Red      RGB
39    0x26    Hotcue 3 R - Green    RGB
40    0x27    Hotcue 3 R - Blue     RGB
41    0x28    Hotcue 4 R - Red      RGB
42    0x29    Hotcue 4 R - Green    RGB
43    0x2A    Hotcue 4 R - Blue     RGB
44    0x2B    Flux L                Single (Blue)
45    0x2C    Sync L                Single (Blue)
46    0x2D    Flux R                Single (Blue)
47    0x2E    Sync R                Single (Blue)
48    0x2F    Cue L                 Single (Blue)
49    0x30    Play L                Single (Green)
50    0x31    Cue R                 Single (Blue)
51    0x32    Play R                Single (Green)
```

### LED Brightness Values

| Value | Brightness |
|-------|------------|
| 0x00 | Off |
| 0x10 | Dim |
| 0x40 | Medium |
| 0x7F | Full |

### RGB Hotcue Colors

Each hotcue pad has 3 consecutive bytes (R, G, B). Values are 0x00-0x7F per channel.

```python
# Example: Light purple/pink
HOTCUE_COLOR_BRIGHT = (0x50, 0x20, 0x60)
HOTCUE_COLOR_DIM = (0x18, 0x08, 0x1A)
```

---

## Output Report 0x81 - Displays & Touch Strip LEDs (91 bytes)

### Structure

| Byte Range | Count | Description |
|------------|-------|-------------|
| 0 | 1 | Report ID (0x81) |
| 1-24 | 24 | Left deck 7-segment display |
| 25-48 | 24 | Right deck 7-segment display |
| 49-90 | 42 | Touch strip LEDs (21 segments × 2 colors) |

### 7-Segment Display

Each deck has 3 digits, each digit has 8 segments (7 segments + decimal point):

```
    ─A─
   │   │
   F   B
   │   │
    ─G─
   │   │
   E   C
   │   │
    ─D─  .DP
```

Each segment is controlled by a single brightness byte (0x00-0x7F).

---

## MIDI Mapping

### Control Changes (CC)

| CC | Control | Shift CC |
|----|---------|----------|
| 10 | FX1 Mix | - |
| 11 | FX1 Knob 1 | - |
| 12 | FX1 Knob 2 | - |
| 13 | FX1 Knob 3 | - |
| 14 | FX2 Mix | - |
| 15 | FX2 Knob 1 | - |
| 16 | FX2 Knob 2 | - |
| 17 | FX2 Knob 3 | - |
| 80 | Browse Encoder | 84 |
| 81 | Loop L Encoder | 85 |
| 82 | Loop R Encoder | 86 |
| 83 | Touch Strip | 87 |

### Notes

**Normal Layer (Notes 40-72):**

| Note | Button |
|------|--------|
| 40-47 | FX1 Focus, FX1 Btn 1-3, FX2 Focus, FX2 Btn 1-3 |
| 48-51 | FX1→Ch1, FX2→Ch1, FX1→Ch2, FX2→Ch2 |
| 52-54 | Load L, Load R, Loop R Press |
| 55-62 | Hotcue 1-4 R, Flux R, Sync R, Cue R, Play R |
| 63-70 | Hotcue 1-4 L, Flux L, Sync L, Cue L, Play L |
| 71-72 | Browse Press, Loop L Press |

**Shift Layer (Notes 74-106):**

Same mapping as above, with +34 offset. Shift button itself sends no MIDI (internal modifier only).

---

## Software Components

### x1_bridge_v1_final.py

The main bridge application. Features:

- Auto-detection of X1 MK2 device
- Virtual MIDI port creation via rtmidi
- Full LED control with stateful hotcue tracking
- Shift layer for doubled button count
- Configurable MIDI channel

**Usage:**
```bash
# Basic usage (auto-detect, MIDI channel 2)
python3 x1_bridge_v1_final.py

# With options
python3 x1_bridge_v1_final.py -v              # Verbose output
python3 x1_bridge_v1_final.py -c 3            # MIDI channel 3
python3 x1_bridge_v1_final.py -d /dev/hidraw4 # Specific device
```

### x1_led_probe.py

Interactive LED testing tool for device reconnaissance.

**Usage:**
```bash
sudo python3 x1_led_probe.py
```

**Commands:**
- `on` / `off` / `dim` - All LEDs
- `b <n>` - Single byte
- `range <start> <end>` - Byte range
- `probe` - Step through all bytes

### x1_display_probe.py

Interactive 7-segment display and touch strip LED testing.

**Usage:**
```bash
sudo python3 x1_display_probe.py
```

**Commands:**
- `left` / `right` / `strip` - Section control
- `digit <deck> <digit>` - Single digit
- `probe` - Step through all bytes

---

## System Integration

### Prerequisites

```bash
# Install Python dependencies
pip install python-rtmidi --break-system-packages

# Load virtual MIDI kernel module (required for Chrome WebMIDI)
sudo modprobe snd-virmidi

# Set up udev rules for non-root access
sudo tee /etc/udev/rules.d/99-ni-controllers.rules << 'EOF'
# Native Instruments Traktor Kontrol X1 MK2
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="17cc", ATTRS{idProduct}=="1220", MODE="0666"
EOF
sudo udevadm control --reload-rules
sudo udevadm trigger
```

### Systemd Service (Planned)

```ini
# /etc/systemd/system/x1-bridge.service
[Unit]
Description=Traktor Kontrol X1 MK2 HID-MIDI Bridge
After=sound.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/ni-bridges/x1_bridge_v1_final.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

## Development Tools

### Reading HID Descriptor

```bash
# Get raw descriptor
sudo usbhid-dump -d 17cc:1220 -e descriptor

# Decode to human-readable format
sudo usbhid-dump -d 17cc:1220 -e descriptor | grep -v : | xxd -r -p | hidrd-convert -o spec
```

### Monitoring HID Input

```bash
# Raw hex dump
sudo cat /dev/hidrawX | hexdump -C

# Using usbhid-dump
sudo usbhid-dump -d 17cc:1220 -e stream -t 0
```

### Testing LED Output

```bash
# Send all LEDs to full brightness
echo -n -e '\x80\x7f\x7f\x7f...(51 bytes)...' | sudo tee /dev/hidrawX > /dev/null
```

---

## Known Issues & Limitations

1. **7-segment displays** - Protocol documented but not implemented in bridge
2. **Touch strip LEDs** - Protocol documented but not implemented in bridge
3. **Hotcue state persistence** - State resets when bridge restarts (future: save to file)
4. **No hot-plug support** - Bridge must be restarted if device is reconnected

---

## Future Plans

- [ ] Systemd service with auto-start
- [ ] Hot-plug support via udev
- [ ] 7-segment display integration (show MIDI channel, BPM, etc.)
- [ ] Touch strip LED visualization
- [ ] State persistence across restarts
- [ ] Multi-channel state machine (100 virtual channels via shift+encoder)
- [ ] Web configuration interface
- [ ] Rust rewrite for sub-millisecond latency

---

## Credits

- **HID Protocol Reference:** Mixxx community mapping by infiniteloop
- **Hardware Probing & Documentation:** Colby's NI Linux Bridge Project

## License

GPL-3.0

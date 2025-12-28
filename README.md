# Native Instruments Traktor Kontrol Z1 - HID to MIDI Bridge

A Linux daemon that translates the Z1's HID protocol to standard MIDI, allowing it to work with any MIDI-capable application including BeatportDJ in Chrome.

## Background

The Traktor Kontrol Z1 is marketed as "class-compliant" but this only applies to its audio interface. The control surface uses a proprietary HID protocol, not USB-MIDI. On Windows/macOS, Native Instruments' `NIHardwareService` daemon handles:

1. Initializing the device (lighting up the LEDs)
2. Reading HID reports from the controller
3. Creating a virtual MIDI port that applications can use

On Linux, there is no NIHardwareService, so the Z1 appears as a dark, uninitialized HID device with no MIDI capability. This bridge solves that problem.

## Features

- **LED Initialization**: Lights up the Z1's buttons on startup
- **HID to MIDI Translation**: Converts all knobs, faders, and buttons to MIDI CC/Note messages
- **Virtual MIDI Port**: Creates an ALSA MIDI port that any application can use
- **Low Latency**: Direct HID reading with minimal overhead
- **Configurable**: Choose MIDI channel, device path, etc.

## Requirements

- Linux with Python 3.6+
- `python-rtmidi` library
- Access to `/dev/hidraw*` devices (via udev rules or root)

## Installation

### Quick Install

```bash
# Clone or download this repository
cd z1-midi-bridge

# Run the installer (as root)
sudo ./install.sh
```

### Manual Install

1. Install python-rtmidi:
   ```bash
   pip3 install python-rtmidi --break-system-packages
   ```

2. Copy the udev rules:
   ```bash
   sudo cp 99-ni-kontrol-z1.rules /etc/udev/rules.d/
   sudo udevadm control --reload-rules
   sudo udevadm trigger
   ```

3. Add yourself to the plugdev group:
   ```bash
   sudo usermod -a -G plugdev $USER
   # Log out and back in
   ```

4. Test the bridge:
   ```bash
   python3 z1_bridge.py
   ```

## Usage

### Manual Start

```bash
# Auto-detect Z1
z1_bridge.py

# Specify device path
z1_bridge.py -d /dev/hidraw5

# Use MIDI channel 2
z1_bridge.py -c 2

# Just initialize LEDs (test mode)
z1_bridge.py --init-only
```

### As a Systemd Service

```bash
# Enable auto-start on boot
sudo systemctl enable z1-bridge

# Start the service
sudo systemctl start z1-bridge

# Check status
sudo systemctl status z1-bridge

# View logs
journalctl -u z1-bridge -f
```

## MIDI Mapping

### Control Change (CC) Messages

| CC | Control | Description |
|----|---------|-------------|
| 16 | CH1 Gain | Channel 1 gain knob |
| 17 | CH1 EQ Hi | Channel 1 high EQ |
| 18 | CH1 EQ Mid | Channel 1 mid EQ |
| 19 | CH1 EQ Lo | Channel 1 low EQ |
| 20 | CH1 FX | Channel 1 filter/FX knob |
| 21 | CH1 Volume | Channel 1 volume fader |
| 22 | Headphone Mix | Cue/Master mix knob |
| 23 | Crossfader | Crossfader |
| 24 | CH2 Gain | Channel 2 gain knob |
| 25 | CH2 EQ Hi | Channel 2 high EQ |
| 26 | CH2 EQ Mid | Channel 2 mid EQ |
| 27 | CH2 EQ Lo | Channel 2 low EQ |
| 28 | CH2 FX | Channel 2 filter/FX knob |
| 29 | CH2 Volume | Channel 2 volume fader |

### Note Messages

| Note | Button |
|------|--------|
| 1 | Mode |
| 2 | Cue A (Headphone CH1) |
| 3 | Cue B (Headphone CH2) |
| 4 | FX A (CH1 FX On) |
| 5 | FX B (CH2 FX On) |

## Using with BeatportDJ

1. Start the Z1 bridge (manually or via systemd)
2. Open BeatportDJ in Chrome
3. Go to Settings → MIDI
4. You should see "Traktor Kontrol Z1" as an available MIDI device
5. Map your controls as desired

## Troubleshooting

### Z1 LEDs don't light up

- Check if the device is detected: `lsusb | grep 17cc`
- Check permissions: `ls -la /dev/hidraw*`
- Try running with sudo: `sudo z1_bridge.py`

### No MIDI port appears

- Check if rtmidi is installed: `python3 -c "import rtmidi"`
- Check ALSA: `aconnect -l`

### Permission denied

- Make sure udev rules are installed
- Make sure you're in the `plugdev` group
- Log out and back in after adding to group

### Device not found

- The bridge looks for vendor ID 0x17cc, product ID 0x1210
- Verify with: `lsusb -d 17cc:1210`
- Try specifying device path: `z1_bridge.py -d /dev/hidraw5`

## Technical Details

### HID Protocol

- **Input Report 0x01**: 30 bytes containing knob/fader positions (12-bit resolution) and button states
- **Output Report 0x80**: 22 bytes for LED control (7-bit brightness values)

### LED Brightness Values

- `0x00`: Off
- `0x0A`: Dim (idle state)
- `0x7F`: Full brightness (active state)

## License

GPL-3.0

## Credits

- HID protocol reverse-engineered from Mixxx's Z1 mapping by djantti
- Based on research from the openAV Ctlra project and Mixxx community

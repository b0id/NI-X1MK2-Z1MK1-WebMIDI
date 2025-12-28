#!/bin/bash

# 1. CLEANUP: Kill any running instances of the bridges
echo "Stopping old bridges..."
pkill -f "z1_bridge.py"
pkill -f "x1_bridge_final.py"
sleep 1

# 2. START Z1 BRIDGE (Channel 1)
echo "Starting Z1 Bridge..."
# Ensure you use the correct filename for your working Z1 script
python3 z1_bridge.py & 

# 3. START X1 BRIDGE (Channel 2)
echo "Starting X1 MK2 Bridge..."
# Using the FINAL Corrected version we just made
python3 x1_bridge_corrected.py --channel 2 &

# 4. WAIT for ports to be created
echo "Waiting for MIDI ports to register..."
sleep 3

# 5. CONNECT TO VIRMIDI
# We find the client ID of the first VirMIDI port automatically
VIRMIDI_PORT=$(aconnect -o | grep "VirMIDI" | head -n 1 | cut -d " " -f 2)

if [ -z "$VIRMIDI_PORT" ]; then
    echo "ERROR: VirMIDI driver not found. Run: sudo modprobe snd-virmidi"
    exit 1
fi

echo "Found VirMIDI at: $VIRMIDI_PORT"

# Connect Z1
echo "Connecting Z1 -> VirMIDI..."
aconnect "Traktor Kontrol Z1":0 $VIRMIDI_PORT

# Connect X1
echo "Connecting X1 -> VirMIDI..."
aconnect "Traktor Kontrol X1 MK2":0 $VIRMIDI_PORT

echo "==================================================="
echo " SYSTEM READY"
echo " Z1 on Channel 1 | X1 on Channel 2"
echo " Both routed to: $VIRMIDI_PORT"
echo " Open Beatport DJ and select 'VirMIDI' as your input."
echo "==================================================="

# Keep script running to maintain background processes
wait

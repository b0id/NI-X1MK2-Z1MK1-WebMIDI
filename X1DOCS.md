Other Reports in the Descriptor
Yes, there are more:
Report IDTypeSizePurpose0x01Input31 bytesButtons, knobs, encoders, touch strip input0x80Output51 bytesButton LEDs (what you just mapped)0x81Output90 bytes7-segment displays + touch strip LEDs0xD0Feature32 bytesConfig/firmware0xD1Feature32 bytesConfig/firmware0xD2Feature32 bytesConfig/firmware0xD8Feature32 bytesConfig/firmware0xD9Feature32 bytesConfig/firmware0xF0Feature8 bytesConfig0xF1Feature16 bytesConfig
The Feature reports (0xD0-0xF1) are likely for:

Firmware version queries
Device mode switching (maybe the MIDI mode toggle?)
Calibration data
Persistent settings

# Modular Hand-Tracking Suite

An ultra-low latency, computer vision suite powered by MediaPipe and OpenCV, featuring decoupled multi-modal control:
1. **Air Controller**: Gesture-based mouse pointer and touch controller for Windows desktops and Android smartphones via ADB.
2. **Virtual Air Harp**: Spatial air-synth enabling mid-air string drawing and real-time physical plucked string simulation (Karplus-Strong audio synthesis).

---

## Architecture Overview

```
                      +-------------------+
                      | Threaded Camera   | (OpenCV CAP_ANY)
                      +---------+---------+
                                |
                                v
                      +-------------------+
                      |   Vision Bridge   | (MediaPipe LiteRT Async)
                      +---------+---------+
                                |
             +------------------+------------------+
             |                                     |
             v                                     v
+------------------------+             +------------------------+
|     Air Controller     |             |        Air Harp        |
| - 1€ Velocity Filter   |             | - 2-Hand Pinch Drawing |
| - Anti-Shake Anchor    |             | - Geometry Intersection|
| - Win32 Mouse Dispatch |             | - Karplus-Strong Audio |
| - Android ADB Queue    |             |   (< 20ms sounddevice) |
+------------------------+             +------------------------+
```

---

## Features

### 1. Air Controller (`air_controller.py`)
- **Laptop Mouse Mode**:
  - **Aim**: Index finger tip smoothed via 1€ adaptive filter.
  - **Left Click**: Pinch Index + Thumb (< 0.28 normalized distance).
  - **Anti-Shake Click Anchor**: Pins pointer coordinate during pinch gesture to eliminate jitter on click down.
  - **Right Click**: Pinch Middle + Thumb.
  - **Drag & Drop**: Hold pinch for > 350 ms.
  - **Scroll**: Extend Index + Middle fingers together and move vertically.
- **Android Phone Mode**:
  - Connects to an Android device via USB/Wi-Fi using ADB.
  - Translates normalized hand coordinates directly to mobile touch coordinates.
  - **Two-Finger Vertical Flick**: Automatically swipes between TikTok, Instagram Reels, or YouTube Shorts.
  - **Open Palm Swipe**: Triggers Android Home (Swipe Up) and Back (Swipe Left) actions.

### 2. Virtual Air Harp (`air_harp.py`)
- **Pinch-to-Draw**: Pinch Index and Thumb on both hands simultaneously to stretch a virtual string between them. Releasing pins the string in 3D air.
- **Physical String Audio**: Plucking a string computes line-segment intersection with fingertip velocity and triggers real-time audio synthesized via the Karplus-Strong algorithm.
- **Clear Strings**: Press `C` on the keyboard to reset the harp.

---

## Quick Start

### Prerequisites
- Python 3.10+
- Webcam (built-in or USB phone camera like DroidCam)
- Optional: Android phone with USB Debugging enabled

### Installation
```bash
git clone https://github.com/<your-username>/<repo-name>.git
cd hand
pip install -r requirements.txt
```

### Running the Suite
Double-click `run_suite.bat` or run:
```bash
python bridge.py
```

### Hotkeys & Controls
| Key / Gesture | Function |
| :--- | :--- |
| **`[1]`** | Switch to Air Controller (Laptop Mouse) |
| **`[2]`** | Switch to Air Controller (Android Phone ADB) |
| **`[3]`** | Switch to Virtual Air Harp |
| **`[T]`** | Toggle between Laptop Mouse and Android Phone target |
| **`[C]`** | Switch Camera index (Cycle 0, 1, 2...) / Clear Harp strings |
| **`[H]`** | Toggle On-Screen Controls HUD |
| **`[Hold Fist 1.5s]`** | Gesture-switch between Controller and Harp |
| **`[Q]` / `[Esc]`** | Exit application cleanly |

---

## License
MIT License

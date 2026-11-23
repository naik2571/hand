# Modular Hand-Tracking Suite

An ultra-low latency, computer vision suite powered by MediaPipe and OpenCV, featuring decoupled multi-modal control:
1. **Air Controller**: Next-Gen "Laser Pointer" mouse and touchless remote controller for Windows 10/11 desktops and Android smartphones via ADB.
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
                      |  - WINDOW_NORMAL  |
                      |  - [F] Fullscreen |
                      |  - [M] Mirror Fix |
                      +---------+---------+
                                |
             +------------------+------------------+
             |                                     |
             v                                     v
+------------------------+             +------------------------+
|     Air Controller     |             |        Air Harp        |
| - Laser Pointer Gating |             | - 2-Hand Pinch Drawing |
| - Air Clutch Rest Mode |             | - Geometry Intersection|
| - Index Air-Tap Click  |             | - Karplus-Strong Audio |
| - Anchor-on-Dip Anti-  |             |   (< 20ms sounddevice) |
|   Shake Drift Lock     |             +------------------------+
| - 2-Finger Tap / Drag  |
| - Android Air Swings   |
| - [S] Skeleton Mesh    |
+------------------------+
```

---

## Features

### 1. Air Controller (`air_controller.py`)
- **Laptop Mouse Mode (Win32 Desktop)**:
  - **Laser Pointer Aiming**: Point single index finger (Middle/Ring/Pinky curled) to smoothly move cursor via 1€ adaptive velocity filter.
  - **Air Clutch (Arm Rest)**: Relax hand or curl into a loose fist to instantly freeze cursor. You can lift your arm, reposition it to the center of your desk/camera view, and point again without disturbing cursor position.
  - **Left Click**: Quick Index Air-Tap (downward dip & release in < 300 ms).
  - **Anti-Shake "Anchor-on-Dip"**: Automatically locks cursor coordinate the millisecond dip starts so clicking never slips off desktop icons.
  - **Double Click**: Two quick Index Air-Taps within 350 ms.
  - **Click & Drag**: Sustained index dip (> 350 ms) while moving arm; straightening finger releases drag cleanly.
  - **Right Click**: Two-Finger Air-Tap (Index + Middle extended, quick synchronized dip < 200 ms).
  - **Scroll**: Two-Finger Drag (Index + Middle extended, continuous vertical motion > 250 ms).
- **Android Phone Mode (ADB Remote Control)**:
  - **Air Swing Tab Navigation**: Quick horizontal hand flick left or right to switch app screens and tabs (with 0.6s return debounce).
  - **Touch / Tap**: Index Air-Tap sends high-precision touch event to phone.
  - **Reels / Shorts Scroll**: Two-finger vertical swipe flips video feeds.
  - **Home & Back Navigation**: Open palm upward flick = Home; leftward flick = Back.
- **Visuals**:
  - **Minimalist Reticle**: Default high-visibility cyan target at index tip.
  - **[S] Skeleton Mesh**: Toggles complete 21-joint glowing hand skeleton with anatomical bone linkages.

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
git clone https://github.com/naik2571/hand.git
cd hand
pip install -r requirements.txt
```

### Running the Suite
Double-click `run_suite.bat` or run:
```bash
python bridge.py
```

### Hotkeys & Controls
| Key / Gesture | Scope | Function |
| :--- | :--- | :--- |
| **`[1]`** | Suite | Switch to Air Controller (Laptop Mouse / Android) |
| **`[2]`** | Suite | Switch to Virtual Air Harp |
| **`[T]`** | Controller | Toggle target: **Laptop Mouse <-> Android Phone (ADB)** |
| **`[F]`** | Display | **Toggle Fullscreen Mode** (Auto-scales feed cleanly across display) |
| **`[M]`** | Vision | **Toggle Camera Mirror Flip** (Fixes inverted Android front cameras) |
| **`[S]`** | Controller | **Toggle Full 21-Joint Hand Skeleton Mesh** on/off |
| **`[K]`** | Universal | Switch Camera index (Cycle Laptop Webcam 0 <-> Phone Cam 1) |
| **`[H]`** | Universal | Toggle On-Screen Guide & Controls HUD |
| **`[C]`** | Harp | Clear active mid-air strings |
| **`[Hold Fist 1.5s]`** | Air Gesture | Toggle between Controller and Harp |
| **`[Q]` / `[Esc]`** | Universal | Cleanly exit suite and release all hardware locks |

---

## License
MIT License

"""
=============================================================================
  Module 1: bridge.py (Central Router, Vision Host & Interactive Launcher)
=============================================================================
Interactive Startup & Persistent Vision Host:
- Prompts at startup with smart recommendations:
    [1] Laptop Air Controller (Touchless Mouse & Scrolling)
    [2] Android Phone Controller (Taps, Reels/Shorts, Back/Home via ADB)
    [3] Virtual Air Harp (Interactive Plucked String Synth)
- Auto-detects connected Android devices via ADB
- Keeps cv2.VideoCapture open continuously to avoid camera re-init freeze
- Supports Laptop Webcam (0), Phone Cam (1), or Wi-Fi RTSP/HTTP URL
- Threaded frame capture at 640x480 for rock-solid 30+ FPS
- MediaPipe Tasks HandLandmarker in asynchronous LIVE_STREAM mode
- 1.5-second closed-fist hold gesture with visual HUD progress ring
- Strict lifecycle isolation: active_module.on_exit() -> next_module.on_enter()
- Hotkeys:
    [1] : Air Controller (Laptop)
    [2] : Virtual Air Harp (Synth)
    [T] : Toggle Target (Laptop Screen <-> Android Phone via ADB)
    [K] : Switch Camera (Webcam 0 <-> Phone Cam 1)
    [H] : Toggle Help & Step-by-Step Guide
    [C] : Clear all strings (in Harp mode)
    [Y] : Confirm switch to Android (when prompt appears)
    [N] : Decline switch to Android (dismiss prompt)
    [Q] / [Esc] : Quit cleanly
=============================================================================
"""

import sys
import os
import time
import math
import argparse
import threading
import cv2
import numpy as np

import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

try:
    import adbutils
    ADBUTILS_AVAILABLE = True
except ImportError:
    ADBUTILS_AVAILABLE = False

# Import feature modules adhering to standard lifecycle contract
from air_controller import AirController
from air_harp import AirHarp

MODEL_PATH = os.path.join(os.path.dirname(__file__), "hand_landmarker.task")


class ThreadedCamera:
    """Grabs camera frames in a lightweight background thread to prevent I/O blocking."""
    def __init__(self, src=0, width=640, height=480):
        self.src = src
        is_url = isinstance(src, str) and (src.startswith("http://") or src.startswith("rtsp://"))
        if is_url:
            self.cap = cv2.VideoCapture(src)
        else:
            cam_idx = int(src)
            # Use CAP_ANY: works with both laptop webcam and DroidCam virtual camera without DirectShow C++ exceptions!
            self.cap = cv2.VideoCapture(cam_idx, cv2.CAP_ANY)
            if not self.cap.isOpened():
                self.cap = cv2.VideoCapture(cam_idx, cv2.CAP_MSMF)
            if not self.cap.isOpened():
                self.cap = cv2.VideoCapture(cam_idx, cv2.CAP_DSHOW)

            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            self.cap.set(cv2.CAP_PROP_FPS, 30)

        self.ret, self.frame = self.cap.read()
        self.running = True
        self.lock = threading.Lock()
        
        self.thread = threading.Thread(target=self._reader, daemon=True)
        self.thread.start()

    def _reader(self):
        while self.running:
            ret, frame = self.cap.read()
            if ret and frame is not None:
                with self.lock:
                    self.frame = frame
                    self.ret = ret
            time.sleep(0.005)

    def read(self):
        with self.lock:
            if self.frame is not None:
                return self.ret, self.frame.copy()
            return False, None

    def release(self):
        self.running = False
        if self.thread.is_alive():
            self.thread.join(timeout=0.5)
        self.cap.release()


class VisionBridge:
    def __init__(self, camera_src=0, initial_mode="CONTROLLER", initial_target="LAPTOP"):
        self.camera_src = camera_src
        self.camera = None
        self.landmarker = None
        
        # Thread-safe async results from MediaPipe
        self.latest_landmarks = []
        self.result_lock = threading.Lock()

        # Modules
        self.controller = AirController()
        self.harp = AirHarp()
        
        # Apply initial settings
        self.active_module_name = initial_mode
        self.active_module = self.controller if initial_mode == "CONTROLLER" else self.harp
        if initial_mode == "CONTROLLER" and initial_target == "ANDROID":
            self.controller.set_target("ANDROID")
        else:
            self.controller.set_target("LAPTOP")

        # Gesture mode switching state
        self.fist_start_time = 0.0
        self.is_holding_fist = False
        self.mode_switched = False
        self.hold_duration = 1.5

        # Automatic Android Device Discovery
        self.known_android_serials = set()
        self.prompt_android_device = None
        self.show_help = False
        self.detector_running = True
        self.detector_thread = threading.Thread(target=self._android_device_listener, daemon=True)
        self.detector_thread.start()

        # Window & Camera Display states
        self.is_fullscreen = False
        self.mirror_flip = True

        # Welcome card timer (shows for first 6 seconds)
        self.welcome_timer = time.time()
        self.show_welcome = True

        # Performance & Inference Timing
        self.fps = 0.0
        self.frame_count = 0
        self.fps_timer = time.time()
        self.last_timestamp_ms = 0

    def _android_device_listener(self):
        """Background daemon polling for newly connected Android devices."""
        if not ADBUTILS_AVAILABLE:
            return

        while self.detector_running:
            try:
                devices = adbutils.adb.device_list()
                current_serials = {d.serial for d in devices}

                for d in devices:
                    if d.serial not in self.known_android_serials:
                        self.known_android_serials.add(d.serial)
                        try:
                            model_name = getattr(d.prop, 'model', d.serial)
                        except Exception:
                            model_name = d.serial

                        if self.controller.target_mode != "ANDROID":
                            self.prompt_android_device = {
                                "serial": d.serial,
                                "model": model_name
                            }
                            self._print_android_steps(model_name)
                        break

                self.known_android_serials = current_serials & self.known_android_serials
            except Exception:
                pass
            time.sleep(2.0)

    def _print_android_steps(self, model_name):
        """Print clear step-by-step guide to console when phone connects."""
        print("\n" + "=" * 70)
        print(f" [!] ANDROID DEVICE DETECTED: {model_name}")
        print("=" * 70)
        print(" Prompt: Switch hand control to your Android Phone?")
        print("   -> Press 'Y' on your keyboard to SWITCH TO ANDROID")
        print("   -> Press 'N' on your keyboard to KEEP LAPTOP CONTROL")
        print("\n Steps for Android Touchless Control:")
        print("   1. Keep phone screen unlocked and placed on a stand.")
        print("   2. Point with index finger to align on phone screen.")
        print("   3. Quick Pinch (Thumb + Index) = Tap on phone.")
        print("   4. Two Fingers Upright + Swipe UP/DOWN = Next/Prev Reel or Short.")
        print("   5. Open Palm Flick LEFT = Android Back Button.")
        print("   6. Open Palm Flick UP = Android Home Screen.")
        print("   7. Press 'T' anytime to toggle back to your Laptop.")
        print("=" * 70 + "\n")

    def _on_detection_result(self, result, output_image, timestamp_ms):
        """Asynchronous callback executed by MediaPipe LIVE_STREAM worker."""
        with self.result_lock:
            if result and result.hand_landmarks:
                self.latest_landmarks = result.hand_landmarks
            else:
                self.latest_landmarks = []

    def _init_vision(self):
        """Initializes the background threaded camera and MediaPipe HandLandmarker."""
        print(f"[Bridge] Opening camera source: {self.camera_src}...")
        self.camera = ThreadedCamera(src=self.camera_src, width=640, height=480)
        
        if not self.camera.ret:
            print("[Bridge] Retrying with generic capture backend...")
            self.camera.release()
            self.camera = ThreadedCamera(src=0, width=640, height=480)

        print(f"[Bridge] Loading HandLandmarker model from: {MODEL_PATH}")
        base_options = python.BaseOptions(model_asset_path=MODEL_PATH)
        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.LIVE_STREAM,
            result_callback=self._on_detection_result,
            num_hands=2,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5
        )
        self.landmarker = vision.HandLandmarker.create_from_options(options)
        print("[Bridge] MediaPipe HandLandmarker successfully initialized.")

    def switch_camera(self):
        """Toggle camera source between index 0 (laptop) and index 1 (phone/external)."""
        if isinstance(self.camera_src, int):
            new_src = 1 if self.camera_src == 0 else 0
        else:
            new_src = 0
        cam_name = "Phone Camera (DroidCam Index 1)" if new_src == 1 else "Laptop Built-in Webcam (Index 0)"
        print(f"\n[Bridge] Switching camera source to: {cam_name}...")
        self.camera.release()
        self.camera_src = new_src
        self.camera = ThreadedCamera(src=self.camera_src, width=640, height=480)
        if self.camera.ret:
            print(f"[Bridge] Successfully connected to {cam_name}!")
        else:
            print(f"[Bridge] Warning: Could not read frame from {cam_name}.")

    def switch_module(self, new_module_name):
        """Strict lifecycle transition: active.on_exit() -> next.on_enter()."""
        if new_module_name == self.active_module_name:
            return

        print(f"\n[Bridge] Switching from {self.active_module_name} -> {new_module_name}")
        self.active_module.on_exit()

        if new_module_name == "CONTROLLER":
            self.active_module = self.controller
            self.active_module_name = "CONTROLLER"
        else:
            self.active_module = self.harp
            self.active_module_name = "HARP"

        self.active_module.on_enter()
        self.show_welcome = True
        self.welcome_timer = time.time()

    def _is_fist_gesture(self, hand_landmarks):
        """Determines if a hand is forming a deliberate closed fist."""
        pts = hand_landmarks.landmark if hasattr(hand_landmarks, 'landmark') else hand_landmarks
        wrist = pts[0]
        tips = [8, 12, 16, 20]
        pips = [6, 10, 14, 18]

        all_curled = True
        for tip_idx, pip_idx in zip(tips, pips):
            d_tip = math.hypot(pts[tip_idx].x - wrist.x, pts[tip_idx].y - wrist.y)
            d_pip = math.hypot(pts[pip_idx].x - wrist.x, pts[pip_idx].y - wrist.y)
            if d_tip > d_pip:
                all_curled = False
                break
        return all_curled

    def _check_fist_mode_switch(self, frame, landmarks_list):
        """Monitors a 1.5s closed fist gesture with a visual circular progress ring."""
        now = time.time()
        h, w, _ = frame.shape

        fist_detected = False
        fist_center = None

        if landmarks_list and len(landmarks_list) > 0:
            hand = landmarks_list[0]
            if self._is_fist_gesture(hand):
                fist_detected = True
                pts = hand.landmark if hasattr(hand, 'landmark') else hand
                fist_center = (int(pts[0].x * w), int(pts[0].y * h))

        if fist_detected:
            if not self.is_holding_fist:
                self.is_holding_fist = True
                self.fist_start_time = now
                self.mode_switched = False
            else:
                elapsed = now - self.fist_start_time
                progress = min(1.0, elapsed / self.hold_duration)

                # Draw radial progress ring
                if fist_center and not self.mode_switched:
                    cx, cy = fist_center
                    cv2.circle(frame, (cx, cy), 35, (80, 80, 80), 2, cv2.LINE_AA)
                    axes = (35, 35)
                    angle = 0
                    start_angle = -90
                    end_angle = int(-90 + progress * 360)
                    cv2.ellipse(frame, (cx, cy), axes, angle, start_angle, end_angle, (0, 255, 255), 4, cv2.LINE_AA)
                    cv2.putText(frame, f"Switching: {int(progress * 100)}%", (cx - 45, cy - 45),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1, cv2.LINE_AA)

                # Trigger mode transition
                if progress >= 1.0 and not self.mode_switched:
                    target_mode = "HARP" if self.active_module_name == "CONTROLLER" else "CONTROLLER"
                    self.switch_module(target_mode)
                    self.mode_switched = True
        else:
            self.is_holding_fist = False
            self.mode_switched = False

    def _render_welcome_card(self, frame):
        """Renders an on-screen startup welcome card showing active mode instructions."""
        h, w, _ = frame.shape
        overlay = frame.copy()
        cw, ch = 560, 110
        cx1 = (w - cw) // 2
        cy1 = 35
        cx2 = cx1 + cw
        cy2 = cy1 + ch

        cv2.rectangle(overlay, (cx1, cy1), (cx2, cy2), (20, 25, 30), -1)
        cv2.addWeighted(overlay, 0.85, frame, 0.15, 0, frame)
        cv2.rectangle(frame, (cx1, cy1), (cx2, cy2), (0, 255, 200), 1, cv2.LINE_AA)

        if self.active_module_name == "CONTROLLER":
            if self.controller.target_mode == "LAPTOP":
                cv2.putText(frame, "ACTIVE: LAPTOP AIR CONTROLLER [Target: Win32 1366x768]",
                            (cx1 + 15, cy1 + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 255, 255), 2, cv2.LINE_AA)
                cv2.putText(frame, "Point Index Finger = Move Cursor | Pinch Thumb+Index = Click/Drag",
                            (cx1 + 15, cy1 + 50), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (230, 230, 230), 1, cv2.LINE_AA)
                cv2.putText(frame, "Pinch Thumb+Middle = Right Click | Two Fingers Up = Scroll Web/Docs",
                            (cx1 + 15, cy1 + 72), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (230, 230, 230), 1, cv2.LINE_AA)
                cv2.putText(frame, "Press 'T' for Android Phone | '2' for Air Harp | 'H' for Help Card",
                            (cx1 + 15, cy1 + 94), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (140, 220, 255), 1, cv2.LINE_AA)
            else:
                cv2.putText(frame, "ACTIVE: ANDROID PHONE CONTROLLER [Target: ADB Phone Screen]",
                            (cx1 + 15, cy1 + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 220, 255), 2, cv2.LINE_AA)
                cv2.putText(frame, "Point in Phone Box = Aim | Pinch Thumb+Index = Tap Screen",
                            (cx1 + 15, cy1 + 50), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (230, 230, 230), 1, cv2.LINE_AA)
                cv2.putText(frame, "Two-Finger Swipe UP/DOWN = Next/Prev Reel or Short",
                            (cx1 + 15, cy1 + 72), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (230, 230, 230), 1, cv2.LINE_AA)
                cv2.putText(frame, "Palm Flick Left = Back | Flick Up = Home | Press 'T' for Laptop",
                            (cx1 + 15, cy1 + 94), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (140, 220, 255), 1, cv2.LINE_AA)
        else:
            cv2.putText(frame, "ACTIVE: VIRTUAL AIR HARP [44.1 kHz Plucked String Synth]",
                        (cx1 + 15, cy1 + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 255, 255), 2, cv2.LINE_AA)
            cv2.putText(frame, "Pinch Thumb+Index & Drag = Draw New Glowing Strings in Space",
                        (cx1 + 15, cy1 + 50), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (230, 230, 230), 1, cv2.LINE_AA)
            cv2.putText(frame, "Swipe Any Fingertip Across Strings = Pluck & Play Acoustic Notes",
                        (cx1 + 15, cy1 + 72), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (230, 230, 230), 1, cv2.LINE_AA)
            cv2.putText(frame, "Press 'C' to Clear Strings | '1' for Controller | 'H' for Help Card",
                        (cx1 + 15, cy1 + 94), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (140, 220, 255), 1, cv2.LINE_AA)

    def _render_android_dialog(self, frame):
        """Render an interactive prompt asking to switch to Android controller with steps."""
        h, w, _ = frame.shape
        overlay = frame.copy()
        cw, ch = 520, 260
        cx1 = (w - cw) // 2
        cy1 = (h - ch) // 2
        cx2 = cx1 + cw
        cy2 = cy1 + ch

        cv2.rectangle(overlay, (cx1, cy1), (cx2, cy2), (20, 20, 20), -1)
        cv2.addWeighted(overlay, 0.88, frame, 0.12, 0, frame)
        cv2.rectangle(frame, (cx1, cy1), (cx2, cy2), (0, 220, 255), 2, cv2.LINE_AA)

        model = self.prompt_android_device.get("model", "Android Device")

        cv2.putText(frame, "ANDROID DEVICE CONNECTED!", (cx1 + 20, cy1 + 32),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(frame, f"Model: {model}", (cx1 + 20, cy1 + 58),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.50, (255, 255, 255), 1, cv2.LINE_AA)

        cv2.putText(frame, "Switch hand controller to Android Phone?", (cx1 + 20, cy1 + 90),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.52, (200, 240, 255), 1, cv2.LINE_AA)

        cv2.putText(frame, "[Y] YES, SWITCH NOW", (cx1 + 25, cy1 + 125),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2, cv2.LINE_AA)
        cv2.putText(frame, "[N] NO, KEEP LAPTOP", (cx1 + 270, cy1 + 125),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (120, 120, 255), 2, cv2.LINE_AA)

        cv2.line(frame, (cx1 + 20, cy1 + 142), (cx2 - 20, cy1 + 142), (80, 80, 80), 1, cv2.LINE_AA)

        cv2.putText(frame, "Steps for Android Control:", (cx1 + 20, cy1 + 165),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 200, 0), 1, cv2.LINE_AA)
        cv2.putText(frame, "1. Tap: Quick Pinch (Thumb + Index)", (cx1 + 25, cy1 + 190),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (220, 220, 220), 1, cv2.LINE_AA)
        cv2.putText(frame, "2. Reels/Shorts: Two Fingers Swipe UP / DOWN", (cx1 + 25, cy1 + 212),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (220, 220, 220), 1, cv2.LINE_AA)
        cv2.putText(frame, "3. Back / Home: Open Palm Flick LEFT / UP", (cx1 + 25, cy1 + 234),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (220, 220, 220), 1, cv2.LINE_AA)

    def _render_help_overlay(self, frame):
        """Renders comprehensive help guide on screen when user presses 'H'."""
        h, w, _ = frame.shape
        overlay = frame.copy()
        cw, ch = 540, 320
        cx1 = (w - cw) // 2
        cy1 = (h - ch) // 2
        cx2 = cx1 + cw
        cy2 = cy1 + ch

        cv2.rectangle(overlay, (cx1, cy1), (cx2, cy2), (25, 25, 25), -1)
        cv2.addWeighted(overlay, 0.90, frame, 0.10, 0, frame)
        cv2.rectangle(frame, (cx1, cy1), (cx2, cy2), (255, 255, 255), 1, cv2.LINE_AA)

        cv2.putText(frame, "HAND-TRACKING SUITE QUICK GUIDE [Press 'H' to Close]", (cx1 + 20, cy1 + 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 255, 255), 2, cv2.LINE_AA)

        lines = [
            ("MODE SWITCHING & DISPLAY:", (255, 200, 0)),
            (" - Hold closed fist for 1.5s to toggle Controller <-> Air Harp", (200, 200, 200)),
            (" - [1] Controller | [2] Air Harp | [F] Fullscreen | [M] Mirror Flip | [S] Skeleton", (200, 200, 200)),
            ("AIR CONTROLLER (LAPTOP & ANDROID):", (255, 200, 0)),
            (" - [T] Toggle Target: Laptop Mouse <-> Android Phone (ADB)", (200, 200, 200)),
            (" - Laptop: Point Index to Aim, Tap Index = Left Click, Double Tap = Double Click", (200, 200, 200)),
            (" - Laptop: Two-finger Tap = Right Click, Two-finger Drag = Scroll, Fist = Rest/Clutch", (200, 200, 200)),
            (" - Android: Open palm flick Left/Right = Switch Screens/Tabs (Air Swing)", (200, 200, 200)),
            (" - Android: Two-finger swipe Up/Down = Reels/Shorts | Tap Index = Touch", (200, 200, 200)),
            ("VIRTUAL AIR HARP:", (255, 200, 0)),
            (" - Pinch & drag in air to stretch glowing strings", (200, 200, 200)),
            (" - Pluck strings with fingertip | Press 'C' to clear strings", (200, 200, 200)),
        ]
        y_offset = cy1 + 55
        for text, col in lines:
            cv2.putText(frame, text, (cx1 + 20, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.38, col, 1, cv2.LINE_AA)
            y_offset += 21

    def run(self):
        """Main execution loop."""
        self._init_vision()
        self.active_module.on_enter()

        window_name = "Decoupled Hand-Tracking Suite (Air Controller & Air Harp)"
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(window_name, 960, 540)

        print("\n" + "=" * 70)
        print("  DECOUPLED HAND-TRACKING SUITE RUNNING")
        print("=" * 70)
        print(" Hotkeys & Controls:")
        print("  - [Hold Fist 1.5s] : Toggle between Air Controller & Air Harp")
        print("  - [1]              : Switch to Air Controller")
        print("  - [2]              : Switch to Virtual Air Harp")
        print("  - [T]              : Toggle Target (Laptop Screen <-> Android Phone)")
        print("  - [F]              : Toggle Fullscreen / Windowed Mode")
        print("  - [M]              : Toggle Camera Mirror Flip (fixes inverted front cams)")
        print("  - [S]              : Toggle Full 21-Joint Hand Skeleton Mesh")
        print("  - [K]              : Switch Camera (Webcam 0 <-> Phone Cam 1)")
        print("  - [H]              : Toggle Help & Step-by-Step Guide")
        print("  - [C]              : Clear all strings (in Harp mode)")
        print("  - [Q] / [Esc]      : Cleanly Exit Suite")
        print("=" * 70 + "\n")

        try:
            while True:
                ret, frame = self.camera.read()
                if not ret or frame is None:
                    time.sleep(0.01)
                    continue

                now = time.time()

                # Mirror frame horizontally for direct manipulation (can be toggled via [M])
                if self.mirror_flip:
                    frame = cv2.flip(frame, 1)

                # Convert to RGB MediaPipe image and trigger asynchronous inference
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

                # Ensure strictly monotonically increasing timestamp for MediaPipe async pipeline
                timestamp_ms = int(now * 1000)
                if timestamp_ms <= self.last_timestamp_ms:
                    timestamp_ms = self.last_timestamp_ms + 1
                self.last_timestamp_ms = timestamp_ms

                self.landmarker.detect_async(mp_image, timestamp_ms)

                with self.result_lock:
                    current_landmarks = list(self.latest_landmarks)

                # Check gesture mode switching
                self._check_fist_mode_switch(frame, current_landmarks)

                # Pass to active module
                if self.active_module_name == "CONTROLLER":
                    frame = self.active_module.update(frame, current_landmarks[:1])
                else:
                    frame = self.active_module.update(frame, current_landmarks)

                # Render startup welcome instruction card
                if self.show_welcome:
                    if now - self.welcome_timer < 6.0:
                        self._render_welcome_card(frame)
                    else:
                        self.show_welcome = False

                # Render interactive Android prompt card if a new phone was plugged in!
                if self.prompt_android_device is not None:
                    self._render_android_dialog(frame)

                # Render Help Overlay if toggled
                if self.show_help:
                    self._render_help_overlay(frame)

                # Calculate & Render FPS
                self.frame_count += 1
                if now - self.fps_timer >= 1.0:
                    self.fps = self.frame_count / (now - self.fps_timer)
                    self.frame_count = 0
                    self.fps_timer = now

                h, w, _ = frame.shape
                cv2.putText(frame, f"FPS: {self.fps:.1f}", (w - 110, 28),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2, cv2.LINE_AA)

                cv2.imshow(window_name, frame)

                key = cv2.waitKey(1) & 0xFF
                if key == ord('q') or key == 27:
                    break

                # Handle interactive prompt keys
                if self.prompt_android_device is not None:
                    if key in (ord('y'), ord('Y')):
                        self.switch_module("CONTROLLER")
                        self.controller.set_target("ANDROID")
                        self.prompt_android_device = None
                    elif key in (ord('n'), ord('N')):
                        self.prompt_android_device = None
                    continue

                if key == ord('1'):
                    self.switch_module("CONTROLLER")
                elif key == ord('2'):
                    self.switch_module("HARP")
                elif key == ord('t') or key == ord('T'):
                    if self.active_module_name == "CONTROLLER":
                        self.controller.toggle_target()
                        self.show_welcome = True
                        self.welcome_timer = now
                elif key == ord('k') or key == ord('K'):
                    self.switch_camera()
                elif key == ord('f') or key == ord('F'):
                    self.is_fullscreen = not self.is_fullscreen
                    prop = cv2.WINDOW_FULLSCREEN if self.is_fullscreen else cv2.WINDOW_NORMAL
                    cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN, prop)
                    print(f"[Bridge] Fullscreen toggled: {'FULLSCREEN' if self.is_fullscreen else 'WINDOWED'}")
                elif key == ord('m') or key == ord('M'):
                    self.mirror_flip = not self.mirror_flip
                    status_str = "MIRROR (Webcam / Direct Selfie)" if self.mirror_flip else "NORMAL (Inverted Front-Cam Fixed)"
                    print(f"[Bridge] Camera flip toggled: {status_str}")
                elif key == ord('s') or key == ord('S'):
                    if hasattr(self.controller, 'toggle_skeleton'):
                        self.controller.toggle_skeleton()
                elif key == ord('h') or key == ord('H'):
                    self.show_help = not self.show_help
                elif key == ord('c') or key == ord('C'):
                    if self.active_module_name == "HARP":
                        self.harp.clear_strings()

        finally:
            print("\n[Bridge] Shutting down suite cleanly...")
            self.detector_running = False
            self.active_module.on_exit()
            if self.landmarker is not None:
                self.landmarker.close()
            if self.camera is not None:
                self.camera.release()
            cv2.destroyAllWindows()
            print("[Bridge] All resources released successfully.")


def interactive_startup_selector():
    """
    Scans hardware and prompts the user at startup with intelligent recommendations.
    Returns: (mode, target, cam_src)
    """
    cam_src = 0

    # 1. Check for connected Android phone via ADB
    phone_detected = False
    phone_name = "Not connected"
    if ADBUTILS_AVAILABLE:
        try:
            devs = adbutils.adb.device_list()
            if devs:
                phone_detected = True
                try:
                    phone_name = getattr(devs[0].prop, 'model', devs[0].serial)
                except Exception:
                    phone_name = devs[0].serial
        except Exception:
            pass

    # 2. Determine Smart Recommendation
    if phone_detected:
        rec_choice = "2"
        rec_title = f"Android Phone Controller (Device '{phone_name}' is plugged in & ready!)"
    else:
        rec_choice = "1"
        rec_title = "Laptop Air Controller (Standard mouse control for Windows 10)"

    print("\n" + "=" * 74)
    print("   DECOUPLED HAND-TRACKING SUITE: STARTUP MODE SELECTOR")
    print("=" * 74)
    print(f" [*] SMART RECOMMENDATION: [{rec_choice}] -> {rec_title}")
    print("-" * 74)
    print(" Choose which experience you want to start:")
    print()
    if rec_choice == "1":
        print("  [1] LAPTOP AIR CONTROLLER             <-- [RECOMMENDED]")
    else:
        print("  [1] LAPTOP AIR CONTROLLER")
    print("      * Full touchless finger mouse for this laptop (Dell Inspiron 5558)")
    print("      * Index pointer, pinch left/right click, anti-shake lock, two-finger scroll.")
    print()
    if rec_choice == "2":
        print(f"  [2] ANDROID PHONE CONTROLLER          <-- [RECOMMENDED: '{phone_name}' CONNECTED!]")
    else:
        print(f"  [2] ANDROID PHONE CONTROLLER          (Status: {phone_name})")
    print("      * Touchless control for your Android phone via ADB")
    print("      * Pinch to tap screen, swipe up/down for Reels & Shorts, Back & Home keys.")
    print()
    print("  [3] VIRTUAL AIR HARP (SYNTH)")
    print("      * Interactive musical instrument: pinch in mid-air to draw glowing strings")
    print("      * Pluck with moving fingertips for real-time acoustic Karplus-Strong audio.")
    print()
    print("  [C] CHOOSE CAMERA SOURCE (Laptop Webcam vs Phone Webcam via DroidCam/IP)")
    print("  [Q] EXIT")
    print("=" * 74)

    prompt_str = f" Enter choice [1, 2, 3, C] or press [ENTER] for Recommended (Default = {rec_choice}): "
    try:
        user_input = input(prompt_str).strip()
    except (EOFError, KeyboardInterrupt):
        user_input = rec_choice

    if not user_input:
        user_input = rec_choice

    if user_input.upper() == 'C':
        print("\nSelect Camera Source:")
        print("  [0] Built-in Laptop Webcam (Default)")
        print("  [1] Android Phone Camera via USB (DroidCam / Iriun Virtual Webcam Index 1)")
        print("  [2] Android Phone Camera via Wi-Fi (IP Webcam RTSP/HTTP Stream)")
        cam_choice = input(" Choose camera [0, 1, 2] (Default = 0): ").strip()
        if cam_choice == "1":
            cam_src = 1
            print(" -> Selected: Android Phone Camera (USB / Index 1)")
        elif cam_choice == "2":
            url = input(" Enter IP Webcam Stream URL (e.g. http://192.168.1.5:8080/video): ").strip()
            cam_src = url if url else "http://192.168.1.5:8080/video"
            print(f" -> Selected: Wi-Fi Camera Stream ({cam_src})")
        else:
            cam_src = 0
            print(" -> Selected: Built-in Laptop Webcam")

        # After picking camera, proceed to pick mode
        user_input = input(f"\nNow choose mode [1 = Laptop, 2 = Android, 3 = Harp] (Default = {rec_choice}): ").strip()
        if not user_input:
            user_input = rec_choice

    if user_input == "1":
        print("\n -> Selected: LAPTOP AIR CONTROLLER")
        return "CONTROLLER", "LAPTOP", cam_src
    elif user_input == "2":
        print("\n -> Selected: ANDROID PHONE CONTROLLER")
        return "CONTROLLER", "ANDROID", cam_src
    elif user_input == "3":
        print("\n -> Selected: VIRTUAL AIR HARP")
        return "HARP", "LAPTOP", cam_src
    elif user_input.upper() in ("Q", "4"):
        print("\nExiting.")
        sys.exit(0)
    else:
        print(f"\nUnrecognized input '{user_input}'. Launching recommended default: [{rec_choice}]")
        if rec_choice == "2":
            return "CONTROLLER", "ANDROID", cam_src
        return "CONTROLLER", "LAPTOP", cam_src


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Decoupled Hand-Tracking Suite")
    parser.add_argument("--camera", default=None, help="Camera index (0, 1) or Wi-Fi RTSP/HTTP URL")
    parser.add_argument("--mode", default=None, choices=["controller", "harp"], help="Bypass menu and set initial mode")
    parser.add_argument("--target", default=None, choices=["laptop", "android"], help="Bypass menu and set initial target")
    args = parser.parse_args()

    # Determine mode and target
    if args.mode is not None:
        init_mode = "CONTROLLER" if args.mode == "controller" else "HARP"
        init_target = "ANDROID" if args.target == "android" else "LAPTOP"
        cam_src = int(args.camera) if (args.camera and args.camera.isdigit()) else (args.camera if args.camera else 0)
    else:
        # Launch interactive startup menu
        init_mode, init_target, selected_cam = interactive_startup_selector()
        cam_src = args.camera if args.camera is not None else selected_cam

    cam_src_final = int(cam_src) if (isinstance(cam_src, str) and cam_src.isdigit()) else cam_src
    bridge = VisionBridge(camera_src=cam_src_final, initial_mode=init_mode, initial_target=init_target)
    bridge.run()

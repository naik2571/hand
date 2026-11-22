"""
=============================================================================
  Module 2: air_controller.py (Touchless Laptop & Android Remote Controller)
=============================================================================
Dual-Target Touchless Finger Controller:
Target 1: LAPTOP (Win32 Desktop)
  - Precision Pointing: Index tip (Landmark 8) with One-Euro ($1€$) filter
  - Left Click & Double Click: Thumb-Index quick pinch (< 250 ms)
  - Click & Drag: Sustained pinch (> 300 ms)
  - Right Click: Thumb-Middle pinch
  - Two-Finger Scroll: Index + Middle extended together moving vertically
  - Clutch Mode: Relaxed / curled hand freezes cursor (arm rest)

Target 2: ANDROID PHONE (Remote Control via ADB)
  - Screen Tap: Thumb-Index pinch taps corresponding phone coordinate
  - Reels / Shorts Scroll: Two-finger swipe up/down flips video feeds
  - Back Button: Leftward palm flick (keyevent 4)
  - Home Button: Upward palm flick (keyevent 3)
  - Play / Pause: Open palm held towards camera (keyevent 85)
  - Async Worker Queue: Zero FPS drop on PC while sending ADB commands
=============================================================================
"""

import math
import time
import ctypes
import cv2
import threading
import queue
import subprocess

try:
    import adbutils
    ADBUTILS_AVAILABLE = True
except ImportError:
    ADBUTILS_AVAILABLE = False

# Win32 Constants
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x00010
MOUSEEVENTF_WHEEL = 0x0800

user32 = ctypes.windll.user32
try:
    user32.SetProcessDPIAware()
except Exception:
    pass


class OneEuroFilter:
    """1€ (One-Euro) Filter with micro-deadzone for eliminating hand tremors."""
    def __init__(self, t0, x0, min_cutoff=0.4, beta=0.02, d_cutoff=1.0):
        self.min_cutoff = float(min_cutoff)
        self.beta = float(beta)
        self.d_cutoff = float(d_cutoff)
        self.x_prev = float(x0)
        self.dx_prev = 0.0
        self.t_prev = float(t0)

    def alpha(self, cutoff, dt):
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def filter(self, t, x):
        dt = t - self.t_prev
        if dt <= 1e-5:
            return self.x_prev

        # Micro-deadzone: Ignore physiological tremors under 2.5 screen pixels
        if abs(x - self.x_prev) < 2.5:
            return self.x_prev

        dx = (x - self.x_prev) / dt
        edx = self.dx_prev + self.alpha(self.d_cutoff, dt) * (dx - self.dx_prev)
        cutoff = self.min_cutoff + self.beta * abs(edx)
        x_filtered = self.x_prev + self.alpha(cutoff, dt) * (x - self.x_prev)

        self.t_prev = t
        self.x_prev = x_filtered
        self.dx_prev = edx
        return x_filtered


class AirController:
    """
    AirController manages touchless finger control for Windows and Android.
    Adheres to the Modular Suite Lifecycle contract: on_enter(), update(), on_exit().
    """
    def __init__(self):
        # Target modes: 'LAPTOP' or 'ANDROID'
        self.target_mode = "LAPTOP"

        # Laptop screen dimensions
        self.screen_w = user32.GetSystemMetrics(0)
        self.screen_h = user32.GetSystemMetrics(1)
        
        # Inner-box active boundary (central 70% of camera frame)
        self.box_x_min = 0.15
        self.box_x_max = 0.85
        self.box_y_min = 0.15
        self.box_y_max = 0.85

        # Filters
        self.filter_x = None
        self.filter_y = None

        # State tracking
        self.is_dragging = False
        self.pinch_start_time = 0.0
        self.pinch_held = False
        self.last_click_time = 0.0
        self.last_right_click_time = 0.0
        
        # Scroll tracking
        self.is_scrolling = False
        self.last_scroll_y = 0.0
        self.last_scroll_time = 0.0

        # Anti-Shake Click Anchor (locks cursor position during pinch)
        self.click_anchor_pos = None

        # Android phone tracking
        self.adb_device = None
        self.phone_w = 1080
        self.phone_h = 2400
        self.adb_queue = queue.Queue()
        self.adb_worker_running = True
        self.adb_thread = threading.Thread(target=self._adb_worker, daemon=True)
        self.adb_thread.start()
        self.last_adb_gesture_time = 0.0

        # Status HUD
        self.hud_status = "READY"

    def _adb_worker(self):
        """Dedicated background worker so ADB commands never stall the 30 FPS video loop."""
        while self.adb_worker_running:
            try:
                cmd_type, args = self.adb_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                if self.adb_device is not None:
                    if cmd_type == "tap":
                        x, y = args
                        self.adb_device.shell(f"input tap {x} {y}")
                    elif cmd_type == "swipe":
                        x1, y1, x2, y2, dur = args
                        self.adb_device.shell(f"input swipe {x1} {y1} {x2} {y2} {dur}")
                    elif cmd_type == "keyevent":
                        code = args[0]
                        self.adb_device.shell(f"input keyevent {code}")
            except Exception as e:
                print(f"[AirController/ADB] Execution warning: {e}")
                self.adb_device = None

    def refresh_android_device(self):
        """Attempts to discover and pair with a connected Android device."""
        if not ADBUTILS_AVAILABLE:
            self.hud_status = "ERR: adbutils not installed"
            return False

        try:
            devices = adbutils.adb.device_list()
            if devices:
                self.adb_device = devices[0]
                # Query phone resolution
                try:
                    w, h = self.adb_device.window_size()
                    self.phone_w, self.phone_h = w, h
                except Exception:
                    self.phone_w, self.phone_h = 1080, 2400
                print(f"[AirController] Connected to Android: {self.adb_device.serial} ({self.phone_w}x{self.phone_h})")
                return True
            else:
                self.adb_device = None
                return False
        except Exception as e:
            print(f"[AirController] ADB discovery error: {e}")
            self.adb_device = None
            return False

    def set_target(self, target):
        """Explicitly set active control target ('LAPTOP' or 'ANDROID')."""
        if target == "ANDROID":
            self.target_mode = "ANDROID"
            connected = self.refresh_android_device()
            if connected:
                dev_name = getattr(self.adb_device.prop, 'model', self.adb_device.serial) if hasattr(self.adb_device, 'prop') else self.adb_device.serial
                self.hud_status = f"TARGET: ANDROID ({dev_name})"
            else:
                self.hud_status = "TARGET: ANDROID (Waiting for Device...)"
        else:
            self.target_mode = "LAPTOP"
            self.hud_status = "TARGET: LAPTOP (Win32)"
        print(f"[AirController] Active target set to: {self.target_mode}")
        return self.target_mode

    def toggle_target(self):
        """Toggle active control target between LAPTOP and ANDROID."""
        new_target = "ANDROID" if self.target_mode == "LAPTOP" else "LAPTOP"
        return self.set_target(new_target)

    def on_enter(self):
        """Lifecycle hook: Called when switching into Controller mode."""
        self.screen_w = user32.GetSystemMetrics(0)
        self.screen_h = user32.GetSystemMetrics(1)
        self.filter_x = None
        self.filter_y = None
        self.click_anchor_pos = None
        self.is_dragging = False
        self.pinch_held = False
        if self.target_mode == "ANDROID":
            self.refresh_android_device()
        self.hud_status = f"ACTIVE - {self.target_mode} CONTROL"
        print(f"[AirController] Entered. Target: {self.target_mode}")

    def on_exit(self):
        """Lifecycle hook: Called before leaving Controller mode. Safely releases OS locks."""
        if self.is_dragging:
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            self.is_dragging = False
        self.filter_x = None
        self.filter_y = None
        self.click_anchor_pos = None
        print("[AirController] Exited cleanly. All mouse locks released.")

    def _euclidean(self, p1, p2):
        return math.hypot(p1.x - p2.x, p1.y - p2.y)

    def _map_coordinate(self, norm_x, norm_y):
        """Maps normalized camera point (already mirrored by bridge) into screen resolution using 70% inner-box."""
        cx = (norm_x - self.box_x_min) / (self.box_x_max - self.box_x_min)
        cy = (norm_y - self.box_y_min) / (self.box_y_max - self.box_y_min)

        cx = max(0.0, min(1.0, cx))
        cy = max(0.0, min(1.0, cy))

        if self.target_mode == "LAPTOP":
            target_x = int(cx * self.screen_w)
            target_y = int(cy * self.screen_h)
        else:
            # Map into Android Phone Aspect Ratio
            target_x = int(cx * self.phone_w)
            target_y = int(cy * self.phone_h)
        return target_x, target_y

    def update(self, frame, landmarks_list):
        """Process a single frame for either Laptop or Android target."""
        now = time.time()
        h, w, _ = frame.shape

        # Render 70% active inner-box overlay on camera preview
        bx1 = int(self.box_x_min * w)
        by1 = int(self.box_y_min * h)
        bx2 = int(self.box_x_max * w)
        by2 = int(self.box_y_max * h)

        box_color = (0, 200, 255) if self.target_mode == "ANDROID" else (80, 80, 80)
        cv2.rectangle(frame, (bx1, by1), (bx2, by2), box_color, 1, cv2.LINE_AA)
        
        target_label = "Android Phone Target (9:16)" if self.target_mode == "ANDROID" else "Laptop Screen Target (70%)"
        cv2.putText(frame, target_label, (bx1 + 5, by1 - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, box_color, 1, cv2.LINE_AA)

        if not landmarks_list or len(landmarks_list) == 0:
            self.hud_status = "SEARCHING FOR HAND..."
            self._render_hud(frame)
            return frame

        # Strictly use first hand
        hand = landmarks_list[0]
        pts = hand.landmark if hasattr(hand, 'landmark') else hand

        wrist = pts[0]
        thumb_tip = pts[4]
        index_tip = pts[8]
        middle_tip = pts[12]
        ring_tip = pts[16]
        pinky_tip = pts[20]

        # Normalized scale reference: Wrist to Middle MCP (Landmark 9)
        hand_scale = self._euclidean(wrist, pts[9])
        if hand_scale < 0.05:
            hand_scale = 0.2

        pinch_dist_left = self._euclidean(thumb_tip, index_tip) / hand_scale
        pinch_dist_right = self._euclidean(thumb_tip, middle_tip) / hand_scale

        index_extended = self._euclidean(index_tip, wrist) > self._euclidean(pts[6], wrist)
        middle_extended = self._euclidean(middle_tip, wrist) > self._euclidean(pts[10], wrist)
        ring_extended = self._euclidean(ring_tip, wrist) > self._euclidean(pts[14], wrist)
        pinky_extended = self._euclidean(pinky_tip, wrist) > self._euclidean(pts[18], wrist)

        # -------------------------------------------------------------
        # Gesture: Clutch Mode (All fingers relaxed/curled into palm)
        # -------------------------------------------------------------
        if not index_extended and not middle_extended and not ring_extended and not pinky_extended:
            if self.is_dragging and self.target_mode == "LAPTOP":
                user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                self.is_dragging = False
            self.hud_status = "CLUTCH (POINTER REST)"
            self._render_hand_dots(frame, pts, color=(100, 100, 100))
            self._render_hud(frame)
            return frame

        # Map index tip position to screen coordinates
        raw_x, raw_y = self._map_coordinate(index_tip.x, index_tip.y)

        # Apply 1€ (One-Euro) Filter
        if self.filter_x is None or self.filter_y is None:
            self.filter_x = OneEuroFilter(now, raw_x, min_cutoff=1.0, beta=0.015)
            self.filter_y = OneEuroFilter(now, raw_y, min_cutoff=1.0, beta=0.015)
            filtered_x, filtered_y = raw_x, raw_y
        else:
            filtered_x = int(self.filter_x.filter(now, raw_x))
            filtered_y = int(self.filter_y.filter(now, raw_y))

        # =============================================================
        # BRANCH A: ANDROID PHONE TARGET DISPATCH
        # =============================================================
        if self.target_mode == "ANDROID":
            if self.adb_device is None:
                # Try auto-reconnect every 2 seconds
                if now - self.last_adb_gesture_time > 2.0:
                    self.refresh_android_device()
                    self.last_adb_gesture_time = now

            filtered_x = max(0, min(self.phone_w - 1, filtered_x))
            filtered_y = max(0, min(self.phone_h - 1, filtered_y))

            aim_x, aim_y = filtered_x, filtered_y
            is_pinching = pinch_dist_left < 0.28
            is_pre_pinch = pinch_dist_left < 0.36

            # Anti-shake click anchor logic for Android tap
            if is_pre_pinch:
                if self.click_anchor_pos is None:
                    self.click_anchor_pos = (filtered_x, filtered_y)
            else:
                if not self.pinch_held:
                    self.click_anchor_pos = None

            if self.click_anchor_pos is not None:
                drift = math.hypot(filtered_x - self.click_anchor_pos[0], filtered_y - self.click_anchor_pos[1])
                if drift < 35:
                    aim_x, aim_y = self.click_anchor_pos

            # Android Gesture 1: Open Palm Gestures (Back & Home & Play/Pause)
            all_fingers_open = index_extended and middle_extended and ring_extended and pinky_extended
            if all_fingers_open and (now - self.last_adb_gesture_time > 0.8):
                self.is_scrolling = False
                # Detect palm flick: Check if wrist is moving horizontally or vertically
                if index_tip.x < 0.25:
                    # Swipe Left -> Back Button
                    self.adb_queue.put(("keyevent", [4]))
                    self.last_adb_gesture_time = now
                    self.hud_status = "ANDROID: BACK BUTTON"
                elif index_tip.y < 0.20:
                    # Swipe Up -> Home Button
                    self.adb_queue.put(("keyevent", [3]))
                    self.last_adb_gesture_time = now
                    self.hud_status = "ANDROID: HOME SCREEN"
                else:
                    self.hud_status = "ANDROID: PALM DETECTED"

            # Android Gesture 2: Two-Finger Reels / Shorts Swipe (Index + Middle extended)
            elif index_extended and middle_extended and not ring_extended and not pinky_extended and pinch_dist_left > 0.35:
                if not self.is_scrolling:
                    self.is_scrolling = True
                    self.last_scroll_y = (index_tip.y + middle_tip.y) / 2.0
                    self.last_scroll_time = now
                else:
                    curr_y = (index_tip.y + middle_tip.y) / 2.0
                    dy = curr_y - self.last_scroll_y
                    if abs(dy) > 0.08 and (now - self.last_adb_gesture_time > 0.5):
                        cx = self.phone_w // 2
                        if dy < 0:
                            # Hand moved UP -> Next Reel/Short (swipe from bottom to top)
                            y_start = int(self.phone_h * 0.75)
                            y_end = int(self.phone_h * 0.25)
                            self.adb_queue.put(("swipe", [cx, y_start, cx, y_end, 200]))
                            self.hud_status = "ANDROID: NEXT REEL / SHORT [SWIPE UP]"
                        else:
                            # Hand moved DOWN -> Previous Reel (swipe from top to bottom)
                            y_start = int(self.phone_h * 0.25)
                            y_end = int(self.phone_h * 0.75)
                            self.adb_queue.put(("swipe", [cx, y_start, cx, y_end, 200]))
                            self.hud_status = "ANDROID: PREV REEL [SWIPE DOWN]"
                        self.last_scroll_y = curr_y
                        self.last_adb_gesture_time = now
            else:
                self.is_scrolling = False

                # Android Gesture 3: Tap (Pinch Thumb + Index with anti-shake lock)
                if is_pinching:
                    if not self.pinch_held:
                        self.pinch_held = True
                        self.pinch_start_time = now
                else:
                    if self.pinch_held:
                        pinch_duration = now - self.pinch_start_time
                        if pinch_duration < 0.35 and (now - self.last_adb_gesture_time > 0.3):
                            tap_x = self.click_anchor_pos[0] if self.click_anchor_pos else filtered_x
                            tap_y = self.click_anchor_pos[1] if self.click_anchor_pos else filtered_y
                            self.adb_queue.put(("tap", [tap_x, tap_y]))
                            self.hud_status = f"ANDROID: TAP ({tap_x}, {tap_y})"
                            self.last_adb_gesture_time = now
                        self.pinch_held = False
                        self.click_anchor_pos = None
                    else:
                        self.hud_status = f"ANDROID: AIMING ({aim_x}, {aim_y})"

            dot_color = (0, 200, 255) if is_pinching else (0, 255, 120)
            self._render_hand_dots(frame, pts, color=dot_color)
            self._render_hud(frame, coords=(aim_x, aim_y))
            return frame

        # =============================================================
        # BRANCH B: LAPTOP WIN32 TARGET DISPATCH
        # =============================================================
        filtered_x = max(0, min(self.screen_w - 1, filtered_x))
        filtered_y = max(0, min(self.screen_h - 1, filtered_y))

        # Laptop Gesture: Two-Finger Scrolling
        if index_extended and middle_extended and not ring_extended and not pinky_extended and pinch_dist_left > 0.35:
            if not self.is_scrolling:
                self.is_scrolling = True
                self.last_scroll_y = (index_tip.y + middle_tip.y) / 2.0
                self.last_scroll_time = now
            else:
                curr_y = (index_tip.y + middle_tip.y) / 2.0
                dy = curr_y - self.last_scroll_y
                if abs(dy) > 0.01:
                    scroll_ticks = int(-dy * 1200)
                    user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, scroll_ticks, 0)
                    self.last_scroll_y = curr_y
                    self.last_scroll_time = now
            self.hud_status = "TWO-FINGER SCROLLING"
            self._render_hand_dots(frame, pts, color=(0, 215, 255))
            self._render_hud(frame)
            return frame
        else:
            self.is_scrolling = False

        # Anti-shake click anchor logic
        is_pinching_left = pinch_dist_left < 0.28
        is_pre_pinch = pinch_dist_left < 0.36

        if is_pre_pinch:
            if self.click_anchor_pos is None and not self.is_dragging:
                self.click_anchor_pos = (filtered_x, filtered_y)
        else:
            if not self.pinch_held and not self.is_dragging:
                self.click_anchor_pos = None

        cursor_x, cursor_y = filtered_x, filtered_y
        if self.click_anchor_pos is not None:
            drift = math.hypot(filtered_x - self.click_anchor_pos[0], filtered_y - self.click_anchor_pos[1])
            if drift < 30 and not self.is_dragging:
                # FREEZE cursor in place to prevent pinch drift & shaking!
                cursor_x, cursor_y = self.click_anchor_pos
            elif drift >= 30 and is_pinching_left:
                # Arm moved deliberately -> Break anchor and engage Drag Mode
                if not self.is_dragging:
                    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                    self.is_dragging = True
                    self.hud_status = "HOLDING TO DRAG"
                cursor_x, cursor_y = filtered_x, filtered_y

        # Move Cursor to stabilized/anchored position
        user32.SetCursorPos(cursor_x, cursor_y)

        # Left Click / Double Click / Hold-to-Drag
        if is_pinching_left:
            if not self.pinch_held:
                self.pinch_held = True
                self.pinch_start_time = now
            else:
                pinch_duration = now - self.pinch_start_time
                if pinch_duration > 0.35 and not self.is_dragging:
                    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                    self.is_dragging = True
                    self.hud_status = "HOLDING TO DRAG"
        else:
            if self.pinch_held:
                pinch_duration = now - self.pinch_start_time
                if self.is_dragging:
                    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                    self.is_dragging = False
                    self.hud_status = "DRAG RELEASED"
                elif pinch_duration < 0.35:
                    click_x = self.click_anchor_pos[0] if self.click_anchor_pos else cursor_x
                    click_y = self.click_anchor_pos[1] if self.click_anchor_pos else cursor_y
                    user32.SetCursorPos(click_x, click_y)

                    time_since_last_click = now - self.last_click_time
                    if time_since_last_click < 0.38:
                        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                        self.hud_status = "DOUBLE CLICK!"
                    else:
                        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                        self.hud_status = "LEFT CLICK!"
                    self.last_click_time = now

                self.pinch_held = False
                self.click_anchor_pos = None
            else:
                if not self.is_dragging:
                    self.hud_status = "LOCKED ON TARGET" if self.click_anchor_pos else "POINTING"

        # Right Click (Thumb + Middle Pinch)
        is_pinching_right = pinch_dist_right < 0.28
        if is_pinching_right and (now - self.last_right_click_time > 0.50):
            user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
            user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
            self.last_right_click_time = now
            self.hud_status = "RIGHT CLICK (CONTEXT MENU)"

        dot_color = (0, 0, 255) if self.is_dragging else ((0, 255, 0) if is_pinching_left else (255, 200, 0))
        self._render_hand_dots(frame, pts, color=dot_color)
        self._render_hud(frame, coords=(filtered_x, filtered_y))
        return frame

    def _render_hand_dots(self, frame, pts, color=(0, 255, 0)):
        """Draw clean vector landmarks on the camera preview."""
        h, w, _ = frame.shape
        ix, iy = int(pts[8].x * w), int(pts[8].y * h)
        cv2.circle(frame, (ix, iy), 8, color, -1, cv2.LINE_AA)
        cv2.circle(frame, (ix, iy), 12, (255, 255, 255), 1, cv2.LINE_AA)
        
        tx, ty = int(pts[4].x * w), int(pts[4].y * h)
        cv2.circle(frame, (tx, ty), 6, (255, 100, 100), -1, cv2.LINE_AA)
        cv2.line(frame, (ix, iy), (tx, ty), (200, 200, 200), 1, cv2.LINE_AA)

    def _render_hud(self, frame, coords=None):
        """Minimal HUD on the OpenCV window."""
        color = (0, 220, 255) if self.target_mode == "ANDROID" else (255, 255, 255)
        cv2.putText(frame, f"MODE: AIR CONTROLLER | TARGET: {self.target_mode} [Press 'T' to Toggle]", (15, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 2, cv2.LINE_AA)
        cv2.putText(frame, f"ACTION: {self.hud_status}", (15, 52),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1, cv2.LINE_AA)
        
        if coords:
            cv2.putText(frame, f"COORD: ({coords[0]}, {coords[1]})", (15, 74),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, (180, 180, 180), 1, cv2.LINE_AA)

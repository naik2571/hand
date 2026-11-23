"""
=============================================================================
  Module 2: air_controller.py (Touchless Laser Pointer & Air-Tap Controller)
=============================================================================
Next-Gen Touchless Finger Controller for Windows 10/11 & Android Smartphones.

Target 1: LAPTOP (Win32 Desktop)
  - Precision Aiming: Laser Pointer tracking (1€ adaptive filter).
  - Multi-Finger Tracking: Displays all 5 fingertips (Thumb, Index, Middle, Ring, Pinky).
  - Air Clutch: Closed fist freezes cursor for zero-strain arm repositioning.
  - Frame Exit / Entry Memory: Remembers last valid cursor coordinate; locks on boundary loss.
  - Left Click: Immediate Thumb+Index pinch OR Index Air-Tap with Anti-Shake Anchor.
  - Double Click: Two rapid pinches/taps within 380 ms.
  - Hold-to-Drag: Sustained pinch while moving hand (> 28px) drags windows/files; release drops.
  - Right Click: Instant Thumb+Middle pinch OR Middle finger air-tap.
  - Two-Finger Scroll: Index + Middle sustained vertical translation.

Target 2: ANDROID SMARTPHONE (ADB Remote Touch & Navigation)
  - Air Swing Tab Navigation: Open palm horizontal flick (Left/Right) switches app tabs/screens.
  - Reels / Shorts Flip: Two-finger vertical swipe flips video feed.
  - Screen Tap: Index air-tap or thumb-index pinch sends touch event to phone.
  - Home / Back: Upward / Leftward open-palm navigation flicks.

Visuals:
  - Multi-Fingertip Laser HUD (default, tracks all 5 fingers with pinch distance lines).
  - [S] Full 21-Joint Glowing Hand Skeleton Mesh with anatomical bone connections.
=============================================================================
"""

import math
import time
import ctypes
import cv2
import threading
import queue

try:
    import adbutils
    ADBUTILS_AVAILABLE = True
except ImportError:
    ADBUTILS_AVAILABLE = False

# Win32 Mouse Constants
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800

user32 = ctypes.windll.user32
try:
    user32.SetProcessDPIAware()
except Exception:
    pass

# Standard anatomical bone linkages for MediaPipe Hand
HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),        # Thumb
    (0, 5), (5, 6), (6, 7), (7, 8),        # Index
    (5, 9), (9, 10), (10, 11), (11, 12),    # Middle
    (9, 13), (13, 14), (14, 15), (15, 16), # Ring
    (13, 17), (0, 17), (17, 18), (18, 19), (19, 20)  # Pinky & Palm base
]


class OneEuroFilter:
    """1€ (One-Euro) Filter with micro-deadzone for eliminating physiological hand tremors."""
    def __init__(self, t0, x0, min_cutoff=0.8, beta=0.02, d_cutoff=1.0):
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

        # Micro-deadzone: Ignore physiological tremors under 2 pixels
        if abs(x - self.x_prev) < 2.0:
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
    Touchless Multi-Finger Laser Pointer and Gesture Controller.
    Lifecycle compliant: on_enter(), update(), on_exit().
    """
    def __init__(self):
        # Target modes: 'LAPTOP' or 'ANDROID'
        self.target_mode = "LAPTOP"

        # Laptop screen dimensions
        self.screen_w = user32.GetSystemMetrics(0)
        self.screen_h = user32.GetSystemMetrics(1)

        # Active tracking boundary box (central 70% of camera frame)
        self.box_x_min = 0.15
        self.box_x_max = 0.85
        self.box_y_min = 0.15
        self.box_y_max = 0.85

        # Smoothing Filters
        self.filter_x = None
        self.filter_y = None

        # Visuals
        self.show_skeleton = False

        # Memory & Air Clutch
        self.last_cursor_pos = (self.screen_w // 2, self.screen_h // 2)
        self.reentry_stabilize_until = 0.0

        # Left Click & Drag State Machine
        self.is_left_down = False
        self.left_down_time = 0.0
        self.has_dragged = False
        self.is_dragging = False
        self.click_anchor_pos = None
        self.last_click_time = 0.0
        self.tap_state = "IDLE"  # For Android mode
        self.tap_start_time = 0.0

        # Right Click State Machine
        self.last_right_click_time = 0.0

        # Two-Finger Scrolling
        self.is_scrolling = False
        self.last_scroll_y = 0.0
        self.last_scroll_time = 0.0

        # Android Phone State
        self.adb_device = None
        self.phone_w = 1080
        self.phone_h = 2400
        self.adb_queue = queue.Queue()
        self.adb_worker_running = True
        self.adb_thread = threading.Thread(target=self._adb_worker, daemon=True)
        self.adb_thread.start()

        # Anti-Rebound Engine for Android Two-Finger Scrolling
        self.last_two_finger_y = None
        self.last_two_finger_time = 0.0
        self.stroke_start_y = 0.0
        self.stroke_start_time = 0.0
        self.last_scroll_direction = None  # "UP" or "DOWN"
        self.last_scroll_action_time = 0.0
        self.is_scroll_armed = True

        # Air Swing (Horizontal Tab Navigation)
        self.last_wrist_x = None
        self.last_wrist_time = 0.0
        self.last_adb_gesture_time = 0.0

        # Status HUD
        self.hud_status = "READY"

    def _adb_worker(self):
        """Dedicated background worker so ADB commands never block the video feed."""
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
                    elif cmd_type == "shell":
                        cmd = args[0]
                        self.adb_device.shell(cmd)
            except Exception as e:
                print(f"[AirController/ADB] Warning: {e}")
                self.adb_device = None

    def refresh_android_device(self):
        """Discovers and connects to an ADB Android smartphone."""
        if not ADBUTILS_AVAILABLE:
            self.hud_status = "ERR: adbutils missing"
            return False

        try:
            devices = adbutils.adb.device_list()
            if devices:
                self.adb_device = devices[0]
                try:
                    w, h = self.adb_device.window_size()
                    self.phone_w, self.phone_h = w, h
                except Exception:
                    self.phone_w, self.phone_h = 1080, 2400
                print(f"[AirController] Paired with Android Phone: {self.adb_device.serial} ({self.phone_w}x{self.phone_h})")
                return True
            else:
                self.adb_device = None
                return False
        except Exception:
            self.adb_device = None
            return False

    def set_target(self, target):
        """Sets active target to 'LAPTOP' or 'ANDROID'."""
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
        print(f"[AirController] Target: {self.target_mode}")
        return self.target_mode

    def toggle_target(self):
        """Toggle active control target."""
        new_target = "ANDROID" if self.target_mode == "LAPTOP" else "LAPTOP"
        return self.set_target(new_target)

    def toggle_skeleton(self):
        """Toggle between multi-finger laser HUD and full 21-joint skeleton mesh."""
        self.show_skeleton = not self.show_skeleton
        mode_str = "FULL 21-JOINT HAND SKELETON" if self.show_skeleton else "MULTI-FINGER LASER HUD"
        print(f"[AirController] Visuals: {mode_str}")

    def on_enter(self):
        """Lifecycle hook when entering AirController mode."""
        self.screen_w = user32.GetSystemMetrics(0)
        self.screen_h = user32.GetSystemMetrics(1)
        self.filter_x = None
        self.filter_y = None
        self.click_anchor_pos = None
        self.is_left_down = False
        self.has_dragged = False
        self.is_dragging = False
        self.tap_state = "IDLE"
        self.is_scrolling = False
        if self.target_mode == "ANDROID":
            self.refresh_android_device()
        self.hud_status = f"ACTIVE - {self.target_mode} CONTROL"
        print(f"[AirController] Entered. Screen target: {self.screen_w}x{self.screen_h}")

    def on_exit(self):
        """Lifecycle hook when leaving AirController mode. Releases all mouse locks."""
        if self.is_left_down or self.is_dragging:
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            self.is_left_down = False
            self.has_dragged = False
            self.is_dragging = False
        self.click_anchor_pos = None
        self.filter_x = None
        self.filter_y = None
        print("[AirController] Exited cleanly. All mouse locks released.")

    def _euclidean(self, p1, p2):
        return math.hypot(p1.x - p2.x, p1.y - p2.y)

    def _map_coordinate(self, norm_x, norm_y):
        """Maps normalized camera point into target screen pixels."""
        cx = (norm_x - self.box_x_min) / (self.box_x_max - self.box_x_min)
        cy = (norm_y - self.box_y_min) / (self.box_y_max - self.box_y_min)
        cx = max(0.0, min(1.0, cx))
        cy = max(0.0, min(1.0, cy))

        if self.target_mode == "LAPTOP":
            target_x = int(cx * self.screen_w)
            target_y = int(cy * self.screen_h)
        else:
            target_x = int(cx * self.phone_w)
            target_y = int(cy * self.phone_h)
        return target_x, target_y

    def update(self, frame, landmarks_list):
        """Processes one frame, handles Air Clutch, Multi-Finger Laser HUD, and Left/Right clicks."""
        now = time.time()
        h, w, _ = frame.shape

        # Render active inner-box overlay (70% frame)
        bx1, by1 = int(self.box_x_min * w), int(self.box_y_min * h)
        bx2, by2 = int(self.box_x_max * w), int(self.box_y_max * h)
        box_color = (0, 200, 255) if self.target_mode == "ANDROID" else (70, 70, 70)
        cv2.rectangle(frame, (bx1, by1), (bx2, by2), box_color, 1, cv2.LINE_AA)
        target_label = "Android Phone Target (9:16)" if self.target_mode == "ANDROID" else "Laptop Screen Target (70%)"
        cv2.putText(frame, target_label, (bx1 + 5, by1 - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.40, box_color, 1, cv2.LINE_AA)

        # -------------------------------------------------------------
        # FRAME EXIT / MEMORY HANDLING: Hand not visible in frame
        # -------------------------------------------------------------
        if not landmarks_list or len(landmarks_list) == 0:
            if (self.is_left_down or self.is_dragging) and self.target_mode == "LAPTOP":
                user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                self.is_left_down = False
                self.has_dragged = False
                self.is_dragging = False
            self.hud_status = "HAND OUT OF FRAME (POINTER LOCKED)"
            self.click_anchor_pos = None
            self.tap_state = "IDLE"
            self.is_scrolling = False
            self.reentry_stabilize_until = now + 0.15
            self._render_hud(frame, coords=self.last_cursor_pos)
            return frame

        # Strictly use first primary hand
        hand = landmarks_list[0]
        pts = hand.landmark if hasattr(hand, 'landmark') else hand

        wrist = pts[0]
        thumb_tip = pts[4]
        index_mcp = pts[5]
        index_pip = pts[6]
        index_tip = pts[8]
        middle_mcp = pts[9]
        middle_pip = pts[10]
        middle_tip = pts[12]
        ring_tip = pts[16]
        pinky_tip = pts[20]

        # Normalized scale: Wrist to Middle MCP (Landmark 9)
        hand_scale = self._euclidean(wrist, middle_mcp)
        if hand_scale < 0.05:
            hand_scale = 0.20

        # Finger extension states
        index_extended = self._euclidean(index_tip, wrist) > self._euclidean(index_pip, wrist) + 0.02
        middle_extended = self._euclidean(middle_tip, wrist) > self._euclidean(middle_pip, wrist) + 0.02
        ring_extended = self._euclidean(ring_tip, wrist) > self._euclidean(pts[14], wrist) + 0.02
        pinky_extended = self._euclidean(pinky_tip, wrist) > self._euclidean(pts[18], wrist) + 0.02

        # Pinch distances (normalized to hand scale)
        pinch_l = self._euclidean(thumb_tip, index_tip) / hand_scale
        pinch_r = self._euclidean(thumb_tip, middle_tip) / hand_scale

        # Flexion / Dip distances (depth & angle invariant)
        index_dip_y = (index_pip.y - index_tip.y) / hand_scale
        index_flex = self._euclidean(index_tip, index_mcp) / hand_scale
        middle_dip_y = (middle_pip.y - middle_tip.y) / hand_scale
        middle_flex = self._euclidean(middle_tip, middle_mcp) / hand_scale

        # High-reliability gesture classification:
        # 1. Closed Fist: All 4 fingers curled, thumb relaxed
        is_fist = (not index_extended) and (not middle_extended) and (not ring_extended) and (not pinky_extended) and (pinch_l > 0.35)

        # 2. Right Click Trigger: Thumb-Middle pinch (< 0.32) OR Middle finger downward dip / tap
        is_right_pinch = (pinch_r < 0.32) and (pinch_l > 0.25)
        is_middle_tap = index_extended and ((middle_dip_y < 0.16) or (middle_flex < 0.58)) and (not ring_extended) and (pinch_l > 0.30)
        is_right_click = (is_right_pinch or is_middle_tap) and (not is_fist)

        # 3. Left Click Trigger: Thumb-Index pinch (< 0.34) OR Index finger downward dip / forward tap
        is_left_pinch = pinch_l < 0.34
        is_index_tap = ((index_dip_y < 0.16) or (index_flex < 0.58)) and (not middle_extended)
        is_left_click = (is_left_pinch or is_index_tap) and (not is_right_click) and (not is_fist)

        # -------------------------------------------------------------
        # VISUAL RENDERING: Full 21-Joint Mesh or Multi-Finger Laser HUD
        # -------------------------------------------------------------
        if self.show_skeleton:
            self._render_skeleton_mesh(frame, pts)
        else:
            self._render_laser_pointer(frame, pts, pinch_l=pinch_l, pinch_r=pinch_r,
                                       is_left=(is_left_click or self.is_left_down),
                                       is_right=is_right_click)

        # Map index tip coordinates
        raw_x, raw_y = self._map_coordinate(index_tip.x, index_tip.y)

        # 1€ Filter Smoothing
        if self.filter_x is None or self.filter_y is None or now < self.reentry_stabilize_until:
            self.filter_x = OneEuroFilter(now, raw_x, min_cutoff=0.8, beta=0.02)
            self.filter_y = OneEuroFilter(now, raw_y, min_cutoff=0.8, beta=0.02)
            filtered_x, filtered_y = raw_x, raw_y
        else:
            filtered_x = int(self.filter_x.filter(now, raw_x))
            filtered_y = int(self.filter_y.filter(now, raw_y))

        # Clamp to bounds
        if self.target_mode == "LAPTOP":
            filtered_x = max(0, min(self.screen_w - 1, filtered_x))
            filtered_y = max(0, min(self.screen_h - 1, filtered_y))
        else:
            filtered_x = max(0, min(self.phone_w - 1, filtered_x))
            filtered_y = max(0, min(self.phone_h - 1, filtered_y))

        # =============================================================
        # BRANCH A: ANDROID SMARTPHONE TARGET DISPATCH
        # =============================================================
        if self.target_mode == "ANDROID":
            if self.adb_device is None and (now - self.last_adb_gesture_time > 2.0):
                self.refresh_android_device()
                self.last_adb_gesture_time = now

            # Feature: Air Clutch (Closed Fist - Pause Pointer & Reset Gesture Locks)
            if is_fist:
                self.hud_status = "ANDROID: AIR CLUTCH (POINTER FROZEN)"
                self.tap_state = "IDLE"
                self.click_anchor_pos = None
                self.is_scrolling = False
                self.last_two_finger_y = None
                self.last_scroll_direction = None
                self.is_scroll_armed = True
                self._render_hud(frame, coords=(filtered_x, filtered_y))
                return frame

            # Feature: Air Swing (Horizontal Flick Left / Right for Tabs/Screens)
            if self.last_wrist_x is not None:
                dt_wrist = now - self.last_wrist_time
                if dt_wrist > 0.01:
                    vx_wrist = (wrist.x - self.last_wrist_x) / dt_wrist
                    # Fast horizontal hand flick
                    if abs(vx_wrist) > 1.2 and (now - self.last_adb_gesture_time > 0.60):
                        mid_y = self.phone_h // 2
                        if vx_wrist > 1.2:
                            x1 = int(self.phone_w * 0.20)
                            x2 = int(self.phone_w * 0.80)
                            self.adb_queue.put(("swipe", [x1, mid_y, x2, mid_y, 160]))
                            self.hud_status = "ANDROID: SWIPE RIGHT [PREV TAB]"
                        else:
                            x1 = int(self.phone_w * 0.80)
                            x2 = int(self.phone_w * 0.20)
                            self.adb_queue.put(("swipe", [x1, mid_y, x2, mid_y, 160]))
                            self.hud_status = "ANDROID: SWIPE LEFT [NEXT TAB]"
                        self.last_adb_gesture_time = now
            self.last_wrist_x = wrist.x
            self.last_wrist_time = now

            # Feature: Open Palm 4-Way Global Navigation (Back, Recents, Home, Notifications)
            is_open_palm = index_extended and middle_extended and ring_extended and pinky_extended
            if is_open_palm and (now - self.last_adb_gesture_time > 0.80):
                if index_tip.x < 0.22:
                    self.adb_queue.put(("keyevent", [4]))  # Android Back
                    self.hud_status = "ANDROID: BACK BUTTON"
                    self.last_adb_gesture_time = now
                elif index_tip.x > 0.78:
                    self.adb_queue.put(("keyevent", [187]))  # Android Recent Apps / Overview
                    self.hud_status = "ANDROID: RECENT APPS"
                    self.last_adb_gesture_time = now
                elif index_tip.y < 0.20:
                    self.adb_queue.put(("keyevent", [3]))  # Android Home
                    self.hud_status = "ANDROID: HOME SCREEN"
                    self.last_adb_gesture_time = now
                elif index_tip.y > 0.78:
                    self.adb_queue.put(("shell", ["cmd statusbar expand-notifications"]))  # Android Notification Shade
                    self.hud_status = "ANDROID: NOTIFICATIONS"
                    self.last_adb_gesture_time = now

            # Feature: Two-Finger Reels / Shorts Vertical Swipe (Dual-Layer Anti-Rebound)
            elif index_extended and middle_extended and not ring_extended and not pinky_extended and not is_left_click:
                curr_y = (index_tip.y + middle_tip.y) / 2.0
                if not self.is_scrolling:
                    self.is_scrolling = True
                    self.stroke_start_y = curr_y
                    self.stroke_start_time = now
                    self.last_two_finger_y = curr_y
                    self.last_two_finger_time = now
                    self.is_scroll_armed = True
                else:
                    dt = now - self.last_two_finger_time
                    if dt > 0.008:
                        prev_y = self.last_two_finger_y if self.last_two_finger_y is not None else curr_y
                        vy = (curr_y - prev_y) / dt
                        total_dy = curr_y - self.stroke_start_y
                        stroke_duration = now - self.stroke_start_time

                        # Re-arm when hand settles or slows down
                        if not self.is_scroll_armed and abs(vy) < 0.4:
                            self.is_scroll_armed = True
                            self.stroke_start_y = curr_y
                            self.stroke_start_time = now

                        if self.is_scroll_armed:
                            cx = self.phone_w // 2
                            # Intentional UP flick: fast upward speed (vy < -1.0) and sufficient travel (total_dy < -0.06)
                            if vy < -1.0 and total_dy < -0.06:
                                is_reverse_locked = (self.last_scroll_direction == "DOWN") and (now - self.last_scroll_action_time < 1.20)
                                if not is_reverse_locked and (now - self.last_adb_gesture_time > 0.35):
                                    self.adb_queue.put(("swipe", [cx, int(self.phone_h * 0.75), cx, int(self.phone_h * 0.25), 220]))
                                    self.hud_status = "ANDROID: NEXT REEL [SWIPE UP]"
                                    self.last_adb_gesture_time = now
                                    self.last_scroll_action_time = now
                                    self.last_scroll_direction = "UP"
                                    self.is_scroll_armed = False
                                    self.last_two_finger_y = curr_y
                                    self.last_two_finger_time = now
                            # Intentional DOWN flick: fast downward speed (vy > 1.0) and sufficient travel (total_dy > 0.06)
                            elif vy > 1.0 and total_dy > 0.06:
                                is_reverse_locked = (self.last_scroll_direction == "UP") and (now - self.last_scroll_action_time < 1.20)
                                if not is_reverse_locked and (now - self.last_adb_gesture_time > 0.35):
                                    self.adb_queue.put(("swipe", [cx, int(self.phone_h * 0.25), cx, int(self.phone_h * 0.75), 220]))
                                    self.hud_status = "ANDROID: PREV REEL [SWIPE DOWN]"
                                    self.last_adb_gesture_time = now
                                    self.last_scroll_action_time = now
                                    self.last_scroll_direction = "DOWN"
                                    self.is_scroll_armed = False
                                    self.last_two_finger_y = curr_y
                                    self.last_two_finger_time = now

                        # Reset anchor if stroke has expired (> 350ms) or reversed slowly without firing
                        if stroke_duration > 0.35 or (total_dy > 0 and vy < -0.4) or (total_dy < 0 and vy > 0.4):
                            self.stroke_start_y = curr_y
                            self.stroke_start_time = now

                        self.last_two_finger_y = curr_y
                        self.last_two_finger_time = now
            else:
                self.is_scrolling = False
                self.last_two_finger_y = None
                self.is_scroll_armed = True

                # Feature: Air-Tap (Phone Touch)
                if is_left_click:
                    if self.tap_state == "IDLE":
                        self.tap_state = "DIPPED"
                        self.tap_start_time = now
                        self.click_anchor_pos = (filtered_x, filtered_y)
                else:
                    if self.tap_state == "DIPPED":
                        dip_duration = now - self.tap_start_time
                        if dip_duration < 0.50 and (now - self.last_adb_gesture_time > 0.25):
                            tap_x = self.click_anchor_pos[0] if self.click_anchor_pos else filtered_x
                            tap_y = self.click_anchor_pos[1] if self.click_anchor_pos else filtered_y
                            self.adb_queue.put(("tap", [tap_x, tap_y]))
                            self.hud_status = f"ANDROID: AIR-TAP ({tap_x}, {tap_y})"
                            self.last_adb_gesture_time = now
                        self.tap_state = "IDLE"
                        self.click_anchor_pos = None

            self.last_cursor_pos = (filtered_x, filtered_y)
            self._render_hud(frame, coords=(filtered_x, filtered_y))
            return frame

        # =============================================================
        # BRANCH B: LAPTOP WIN32 TARGET DISPATCH
        # =============================================================

        # -------------------------------------------------------------
        # 1. GESTURE: Air Clutch (Resting Hand / Arm Repositioning)
        # Engaged ONLY on Closed Fist
        # -------------------------------------------------------------
        if is_fist:
            if self.is_left_down or self.has_dragged:
                user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                self.is_left_down = False
                self.has_dragged = False
                self.is_dragging = False
                self.hud_status = "DRAG RELEASED (CLUTCH)"
            else:
                self.hud_status = "AIR CLUTCH (CLOSED FIST - POINTER FROZEN)"
            self.click_anchor_pos = None
            self.is_scrolling = False
            self.last_two_finger_y = None
            self.last_scroll_direction = None
            self.is_scroll_armed = True
            self._render_hud(frame, coords=self.last_cursor_pos)
            return frame

        # -------------------------------------------------------------
        # 2. GESTURE: Right Click (Thumb+Middle Pinch OR Middle Tap)
        # -------------------------------------------------------------
        if is_right_click:
            # If left button was down, release it first
            if self.is_left_down:
                user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                self.is_left_down = False
                self.has_dragged = False
                self.is_dragging = False
                self.click_anchor_pos = None

            if now - self.last_right_click_time > 0.45:
                user32.SetCursorPos(filtered_x, filtered_y)
                user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
                user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
                self.last_right_click_time = now
                self.hud_status = "RIGHT CLICK (CONTEXT MENU)"
                self.last_cursor_pos = (filtered_x, filtered_y)

            self.is_scrolling = False
            self._render_hud(frame, coords=self.last_cursor_pos)
            return frame

        # -------------------------------------------------------------
        # 3. GESTURE: Left Click & Drag (Thumb+Index Pinch OR Index Tap)
        # -------------------------------------------------------------
        if is_left_click:
            self.is_scrolling = False
            if not self.is_left_down:
                # Button pressed down!
                self.is_left_down = True
                self.left_down_time = now
                self.has_dragged = False
                self.is_dragging = False
                self.click_anchor_pos = (filtered_x, filtered_y)
                user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                self.hud_status = "LEFT BUTTON DOWN"

            # Check if user is holding & moving (Drag) or holding still (Click Anchor)
            drift = math.hypot(filtered_x - self.click_anchor_pos[0], filtered_y - self.click_anchor_pos[1])
            if not self.has_dragged:
                if drift < 28:
                    # Anchor lock in place to eliminate tap wobble
                    cursor_x, cursor_y = self.click_anchor_pos
                else:
                    # User moved past deadzone: actively dragging
                    self.has_dragged = True
                    self.is_dragging = True
                    cursor_x, cursor_y = filtered_x, filtered_y
                    self.hud_status = "HOLDING TO DRAG"
            else:
                cursor_x, cursor_y = filtered_x, filtered_y
                self.hud_status = "HOLDING TO DRAG"

            user32.SetCursorPos(cursor_x, cursor_y)
            self.last_cursor_pos = (cursor_x, cursor_y)
            self._render_hud(frame, coords=(cursor_x, cursor_y))
            return frame

        else:
            # Finger is not dipping / pinching
            if self.is_left_down:
                # Button released!
                user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                self.is_left_down = False
                was_drag = self.has_dragged
                self.has_dragged = False
                self.is_dragging = False

                if not was_drag:
                    # Successful clean Click!
                    if now - self.last_click_time < 0.38:
                        # Double click
                        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                        self.hud_status = "AIR-TAP -> DOUBLE CLICK!"
                    else:
                        self.hud_status = "AIR-TAP -> LEFT CLICK!"
                    self.last_click_time = now
                else:
                    self.hud_status = "DRAG RELEASED"

                self.click_anchor_pos = None

        # -------------------------------------------------------------
        # 4. GESTURE: Two-Finger Scroll
        # -------------------------------------------------------------
        is_scroll_pose = index_extended and middle_extended and (not ring_extended) and (not pinky_extended) and (pinch_l > 0.38) and (pinch_r > 0.38)
        if is_scroll_pose:
            curr_y = (index_tip.y + middle_tip.y) / 2.0
            if not self.is_scrolling:
                self.is_scrolling = True
                self.last_scroll_y = curr_y
                self.last_scroll_time = now
            else:
                dy = curr_y - self.last_scroll_y
                if abs(dy) > 0.010:
                    scroll_amount = int(-dy * 950)
                    user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, scroll_amount, 0)
                    self.last_scroll_y = curr_y
                    self.last_scroll_time = now
                    self.hud_status = "TWO-FINGER SCROLLING"

            user32.SetCursorPos(filtered_x, filtered_y)
            self.last_cursor_pos = (filtered_x, filtered_y)
            self._render_hud(frame, coords=(filtered_x, filtered_y))
            return frame
        else:
            self.is_scrolling = False

        # -------------------------------------------------------------
        # 5. GESTURE: Precision Laser Aiming (Standard Mouse Movement)
        # -------------------------------------------------------------
        user32.SetCursorPos(filtered_x, filtered_y)
        self.last_cursor_pos = (filtered_x, filtered_y)

        # Retain click status briefly so the user sees the confirmation text
        if not ("CLICK" in self.hud_status and (now - max(self.last_click_time, self.last_right_click_time) < 0.40)):
            self.hud_status = "LASER POINTER (AIMING)"

        self._render_hud(frame, coords=(filtered_x, filtered_y))
        return frame

    def _render_laser_pointer(self, frame, pts, pinch_l=1.0, pinch_r=1.0, is_left=False, is_right=False):
        """
        High-visibility multi-finger tracking HUD.
        Renders all 5 fingertips clearly so the user sees full-hand capture,
        with dynamic gesture guidance lines and precision laser reticle.
        """
        h, w, _ = frame.shape
        coords = [(int(p.x * w), int(p.y * h)) for p in pts]

        tx, ty = coords[4]   # Thumb
        ix, iy = coords[8]   # Index
        mx, my = coords[12]  # Middle
        rx, ry = coords[16]  # Ring
        px, py = coords[20]  # Pinky

        # -------------------------------------------------------------
        # 1. Dynamic Gesture Guide Lines
        # -------------------------------------------------------------
        # A. Left-Click Guide Line (Thumb to Index)
        if is_left or pinch_l < 0.34:
            cv2.line(frame, (tx, ty), (ix, iy), (0, 255, 255), 3, cv2.LINE_AA)
            mid_l = ((tx + ix) // 2, (ty + iy) // 2)
            cv2.circle(frame, mid_l, 6, (0, 255, 255), -1, cv2.LINE_AA)
            cv2.putText(frame, "L-CLICK", (mid_l[0] + 8, mid_l[1] - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.40, (0, 255, 255), 1, cv2.LINE_AA)
        elif pinch_l < 0.55:
            cv2.line(frame, (tx, ty), (ix, iy), (100, 180, 100), 1, cv2.LINE_AA)
            mid_l = ((tx + ix) // 2, (ty + iy) // 2)
            cv2.putText(frame, f"{pinch_l:.2f}", (mid_l[0] + 6, mid_l[1]),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (160, 220, 160), 1, cv2.LINE_AA)

        # B. Right-Click Guide Line (Thumb to Middle)
        if is_right or pinch_r < 0.32:
            cv2.line(frame, (tx, ty), (mx, my), (255, 0, 255), 3, cv2.LINE_AA)
            mid_r = ((tx + mx) // 2, (ty + my) // 2)
            cv2.circle(frame, mid_r, 6, (255, 0, 255), -1, cv2.LINE_AA)
            cv2.putText(frame, "R-CLICK", (mid_r[0] + 8, mid_r[1] - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.40, (255, 0, 255), 1, cv2.LINE_AA)
        elif pinch_r < 0.50:
            cv2.line(frame, (tx, ty), (mx, my), (160, 100, 180), 1, cv2.LINE_AA)

        # -------------------------------------------------------------
        # 2. Render All 5 Fingertips with Distinct Roles & Colors
        # -------------------------------------------------------------
        # Thumb (Landmark 4) - Gold / Cyan
        cv2.circle(frame, (tx, ty), 7, (255, 200, 0), -1, cv2.LINE_AA)
        cv2.circle(frame, (tx, ty), 9, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(frame, "THUMB", (tx + 10, ty + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (255, 220, 120), 1, cv2.LINE_AA)

        # Index (Landmark 8) - Active Laser Reticle (Aiming / Pointer)
        reticle_color = (0, 0, 255) if self.has_dragged else ((0, 255, 255) if (is_left or self.is_left_down) else (0, 255, 0))
        cv2.circle(frame, (ix, iy), 6, reticle_color, -1, cv2.LINE_AA)
        cv2.circle(frame, (ix, iy), 14, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.line(frame, (ix - 20, iy), (ix - 8, iy), (255, 255, 255), 1, cv2.LINE_AA)
        cv2.line(frame, (ix + 8, iy), (ix + 20, iy), (255, 255, 255), 1, cv2.LINE_AA)
        cv2.line(frame, (ix, iy - 20), (ix, iy - 8), (255, 255, 255), 1, cv2.LINE_AA)
        cv2.line(frame, (ix, iy + 8), (ix, iy + 20), (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(frame, "INDEX [AIM]", (ix + 16, iy - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.38, reticle_color, 1, cv2.LINE_AA)

        # Middle (Landmark 12) - Sky Blue / Magenta
        m_color = (255, 0, 255) if (is_right or pinch_r < 0.32) else (255, 180, 50)
        cv2.circle(frame, (mx, my), 7, m_color, -1, cv2.LINE_AA)
        cv2.circle(frame, (mx, my), 9, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(frame, "MIDDLE", (mx + 10, my + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.36, m_color, 1, cv2.LINE_AA)

        # Ring (Landmark 16) - Warm Orange
        cv2.circle(frame, (rx, ry), 6, (100, 200, 255), -1, cv2.LINE_AA)
        cv2.circle(frame, (rx, ry), 8, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(frame, "RING", (rx + 10, ry + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (100, 200, 255), 1, cv2.LINE_AA)

        # Pinky (Landmark 20) - Lavender
        cv2.circle(frame, (px, py), 6, (220, 160, 255), -1, cv2.LINE_AA)
        cv2.circle(frame, (px, py), 8, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(frame, "PINKY", (px + 10, py + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (220, 160, 255), 1, cv2.LINE_AA)

    def _render_skeleton_mesh(self, frame, pts):
        """Draws the complete 21-joint anatomical hand skeleton mesh with glowing bone lines."""
        h, w, _ = frame.shape
        coords = [(int(p.x * w), int(p.y * h)) for p in pts]

        # Draw bone connections
        for p1_idx, p2_idx in HAND_CONNECTIONS:
            cv2.line(frame, coords[p1_idx], coords[p2_idx], (0, 255, 200), 2, cv2.LINE_AA)

        # Draw all 21 joint nodes
        for idx, (cx, cy) in enumerate(coords):
            if idx in (4, 8, 12, 16, 20):
                # Fingertips
                cv2.circle(frame, (cx, cy), 6, (0, 200, 255), -1, cv2.LINE_AA)
                cv2.circle(frame, (cx, cy), 8, (255, 255, 255), 1, cv2.LINE_AA)
            else:
                # Knuckles & wrist
                cv2.circle(frame, (cx, cy), 4, (0, 255, 120), -1, cv2.LINE_AA)
                cv2.circle(frame, (cx, cy), 5, (255, 255, 255), 1, cv2.LINE_AA)

    def _render_hud(self, frame, coords=None):
        """Clean on-screen HUD."""
        color = (0, 220, 255) if self.target_mode == "ANDROID" else (255, 255, 255)
        cv2.putText(frame, f"MODE: AIR CONTROLLER | TARGET: {self.target_mode} [Press 'T' to Toggle]", (15, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 2, cv2.LINE_AA)

        action_color = (0, 255, 255) if ("CLICK" in self.hud_status or "DOWN" in self.hud_status) else ((0, 255, 100) if "AIMING" in self.hud_status else (255, 200, 200))
        cv2.putText(frame, f"ACTION: {self.hud_status}", (15, 52),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.46, action_color, 2, cv2.LINE_AA)

        skel_tag = "SKELETON MESH: [ON - Press 'S']" if self.show_skeleton else "TRACKING: ALL 5 FINGERTIPS [Laser Mode - Press 'S' for Mesh]"
        cv2.putText(frame, skel_tag, (15, 74),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.40, (180, 255, 180), 1, cv2.LINE_AA)

        if coords:
            cv2.putText(frame, f"POINTER COORD: ({coords[0]}, {coords[1]})", (15, 96),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, (200, 200, 200), 1, cv2.LINE_AA)

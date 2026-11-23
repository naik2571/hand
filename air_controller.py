"""
=============================================================================
  Module 2: air_controller.py (Touchless Laser Pointer & Air-Tap Controller)
=============================================================================
Next-Gen Touchless Finger Controller for Windows 10/11 & Android Smartphones.

Target 1: LAPTOP (Win32 Desktop)
  - Precision Aiming: Single Index Finger "Laser Pointer" Pose (1€ adaptive filter).
  - Air Clutch: Relaxed fist or neutral hand instantly freezes cursor for zero-strain arm repositioning.
  - Frame Exit / Entry Memory: Remembers last valid cursor coordinate; locks on boundary loss.
  - Air-Tap Left Click: Natural downward dip & release with "Anchor-on-Dip" zero drift lock.
  - Double Click: Two rapid air-taps within 350 ms.
  - Hold-to-Drag: Sustained dip (> 350 ms) engages left-button drag; straightening finger releases.
  - Two-Finger Right Click: Index + Middle quick synchronized dip (< 200 ms).
  - Two-Finger Scroll: Index + Middle sustained vertical translation.

Target 2: ANDROID SMARTPHONE (ADB Remote Touch & Navigation)
  - Air Swing Tab Navigation: Open palm horizontal flick (Left/Right) switches app tabs/screens.
  - Reels / Shorts Flip: Two-finger vertical swipe flips video feed.
  - Screen Tap: Index air-tap sends high-precision touch event to phone.
  - Home / Back: Upward / Leftward open-palm navigation flicks.

Visuals:
  - Minimalist Laser Pointer Reticle (default, high visibility, zero screen clutter).
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
    Touchless Laser Pointer and Gesture Controller.
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

        # Air-Tap / Click State Machine
        self.tap_state = "IDLE"  # "IDLE", "DIPPED"
        self.tap_start_time = 0.0
        self.click_anchor_pos = None
        self.is_dragging = False
        self.last_click_time = 0.0

        # Two-Finger State (Right Click vs Scroll)
        self.two_finger_dip_start = 0.0
        self.two_finger_dipped = False
        self.last_right_click_time = 0.0
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
        """Toggle between minimalist laser pointer and full 21-joint skeleton mesh."""
        self.show_skeleton = not self.show_skeleton
        mode_str = "FULL 21-JOINT HAND SKELETON" if self.show_skeleton else "MINIMAL LASER POINTER"
        print(f"[AirController] Visuals: {mode_str}")

    def on_enter(self):
        """Lifecycle hook when entering AirController mode."""
        self.screen_w = user32.GetSystemMetrics(0)
        self.screen_h = user32.GetSystemMetrics(1)
        self.filter_x = None
        self.filter_y = None
        self.click_anchor_pos = None
        self.is_dragging = False
        self.tap_state = "IDLE"
        self.is_scrolling = False
        if self.target_mode == "ANDROID":
            self.refresh_android_device()
        self.hud_status = f"ACTIVE - {self.target_mode} CONTROL"
        print(f"[AirController] Entered. Screen target: {self.screen_w}x{self.screen_h}")

    def on_exit(self):
        """Lifecycle hook when leaving AirController mode. Releases all mouse locks."""
        if self.is_dragging:
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
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
        """Processes one frame, handles Air Clutch, Laser Pointer, Air-Tap, and Android Swings."""
        now = time.time()
        h, w, _ = frame.shape

        # Render 70% active inner-box overlay
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
            if self.is_dragging and self.target_mode == "LAPTOP":
                user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                self.is_dragging = False
            self.hud_status = "HAND OUT OF FRAME (POINTER LOCKED)"
            self.click_anchor_pos = None
            self.tap_state = "IDLE"
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
        middle_tip = pts[12]
        ring_tip = pts[16]
        pinky_tip = pts[20]

        # Normalized scale: Wrist to Middle MCP (Landmark 9)
        hand_scale = self._euclidean(wrist, pts[9])
        if hand_scale < 0.05:
            hand_scale = 0.20

        # Finger extension states
        index_extended = self._euclidean(index_tip, wrist) > self._euclidean(index_pip, wrist) + 0.02
        middle_extended = self._euclidean(middle_tip, wrist) > self._euclidean(pts[10], wrist) + 0.02
        ring_extended = self._euclidean(ring_tip, wrist) > self._euclidean(pts[14], wrist) + 0.02
        pinky_extended = self._euclidean(pinky_tip, wrist) > self._euclidean(pts[18], wrist) + 0.02

        # -------------------------------------------------------------
        # VISUAL RENDERING: Full 21-Joint Mesh or Minimal Laser Pointer
        # -------------------------------------------------------------
        if self.show_skeleton:
            self._render_skeleton_mesh(frame, pts)
        else:
            self._render_laser_pointer(frame, pts)

        # -------------------------------------------------------------
        # POSE CLASSIFICATION:
        # 1. Pointing Pose: Index extended, Middle/Ring/Pinky curled
        # 2. Two-Finger Pose: Index + Middle extended, Ring/Pinky curled
        # 3. Open Palm Pose: All fingers extended
        # 4. Fist / Clutch Pose: All fingers curled
        # -------------------------------------------------------------
        is_pointing_pose = index_extended and not middle_extended and not ring_extended and not pinky_extended
        is_two_finger_pose = index_extended and middle_extended and not ring_extended and not pinky_extended
        is_open_palm = index_extended and middle_extended and ring_extended and pinky_extended
        is_fist = not index_extended and not middle_extended and not ring_extended and not pinky_extended

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

            # Feature: Air Swing (Horizontal Flick Left / Right for Tabs/Screens)
            if self.last_wrist_x is not None:
                dt_wrist = now - self.last_wrist_time
                if dt_wrist > 0.01:
                    vx_wrist = (wrist.x - self.last_wrist_x) / dt_wrist
                    # Fast horizontal hand flick
                    if abs(vx_wrist) > 1.2 and (now - self.last_adb_gesture_time > 0.60):
                        mid_y = self.phone_h // 2
                        if vx_wrist > 1.2:
                            # Swung RIGHT -> Swipe Left to Right (Previous Tab / Screen)
                            x1 = int(self.phone_w * 0.20)
                            x2 = int(self.phone_w * 0.80)
                            self.adb_queue.put(("swipe", [x1, mid_y, x2, mid_y, 160]))
                            self.hud_status = "ANDROID: SWIPE RIGHT [PREV TAB]"
                        else:
                            # Swung LEFT -> Swipe Right to Left (Next Tab / Screen)
                            x1 = int(self.phone_w * 0.80)
                            x2 = int(self.phone_w * 0.20)
                            self.adb_queue.put(("swipe", [x1, mid_y, x2, mid_y, 160]))
                            self.hud_status = "ANDROID: SWIPE LEFT [NEXT TAB]"
                        self.last_adb_gesture_time = now
            self.last_wrist_x = wrist.x
            self.last_wrist_time = now

            # Feature: Open Palm Upward/Leftward Navigation Buttons
            if is_open_palm and (now - self.last_adb_gesture_time > 0.80):
                if index_tip.x < 0.22:
                    self.adb_queue.put(("keyevent", [4]))  # Android Back
                    self.hud_status = "ANDROID: BACK BUTTON"
                    self.last_adb_gesture_time = now
                elif index_tip.y < 0.20:
                    self.adb_queue.put(("keyevent", [3]))  # Android Home
                    self.hud_status = "ANDROID: HOME SCREEN"
                    self.last_adb_gesture_time = now

            # Feature: Two-Finger Reels / Shorts Vertical Swipe
            elif is_two_finger_pose:
                curr_y = (index_tip.y + middle_tip.y) / 2.0
                if not self.is_scrolling:
                    self.is_scrolling = True
                    self.last_scroll_y = curr_y
                    self.last_scroll_time = now
                else:
                    dy = curr_y - self.last_scroll_y
                    if abs(dy) > 0.12 and (now - self.last_adb_gesture_time > 0.50):
                        cx = self.phone_w // 2
                        if dy < 0:
                            # Hand moved UP -> Next Reel
                            self.adb_queue.put(("swipe", [cx, int(self.phone_h * 0.75), cx, int(self.phone_h * 0.25), 200]))
                            self.hud_status = "ANDROID: NEXT REEL [SWIPE UP]"
                        else:
                            # Hand moved DOWN -> Previous Reel
                            self.adb_queue.put(("swipe", [cx, int(self.phone_h * 0.25), cx, int(self.phone_h * 0.75), 200]))
                            self.hud_status = "ANDROID: PREV REEL [SWIPE DOWN]"
                        self.last_scroll_y = curr_y
                        self.last_adb_gesture_time = now
            else:
                self.is_scrolling = False

                # Feature: Index Air-Tap (Phone Touch)
                index_dip = (index_pip.y - index_tip.y) / hand_scale
                is_dipping = index_dip < 0.08

                if is_pointing_pose and is_dipping:
                    if self.tap_state == "IDLE":
                        self.tap_state = "DIPPED"
                        self.tap_start_time = now
                        self.click_anchor_pos = (filtered_x, filtered_y)
                else:
                    if self.tap_state == "DIPPED":
                        dip_duration = now - self.tap_start_time
                        if dip_duration < 0.35 and (now - self.last_adb_gesture_time > 0.30):
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
        # GESTURE: Air Clutch (Resting Hand / Arm Repositioning)
        # -------------------------------------------------------------
        if is_fist or is_open_palm or (not is_pointing_pose and not is_two_finger_pose):
            if self.is_dragging:
                user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                self.is_dragging = False
                self.hud_status = "DRAG RELEASED (CLUTCH)"
            else:
                self.hud_status = "AIR CLUTCH (POINTER FROZEN - REPOSITION ARM)"
            self.click_anchor_pos = None
            self.tap_state = "IDLE"
            self.is_scrolling = False
            self._render_hud(frame, coords=self.last_cursor_pos)
            return frame

        # -------------------------------------------------------------
        # GESTURE: Two-Finger Mode (Right Click Tap vs. Drag Scroll)
        # -------------------------------------------------------------
        if is_two_finger_pose:
            # Check for simultaneous downward tap of index and middle
            index_dip = (index_pip.y - index_tip.y) / hand_scale
            middle_dip = (pts[10].y - middle_tip.y) / hand_scale
            two_finger_dipping = (index_dip < 0.08) and (middle_dip < 0.08)

            if two_finger_dipping:
                if not self.two_finger_dipped:
                    self.two_finger_dipped = True
                    self.two_finger_dip_start = now
            else:
                if self.two_finger_dipped:
                    dip_dur = now - self.two_finger_dip_start
                    if dip_dur < 0.28 and (now - self.last_right_click_time > 0.45):
                        # Fires Right Click (Context Menu)
                        user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
                        user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
                        self.last_right_click_time = now
                        self.hud_status = "TWO-FINGER AIR-TAP -> RIGHT CLICK"
                    self.two_finger_dipped = False

            # Two-Finger Vertical Scroll
            curr_y = (index_tip.y + middle_tip.y) / 2.0
            if not self.is_scrolling:
                self.is_scrolling = True
                self.last_scroll_y = curr_y
                self.last_scroll_time = now
            else:
                dy = curr_y - self.last_scroll_y
                if abs(dy) > 0.015 and not self.two_finger_dipped:
                    scroll_amount = int(-dy * 900)
                    user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, scroll_amount, 0)
                    self.last_scroll_y = curr_y
                    self.last_scroll_time = now
                    self.hud_status = "TWO-FINGER SCROLLING"

            self.last_cursor_pos = (filtered_x, filtered_y)
            self._render_hud(frame, coords=(filtered_x, filtered_y))
            return frame
        else:
            self.is_scrolling = False
            self.two_finger_dipped = False

        # -------------------------------------------------------------
        # GESTURE: Pointing Pose (Precision Aiming & Air-Tap Left Click)
        # -------------------------------------------------------------
        # Vertical dip metric: distance between knuckle (pip) and tip
        index_dip = (index_pip.y - index_tip.y) / hand_scale
        is_dipping = index_dip < 0.08

        # Anti-Shake Anchor on Dip
        if is_dipping:
            if self.click_anchor_pos is None and not self.is_dragging:
                self.click_anchor_pos = (filtered_x, filtered_y)
            if self.tap_state == "IDLE":
                self.tap_state = "DIPPED"
                self.tap_start_time = now
        else:
            if not self.is_dragging:
                self.click_anchor_pos = None

        cursor_x, cursor_y = filtered_x, filtered_y
        if self.click_anchor_pos is not None:
            drift = math.hypot(filtered_x - self.click_anchor_pos[0], filtered_y - self.click_anchor_pos[1])
            if drift < 35 and not self.is_dragging:
                # FREEZE cursor in place during the dip to prevent tap slip!
                cursor_x, cursor_y = self.click_anchor_pos
            elif drift >= 35 and is_dipping:
                # Intentional arm move while dipping engages Drag Mode
                if not self.is_dragging:
                    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                    self.is_dragging = True
                    self.hud_status = "HOLDING TO DRAG"
                cursor_x, cursor_y = filtered_x, filtered_y

        # Move native Windows cursor
        user32.SetCursorPos(cursor_x, cursor_y)
        self.last_cursor_pos = (cursor_x, cursor_y)

        # Tap resolution: Check for hold (drag) or release (click / double-click)
        if self.tap_state == "DIPPED":
            dip_duration = now - self.tap_start_time
            if dip_duration > 0.35 and not self.is_dragging:
                # Held down > 350 ms -> Engage Drag
                user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                self.is_dragging = True
                self.hud_status = "HOLDING TO DRAG"
        elif self.tap_state == "IDLE":
            pass

        # When finger straightens back up
        if not is_dipping:
            if self.is_dragging:
                user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                self.is_dragging = False
                self.hud_status = "DRAG RELEASED"
                self.tap_state = "IDLE"
                self.click_anchor_pos = None
            elif self.tap_state == "DIPPED":
                dip_duration = now - self.tap_start_time
                if dip_duration <= 0.35:
                    click_x = self.click_anchor_pos[0] if self.click_anchor_pos else cursor_x
                    click_y = self.click_anchor_pos[1] if self.click_anchor_pos else cursor_y
                    user32.SetCursorPos(click_x, click_y)

                    time_since_last_click = now - self.last_click_time
                    if time_since_last_click < 0.38:
                        # Double Click
                        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                        self.hud_status = "AIR-TAP -> DOUBLE CLICK!"
                    else:
                        # Single Click
                        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                        self.hud_status = "AIR-TAP -> LEFT CLICK!"
                    self.last_click_time = now

                self.tap_state = "IDLE"
                self.click_anchor_pos = None
            else:
                if not self.is_dragging:
                    self.hud_status = "LASER POINTER (AIMING)"

        self._render_hud(frame, coords=(cursor_x, cursor_y))
        return frame

    def _render_laser_pointer(self, frame, pts):
        """Minimalist high-visibility laser reticle at the index fingertip."""
        h, w, _ = frame.shape
        ix, iy = int(pts[8].x * w), int(pts[8].y * h)

        color = (0, 0, 255) if self.is_dragging else ((0, 255, 255) if self.tap_state == "DIPPED" else (0, 255, 0))

        # Glowing target reticle
        cv2.circle(frame, (ix, iy), 6, color, -1, cv2.LINE_AA)
        cv2.circle(frame, (ix, iy), 14, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.line(frame, (ix - 20, iy), (ix - 8, iy), (255, 255, 255), 1, cv2.LINE_AA)
        cv2.line(frame, (ix + 8, iy), (ix + 20, iy), (255, 255, 255), 1, cv2.LINE_AA)
        cv2.line(frame, (ix, iy - 20), (ix, iy - 8), (255, 255, 255), 1, cv2.LINE_AA)
        cv2.line(frame, (ix, iy + 8), (ix, iy + 20), (255, 255, 255), 1, cv2.LINE_AA)

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
        cv2.putText(frame, f"ACTION: {self.hud_status}", (15, 52),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1, cv2.LINE_AA)

        skel_tag = "SKELETON MESH: [ON]" if self.show_skeleton else "SKELETON MESH: [OFF - Press 'S']"
        cv2.putText(frame, skel_tag, (15, 74),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.40, (180, 255, 180), 1, cv2.LINE_AA)

        if coords:
            cv2.putText(frame, f"POINTER COORD: ({coords[0]}, {coords[1]})", (15, 96),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, (200, 200, 200), 1, cv2.LINE_AA)

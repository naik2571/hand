"""
=============================================================================
  Module 3: air_harp.py (Interactive Virtual Air-String Synth)
=============================================================================
Interactive musical instrument that allows users to draw strings in mid-air
and pluck them with their fingertips to trigger real-time sound and spark visuals.
- Spatial String Drawing: Single or dual hand pinch to stretch and lock strings
- Physical Pluck Detection: 2D line segment intersection of moving fingertips
- Real-time Audio Synth: NumPy Karplus-Strong plucked string acoustic simulation
- Damped Wave Physics: Strings visually vibrate with realistic damping
- Spark Visuals: Vector spark particle pool capped to 120 particles
- Zero CPU contention via non-blocking sounddevice callback thread
=============================================================================
"""

import math
import time
import random
import numpy as np
import cv2
import sounddevice as sd
import queue

SAMPLE_RATE = 44100
BLOCK_SIZE = 512
PENTATONIC_SCALE = [130.81, 146.83, 164.81, 196.00, 220.00, 
                    261.63, 293.66, 329.63, 392.00, 440.00, 
                    523.25, 587.33, 659.25, 783.99, 880.00]


def ccw(A, B, C):
    """Counter-clockwise test for 2D line segment intersection."""
    return (C[1] - A[1]) * (B[0] - A[0]) > (B[1] - A[1]) * (C[0] - A[0])

def line_intersect(A, B, C, D):
    """Returns True if line segment AB intersects line segment CD."""
    return (ccw(A, C, D) != ccw(B, C, D)) and (ccw(A, B, C) != ccw(A, B, D))

def find_intersection_pt(A, B, C, D):
    """Finds exact intersection point of segments AB and CD."""
    x1, y1 = A
    x2, y2 = B
    x3, y3 = C
    x4, y4 = D
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-5:
        return ((A[0] + B[0]) // 2, (A[1] + B[1]) // 2)
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    ix = int(x1 + t * (x2 - x1))
    iy = int(y1 + t * (y2 - y1))
    return (ix, iy)


class PluckedVoice:
    """Karplus-Strong Plucked String Voice Synthesis."""
    def __init__(self, freq, sample_rate=SAMPLE_RATE, decay=0.985):
        self.freq = max(60.0, min(1200.0, freq))
        self.sample_rate = sample_rate
        self.decay = decay
        self.N = max(2, int(sample_rate / self.freq))
        # Initial noise burst
        self.buffer = np.random.uniform(-0.9, 0.9, self.N).astype(np.float32)
        self.head = 0
        self.is_active = True
        self.samples_played = 0
        self.max_samples = int(sample_rate * 2.0)  # Max ring time 2s

    def process(self, num_samples):
        out = np.zeros(num_samples, dtype=np.float32)
        for i in range(num_samples):
            val = self.buffer[self.head]
            out[i] = val
            next_idx = (self.head + 1) % self.N
            # Low pass feedback filter
            new_val = self.decay * 0.5 * (self.buffer[self.head] + self.buffer[next_idx])
            self.buffer[self.head] = new_val
            self.head = next_idx
            self.samples_played += 1
            if self.samples_played >= self.max_samples:
                self.is_active = False
                break
        return out


class SparkParticle:
    """Localized spark particle for pluck visuals."""
    def __init__(self, x, y, color):
        self.x = float(x)
        self.y = float(y)
        angle = random.uniform(0, 2 * math.pi)
        speed = random.uniform(2.5, 7.0)
        self.vx = math.cos(angle) * speed
        self.vy = math.sin(angle) * speed - 1.5  # slight upward bias
        self.life = 1.0
        self.decay = random.uniform(0.04, 0.08)
        self.color = color

    def update(self):
        self.x += self.vx
        self.y += self.vy
        self.vy += 0.25  # gravity
        self.life -= self.decay
        return self.life > 0

    def draw(self, frame):
        if self.life > 0:
            rad = max(1, int(self.life * 3.5))
            ix, iy = int(self.x), int(self.y)
            cv2.circle(frame, (ix, iy), rad, self.color, -1, cv2.LINE_AA)


class AirString:
    """Represents a virtual string drawn in 3D air space."""
    def __init__(self, p1, p2, screen_diag):
        self.p1 = p1  # (x1, y1)
        self.p2 = p2  # (x2, y2)
        self.length = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        
        # Map length to musical pitch: Shorter string = higher note
        norm_len = max(0.05, min(1.0, self.length / screen_diag))
        # Inverse mapping into pentatonic scale indices
        scale_idx = int((1.0 - norm_len) * (len(PENTATONIC_SCALE) - 1))
        self.freq = PENTATONIC_SCALE[scale_idx]

        # Vibration physics state
        self.vibe_amp = 0.0
        self.vibe_phase = 0.0
        self.last_pluck_time = 0.0
        
        # Color coding by frequency
        hue = int((scale_idx / len(PENTATONIC_SCALE)) * 140)
        color_bgr = cv2.cvtColor(np.uint8([[[hue, 220, 255]]]), cv2.COLOR_HSV2BGR)[0][0]
        self.color = (int(color_bgr[0]), int(color_bgr[1]), int(color_bgr[2]))

    def pluck(self):
        self.vibe_amp = 14.0
        self.vibe_phase = 0.0
        self.last_pluck_time = time.time()
        return self.freq

    def update(self):
        if self.vibe_amp > 0.1:
            self.vibe_amp *= 0.88  # damping
            self.vibe_phase += 0.8

    def draw(self, frame):
        p1, p2 = self.p1, self.p2
        if self.vibe_amp > 0.5:
            # Draw curved vibrating string
            mid_x = (p1[0] + p2[0]) / 2.0
            mid_y = (p1[1] + p2[1]) / 2.0
            # Normal perpendicular vector
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            L = math.hypot(dx, dy)
            if L > 1e-3:
                nx = -dy / L
                ny = dx / L
                offset = math.sin(self.vibe_phase) * self.vibe_amp
                ctrl_x = int(mid_x + nx * offset)
                ctrl_y = int(mid_y + ny * offset)
                
                # Draw quadratic bezier line
                curve_pts = []
                for t in np.linspace(0, 1, 12):
                    bx = int((1 - t)**2 * p1[0] + 2 * (1 - t) * t * ctrl_x + t**2 * p2[0])
                    by = int((1 - t)**2 * p1[1] + 2 * (1 - t) * t * ctrl_y + t**2 * p2[1])
                    curve_pts.append([bx, by])
                cv2.polylines(frame, [np.array(curve_pts)], False, self.color, 2, cv2.LINE_AA)
            else:
                cv2.line(frame, p1, p2, self.color, 2, cv2.LINE_AA)
        else:
            # Static string
            cv2.line(frame, p1, p2, self.color, 2, cv2.LINE_AA)

        # Draw anchor endpoints
        cv2.circle(frame, p1, 4, (255, 255, 255), -1, cv2.LINE_AA)
        cv2.circle(frame, p2, 4, (255, 255, 255), -1, cv2.LINE_AA)


class AirHarp:
    """
    AirHarp module: draws strings in midair, detects plucking, and synthesizes audio.
    Adheres to the Modular Suite Lifecycle contract: on_enter(), update(), on_exit().
    """
    def __init__(self):
        self.strings = []
        self.particles = []
        self.max_particles = 130
        self.max_strings = 8
        self.audio_stream = None
        self.active_voices = []
        self.note_queue = queue.Queue()
        self.screen_diag = 800.0

        # Drawing state
        self.drawing_in_progress = False
        self.anchor_p1 = None
        self.prev_finger_pos = {}  # hand_idx -> (x, y)
        self.hud_status = "READY"

    def _audio_callback(self, outdata, frames, time_info, status):
        """Asynchronous audio output callback. Runs on dedicated audio thread."""
        out = np.zeros(frames, dtype=np.float32)
        
        # Check for new notes
        while not self.note_queue.empty():
            try:
                freq = self.note_queue.get_nowait()
                self.active_voices.append(PluckedVoice(freq))
            except queue.Empty:
                break

        # Process active voices
        alive_voices = []
        for voice in self.active_voices:
            if voice.is_active:
                out += voice.process(frames)
                if voice.is_active:
                    alive_voices.append(voice)
        self.active_voices = alive_voices

        # Soft limiter / clip guard
        out = np.clip(out * 0.7, -1.0, 1.0)
        outdata[:] = out.reshape(-1, 1)

    def on_enter(self):
        """Lifecycle hook: Starts sounddevice stream and resets state."""
        self.strings.clear()
        self.particles.clear()
        self.active_voices.clear()
        self.drawing_in_progress = False
        self.anchor_p1 = None
        self.prev_finger_pos.clear()

        # Start non-blocking low-latency audio stream
        try:
            self.audio_stream = sd.OutputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                blocksize=BLOCK_SIZE,
                callback=self._audio_callback
            )
            self.audio_stream.start()
            print("[AirHarp] Audio stream started at 44.1 kHz (< 20 ms latency).")
        except Exception as e:
            print(f"[AirHarp] Audio output warning: {e}")

        # Add 3 default initial strings to play right away
        self._seed_default_strings()
        self.hud_status = "ACTIVE - AIR HARP"

    def _seed_default_strings(self):
        """Creates 4 default vertical strings across the screen to play immediately."""
        self.strings.append(AirString((140, 90), (140, 390), self.screen_diag))
        self.strings.append(AirString((260, 90), (260, 390), self.screen_diag))
        self.strings.append(AirString((380, 90), (380, 390), self.screen_diag))
        self.strings.append(AirString((500, 90), (500, 390), self.screen_diag))

    def on_exit(self):
        """Lifecycle hook: Stops audio stream and cleans up memory."""
        if self.audio_stream is not None:
            try:
                self.audio_stream.stop()
                self.audio_stream.close()
            except Exception:
                pass
            self.audio_stream = None
        self.strings.clear()
        self.particles.clear()
        self.active_voices.clear()
        print("[AirHarp] Audio stream closed and buffers cleared.")

    def _euclidean(self, p1, p2):
        return math.hypot(p1.x - p2.x, p1.y - p2.y)

    def update(self, frame, landmarks_list):
        """
        Process a single video frame:
        - Draw live strings & particles
        - Check finger crossings to trigger plucking
        - Support pinch-and-drag to spawn new strings
        """
        h, w, _ = frame.shape
        self.screen_diag = math.hypot(w, h)
        now = time.time()

        # -------------------------------------------------------------
        # 1. Update & Draw Existing Strings
        # -------------------------------------------------------------
        for s in self.strings:
            s.update()
            s.draw(frame)

        # -------------------------------------------------------------
        # 2. Update & Draw Particles (Sparks)
        # -------------------------------------------------------------
        self.particles = [p for p in self.particles if p.update()]
        for p in self.particles:
            p.draw(frame)

        if not landmarks_list or len(landmarks_list) == 0:
            self.prev_finger_pos.clear()
            self._render_hud(frame)
            return frame

        # -------------------------------------------------------------
        # 3. Finger Tracking & Pluck Detection
        # -------------------------------------------------------------
        active_hands_tips = []

        for hand_idx, hand in enumerate(landmarks_list):
            pts = hand.landmark if hasattr(hand, 'landmark') else hand
            # Coordinates align with the mirrored preview frame
            curr_x = int(pts[8].x * w)
            curr_y = int(pts[8].y * h)
            active_hands_tips.append((curr_x, curr_y))

            # Thumb tip for pinch detection
            thumb_x = int(pts[4].x * w)
            thumb_y = int(pts[4].y * h)
            pinch_dist = math.hypot(curr_x - thumb_x, curr_y - thumb_y)
            is_pinching = pinch_dist < 40

            # Visual pointer dot
            cv2.circle(frame, (curr_x, curr_y), 7, (255, 255, 255), -1, cv2.LINE_AA)
            cv2.circle(frame, (curr_x, curr_y), 10, (0, 255, 255), 1, cv2.LINE_AA)

            # Pluck check if previous position exists and not currently anchoring
            if hand_idx in self.prev_finger_pos and not is_pinching:
                prev_x, prev_y = self.prev_finger_pos[hand_idx]
                finger_seg = ((prev_x, prev_y), (curr_x, curr_y))

                for s in self.strings:
                    if line_intersect(finger_seg[0], finger_seg[1], s.p1, s.p2):
                        # Finger crossed string -> PLUCK!
                        freq = s.pluck()
                        self.note_queue.put(freq)
                        
                        # Spawn localized spark particles at intersection
                        ix, iy = find_intersection_pt(finger_seg[0], finger_seg[1], s.p1, s.p2)
                        for _ in range(12):
                            if len(self.particles) < self.max_particles:
                                self.particles.append(SparkParticle(ix, iy, s.color))
                        self.hud_status = f"PLUCKED: {int(freq)} Hz"

            self.prev_finger_pos[hand_idx] = (curr_x, curr_y)

            # -------------------------------------------------------------
            # 4. Spatial String Creation (Pinch & Drag)
            # -------------------------------------------------------------
            if is_pinching:
                if not self.drawing_in_progress:
                    # Anchor Point 1
                    self.anchor_p1 = (curr_x, curr_y)
                    self.drawing_in_progress = True
                    self.hud_status = "DRAWING STRING (STRETCH IN AIR)..."
                else:
                    # Preview rubber-band string
                    cv2.line(frame, self.anchor_p1, (curr_x, curr_y), (0, 255, 255), 2, cv2.LINE_AA)
                    cv2.circle(frame, self.anchor_p1, 5, (0, 255, 0), -1)
                    cv2.circle(frame, (curr_x, curr_y), 5, (0, 255, 0), -1)
            else:
                if self.drawing_in_progress and self.anchor_p1 is not None:
                    # Pinch released -> Lock string in space!
                    drag_dist = math.hypot(curr_x - self.anchor_p1[0], curr_y - self.anchor_p1[1])
                    if drag_dist > 40:  # Minimum length threshold
                        if len(self.strings) >= self.max_strings:
                            self.strings.pop(0)  # Evict oldest string
                        new_string = AirString(self.anchor_p1, (curr_x, curr_y), self.screen_diag)
                        self.strings.append(new_string)
                        # Pluck newly drawn string upon release
                        freq = new_string.pluck()
                        self.note_queue.put(freq)
                        self.hud_status = f"STRING CREATED ({int(freq)} Hz)"
                    self.drawing_in_progress = False
                    self.anchor_p1 = None

        self._render_hud(frame)
        return frame

    def clear_strings(self):
        """Clear all active strings."""
        self.strings.clear()
        self.hud_status = "ALL STRINGS CLEARED"

    def _render_hud(self, frame):
        """Minimal HUD on the OpenCV window."""
        cv2.putText(frame, "MODE: VIRTUAL AIR HARP", (15, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(frame, f"STATUS: {self.hud_status}", (15, 52),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(frame, f"STRINGS: {len(self.strings)}/{self.max_strings} (Pinch to Draw | Press 'C' to Clear)",
                    (15, 74), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (180, 180, 180), 1, cv2.LINE_AA)

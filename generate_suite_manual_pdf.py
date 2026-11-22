"""
=============================================================================
  generate_suite_manual_pdf.py (Optimized 4-Page Edition)
=============================================================================
Generates a professional, balanced 4-page PDF manual:
  Page 1: Title, Architecture, Startup Selector & Master Hotkeys
  Page 2: Mode 1 (Laptop Controller) & Mode 2 (Android Phone Remote)
  Page 3: Mode 3 (Virtual Air Harp) & Camera Setup (Phone as Webcam)
  Page 4: Hardware Profiles (Dell vs ProBook) & Quick Start Cheat Sheet
=============================================================================
"""

import os
import sys
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

PDF_FILENAME = "Hand_Tracking_Suite_Complete_Manual.pdf"

class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas to dynamically compute and print 'Page X of Y' in footer."""
    def __init__(self, *args, **kwargs):
        super(NumberedCanvas, self).__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super(NumberedCanvas, self).showPage()
        super(NumberedCanvas, self).save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 7.5)
        self.setFillColor(colors.HexColor("#718096"))

        # Header (pages > 1)
        if self._pageNumber > 1:
            self.drawString(32, 762, "Modular Hand-Tracking Suite — Complete Operating Manual & Reference Guide")
            self.setStrokeColor(colors.HexColor("#CBD5E0"))
            self.setLineWidth(0.5)
            self.line(32, 756, 580, 756)

        # Footer (all pages)
        self.setStrokeColor(colors.HexColor("#CBD5E0"))
        self.setLineWidth(0.5)
        self.line(32, 36, 580, 36)

        self.drawString(32, 25, "Confidential — Optimized for Windows 10, Android Debug Bridge, and Low-Power Dual-Core CPUs")
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(580, 25, page_str)
        self.restoreState()


def build_pdf():
    pdf_path = os.path.join(os.path.dirname(__file__), PDF_FILENAME)
    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=letter,
        leftMargin=32,
        rightMargin=32,
        topMargin=34,
        bottomMargin=42
    )

    styles = getSampleStyleSheet()

    # Typography styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=23,
        textColor=colors.HexColor('#1A365D'),
        spaceAfter=2
    )

    subtitle_style = ParagraphStyle(
        'DocSubTitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=13,
        textColor=colors.HexColor('#4A5568'),
        spaceAfter=6
    )

    h1_style = ParagraphStyle(
        'Heading1_Custom',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11.5,
        leading=15,
        textColor=colors.HexColor('#2B6CB0'),
        spaceBefore=6,
        spaceAfter=4,
        keepWithNext=True
    )

    h2_style = ParagraphStyle(
        'Heading2_Custom',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9.5,
        leading=13,
        textColor=colors.HexColor('#2D3748'),
        spaceBefore=5,
        spaceAfter=3,
        keepWithNext=True
    )

    body_style = ParagraphStyle(
        'Body_Custom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=11.5,
        textColor=colors.HexColor('#2D3748'),
        spaceAfter=4
    )

    bullet_style = ParagraphStyle(
        'Bullet_Custom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=10.5,
        textColor=colors.HexColor('#2D3748'),
        leftIndent=10,
        spaceAfter=2
    )

    table_header_style = ParagraphStyle(
        'TableHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=7.5,
        leading=9.5,
        textColor=colors.white,
        alignment=TA_LEFT
    )

    table_cell_style = ParagraphStyle(
        'TableCell',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor('#1A202C')
    )

    table_cell_bold = ParagraphStyle(
        'TableCellBold',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor('#1A202C')
    )

    story = []

    # =========================================================================
    # PAGE 1: TITLE, ARCHITECTURE, STARTUP SELECTOR & MASTER HOTKEYS
    # =========================================================================
    story.append(Paragraph("MODULAR HAND-TRACKING SUITE", title_style))
    story.append(Paragraph("Complete Operating Manual, Master Hotkeys & Architectural Blueprint", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#2B6CB0'), spaceBefore=0, spaceAfter=6))

    meta_data = [
        [Paragraph("<b>Target Hardware:</b> Dell Inspiron 5558 (Core i5-5200U, 8GB RAM, 1366x768 Display, Win10)", table_cell_style),
         Paragraph("<b>Runtime Backend:</b> MediaPipe Tasks (LiteRT XNNPACK) + Win32 user32 Ctypes", table_cell_style)],
        [Paragraph("<b>Companion Mobile:</b> Android Remote Controller via ADB (USB / Wi-Fi)", table_cell_style),
         Paragraph("<b>Audio Engine:</b> NumPy Karplus-Strong Plucked String Synthesis (44.1 kHz, &lt;20ms)", table_cell_style)]
    ]
    t_meta = Table(meta_data, colWidths=[274, 274])
    t_meta.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F7FAFC')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(t_meta)
    story.append(Spacer(1, 4))

    story.append(Paragraph("1. System Architecture & Core Modules", h1_style))
    story.append(Paragraph(
        "Combining real-time vision, desktop automation, and audio synthesis into a monolithic script causes severe CPU contention "
        "on dual-core processors. The suite solves this by decoupling into independent modules adhering to a uniform lifecycle contract: "
        "<code>on_enter()</code>, <code>update(frame, landmarks)</code>, and <code>on_exit()</code>.", body_style
    ))

    arch_table_data = [
        [Paragraph("Module File", table_header_style), Paragraph("Primary Role", table_header_style), Paragraph("Underlying Technologies", table_header_style), Paragraph("Key Optimizations", table_header_style)],
        [Paragraph("<b>bridge.py</b>", table_cell_bold),
         Paragraph("Central Vision Host & Router. Owns webcam capture and MediaPipe model.", table_cell_style),
         Paragraph("OpenCV Threaded Capture, MediaPipe Tasks LIVE_STREAM", table_cell_style),
         Paragraph("640x480 resolution, async frame drop, 1.5s fist-hold mode switcher.", table_cell_style)],
        [Paragraph("<b>air_controller.py</b>", table_cell_bold),
         Paragraph("Full Laptop Mouse & Android Phone Remote Touch Controller.", table_cell_style),
         Paragraph("Win32 Ctypes (user32.dll), adbutils, One-Euro Filter", table_cell_style),
         Paragraph("Single-hand lock (num_hands=1), anti-shake click anchor, async ADB queue.", table_cell_style)],
        [Paragraph("<b>air_harp.py</b>", table_cell_bold),
         Paragraph("Virtual Musical Instrument. Draws glowing strings in air and plays synth.", table_cell_style),
         Paragraph("sounddevice, NumPy Karplus-Strong, OpenCV Vector AA", table_cell_style),
         Paragraph("Dedicated audio thread (&lt;20ms latency), 130 max spark particles, no GPU glow.", table_cell_style)],
        [Paragraph("<b>check_compatibility.py</b>", table_cell_bold),
         Paragraph("Zero-dependency hardware diagnostics script to audit any laptop.", table_cell_style),
         Paragraph("Pure Python + Windows Kernel32 API (IsProcessorFeaturePresent)", table_cell_style),
         Paragraph("Audits AVX/AVX2/SSE4.2, RAM, 64-bit Python, auto-saves text report.", table_cell_style)],
    ]
    t_arch = Table(arch_table_data, colWidths=[90, 160, 150, 148])
    t_arch.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2B6CB0')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E0')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F7FAFC')]),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(t_arch)
    story.append(Spacer(1, 4))

    story.append(Paragraph("2. Launching & Interactive Startup Selector", h1_style))
    story.append(Paragraph(
        "Run <b>python bridge.py</b> (or double-click <b>run_suite.bat</b>). The suite scans connected devices and displays smart options:", body_style
    ))
    story.append(Paragraph("<b>[1] Laptop Air Controller:</b> Standard recommended choice for Windows mouse control. Press [Enter] to launch.", bullet_style))
    story.append(Paragraph("<b>[2] Android Phone Controller:</b> Auto-promoted when your Android device is detected via USB/Wi-Fi debugging.", bullet_style))
    story.append(Paragraph("<b>[3] Virtual Air Harp:</b> Starts the interactive musical air instrument immediately.", bullet_style))
    story.append(Paragraph("<b>[C] Camera Settings:</b> Prompts you to pick Laptop Webcam (0), Phone Cam (1), or Wi-Fi IP Webcam stream.", bullet_style))
    story.append(Spacer(1, 4))

    story.append(Paragraph("3. Master Keyboard Hotkeys & Controls", h1_style))
    hotkeys_data = [
        [Paragraph("Hotkey / Gesture", table_header_style), Paragraph("Scope", table_header_style), Paragraph("Action Description", table_header_style)],
        [Paragraph("<b>Hold Fist (1.5s)</b>", table_cell_bold), Paragraph("Air Gesture", table_cell_style),
         Paragraph("Circular radial ring fills around hand; toggles between Air Controller and Air Harp.", table_cell_style)],
        [Paragraph("<b>Key '1'</b>", table_cell_bold), Paragraph("Keyboard", table_cell_style),
         Paragraph("Instantly activates Air Controller mode (Laptop Mouse / Android).", table_cell_style)],
        [Paragraph("<b>Key '2'</b>", table_cell_bold), Paragraph("Keyboard", table_cell_style),
         Paragraph("Instantly activates Virtual Air Harp mode (Musical String Synth).", table_cell_style)],
        [Paragraph("<b>Key 'T'</b>", table_cell_bold), Paragraph("Controller Mode", table_cell_style),
         Paragraph("Toggles active target between <b>Laptop Windows Screen</b> and <b>Android Phone (ADB)</b>.", table_cell_style)],
        [Paragraph("<b>Key 'K'</b>", table_cell_bold), Paragraph("Universal", table_cell_style),
         Paragraph("Switches camera feed on the fly (Laptop Webcam 0 &harr; Phone Camera 1 via DroidCam).", table_cell_style)],
        [Paragraph("<b>Key 'H'</b>", table_cell_bold), Paragraph("Universal", table_cell_style),
         Paragraph("Toggles the on-screen semi-transparent Help and Gesture Guide overlay.", table_cell_style)],
        [Paragraph("<b>Key 'C'</b>", table_cell_bold), Paragraph("Air Harp Mode", table_cell_style),
         Paragraph("Clears all active mid-air strings, allowing you to draw a fresh set.", table_cell_style)],
        [Paragraph("<b>Key 'Y' / 'N'</b>", table_cell_bold), Paragraph("Auto-Detect Dialog", table_cell_style),
         Paragraph("Confirms ('Y') or declines ('N') switching to Android phone when a newly connected device is found.", table_cell_style)],
        [Paragraph("<b>Key 'Q' / 'Esc'</b>", table_cell_bold), Paragraph("Universal", table_cell_style),
         Paragraph("Cleanly shuts down all background camera threads, audio streams, and releases OS locks.", table_cell_style)],
    ]
    t_hotkeys = Table(hotkeys_data, colWidths=[110, 85, 353])
    t_hotkeys.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2B6CB0')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E0')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F7FAFC')]),
        ('TOPPADDING', (0, 0), (-1, -1), 2.2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.2),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(t_hotkeys)

    story.append(PageBreak())

    # =========================================================================
    # PAGE 2: MODE 1 (LAPTOP CONTROLLER) & MODE 2 (ANDROID REMOTE)
    # =========================================================================
    story.append(Paragraph("4. Mode 1: Laptop Air Controller (Touchless Mouse)", h1_style))
    story.append(Paragraph(
        "Transforms your webcam into a touchless trackpad and mouse for Windows 10. "
        "Operates via native Win32 kernel calls (<code>ctypes.windll.user32</code>) with zero automation latency.", body_style
    ))

    controller_gestures = [
        [Paragraph("Desktop Action", table_header_style), Paragraph("Finger Gesture", table_header_style), Paragraph("Behavior & Anti-Shake Stabilization", table_header_style)],
        [Paragraph("<b>Move Cursor</b>", table_cell_bold),
         Paragraph("Point index fingertip (Landmark 8) with thumb relaxed.", table_cell_style),
         Paragraph("Smooth 1:1 motion filtered by a 1&euro; adaptive velocity filter mapped to 1366x768 display.", table_cell_style)],
        [Paragraph("<b>Left Click</b>", table_cell_bold),
         Paragraph("Quick pinch between Thumb and Index finger (&lt;250 ms).", table_cell_style),
         Paragraph("<b>Anti-Shake Lock:</b> Cursor freezes in place during pinch so finger motion does not slip off targets.", table_cell_style)],
        [Paragraph("<b>Double Click</b>", table_cell_bold),
         Paragraph("Two quick pinches within 400 ms.", table_cell_style),
         Paragraph("Fires native double left-click event to open files, folders, and desktop shortcuts.", table_cell_style)],
        [Paragraph("<b>Click &amp; Drag</b>", table_cell_bold),
         Paragraph("Sustained pinch (&gt;350 ms) held while moving your hand.", table_cell_style),
         Paragraph("Locks MOUSEEVENTF_LEFTDOWN. Allows dragging windows, moving sliders, or selecting text.", table_cell_style)],
        [Paragraph("<b>Right Click</b>", table_cell_bold),
         Paragraph("Quick pinch between Thumb and Middle finger (Landmarks 4 &amp; 12).", table_cell_style),
         Paragraph("Fires native right-click event to open context menus without needing to pause or hold cursor.", table_cell_style)],
        [Paragraph("<b>Two-Finger Scroll</b>", table_cell_bold),
         Paragraph("Index and Middle fingers extended upright together; move hand vertically.", table_cell_style),
         Paragraph("Generates smooth mouse wheel scroll events (MOUSEEVENTF_WHEEL) for web pages and documents.", table_cell_style)],
        [Paragraph("<b>Arm Rest / Clutch</b>", table_cell_bold),
         Paragraph("Curl all fingers into a loose fist or relax hand below active box.", table_cell_style),
         Paragraph("Freezes pointer completely. Allows you to rest or reposition your arm without moving the cursor.", table_cell_style)],
    ]
    t_ctrl = Table(controller_gestures, colWidths=[105, 165, 278])
    t_ctrl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2B6CB0')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E0')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F7FAFC')]),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(t_ctrl)
    story.append(Spacer(1, 4))

    story.append(Paragraph("<b>Anti-Shake Click Anchor &amp; Ergonomics Advice:</b>", h2_style))
    story.append(Paragraph("<b>1. How the Anchor Works:</b> When closing your thumb and index finger to click, natural biomechanics cause the index fingertip to shift 15–30 pixels. The software detects the pre-pinch motion and automatically freezes cursor coordinates on your intended button until the pinch releases.", bullet_style))
    story.append(Paragraph("<b>2. Forearm Resting:</b> Always rest your forearm or elbow on the desk or chair armrest. Pivot from your wrist and fingers—never hover your entire shoulder in mid-air (prevents 'gorilla arm' fatigue).", bullet_style))
    story.append(Spacer(1, 6))

    story.append(Paragraph("5. Mode 2: Android Phone Remote Controller (ADB)", h1_style))
    story.append(Paragraph(
        "Remotely control your Android smartphone touchlessly from your laptop webcam without installing any app on the phone. "
        "Commands run via an asynchronous ADB worker queue to ensure zero frame drops on your PC.", body_style
    ))

    android_gestures = [
        [Paragraph("Phone Action", table_header_style), Paragraph("Finger Gesture", table_header_style), Paragraph("ADB Command Executed", table_header_style)],
        [Paragraph("<b>Touch / Tap Screen</b>", table_cell_bold),
         Paragraph("Quick pinch between Thumb and Index finger.", table_cell_style),
         Paragraph("Translates finger position into phone resolution and executes <code>adb shell input tap X Y</code>.", table_cell_style)],
        [Paragraph("<b>Next Reel / Short</b>", table_cell_bold),
         Paragraph("Two fingers extended upright &rarr; <b>Swipe UP</b>.", table_cell_style),
         Paragraph("Executes vertical bottom-to-top swipe (<code>input swipe X Y_bottom X Y_top 200</code>).", table_cell_style)],
        [Paragraph("<b>Previous Reel / Short</b>", table_cell_bold),
         Paragraph("Two fingers extended upright &rarr; <b>Swipe DOWN</b>.", table_cell_style),
         Paragraph("Executes vertical top-to-bottom swipe (<code>input swipe X Y_top X Y_bottom 200</code>).", table_cell_style)],
        [Paragraph("<b>Android Back Key</b>", table_cell_bold),
         Paragraph("Open palm flicked to the <b>LEFT</b>.", table_cell_style),
         Paragraph("Fires Android Back key event (<code>adb shell input keyevent 4</code>).", table_cell_style)],
        [Paragraph("<b>Android Home Screen</b>", table_cell_bold),
         Paragraph("Open palm flicked <b>UPWARDS</b>.", table_cell_style),
         Paragraph("Fires Android Home key event (<code>adb shell input keyevent 3</code>).", table_cell_style)],
    ]
    t_and = Table(android_gestures, colWidths=[110, 160, 278])
    t_and.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2B6CB0')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E0')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F7FAFC')]),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(t_and)
    story.append(Spacer(1, 4))

    story.append(Paragraph("<b>One-Time Android Device Setup:</b>", h2_style))
    story.append(Paragraph("1. On phone: <b>Settings &rarr; About Phone</b> &rarr; Tap <b>Build Number</b> 7 times to enable Developer Options.", bullet_style))
    story.append(Paragraph("2. In <b>Settings &rarr; Developer Options</b>, toggle on <b>USB Debugging</b>.", bullet_style))
    story.append(Paragraph("3. Connect phone via USB cable and tap <b>Always Allow from this Computer</b> when prompted.", bullet_style))
    story.append(Paragraph("4. <i>Optional Wireless:</i> Run <code>adb tcpip 5555</code> once, then connect wirelessly via <code>adb connect &lt;phone_ip&gt;:5555</code>.", bullet_style))

    story.append(PageBreak())

    # =========================================================================
    # PAGE 3: MODE 3 (VIRTUAL AIR HARP) & CAMERA OPTIONS
    # =========================================================================
    story.append(Paragraph("6. Mode 3: Virtual Air Harp (Interactive Plucked Synth)", h1_style))
    story.append(Paragraph(
        "Inspired by interactive mid-air musical instruments, the Air Harp lets you draw glowing strings in 3D space "
        "and pluck them with moving fingertips to generate acoustic sounds and localized spark visuals.", body_style
    ))

    harp_features = [
        [Paragraph("Feature Component", table_header_style), Paragraph("Implementation Detail", table_header_style), Paragraph("Acoustic / Visual Result", table_header_style)],
        [Paragraph("<b>Spatial String Creation</b>", table_cell_bold),
         Paragraph("Pinch thumb and index finger, stretch hand in air, release pinch to anchor string in space.", table_cell_style),
         Paragraph("Strings lock in 2D/3D space with anchor circles. Supports up to 8 active strings.", table_cell_style)],
        [Paragraph("<b>Pluck Detection Physics</b>", table_cell_bold),
         Paragraph("Continuous 2D line segment intersection (CCW test) between moving fingertips and active strings.", table_cell_style),
         Paragraph("Instant trigger when fingertip crosses string segment. Zero false triggers while anchoring.", table_cell_style)],
        [Paragraph("<b>Karplus-Strong Audio</b>", table_cell_bold),
         Paragraph("Real-time physical string modeling in NumPy with delay-line feedback filter running at 44.1 kHz.", table_cell_style),
         Paragraph("Sub-20ms latency via non-blocking sounddevice callback thread. Soft limiter clip protection.", table_cell_style)],
        [Paragraph("<b>Pitch Mapping</b>", table_cell_bold),
         Paragraph("String Euclidean length mapped inversely to musical pentatonic scale (C, D, E, G, A across octaves).", table_cell_style),
         Paragraph("Shorter strings produce bright high notes; longer strings produce deep bass plucks.", table_cell_style)],
        [Paragraph("<b>Damped Wave &amp; Sparks</b>", table_cell_bold),
         Paragraph("Plucked strings oscillate with realistic quadratic bezier damping. Spawns 12 spark particles.", table_cell_style),
         Paragraph("Anti-aliased vector rendering (cv2.LINE_AA). Particle pool capped at 130 to save Intel HD 5500 iGPU.", table_cell_style)],
    ]
    t_harp = Table(harp_features, colWidths=[120, 200, 228])
    t_harp.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2B6CB0')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E0')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F7FAFC')]),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(t_harp)
    story.append(Spacer(1, 8))

    story.append(Paragraph("7. Camera Setup: Using Your Phone as a High-Res Webcam", h1_style))
    story.append(Paragraph(
        "Phone cameras have superior optics, higher frame rates, and superior low-light sensitivity compared to older laptop webcams. "
        "The suite supports two seamless integration methods:", body_style
    ))

    cam_data = [
        [Paragraph("Method", table_header_style), Paragraph("Connection", table_header_style), Paragraph("Setup Procedure", table_header_style), Paragraph("How to Select in Suite", table_header_style)],
        [Paragraph("<b>DroidCam / Iriun</b>", table_cell_bold), Paragraph("USB or Wi-Fi", table_cell_style),
         Paragraph("Install app on phone and Windows client on PC. Mounts phone as virtual Camera Index 1.", table_cell_style),
         Paragraph("Select <b>[1]</b> in startup menu or press <b>'K'</b> on keyboard while running.", table_cell_style)],
        [Paragraph("<b>IP Webcam</b>", table_cell_bold), Paragraph("Wi-Fi (Zero PC Install)", table_cell_style),
         Paragraph("Install free IP Webcam app on phone. Tap 'Start server' to get URL (e.g. <code>http://192.168.1.15:8080/video</code>).", table_cell_style),
         Paragraph("Select <b>[C] &rarr; [2]</b> in startup menu and paste URL. OpenCV streams directly.", table_cell_style)],
    ]
    t_cam = Table(cam_data, colWidths=[95, 85, 228, 140])
    t_cam.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2B6CB0')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E0')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F7FAFC')]),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(t_cam)
    story.append(Spacer(1, 8))

    story.append(Paragraph("<b>Camera Positioning Tips:</b>", h2_style))
    story.append(Paragraph("&bull; Place your phone camera roughly at chest height, angled slightly downward toward your desk.", bullet_style))
    story.append(Paragraph("&bull; Ensure even ambient lighting; avoid bright windows directly behind your hand.", bullet_style))
    story.append(Paragraph("&bull; Switching cameras takes under 1 second and does not freeze or restart the hand-tracking engine.", bullet_style))

    story.append(PageBreak())

    # =========================================================================
    # PAGE 4: HARDWARE PROFILES & QUICK START CHEAT SHEET
    # =========================================================================
    story.append(Paragraph("8. Hardware Auditing & Optimization Profiles", h1_style))
    story.append(Paragraph(
        "Running neural hand tracking on entry-level or legacy laptops requires customized software profiles. "
        "Run <b>check_compatibility.py</b> on any machine to automatically audit its instruction sets and memory headroom:", body_style
    ))

    hw_data = [
        [Paragraph("Profile Parameter", table_header_style), Paragraph("Dell Inspiron 5558 (Current PC)", table_header_style), Paragraph("HP ProBook 6450b (Legacy Target)", table_header_style)],
        [Paragraph("<b>Processor &amp; Instructions</b>", table_cell_bold),
         Paragraph("Intel Core i5-5200U (AVX, AVX2 supported)", table_cell_style),
         Paragraph("Intel Core i5-520M / i3-350M (<b>No AVX</b> &mdash; SSE4.2 only)", table_cell_style)],
        [Paragraph("<b>MediaPipe Version</b>", table_cell_bold),
         Paragraph("Standard modern build (<code>pip install mediapipe</code>)", table_cell_style),
         Paragraph("Legacy non-AVX pin (<code>pip install mediapipe&lt;=0.8.11</code>)", table_cell_style)],
        [Paragraph("<b>Inference Resolution</b>", table_cell_bold),
         Paragraph("640 x 480 @ 30 FPS", table_cell_style),
         Paragraph("Downscale to <b>320 x 240</b> (cuts matrix ops by 75%)", table_cell_style)],
        [Paragraph("<b>Tracking Cadence</b>", table_cell_bold),
         Paragraph("Every frame (30 Hz real-time)", table_cell_style),
         Paragraph("Every 2nd frame (15 Hz inference + velocity interpolation)", table_cell_style)],
        [Paragraph("<b>RAM Ceiling</b>", table_cell_bold),
         Paragraph("&lt; 180 MB RSS headroom (2.7 GB free)", table_cell_style),
         Paragraph("Strict &lt; 80 MB RSS + explicit <code>gc.collect()</code> on exit", table_cell_style)],
        [Paragraph("<b>Audio Synthesis</b>", table_cell_bold),
         Paragraph("44.1 kHz Stereo Karplus-Strong", table_cell_style),
         Paragraph("22.05 kHz Mono Karplus-Strong (buffer size 512)", table_cell_style)],
    ]
    t_hw = Table(hw_data, colWidths=[120, 214, 214])
    t_hw.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2B6CB0')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E0')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F7FAFC')]),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(t_hw)
    story.append(Spacer(1, 10))

    story.append(Paragraph("9. Troubleshooting & FAQ", h1_style))
    story.append(Paragraph("<b>Q: Cursor jumps or lags when moving?</b><br/>"
                           "A: Ensure your hand is within the central 70% active zone indicated by the on-screen box. Keep room lighting adequate.", bullet_style))
    story.append(Paragraph("<b>Q: ADB says 'device unauthorized'?</b><br/>"
                           "A: Unlock your phone screen, check the USB notification, and tap 'Always Allow from this Computer'.", bullet_style))
    story.append(Paragraph("<b>Q: Can I run this without installing Python on another PC?</b><br/>"
                           "A: Run <code>check_compatibility.py</code> first; it uses 100% standard Python libraries without any pip dependencies.", bullet_style))
    story.append(Spacer(1, 10))

    # =========================================================================
    # QUICK START SUMMARY
    # =========================================================================
    summary_box = [
        [Paragraph("<b>QUICK START CHEAT SHEET</b>", table_cell_bold)],
        [Paragraph("<b>1. Start:</b> Double-click <code>run_suite.bat</code> (or run <code>python bridge.py</code>) &rarr; Press [Enter] for Recommended mode.<br/>"
                   "<b>2. Laptop Mouse:</b> Point Index Finger to steer | Pinch Thumb+Index to Click &amp; Drag (Anti-Shake Lock holds cursor).<br/>"
                   "<b>3. Android Phone:</b> Press <b>'T'</b> anytime to control your Android Phone over USB/Wi-Fi (Pinch=Tap, 2-Finger=Reels).<br/>"
                   "<b>4. Virtual Air Harp:</b> Hold a <b>Closed Fist for 1.5s</b> (or press <b>'2'</b>) &rarr; Draw strings in air &amp; pluck.<br/>"
                   "<b>5. On-Screen Help:</b> Press <b>'H'</b> for on-screen help card | Press <b>'Q'</b> or <b>Esc</b> to exit cleanly.", table_cell_style)]
    ]
    t_sum = Table(summary_box, colWidths=[548])
    t_sum.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#EBF8FF')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#3182CE')),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(t_sum)

    # Build document
    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"[OK] Generated 4-Page PDF Manual: {pdf_path}")
    print(f"File size: {os.path.getsize(pdf_path)} bytes")

if __name__ == "__main__":
    build_pdf()

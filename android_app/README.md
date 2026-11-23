# AirTouch: Touchless Hand-Tracking Android App

AirTouch is a native Kotlin Android application that enables touchless front-camera gesture control for Android smartphones without requiring a PC, cable, or ADB connection.

---

## Architecture & How It Works

1. **CameraX & MediaPipe Tasks Vision**:
   - Captures real-time frames from the smartphone's front camera (`CameraSelector.DEFAULT_FRONT_CAMERA`).
   - Runs `hand_landmarker.task` on the phone's mobile GPU delegate to detect 21 3D joint landmarks.

2. **AccessibilityService Touch Engine**:
   - Simulates native touch gestures anywhere on the screen using Android's `dispatchGesture()` API:
     - **Index Air-Tap**: Dispatches a screen tap (`GestureDescription.StrokeDescription`) with anti-shake coordinate locking.
     - **Two-Finger Vertical Swipe**: Swipes between Instagram Reels, YouTube Shorts, and TikTok videos.
     - **Horizontal Air Swing**: Swipes left or right to switch between app tabs or screens (with 0.6s return debounce).
     - **Open Palm Flick**: Navigates Back (`GLOBAL_ACTION_BACK`) and Home (`GLOBAL_ACTION_HOME`).

3. **Floating Overlay Bubble**:
   - Uses `TYPE_APPLICATION_OVERLAY` to keep camera tracking alive as a small draggable bubble while you interact with other apps.

---

## Project Structure

```
android_app/
├── app/
│   ├── src/main/
│   │   ├── assets/
│   │   │   └── hand_landmarker.task      <-- MediaPipe LiteRT model
│   │   ├── java/com/hand/airtouch/
│   │   │   ├── MainActivity.kt           <-- Setup & permission flow
│   │   │   ├── AirTouchAccessibilityService.kt <-- Touch injection & overlay
│   │   │   └── HandGestureDetector.kt    <-- Gesture classifier
│   │   ├── res/
│   │   │   ├── layout/
│   │   │   │   ├── activity_main.xml
│   │   │   │   └── overlay_bubble.xml
│   │   │   └── xml/
│   │   │       └── accessibility_service_config.xml
│   │   └── AndroidManifest.xml
│   └── build.gradle.kts
├── build.gradle.kts
└── settings.gradle.kts
```

---

## One-Time Permissions Required

When launching the app on your phone, complete these 3 setup steps:
1. **Camera Permission**: Allow front camera capture.
2. **Display over other apps**: Allow floating bubble overlay.
3. **Accessibility**: Open **Settings &rarr; Accessibility &rarr; Installed Apps &rarr; Enable 'AirTouch'**.

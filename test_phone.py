"""
Quick test script to verify if your realme 7 Pro is connected via ADB and if DroidCam is active.
"""
import subprocess
import cv2
import adbutils

print("=" * 65)
print("  REALME 7 PRO & DROIDCAM CONNECTION STATUS")
print("=" * 65)

# 1. Check ADB
devices = adbutils.adb.device_list()
if devices:
    d = devices[0]
    print(f"\n[OK] Android Phone Connected via ADB!")
    print(f"     Serial : {d.serial}")
    print(f"     State  : {d.get_state()}")
    try:
        model = getattr(d.prop, 'model', 'unknown')
        print(f"     Model  : {model}")
    except Exception:
        pass
    print("\n -> You are READY to touchlessly control your phone!")
else:
    print("\n[!] Phone NOT detected in ADB mode yet.")
    print("    Follow these 3 steps on your realme 7 Pro:")
    print("    1. Settings -> About Device -> Version -> Tap 'Build Number' 7 times.")
    print("    2. Settings -> Additional Settings -> Developer Options -> Turn ON 'USB Debugging'.")
    print("    3. Plug in USB cable & tap 'Allow USB Debugging' on phone screen.")

# 2. Check Cameras
print("\n" + "-" * 65)
print("Checking Available Cameras for Laptop Hand-Tracking:")
for idx in range(3):
    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
    if cap.isOpened():
        ret, frame = cap.read()
        cap.release()
        if ret and frame is not None:
            cam_name = "Built-in Laptop Webcam" if idx == 0 else "DroidCam Virtual Phone Camera"
            print(f"  [Camera {idx}] READY -> {cam_name} ({frame.shape[1]}x{frame.shape[0]})")
    else:
        print(f"  [Camera {idx}] Not active")

print("=" * 65)

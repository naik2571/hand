import subprocess
import cv2
import adbutils

print("=" * 65)
print("  ANDROID CONNECTION & CAMERA DIAGNOSTICS")
print("=" * 65)

# 1. ADB Check
print("\n[1] ADB Check:")
try:
    devs = adbutils.adb.device_list()
    if devs:
        print(f"  Found {len(devs)} ADB device(s):")
        for d in devs:
            try:
                state = d.get_state()
                model = getattr(d.prop, 'model', 'unknown')
                print(f"    - Serial: {d.serial} | State: {state} | Model: {model}")
            except Exception as e:
                print(f"    - Serial: {d.serial} | State query error: {e}")
    else:
        print("  [!] No ADB devices found by adb server.")
except Exception as e:
    print(f"  [!] ADB error: {e}")

# 2. Windows USB / PnP Devices
print("\n[2] Windows PnP Devices (Phones, Cameras, Media Devices):")
try:
    cmd = [
        "powershell", "-NoProfile", "-Command",
        "Get-PnpDevice -Status OK | Where-Object { $_.Class -in @('Camera','Image','WPD','AndroidUsbDeviceClass') } | Select-Object FriendlyName, Class | Format-Table -AutoSize"
    ]
    output = subprocess.check_output(cmd, text=True).strip()
    print(output if output else "  No matching devices found.")
except Exception as e:
    print(f"  Error: {e}")

# 3. Camera Check
print("\n[3] OpenCV Camera Stream Check:")
for idx in range(3):
    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
    if cap.isOpened():
        ret, frame = cap.read()
        shape = frame.shape if ret else "None"
        print(f"  Camera Index {idx}: OPENED (ret={ret}, frame={shape})")
        cap.release()
    else:
        print(f"  Camera Index {idx}: Not available / closed")

print("=" * 65)

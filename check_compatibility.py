"""
=============================================================================
  Hand-Tracking Suite Compatibility & Hardware Diagnostics Checker
=============================================================================
This script audits your PC specifications (CPU, AVX/SSE support, RAM, GPU, 
webcam, and Python environment) to determine whether it can run the Modular
Decoupled Hand-Tracking Suite (Air Controller & Air Harp) and recommends the
exact configuration profiles needed.

Runs with 100% standard Python libraries (no pip install required).
=============================================================================
"""

import sys
import os
import platform
import subprocess
import ctypes
import json
from datetime import datetime

# Windows API Constants
PF_XMMI_INSTRUCTIONS_AVAILABLE = 6          # SSE
PF_XMMI64_INSTRUCTIONS_AVAILABLE = 10       # SSE2
PF_SSE3_INSTRUCTIONS_AVAILABLE = 13         # SSE3
PF_SSSE3_INSTRUCTIONS_AVAILABLE = 36        # SSSE3
PF_SSE4_1_INSTRUCTIONS_AVAILABLE = 37       # SSE4.1
PF_SSE4_2_INSTRUCTIONS_AVAILABLE = 38       # SSE4.2
PF_AVX_INSTRUCTIONS_AVAILABLE = 17          # AVX
PF_AVX2_INSTRUCTIONS_AVAILABLE = 40         # AVX2
PF_AVX512F_INSTRUCTIONS_AVAILABLE = 41     # AVX-512 Foundation

class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]

def get_cpu_features():
    """Detect hardware instruction sets using Windows kernel32."""
    kernel32 = ctypes.windll.kernel32
    return {
        "SSE": bool(kernel32.IsProcessorFeaturePresent(PF_XMMI_INSTRUCTIONS_AVAILABLE)),
        "SSE2": bool(kernel32.IsProcessorFeaturePresent(PF_XMMI64_INSTRUCTIONS_AVAILABLE)),
        "SSE3": bool(kernel32.IsProcessorFeaturePresent(PF_SSE3_INSTRUCTIONS_AVAILABLE)),
        "SSSE3": bool(kernel32.IsProcessorFeaturePresent(PF_SSSE3_INSTRUCTIONS_AVAILABLE)),
        "SSE4.1": bool(kernel32.IsProcessorFeaturePresent(PF_SSE4_1_INSTRUCTIONS_AVAILABLE)),
        "SSE4.2": bool(kernel32.IsProcessorFeaturePresent(PF_SSE4_2_INSTRUCTIONS_AVAILABLE)),
        "AVX": bool(kernel32.IsProcessorFeaturePresent(PF_AVX_INSTRUCTIONS_AVAILABLE)),
        "AVX2": bool(kernel32.IsProcessorFeaturePresent(PF_AVX2_INSTRUCTIONS_AVAILABLE)),
        "AVX512": bool(kernel32.IsProcessorFeaturePresent(PF_AVX512F_INSTRUCTIONS_AVAILABLE)),
    }

def get_memory_info():
    """Get physical RAM metrics via GlobalMemoryStatusEx."""
    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
    total_gb = stat.ullTotalPhys / (1024 ** 3)
    avail_gb = stat.ullAvailPhys / (1024 ** 3)
    return {
        "total_gb": round(total_gb, 2),
        "avail_gb": round(avail_gb, 2),
        "load_pct": stat.dwMemoryLoad,
    }

def get_display_resolution():
    """Get screen resolution using Windows user32."""
    try:
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
        w = user32.GetSystemMetrics(0)
        h = user32.GetSystemMetrics(1)
        return f"{w} x {h}"
    except Exception:
        return "Unknown"

def run_powershell(cmd):
    """Utility to run a quiet PowerShell command and return stripped string."""
    try:
        res = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", cmd],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5
        ).strip()
        return res
    except Exception:
        return ""

def get_cpu_name():
    """Query CPU model name."""
    name = run_powershell("(Get-CimInstance Win32_Processor).Name")
    if not name:
        name = os.environ.get("PROCESSOR_IDENTIFIER", platform.processor())
    return name.strip()

def get_cpu_cores():
    """Query physical and logical core count."""
    logical = os.cpu_count() or 1
    phys_str = run_powershell("(Get-CimInstance Win32_Processor).NumberOfCores")
    try:
        physical = int(phys_str)
    except Exception:
        physical = logical // 2 if logical > 1 else 1
    return physical, logical

def get_gpus():
    """Query installed graphics cards."""
    gpu_list = []
    gpu_str = run_powershell("Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name")
    if gpu_str:
        for line in gpu_str.splitlines():
            line = line.strip()
            if line and line not in gpu_list:
                gpu_list.append(line)
    if not gpu_list:
        gpu_list.append("Generic Display Adapter")
    return gpu_list

def test_webcam():
    """Test webcam availability using OpenCV if available, or PowerShell PNP query."""
    result = {"available": False, "method": "None", "details": ""}
    try:
        import cv2
        cap = cv2.VideoCapture(0)
        if cap.isOpened():
            ret, frame = cap.read()
            if ret and frame is not None:
                h, w, _ = frame.shape
                result["available"] = True
                result["method"] = "OpenCV VideoCapture(0) [Verified Functional]"
                result["details"] = f"Native capture size: {w}x{h}"
            cap.release()
            return result
    except ImportError:
        pass
    except Exception:
        pass

    # Fallback to Windows PnP Camera detection
    cam_devices = run_powershell("Get-PnpDevice -Class Camera, Image -Status OK -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FriendlyName")
    if cam_devices:
        first_cam = cam_devices.splitlines()[0].strip()
        result["available"] = True
        result["method"] = "Windows Device Manager (PnP Check)"
        result["details"] = f"Detected device: {first_cam} (OpenCV not installed yet)"
    else:
        result["available"] = False
        result["method"] = "Windows Device Manager"
        result["details"] = "No active camera found. Connect webcam or phone via DroidCam/Iriun."
    return result

def evaluate_compatibility(specs):
    """
    Evaluates hardware specs against Hand-Tracking Suite requirements.
    Returns: status ('EXCELLENT', 'COMPATIBLE WITH OPTIMIZATIONS', 'LIMITED / REQUIRES TWEAKS', 'UNSUPPORTED'),
             score (1-10), issues list, and recommendations.
    """
    issues = []
    recommendations = []
    status = "EXCELLENT"
    score = 10

    # 1. Python Architecture Check
    is_64bit = sys.maxsize > 2**32
    if not is_64bit:
        issues.append("CRITICAL: Python is 32-bit! MediaPipe strictly requires 64-bit Python.")
        recommendations.append("Reinstall Python using the 64-bit (Windows x86-64) installer.")
        return "UNSUPPORTED", 1, issues, recommendations

    # 2. AVX / AVX2 Check (Crucial for HP ProBook 6450b vs Modern PCs)
    has_avx = specs["cpu_features"]["AVX"]
    has_avx2 = specs["cpu_features"]["AVX2"]
    has_sse42 = specs["cpu_features"]["SSE4.2"]

    if not has_avx:
        issues.append("HARDWARE LIMIT: CPU does not support AVX (e.g. 1st-Gen Intel Core like i5-520M).")
        issues.append("Modern 'pip install mediapipe>=0.10' will crash with STATUS_ILLEGAL_INSTRUCTION.")
        recommendations.append("Install legacy MediaPipe: pip install 'mediapipe<=0.8.11'")
        recommendations.append("OR use OpenCV DNN with quantized MobileNet-Hand ONNX (pure SSE fallback).")
        score -= 3
        status = "LIMITED / REQUIRES TWEAKS"

    # 3. RAM Check
    total_ram = specs["memory"]["total_gb"]
    avail_ram = specs["memory"]["avail_gb"]

    if total_ram < 3.5:
        issues.append(f"RAM CRITICAL: Only {total_ram} GB total. Windows will page heavily.")
        recommendations.append("Cap app memory to < 70MB. Close Chrome and background apps before running.")
        score -= 3
        status = "LIMITED / REQUIRES TWEAKS"
    elif total_ram <= 4.5:
        issues.append(f"RAM BUDGET (4GB Detected): Available RAM is {avail_ram} GB.")
        recommendations.append("Set lean memory profile: enforce on_exit() buffer clearing & gc.collect().")
        score -= 1
        if status == "EXCELLENT":
            status = "COMPATIBLE WITH OPTIMIZATIONS"
    else:
        recommendations.append(f"RAM Headroom: {total_ram} GB total ({avail_ram} GB free) is optimal.")

    # 4. CPU Cores & Performance
    phys_cores = specs["cpu_physical_cores"]
    if phys_cores < 2:
        issues.append("CPU Single-Core: Real-time hand tracking will struggle.")
        recommendations.append("Use 320x240 resolution and skip every 2nd frame.")
        score -= 3
        status = "LIMITED / REQUIRES TWEAKS"
    elif phys_cores == 2:
        recommendations.append("Dual-core CPU detected: Run single-hand tracking (num_hands=1) for air_controller.")
        if not has_avx:
            recommendations.append("Downscale inference resolution to 320x240 to sustain 25-30 FPS.")
        else:
            recommendations.append("Run at 640x480 with MediaPipe Lite (model_complexity=0).")
        if status == "EXCELLENT":
            status = "COMPATIBLE WITH OPTIMIZATIONS"

    # 5. Webcam
    if not specs["webcam"]["available"]:
        issues.append("No active webcam detected.")
        recommendations.append("Plug in a USB webcam or connect an Android phone using DroidCam / Iriun.")
        score -= 2

    # Final summary grading
    if score >= 9:
        status = "EXCELLENT (Runs Full High-Speed Mode)"
    elif score >= 6:
        status = "COMPATIBLE WITH OPTIMIZATIONS (Runs Smoothly with Low-Spec Profile)"
    elif score >= 4:
        status = "LIMITED (Runs with Reduced Resolution 320x240 & Legacy MediaPipe)"
    else:
        status = "UNSUPPORTED"

    return status, score, issues, recommendations

def main():
    print("=" * 75)
    print("   Modular Hand-Tracking Suite: Hardware & Environment Diagnostics")
    print("=" * 75)
    print("Scanning system components... Please wait a few seconds.\n")

    # Gather data
    cpu_name = get_cpu_name()
    phys_cores, log_cores = get_cpu_cores()
    cpu_features = get_cpu_features()
    memory = get_memory_info()
    resolution = get_display_resolution()
    gpus = get_gpus()
    webcam = test_webcam()

    specs = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "os": f"{platform.system()} {platform.release()} (Build {platform.version()})",
        "python_version": f"{platform.python_version()} ({'64-bit' if sys.maxsize > 2**32 else '32-bit'})",
        "cpu_name": cpu_name,
        "cpu_physical_cores": phys_cores,
        "cpu_logical_cores": log_cores,
        "cpu_features": cpu_features,
        "memory": memory,
        "resolution": resolution,
        "gpus": gpus,
        "webcam": webcam,
    }

    verdict, score, issues, recommendations = evaluate_compatibility(specs)

    # Build report text
    report_lines = []
    report_lines.append("=" * 75)
    report_lines.append(f"  SYSTEM SPECIFICATION AUDIT REPORT  [{specs['timestamp']}]")
    report_lines.append("=" * 75)
    report_lines.append(f"Operating System  : {specs['os']}")
    report_lines.append(f"Python Runtime    : {specs['python_version']}")
    report_lines.append(f"Display Resolution: {specs['resolution']}")
    report_lines.append(f"Processor (CPU)   : {specs['cpu_name']}")
    report_lines.append(f"Cores / Threads   : {specs['cpu_physical_cores']} Physical Cores / {specs['cpu_logical_cores']} Threads")
    
    # Instruction sets line
    feat_str = []
    for k, v in specs['cpu_features'].items():
        feat_str.append(f"{k}: {'YES' if v else 'NO'}")
    report_lines.append(f"Instruction Sets  : {', '.join(feat_str)}")

    report_lines.append(f"Total System RAM  : {specs['memory']['total_gb']} GB (Available: {specs['memory']['avail_gb']} GB, {specs['memory']['load_pct']}% used)")
    report_lines.append(f"Graphics (GPU)    : {', '.join(specs['gpus'])}")
    report_lines.append(f"Webcam Status     : {'READY' if specs['webcam']['available'] else 'NOT DETECTED'} ({specs['webcam']['details']})")
    
    report_lines.append("\n" + "=" * 75)
    report_lines.append(f"  COMPATIBILITY VERDICT: {verdict}")
    report_lines.append(f"  HARDWARE READINESS SCORE: {score} / 10")
    report_lines.append("=" * 75)

    if issues:
        report_lines.append("\n[!] DETECTED CONSTRAINTS & LIMITATIONS:")
        for idx, issue in enumerate(issues, 1):
            report_lines.append(f"  {idx}. {issue}")

    report_lines.append("\n[*] RECOMMENDED CONFIGURATION PROFILE:")
    for idx, rec in enumerate(recommendations, 1):
        report_lines.append(f"  {idx}. {rec}")

    # Specific profile advice
    report_lines.append("\n[+] SUMMARY PROFILE CONFIGURATION:")
    if specs['cpu_features']['AVX']:
        report_lines.append("  * MediaPipe Version : Standard ('pip install mediapipe')")
        report_lines.append("  * Video Stream Res  : 640 x 480 @ 30 FPS")
        report_lines.append("  * Inference Model   : Lite (model_complexity=0)")
        report_lines.append("  * Air Controller    : Full Win32 Direct Cursor + Pinch Click")
        report_lines.append("  * Air Harp Audio    : 44.1 kHz Karplus-Strong Plucked Strings")
    else:
        report_lines.append("  * MediaPipe Version : Legacy Pin ('pip install mediapipe<=0.8.11') or OpenCV DNN")
        report_lines.append("  * Video Stream Res  : Downscale to 320 x 240 for Neural Network Inference")
        report_lines.append("  * Frame Cadence     : 15 Hz inference + 30 Hz velocity interpolation")
        report_lines.append("  * Air Controller    : Full Win32 Direct Cursor (Optimized 320x240 map)")
        report_lines.append("  * Air Harp Audio    : 22.05 kHz Mono Karplus-Strong (Cap 35 particles)")

    report_lines.append("=" * 75)

    report_text = "\n".join(report_lines)
    print(report_text)

    # Save to file
    output_filename = "hand_tracking_compatibility_report.txt"
    try:
        with open(output_filename, "w", encoding="utf-8") as f:
            f.write(report_text)
        print(f"\n[OK] Report successfully saved to: {os.path.abspath(output_filename)}")
        print("You can send this report or script directly to your friend!")
    except Exception as e:
        print(f"\n[!] Warning: Could not write report file: {e}")

if __name__ == "__main__":
    main()

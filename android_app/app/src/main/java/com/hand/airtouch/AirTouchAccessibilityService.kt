package com.hand.airtouch

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Intent
import android.graphics.Path
import android.graphics.PixelFormat
import android.os.Build
import android.util.DisplayMetrics
import android.util.Log
import android.view.Gravity
import android.view.LayoutInflater
import android.view.View
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.content.ContextCompat
import com.google.mediapipe.framework.image.BitmapImageBuilder
import com.google.mediapipe.framework.image.MPImage
import com.google.mediapipe.tasks.core.BaseOptions
import com.google.mediapipe.tasks.vision.core.RunningMode
import com.google.mediapipe.tasks.vision.handlandmarker.HandLandmarker
import com.google.mediapipe.tasks.vision.handlandmarker.HandLandmarkerResult
import java.util.concurrent.Executors

class AirTouchAccessibilityService : AccessibilityService() {

    private val TAG = "AirTouchService"
    private var windowManager: WindowManager? = null
    private var overlayView: View? = null
    private var gestureDetector: HandGestureDetector? = null
    private var handLandmarker: HandLandmarker? = null
    private val cameraExecutor = Executors.newSingleThreadExecutor()

    companion object {
        var instance: AirTouchAccessibilityService? = null
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        Log.d(TAG, "AirTouchAccessibilityService connected successfully")

        val metrics = DisplayMetrics()
        val wm = getSystemService(WINDOW_SERVICE) as WindowManager
        wm.defaultDisplay.getRealMetrics(metrics)

        gestureDetector = HandGestureDetector(metrics.widthPixels, metrics.heightPixels)
        initMediaPipe()
        showFloatingBubble()
    }

    private fun initMediaPipe() {
        try {
            val baseOptions = BaseOptions.builder()
                .setModelAssetPath("hand_landmarker.task")
                .build()

            val options = HandLandmarker.HandLandmarkerOptions.builder()
                .setBaseOptions(baseOptions)
                .setRunningMode(RunningMode.LIVE_STREAM)
                .setNumHands(2)
                .setMinHandDetectionConfidence(0.35f)
                .setMinTrackingConfidence(0.35f)
                .setMinHandPresenceConfidence(0.35f)
                .setResultListener { result: HandLandmarkerResult, _: MPImage ->
                    handleDetectionResult(result)
                }
                .build()

            handLandmarker = HandLandmarker.createFromOptions(this, options)
            Log.d(TAG, "MediaPipe HandLandmarker initialized on device")
        } catch (e: Exception) {
            Log.e(TAG, "Error initializing MediaPipe: ${e.message}")
        }
    }

    private fun handleDetectionResult(result: HandLandmarkerResult) {
        val landmarksList = result.landmarks()
        if (landmarksList.isNotEmpty()) {
            val primaryHand = landmarksList[0]
            val action = gestureDetector?.processLandmarks(primaryHand)
            action?.let { executeGesture(it) }
        }
    }

    private fun executeGesture(action: GestureAction) {
        when (action) {
            is GestureAction.Tap -> {
                Log.d(TAG, "Dispatching Tap at (${action.x}, ${action.y})")
                val path = Path().apply { moveTo(action.x, action.y) }
                val stroke = GestureDescription.StrokeDescription(path, 0, 40)
                val gesture = GestureDescription.Builder().addStroke(stroke).build()
                dispatchGesture(gesture, null, null)
            }
            is GestureAction.Swipe -> {
                Log.d(TAG, "Dispatching Swipe from (${action.x1}, ${action.y1}) to (${action.x2}, ${action.y2})")
                val path = Path().apply {
                    moveTo(action.x1, action.y1)
                    lineTo(action.x2, action.y2)
                }
                val stroke = GestureDescription.StrokeDescription(path, 0, action.durationMs)
                val gesture = GestureDescription.Builder().addStroke(stroke).build()
                dispatchGesture(gesture, null, null)
            }
            is GestureAction.Back -> {
                Log.d(TAG, "Performing Global Back")
                performGlobalAction(GLOBAL_ACTION_BACK)
            }
            is GestureAction.Home -> {
                Log.d(TAG, "Performing Global Home")
                performGlobalAction(GLOBAL_ACTION_HOME)
            }
        }
    }

    private fun showFloatingBubble() {
        windowManager = getSystemService(WINDOW_SERVICE) as WindowManager
        val layoutType = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        } else {
            WindowManager.LayoutParams.TYPE_PHONE
        }

        val params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            layoutType,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = 20
            y = 120
        }

        overlayView = LayoutInflater.from(this).inflate(R.layout.overlay_bubble, null)
        windowManager?.addView(overlayView, params)
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {}
    override fun onInterrupt() {}

    override fun onDestroy() {
        super.onDestroy()
        instance = null
        overlayView?.let { windowManager?.removeView(it) }
        handLandmarker?.close()
        cameraExecutor.shutdown()
    }
}

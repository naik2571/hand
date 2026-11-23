package com.hand.airtouch

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Bitmap
import android.graphics.Matrix
import android.graphics.Path
import android.graphics.PixelFormat
import android.os.Build
import android.os.SystemClock
import android.util.DisplayMetrics
import android.util.Log
import android.view.Gravity
import android.view.LayoutInflater
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import android.widget.TextView
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.LifecycleRegistry
import com.google.mediapipe.framework.image.BitmapImageBuilder
import com.google.mediapipe.framework.image.MPImage
import com.google.mediapipe.tasks.core.BaseOptions
import com.google.mediapipe.tasks.vision.core.RunningMode
import com.google.mediapipe.tasks.vision.handlandmarker.HandLandmarker
import com.google.mediapipe.tasks.vision.handlandmarker.HandLandmarkerResult
import java.util.concurrent.Executors

class AirTouchAccessibilityService : AccessibilityService(), LifecycleOwner {

    private val TAG = "AirTouchService"
    private val lifecycleRegistry = LifecycleRegistry(this)
    override val lifecycle: Lifecycle get() = lifecycleRegistry

    private var windowManager: WindowManager? = null
    private var overlayView: View? = null
    private var gestureDetector: HandGestureDetector? = null
    private var handLandmarker: HandLandmarker? = null
    private val cameraExecutor = Executors.newSingleThreadExecutor()
    private var lastTimestampMs = 0L
    private var isCameraBound = false

    companion object {
        var instance: AirTouchAccessibilityService? = null
    }

    override fun onCreate() {
        super.onCreate()
        lifecycleRegistry.currentState = Lifecycle.State.CREATED
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        lifecycleRegistry.currentState = Lifecycle.State.STARTED
        lifecycleRegistry.currentState = Lifecycle.State.RESUMED
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
                .setNumHands(1)
                .setMinHandDetectionConfidence(0.35f)
                .setMinTrackingConfidence(0.35f)
                .setMinHandPresenceConfidence(0.35f)
                .setResultListener { result: HandLandmarkerResult, _: MPImage ->
                    handleDetectionResult(result)
                }
                .build()

            handLandmarker = HandLandmarker.createFromOptions(this, options)
            Log.d(TAG, "MediaPipe HandLandmarker initialized in Accessibility Service")
        } catch (e: Exception) {
            Log.e(TAG, "Error initializing MediaPipe in Service: ${e.message}")
        }
    }

    fun startBackgroundCameraTracking() {
        if (isCameraBound) return
        val bubblePreview = overlayView?.findViewById<PreviewView>(R.id.bubble_camera_preview) ?: return

        val cameraProviderFuture = ProcessCameraProvider.getInstance(this)
        cameraProviderFuture.addListener({
            try {
                val cameraProvider = cameraProviderFuture.get()
                val preview = Preview.Builder().build().also {
                    it.setSurfaceProvider(bubblePreview.surfaceProvider)
                }

                val imageAnalysis = ImageAnalysis.Builder()
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_RGBA_8888)
                    .build()

                imageAnalysis.setAnalyzer(cameraExecutor) { imageProxy ->
                    try {
                        val rotationDegrees = imageProxy.imageInfo.rotationDegrees
                        val bitmap = imageProxy.toBitmap()

                        val matrix = Matrix().apply {
                            postRotate(rotationDegrees.toFloat())
                            postScale(-1f, 1f)
                        }
                        val rotatedBitmap = Bitmap.createBitmap(bitmap, 0, 0, bitmap.width, bitmap.height, matrix, true)
                        val mpImage = BitmapImageBuilder(rotatedBitmap).build()

                        val nowMs = SystemClock.uptimeMillis()
                        val frameTime = if (nowMs <= lastTimestampMs) lastTimestampMs + 1 else nowMs
                        lastTimestampMs = frameTime

                        handLandmarker?.detectAsync(mpImage, frameTime)
                    } catch (e: Exception) {
                        Log.e(TAG, "Background frame error: ${e.message}")
                    } finally {
                        imageProxy.close()
                    }
                }

                val cameraSelector = CameraSelector.DEFAULT_FRONT_CAMERA
                cameraProvider.unbindAll()
                cameraProvider.bindToLifecycle(this, cameraSelector, preview, imageAnalysis)
                isCameraBound = true
                Log.d(TAG, "Background camera bound to AccessibilityService successfully")
            } catch (e: Exception) {
                Log.e(TAG, "Failed to start background camera: ${e.message}")
            }
        }, ContextCompat.getMainExecutor(this))
    }

    fun stopBackgroundCameraTracking() {
        if (!isCameraBound) return
        try {
            val cameraProvider = ProcessCameraProvider.getInstance(this).get()
            cameraProvider.unbindAll()
            isCameraBound = false
            Log.d(TAG, "Background camera unbound from AccessibilityService")
        } catch (e: Exception) {
            Log.e(TAG, "Error stopping background camera: ${e.message}")
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

    fun executeGesture(action: GestureAction) {
        when (action) {
            is GestureAction.Tap -> {
                Log.d(TAG, "Dispatching Tap at (${action.x}, ${action.y})")
                val path = Path().apply {
                    moveTo(action.x, action.y)
                    lineTo(action.x + 1f, action.y + 1f) // Required for non-empty stroke
                }
                val stroke = GestureDescription.StrokeDescription(path, 0, 80)
                val gesture = GestureDescription.Builder().addStroke(stroke).build()
                val ok = dispatchGesture(gesture, object : AccessibilityService.GestureResultCallback() {
                    override fun onCompleted(gestureDescription: GestureDescription?) {
                        Log.d(TAG, "TAP gesture completed successfully!")
                        flashBadge("TAP!")
                    }
                    override fun onCancelled(gestureDescription: GestureDescription?) {
                        Log.e(TAG, "TAP gesture cancelled by system")
                    }
                }, null)
                Log.d(TAG, "dispatchGesture(Tap) returned: $ok")
            }
            is GestureAction.Swipe -> {
                Log.d(TAG, "Dispatching Swipe from (${action.x1}, ${action.y1}) to (${action.x2}, ${action.y2})")
                val path = Path().apply {
                    moveTo(action.x1, action.y1)
                    lineTo(action.x2, action.y2)
                }
                val stroke = GestureDescription.StrokeDescription(path, 0, 320)
                val gesture = GestureDescription.Builder().addStroke(stroke).build()
                val ok = dispatchGesture(gesture, object : AccessibilityService.GestureResultCallback() {
                    override fun onCompleted(gestureDescription: GestureDescription?) {
                        Log.d(TAG, "SWIPE gesture completed successfully!")
                        flashBadge("SWIPE!")
                    }
                    override fun onCancelled(gestureDescription: GestureDescription?) {
                        Log.e(TAG, "SWIPE gesture cancelled by system")
                    }
                }, null)
                Log.d(TAG, "dispatchGesture(Swipe) returned: $ok")
            }
            is GestureAction.Back -> {
                Log.d(TAG, "Performing Global Back")
                performGlobalAction(GLOBAL_ACTION_BACK)
                flashBadge("BACK")
            }
            is GestureAction.Home -> {
                Log.d(TAG, "Performing Global Home")
                performGlobalAction(GLOBAL_ACTION_HOME)
                flashBadge("HOME")
            }
        }
    }

    private fun flashBadge(text: String) {
        overlayView?.post {
            val badge = overlayView?.findViewById<TextView>(R.id.bubble_badge)
            badge?.text = text
            badge?.setBackgroundColor(0xCC00E5FF.toInt())
            badge?.postDelayed({
                badge.text = "AIRTOUCH"
                badge.setBackgroundColor(0x99000000.toInt())
            }, 600)
        }
    }

    private fun showFloatingBubble() {
        try {
            windowManager = getSystemService(WINDOW_SERVICE) as WindowManager
            val layoutType = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            } else {
                @Suppress("DEPRECATION")
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
                x = 30
                y = 150
            }

            overlayView = LayoutInflater.from(this).inflate(R.layout.overlay_bubble, null)

            // Drag floating bubble anywhere
            overlayView?.setOnTouchListener(object : View.OnTouchListener {
                private var initialX = 0
                private var initialY = 0
                private var initialTouchX = 0f
                private var initialTouchY = 0f

                override fun onTouch(v: View, event: MotionEvent): Boolean {
                    when (event.action) {
                        MotionEvent.ACTION_DOWN -> {
                            initialX = params.x
                            initialY = params.y
                            initialTouchX = event.rawX
                            initialTouchY = event.rawY
                            return true
                        }
                        MotionEvent.ACTION_MOVE -> {
                            params.x = initialX + (event.rawX - initialTouchX).toInt()
                            params.y = initialY + (event.rawY - initialTouchY).toInt()
                            windowManager?.updateViewLayout(overlayView, params)
                            return true
                        }
                    }
                    return false
                }
            })

            windowManager?.addView(overlayView, params)
            Log.d(TAG, "Floating overlay bubble added to WindowManager")
        } catch (e: Exception) {
            Log.e(TAG, "Failed to show overlay bubble: ${e.message}")
        }
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {}
    override fun onInterrupt() {}

    override fun onDestroy() {
        super.onDestroy()
        instance = null
        lifecycleRegistry.currentState = Lifecycle.State.DESTROYED
        overlayView?.let { windowManager?.removeView(it) }
        handLandmarker?.close()
        cameraExecutor.shutdown()
    }
}

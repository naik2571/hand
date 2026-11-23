package com.hand.airtouch

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.Matrix
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.SystemClock
import android.provider.Settings
import android.util.DisplayMetrics
import android.util.Log
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.google.mediapipe.framework.image.BitmapImageBuilder
import com.google.mediapipe.framework.image.MPImage
import com.google.mediapipe.tasks.core.BaseOptions
import com.google.mediapipe.tasks.vision.core.RunningMode
import com.google.mediapipe.tasks.vision.handlandmarker.HandLandmarker
import com.google.mediapipe.tasks.vision.handlandmarker.HandLandmarkerResult
import java.util.concurrent.Executors

class MainActivity : AppCompatActivity() {

    private val TAG = "AirTouchMainActivity"
    private val CAMERA_REQ_CODE = 101

    private lateinit var btnCam: Button
    private lateinit var btnOverlay: Button
    private lateinit var btnAccess: Button
    private lateinit var btnTestTarget: Button
    private lateinit var tvStatus: TextView
    private lateinit var previewView: PreviewView

    private var gestureDetector: HandGestureDetector? = null
    private var handLandmarker: HandLandmarker? = null
    private val cameraExecutor = Executors.newSingleThreadExecutor()
    private var lastTimestampMs = 0L
    private var isCameraRunning = false
    private var testTapCount = 0

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        btnCam = findViewById(R.id.btn_camera_permission)
        btnOverlay = findViewById(R.id.btn_overlay_permission)
        btnAccess = findViewById(R.id.btn_accessibility_permission)
        btnTestTarget = findViewById(R.id.btn_test_target)
        tvStatus = findViewById(R.id.tv_status)
        previewView = findViewById(R.id.camera_preview)

        val metrics = DisplayMetrics()
        windowManager.defaultDisplay.getRealMetrics(metrics)
        gestureDetector = HandGestureDetector(metrics.widthPixels, metrics.heightPixels)

        btnTestTarget.setOnClickListener {
            testTapCount++
            btnTestTarget.text = "AIR-TAP SUCCESS! (Tapped: $testTapCount)"
            btnTestTarget.setBackgroundColor(Color.parseColor("#15803D")) // Green flash
            btnTestTarget.postDelayed({
                btnTestTarget.setBackgroundColor(Color.parseColor("#8B5CF6"))
            }, 500)
        }

        btnCam.setOnClickListener {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
                ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.CAMERA), CAMERA_REQ_CODE)
            } else {
                Toast.makeText(this, "Camera permission already granted!", Toast.LENGTH_SHORT).show()
                startCamera()
            }
        }

        btnOverlay.setOnClickListener {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && !Settings.canDrawOverlays(this)) {
                val intent = Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName"))
                startActivity(intent)
            } else {
                Toast.makeText(this, "Floating Overlay permission already enabled!", Toast.LENGTH_SHORT).show()
            }
        }

        btnAccess.setOnClickListener {
            val intent = Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)
            startActivity(intent)
            Toast.makeText(this, "Find 'AirTouch' and toggle it ON", Toast.LENGTH_LONG).show()
        }

        initMediaPipe()
    }

    override fun onResume() {
        super.onResume()
        updatePermissionButtons()

        // Yield camera from background service to MainActivity
        AirTouchAccessibilityService.instance?.stopBackgroundCameraTracking()

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            if (!isCameraRunning) {
                startCamera()
            }
        }
    }

    override fun onPause() {
        super.onPause()
        if (isCameraRunning) {
            try {
                ProcessCameraProvider.getInstance(this).get().unbindAll()
                isCameraRunning = false
            } catch (e: Exception) {
                Log.e(TAG, "Error unbinding camera on pause: ${e.message}")
            }
        }
        // Handover camera to background accessibility service
        AirTouchAccessibilityService.instance?.startBackgroundCameraTracking()
    }

    private fun updatePermissionButtons() {
        val hasCam = ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
        if (hasCam) {
            btnCam.text = "1. Camera Permission: GRANTED (OK)"
            btnCam.setBackgroundColor(Color.parseColor("#15803D")) // Green
        } else {
            btnCam.text = "1. Grant Camera Permission"
            btnCam.setBackgroundColor(Color.parseColor("#2563EB")) // Blue
        }

        val hasOverlay = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) Settings.canDrawOverlays(this) else true
        if (hasOverlay) {
            btnOverlay.text = "2. Floating Overlay: ENABLED (OK)"
            btnOverlay.setBackgroundColor(Color.parseColor("#15803D"))
        } else {
            btnOverlay.text = "2. Enable Floating Overlay"
            btnOverlay.setBackgroundColor(Color.parseColor("#2563EB"))
        }

        val isAccessRunning = AirTouchAccessibilityService.instance != null
        if (isAccessRunning) {
            btnAccess.text = "3. Accessibility Service: ACTIVE (OK)"
            btnAccess.setBackgroundColor(Color.parseColor("#15803D"))
        } else {
            btnAccess.text = "3. Enable Accessibility Service"
            btnAccess.setBackgroundColor(Color.parseColor("#2563EB"))
        }
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
            Log.d(TAG, "MediaPipe HandLandmarker initialized successfully in MainActivity")
        } catch (e: Exception) {
            Log.e(TAG, "Failed to initialize MediaPipe: ${e.message}", e)
            tvStatus.text = "MediaPipe Error: ${e.message}"
            tvStatus.setTextColor(Color.RED)
        }
    }

    private fun startCamera() {
        val cameraProviderFuture = ProcessCameraProvider.getInstance(this)
        cameraProviderFuture.addListener({
            try {
                val cameraProvider = cameraProviderFuture.get()

                val preview = Preview.Builder().build().also {
                    it.setSurfaceProvider(previewView.surfaceProvider)
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
                            postScale(-1f, 1f) // Mirror horizontally for front camera
                        }
                        val rotatedBitmap = Bitmap.createBitmap(bitmap, 0, 0, bitmap.width, bitmap.height, matrix, true)
                        val mpImage = BitmapImageBuilder(rotatedBitmap).build()

                        val nowMs = SystemClock.uptimeMillis()
                        val frameTime = if (nowMs <= lastTimestampMs) lastTimestampMs + 1 else nowMs
                        lastTimestampMs = frameTime

                        handLandmarker?.detectAsync(mpImage, frameTime)
                    } catch (e: Exception) {
                        Log.e(TAG, "Frame analysis error: ${e.message}")
                    } finally {
                        imageProxy.close()
                    }
                }

                val cameraSelector = CameraSelector.DEFAULT_FRONT_CAMERA
                cameraProvider.unbindAll()
                cameraProvider.bindToLifecycle(this, cameraSelector, preview, imageAnalysis)
                isCameraRunning = true
                tvStatus.text = "Camera Active! Show your hand to the front camera."
                tvStatus.setTextColor(Color.parseColor("#38BDF8"))
            } catch (e: Exception) {
                Log.e(TAG, "Camera startup failed: ${e.message}", e)
                tvStatus.text = "Camera Error: ${e.message}"
                tvStatus.setTextColor(Color.RED)
            }
        }, ContextCompat.getMainExecutor(this))
    }

    private fun handleDetectionResult(result: HandLandmarkerResult) {
        val landmarksList = result.landmarks()
        runOnUiThread {
            if (landmarksList.isNotEmpty()) {
                val primaryHand = landmarksList[0]
                val action = gestureDetector?.processLandmarks(primaryHand)
                val stateText = gestureDetector?.lastDetectedState ?: "TRACKING"

                tvStatus.text = "HAND DETECTED!\nState: $stateText"
                tvStatus.setTextColor(Color.parseColor("#4ADE80")) // Bright Green

                action?.let { act ->
                    tvStatus.text = "GESTURE TRIGGERED:\n$act"
                    tvStatus.setTextColor(Color.parseColor("#FACC15")) // Yellow

                    val service = AirTouchAccessibilityService.instance
                    if (service != null) {
                        service.executeGesture(act)
                    } else {
                        Toast.makeText(this@MainActivity, "Gesture: $act\n(Step 3 needed to click outside)", Toast.LENGTH_SHORT).show()
                    }
                }
            } else {
                tvStatus.text = "No Hand Detected\nHold your hand in front of the camera"
                tvStatus.setTextColor(Color.parseColor("#94A3B8")) // Slate Gray
            }
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == CAMERA_REQ_CODE && grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            startCamera()
            updatePermissionButtons()
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        handLandmarker?.close()
        cameraExecutor.shutdown()
    }
}

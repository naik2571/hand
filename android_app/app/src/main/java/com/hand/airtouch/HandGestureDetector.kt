package com.hand.airtouch

import android.os.SystemClock
import com.google.mediapipe.tasks.components.containers.NormalizedLandmark
import kotlin.math.hypot

sealed class GestureAction {
    data class Tap(val x: Float, val y: Float) : GestureAction()
    data class Swipe(val x1: Float, val y1: Float, val x2: Float, val y2: Float, val durationMs: Long) : GestureAction()
    object Back : GestureAction()
    object Home : GestureAction()
}

class HandGestureDetector(
    private val screenWidth: Int,
    private val screenHeight: Int
) {
    private var lastGestureTime = 0L
    private var lastScrollY = 0f
    private var isScrolling = false
    private var lastWristX: Float? = null
    private var lastWristTime = 0L

    // Anti-shake anchor
    private var clickAnchorPos: Pair<Float, Float>? = null
    private var tapState = "IDLE"
    private var tapStartTime = 0L

    private fun dist(p1: NormalizedLandmark, p2: NormalizedLandmark): Float {
        return hypot(p1.x() - p2.x(), p1.y() - p2.y())
    }

    fun processLandmarks(landmarks: List<NormalizedLandmark>): GestureAction? {
        val now = SystemClock.uptimeMillis()
        if (landmarks.size < 21) return null

        val wrist = landmarks[0]
        val thumbTip = landmarks[4]
        val indexPip = landmarks[6]
        val indexTip = landmarks[8]
        val middleTip = landmarks[12]
        val ringTip = landmarks[16]
        val pinkyTip = landmarks[20]

        val handScale = maxOf(0.05f, dist(wrist, landmarks[9]))

        // Finger extensions
        val indexExtended = dist(indexTip, wrist) > dist(indexPip, wrist) + 0.02f
        val middleExtended = dist(middleTip, wrist) > dist(landmarks[10], wrist) + 0.02f
        val ringExtended = dist(ringTip, wrist) > dist(landmarks[14], wrist) + 0.02f
        val pinkyExtended = dist(pinkyTip, wrist) > dist(landmarks[18], wrist) + 0.02f

        val isOpenPalm = indexExtended && middleExtended && ringExtended && pinkyExtended
        val isTwoFinger = indexExtended && middleExtended && !ringExtended && !pinkyExtended
        val isFist = !indexExtended && !middleExtended && !ringExtended && !pinkyExtended

        // Map index tip into screen space (with front camera selfie mirror)
        // Note: CameraX front camera is mirrored, so normX = 1 - indexTip.x() or indexTip.x()
        val mappedX = (1.0f - indexTip.x()).coerceIn(0f, 1f) * screenWidth
        val mappedY = indexTip.y().coerceIn(0f, 1f) * screenHeight

        // -------------------------------------------------------------
        // 1. Air Swing: Horizontal Flick Left / Right for Tabs/Screens
        // -------------------------------------------------------------
        lastWristX?.let { prevX ->
            val dt = (now - lastWristTime) / 1000f
            if (dt > 0.01f) {
                val vx = (wrist.x() - prevX) / dt
                if (Math.abs(vx) > 1.2f && (now - lastGestureTime > 600)) {
                    val midY = screenHeight / 2f
                    lastGestureTime = now
                    if (vx > 1.2f) {
                        return GestureAction.Swipe(
                            screenWidth * 0.2f, midY,
                            screenWidth * 0.8f, midY,
                            160
                        )
                    } else {
                        return GestureAction.Swipe(
                            screenWidth * 0.8f, midY,
                            screenWidth * 0.2f, midY,
                            160
                        )
                    }
                }
            }
        }
        lastWristX = wrist.x()
        lastWristTime = now

        // -------------------------------------------------------------
        // 2. Open Palm Navigation (Back & Home)
        // -------------------------------------------------------------
        if (isOpenPalm && (now - lastGestureTime > 800)) {
            if (indexTip.x() < 0.22f) {
                lastGestureTime = now
                return GestureAction.Back
            } else if (indexTip.y() < 0.20f) {
                lastGestureTime = now
                return GestureAction.Home
            }
        }

        // -------------------------------------------------------------
        // 3. Two-Finger Reels / Shorts Vertical Swipe
        // -------------------------------------------------------------
        if (isTwoFinger) {
            val currY = (indexTip.y() + middleTip.y()) / 2f
            if (!isScrolling) {
                isScrolling = true
                lastScrollY = currY
            } else {
                val dy = currY - lastScrollY
                if (Math.abs(dy) > 0.12f && (now - lastGestureTime > 500)) {
                    val cx = screenWidth / 2f
                    lastScrollY = currY
                    lastGestureTime = now
                    return if (dy < 0) {
                        // Swipe UP -> Next Reel
                        GestureAction.Swipe(cx, screenHeight * 0.75f, cx, screenHeight * 0.25f, 200)
                    } else {
                        // Swipe DOWN -> Prev Reel
                        GestureAction.Swipe(cx, screenHeight * 0.25f, cx, screenHeight * 0.75f, 200)
                    }
                }
            }
            return null
        } else {
            isScrolling = false
        }

        // -------------------------------------------------------------
        // 4. Air-Tap Left Click / Phone Touch with Anchor
        // -------------------------------------------------------------
        val indexDip = (indexPip.y() - indexTip.y()) / handScale
        val pinchDist = dist(thumbTip, indexTip) / handScale
        val isDipping = (indexDip < 0.10f) || (pinchDist < 0.28f)

        if (isDipping) {
            if (clickAnchorPos == null) {
                clickAnchorPos = Pair(mappedX, mappedY)
            }
            if (tapState == "IDLE") {
                tapState = "DIPPED"
                tapStartTime = now
            }
        } else {
            if (tapState == "DIPPED") {
                val dipDur = now - tapStartTime
                if (dipDur in 40..350 && (now - lastGestureTime > 300)) {
                    val targetPos = clickAnchorPos ?: Pair(mappedX, mappedY)
                    lastGestureTime = now
                    tapState = "IDLE"
                    clickAnchorPos = null
                    return GestureAction.Tap(targetPos.first, targetPos.second)
                }
                tapState = "IDLE"
                clickAnchorPos = null
            }
        }

        return null
    }
}

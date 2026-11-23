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
    var lastDetectedState: String = "NO HAND"
        private set

    private var lastGestureTime = 0L
    private var lastScrollY = 0f
    private var isScrolling = false
    private var lastWristX: Float? = null
    private var lastWristTime = 0L

    // Anti-shake anchor for air tap
    private var clickAnchorPos: Pair<Float, Float>? = null
    private var tapState = "IDLE"
    private var tapStartTime = 0L

    private fun dist(p1: NormalizedLandmark, p2: NormalizedLandmark): Float {
        return hypot(p1.x() - p2.x(), p1.y() - p2.y())
    }

    fun processLandmarks(landmarks: List<NormalizedLandmark>): GestureAction? {
        val now = SystemClock.uptimeMillis()
        if (landmarks.size < 21) {
            lastDetectedState = "NO HAND"
            return null
        }

        val wrist = landmarks[0]
        val thumbTip = landmarks[4]
        val indexMcp = landmarks[5]
        val indexPip = landmarks[6]
        val indexTip = landmarks[8]
        val middleMcp = landmarks[9]
        val middlePip = landmarks[10]
        val middleTip = landmarks[12]
        val ringTip = landmarks[16]
        val pinkyTip = landmarks[20]

        val handScale = maxOf(0.08f, dist(wrist, middleMcp))

        // Finger extensions relative to wrist and knuckles
        val indexExtended = dist(indexTip, wrist) > dist(indexPip, wrist) + 0.02f
        val middleExtended = dist(middleTip, wrist) > dist(middlePip, wrist) + 0.02f
        val ringExtended = dist(ringTip, wrist) > dist(landmarks[14], wrist) + 0.02f
        val pinkyExtended = dist(pinkyTip, wrist) > dist(landmarks[18], wrist) + 0.02f

        val isOpenPalm = indexExtended && middleExtended && ringExtended && pinkyExtended
        val isTwoFinger = indexExtended && middleExtended && !ringExtended && !pinkyExtended
        val isFist = !indexExtended && !middleExtended && !ringExtended && !pinkyExtended

        // Map index tip into screen space
        val mappedX = indexTip.x().coerceIn(0f, 1f) * screenWidth
        val mappedY = indexTip.y().coerceIn(0f, 1f) * screenHeight

        // -------------------------------------------------------------
        // 1. Air Clutch / Closed Fist (Freezes and resets)
        // -------------------------------------------------------------
        if (isFist) {
            lastDetectedState = "FIST (IDLE CLUTCH)"
            tapState = "IDLE"
            clickAnchorPos = null
            isScrolling = false
            return null
        }

        // -------------------------------------------------------------
        // 2. Open Palm Global Navigation (Back & Home)
        // -------------------------------------------------------------
        if (isOpenPalm) {
            lastDetectedState = "OPEN PALM"
            if (now - lastGestureTime > 800) {
                if (indexTip.x() < 0.20f) {
                    lastGestureTime = now
                    lastDetectedState = "ACTION: BACK"
                    return GestureAction.Back
                } else if (indexTip.y() < 0.20f) {
                    lastGestureTime = now
                    lastDetectedState = "ACTION: HOME"
                    return GestureAction.Home
                }
            }
        }

        // -------------------------------------------------------------
        // 3. Air Swing (Fast Horizontal Wrist Flick)
        // -------------------------------------------------------------
        lastWristX?.let { prevX ->
            val dt = (now - lastWristTime) / 1000f
            if (dt > 0.01f) {
                val vx = (wrist.x() - prevX) / dt
                if (Math.abs(vx) > 1.2f && (now - lastGestureTime > 600)) {
                    val midY = screenHeight / 2f
                    lastGestureTime = now
                    if (vx > 1.2f) {
                        lastDetectedState = "ACTION: SWIPE RIGHT"
                        return GestureAction.Swipe(
                            screenWidth * 0.2f, midY,
                            screenWidth * 0.8f, midY,
                            160
                        )
                    } else {
                        lastDetectedState = "ACTION: SWIPE LEFT"
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
        // 4. Two-Finger Reels / Shorts Vertical Swipe
        // -------------------------------------------------------------
        if (isTwoFinger) {
            lastDetectedState = "TWO FINGERS (SCROLL MODE)"
            val currY = (indexTip.y() + middleTip.y()) / 2f
            if (!isScrolling) {
                isScrolling = true
                lastScrollY = currY
            } else {
                val dy = currY - lastScrollY
                if (Math.abs(dy) > 0.08f && (now - lastGestureTime > 450)) {
                    val cx = screenWidth / 2f
                    lastScrollY = currY
                    lastGestureTime = now
                    return if (dy < 0) {
                        lastDetectedState = "ACTION: NEXT REEL [SWIPE UP]"
                        GestureAction.Swipe(cx, screenHeight * 0.75f, cx, screenHeight * 0.25f, 220)
                    } else {
                        lastDetectedState = "ACTION: PREV REEL [SWIPE DOWN]"
                        GestureAction.Swipe(cx, screenHeight * 0.25f, cx, screenHeight * 0.75f, 220)
                    }
                }
            }
            return null
        } else {
            isScrolling = false
        }

        // -------------------------------------------------------------
        // 5. Air-Tap Left Click / Phone Touch with Anchor
        // Dual trigger: Thumb+Index pinch (<0.34) OR Index dip/flex
        // -------------------------------------------------------------
        val pinchDist = dist(thumbTip, indexTip) / handScale
        val indexDipY = (indexPip.y() - indexTip.y()) / handScale
        val indexFlex = dist(indexTip, indexMcp) / handScale

        val isPinched = pinchDist < 0.34f
        val isTapped = (indexDipY < 0.16f || indexFlex < 0.58f) && !middleExtended
        val isDipping = isPinched || isTapped

        if (isDipping) {
            lastDetectedState = if (isPinched) "PINCHING THUMB+INDEX" else "INDEX DIPPING"
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
                if (dipDur in 40..550 && (now - lastGestureTime > 300)) {
                    val targetPos = clickAnchorPos ?: Pair(mappedX, mappedY)
                    lastGestureTime = now
                    tapState = "IDLE"
                    clickAnchorPos = null
                    lastDetectedState = "ACTION: AIR-TAP (${targetPos.first.toInt()}, ${targetPos.second.toInt()})"
                    return GestureAction.Tap(targetPos.first, targetPos.second)
                }
                tapState = "IDLE"
                clickAnchorPos = null
            } else {
                lastDetectedState = "AIMING (TRACKING 5/5 FINGERS)"
            }
        }

        return null
    }
}

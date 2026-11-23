package com.hand.airtouch

import android.os.SystemClock
import com.google.mediapipe.tasks.components.containers.NormalizedLandmark
import kotlin.math.hypot

sealed class GestureAction {
    data class Tap(val x: Float, val y: Float) : GestureAction()
    data class Swipe(val x1: Float, val y1: Float, val x2: Float, val y2: Float, val durationMs: Long) : GestureAction()
    object Back : GestureAction()
    object Home : GestureAction()
    object Recents : GestureAction()
    object Notifications : GestureAction()
}

class HandGestureDetector(
    private val screenWidth: Int,
    private val screenHeight: Int
) {
    var lastDetectedState: String = "NO HAND"
        private set

    var currentPointerX: Float = screenWidth / 2f
        private set
    var currentPointerY: Float = screenHeight / 2f
        private set
    var isDippingOrPinching: Boolean = false
        private set
    var isHandPresent: Boolean = false
        private set

    private var smoothX: Float = screenWidth / 2f
    private var smoothY: Float = screenHeight / 2f

    private var lastGestureTime = 0L
    private var isScrolling = false
    private var lastWristX: Float? = null
    private var lastWristTime = 0L

    // Two-finger scroll & tab anti-rebound engine
    private var lastTwoFingerX: Float? = null
    private var lastTwoFingerY: Float? = null
    private var lastTwoFingerTime: Long = 0L
    private var strokeStartX: Float = 0f
    private var strokeStartY: Float = 0f
    private var strokeStartTime: Long = 0L
    private var lastScrollDirection: String? = null // "UP", "DOWN", "LEFT", "RIGHT"
    private var lastScrollActionTime: Long = 0L
    private var isScrollArmed: Boolean = true

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
            isHandPresent = false
            isDippingOrPinching = false
            lastDetectedState = "NO HAND"
            return null
        }
        isHandPresent = true

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

        // Active 70% boundary mapping with smoothing for steady pointer control
        val normX = ((indexTip.x() - 0.15f) / 0.70f).coerceIn(0f, 1f)
        val normY = ((indexTip.y() - 0.15f) / 0.70f).coerceIn(0f, 1f)
        val rawMappedX = normX * screenWidth
        val rawMappedY = normY * screenHeight

        // Smooth cursor translation (removes physiological tremor)
        smoothX += 0.35f * (rawMappedX - smoothX)
        smoothY += 0.35f * (rawMappedY - smoothY)
        currentPointerX = smoothX
        currentPointerY = smoothY

        // -------------------------------------------------------------
        // 1. Air Clutch / Closed Fist (Freezes pointer and resets)
        // -------------------------------------------------------------
        if (isFist) {
            lastDetectedState = "FIST (AIR CLUTCH - FROZEN)"
            tapState = "IDLE"
            clickAnchorPos = null
            isScrolling = false
            isDippingOrPinching = false
            lastTwoFingerX = null
            lastTwoFingerY = null
            lastScrollDirection = null
            isScrollArmed = true
            return null
        }

        // -------------------------------------------------------------
        // 2. Open Palm Global Navigation (Back, Home, Recents, Notifications)
        // -------------------------------------------------------------
        if (isOpenPalm) {
            lastDetectedState = "OPEN PALM"
            isDippingOrPinching = false
            if (now - lastGestureTime > 800) {
                if (indexTip.x() < 0.20f) {
                    lastGestureTime = now
                    lastDetectedState = "ACTION: BACK"
                    return GestureAction.Back
                } else if (indexTip.x() > 0.80f) {
                    lastGestureTime = now
                    lastDetectedState = "ACTION: RECENTS (APP SWITCHER)"
                    return GestureAction.Recents
                } else if (indexTip.y() < 0.20f) {
                    lastGestureTime = now
                    lastDetectedState = "ACTION: HOME"
                    return GestureAction.Home
                } else if (indexTip.y() > 0.80f) {
                    lastGestureTime = now
                    lastDetectedState = "ACTION: NOTIFICATIONS"
                    return GestureAction.Notifications
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
        // 4. Two-Finger Reels / Shorts & Tab Switching (Option A - Directional Dominance)
        // -------------------------------------------------------------
        if (isTwoFinger) {
            lastDetectedState = "TWO FINGERS (SCROLL & TAB MODE)"
            isDippingOrPinching = false
            val currX = (indexTip.x() + middleTip.x()) / 2f
            val currY = (indexTip.y() + middleTip.y()) / 2f

            if (!isScrolling) {
                isScrolling = true
                strokeStartX = currX
                strokeStartY = currY
                strokeStartTime = now
                lastTwoFingerX = currX
                lastTwoFingerY = currY
                lastTwoFingerTime = now
                isScrollArmed = true
            } else {
                val dt = (now - lastTwoFingerTime) / 1000f
                if (dt > 0.008f) {
                    val prevX = lastTwoFingerX ?: currX
                    val prevY = lastTwoFingerY ?: currY
                    val vx = (currX - prevX) / dt // Horizontal velocity (units / sec)
                    val vy = (currY - prevY) / dt // Vertical velocity (units / sec)
                    val totalDx = currX - strokeStartX
                    val totalDy = currY - strokeStartY
                    val strokeDuration = now - strokeStartTime
                    val speed = hypot(vx, vy)

                    // Re-arm when hand settles or slows down
                    if (!isScrollArmed && speed < 0.45f) {
                        isScrollArmed = true
                        strokeStartX = currX
                        strokeStartY = currY
                        strokeStartTime = now
                    }

                    if (isScrollArmed) {
                        val absVx = Math.abs(vx)
                        val absVy = Math.abs(vy)
                        val absDx = Math.abs(totalDx)
                        val absDy = Math.abs(totalDy)

                        // 1. VERTICAL DOMINANCE (Reels & Shorts): absVy > 1.35 * absVx
                        if (absVy > 1.35f * absVx && absVy > 1.0f && absDy > 0.06f) {
                            val cx = screenWidth / 2f
                            if (vy < 0) {
                                // Flick UP -> NEXT REEL
                                val isReverseLocked = (lastScrollDirection == "DOWN") && (now - lastScrollActionTime < 1200L)
                                if (!isReverseLocked && (now - lastGestureTime > 350L)) {
                                    lastGestureTime = now
                                    lastScrollActionTime = now
                                    lastScrollDirection = "UP"
                                    isScrollArmed = false
                                    lastTwoFingerX = currX
                                    lastTwoFingerY = currY
                                    lastTwoFingerTime = now
                                    lastDetectedState = "ACTION: NEXT REEL [FLICK UP]"
                                    return GestureAction.Swipe(cx, screenHeight * 0.75f, cx, screenHeight * 0.25f, 220)
                                }
                            } else {
                                // Flick DOWN -> PREVIOUS REEL
                                val isReverseLocked = (lastScrollDirection == "UP") && (now - lastScrollActionTime < 1200L)
                                if (!isReverseLocked && (now - lastGestureTime > 350L)) {
                                    lastGestureTime = now
                                    lastScrollActionTime = now
                                    lastScrollDirection = "DOWN"
                                    isScrollArmed = false
                                    lastTwoFingerX = currX
                                    lastTwoFingerY = currY
                                    lastTwoFingerTime = now
                                    lastDetectedState = "ACTION: PREV REEL [FLICK DOWN]"
                                    return GestureAction.Swipe(cx, screenHeight * 0.25f, cx, screenHeight * 0.75f, 220)
                                }
                            }
                        }
                        // 2. HORIZONTAL DOMINANCE (Tabs, Photos & Stories): absVx > 1.35 * absVy
                        else if (absVx > 1.35f * absVy && absVx > 0.90f && absDx > 0.06f) {
                            val midY = screenHeight / 2f
                            if (vx < 0) {
                                // Push LEFT -> NEXT TAB / STORY (Simulates finger swiping right-to-left)
                                val isReverseLocked = (lastScrollDirection == "RIGHT") && (now - lastScrollActionTime < 1200L)
                                if (!isReverseLocked && (now - lastGestureTime > 350L)) {
                                    lastGestureTime = now
                                    lastScrollActionTime = now
                                    lastScrollDirection = "LEFT"
                                    isScrollArmed = false
                                    lastTwoFingerX = currX
                                    lastTwoFingerY = currY
                                    lastTwoFingerTime = now
                                    lastDetectedState = "ACTION: NEXT TAB [SWIPE LEFT]"
                                    return GestureAction.Swipe(screenWidth * 0.85f, midY, screenWidth * 0.15f, midY, 180)
                                }
                            } else {
                                // Push RIGHT -> PREV TAB / STORY (Simulates finger swiping left-to-right)
                                val isReverseLocked = (lastScrollDirection == "LEFT") && (now - lastScrollActionTime < 1200L)
                                if (!isReverseLocked && (now - lastGestureTime > 350L)) {
                                    lastGestureTime = now
                                    lastScrollActionTime = now
                                    lastScrollDirection = "RIGHT"
                                    isScrollArmed = false
                                    lastTwoFingerX = currX
                                    lastTwoFingerY = currY
                                    lastTwoFingerTime = now
                                    lastDetectedState = "ACTION: PREV TAB [SWIPE RIGHT]"
                                    return GestureAction.Swipe(screenWidth * 0.15f, midY, screenWidth * 0.85f, midY, 180)
                                }
                            }
                        }
                    }

                    // Reset anchor if stroke has expired (> 350ms) or reversed slowly without firing
                    if (strokeDuration > 350 || (totalDy > 0 && vy < -0.4f) || (totalDy < 0 && vy > 0.4f)
                        || (totalDx > 0 && vx < -0.4f) || (totalDx < 0 && vx > 0.4f)) {
                        strokeStartX = currX
                        strokeStartY = currY
                        strokeStartTime = now
                    }

                    lastTwoFingerX = currX
                    lastTwoFingerY = currY
                    lastTwoFingerTime = now
                }
            }
            return null
        } else {
            isScrolling = false
            lastTwoFingerX = null
            lastTwoFingerY = null
            isScrollArmed = true
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
        isDippingOrPinching = isDipping

        if (isDipping) {
            lastDetectedState = if (isPinched) "PINCHING THUMB+INDEX" else "INDEX DIPPING"
            if (clickAnchorPos == null) {
                clickAnchorPos = Pair(currentPointerX, currentPointerY)
            }
            if (tapState == "IDLE") {
                tapState = "DIPPED"
                tapStartTime = now
            }
        } else {
            if (tapState == "DIPPED") {
                val dipDur = now - tapStartTime
                if (dipDur in 40..550 && (now - lastGestureTime > 300)) {
                    val targetPos = clickAnchorPos ?: Pair(currentPointerX, currentPointerY)
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

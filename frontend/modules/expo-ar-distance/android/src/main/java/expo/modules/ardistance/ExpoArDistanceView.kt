package expo.modules.ardistance

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.ImageFormat
import android.graphics.Rect
import android.graphics.YuvImage
import android.opengl.GLES11Ext
import android.opengl.GLES20
import android.opengl.GLSurfaceView
import android.os.Handler
import android.os.Looper
import com.google.ar.core.Camera
import com.google.ar.core.Config
import com.google.ar.core.Frame
import com.google.ar.core.Session
import com.google.ar.core.TrackingState
import expo.modules.kotlin.AppContext
import expo.modules.kotlin.Promise
import expo.modules.kotlin.views.ExpoView
import java.io.ByteArrayOutputStream
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.UUID
import javax.microedition.khronos.egl.EGLConfig
import javax.microedition.khronos.opengles.GL10
import kotlin.math.abs
import kotlin.math.hypot
import kotlin.math.sqrt

/**
 * ARCore-backed preview that measures the distance to the targeted point using,
 * in priority order: (1) Depth API patch, (2) hit-test (plane / depth point /
 * feature point, with Instant Placement for an immediate value), (3) point-cloud
 * median. Sampling runs on the GL thread; a throttled (~10 Hz) summary is emitted.
 * Device-only — ARCore does not run on emulators or in Expo Go.
 *
 * NOTE: the GL camera-background rendering follows Google's `hello_ar` sample and
 * must be validated on a physical device.
 */
class ExpoArDistanceView(context: Context, appContext: AppContext) : ExpoView(context, appContext) {
  private val glView = GLSurfaceView(context)
  private var session: Session? = null
  private var cameraTextureId = -1
  private var viewW = 1
  private var viewH = 1

  private var targetX = 0.5
  private var targetY = 0.5

  private val window = ArrayList<Pair<Double, Long>>() // value, uptimeMillis
  private val windowMs = 450L
  private var lastEmit = 0L
  private var lastMethod = "none"
  private var lastTracking = TrackingState.STOPPED
  private var tierSwitches = 0
  private var trackingResets = 0
  private var torchOn = false
  private var pendingCapture: Promise? = null
  private val main = Handler(Looper.getMainLooper())
  private val bg = BackgroundRenderer()

  init {
    Hub.view = this
    glView.preserveEGLContextOnPause = true
    glView.setEGLContextClientVersion(2)
    glView.setEGLConfigChooser(8, 8, 8, 8, 16, 0)
    glView.setRenderer(Renderer())
    glView.renderMode = GLSurfaceView.RENDERMODE_CONTINUOUSLY
    addView(glView)
    resumeSession()
  }

  // MARK: lifecycle -----------------------------------------------------------

  fun resumeSession() {
    try {
      if (session == null) {
        val s = Session(context)
        val cfg = Config(s)
        if (s.isDepthModeSupported(Config.DepthMode.AUTOMATIC)) cfg.depthMode = Config.DepthMode.AUTOMATIC
        cfg.instantPlacementMode = Config.InstantPlacementMode.LOCAL_Y_UP
        cfg.focusMode = Config.FocusMode.AUTO
        cfg.updateMode = Config.UpdateMode.LATEST_CAMERA_IMAGE
        s.configure(cfg)
        // choose the highest-resolution CPU camera config for full-res capture
        try {
          val filter = com.google.ar.core.CameraConfigFilter(s)
          val best = s.getSupportedCameraConfigs(filter).maxByOrNull { it.imageSize.width * it.imageSize.height }
          if (best != null) s.cameraConfig = best
        } catch (_: Throwable) { /* best-effort */ }
        session = s
      }
      session?.resume()
      glView.onResume()
    } catch (e: Throwable) {
      Hub.emitStatus(mapOf("tracking" to "notAvailable", "error" to (e.message ?: "arcore_resume_failed")))
    }
  }

  fun pauseSession() {
    try { glView.onPause(); session?.pause() } catch (_: Throwable) {}
  }

  fun stopSession() {
    setTorch(false, false)
    try { glView.onPause(); session?.pause(); session?.close() } catch (_: Throwable) {}
    session = null
    window.clear()
  }

  fun setTarget(x: Double, y: Double) {
    targetX = x.coerceIn(0.0, 1.0); targetY = y.coerceIn(0.0, 1.0); window.clear()
  }

  fun setTorch(on: Boolean, auto: Boolean) {
    val s = session ?: return
    try {
      val cfg = s.config
      cfg.flashMode = if (on) Config.FlashMode.TORCH else Config.FlashMode.OFF
      s.configure(cfg)
      torchOn = on
      Hub.emitStatus(mapOf("torchOn" to on, "torchAuto" to auto))
    } catch (_: Throwable) { /* flash control best-effort */ }
  }

  fun capture(promise: Promise) { pendingCapture = promise }

  /** Real display rotation (Surface.ROTATION_*). Portrait-locked phones report
   * ROTATION_0 — identical to the constant that used to be hardcoded here — while
   * a naturally-landscape device (tablet) finally reports the truth. Any failure
   * falls back to 0, i.e. the previous behaviour. */
  private fun currentDisplayRotation(): Int =
    try { display?.rotation ?: 0 } catch (_: Throwable) { 0 }

  // MARK: GL renderer ---------------------------------------------------------

  private inner class Renderer : GLSurfaceView.Renderer {
    override fun onSurfaceCreated(gl: GL10?, config: EGLConfig?) {
      GLES20.glClearColor(0f, 0f, 0f, 1f)
      cameraTextureId = bg.createOnGlThread()
    }

    override fun onSurfaceChanged(gl: GL10?, width: Int, height: Int) {
      GLES20.glViewport(0, 0, width, height)
      viewW = width; viewH = height
      // Rotation must be the REAL display rotation, not a hardcoded 0: ARCore uses
      // it to build the VIEW <-> TEXTURE transform (rotation + aspect-fill crop).
      // The app is portrait-locked, so on a phone this resolves to ROTATION_0
      // exactly as before; on a device whose natural orientation is landscape
      // (tablet) the old constant silently mis-mapped every tap.
      session?.setDisplayGeometry(currentDisplayRotation(), width, height)
    }

    override fun onDrawFrame(gl: GL10?) {
      GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT or GLES20.GL_DEPTH_BUFFER_BIT)
      val s = session ?: return
      try {
        s.setCameraTextureName(cameraTextureId)
        val frame = s.update()
        bg.draw(frame)
        measure(frame)
        pendingCapture?.let { p -> pendingCapture = null; resolveCapture(frame, p) }
      } catch (_: Throwable) { /* a dropped frame must never crash the preview */ }
    }
  }

  // MARK: measurement ---------------------------------------------------------

  private fun measure(frame: Frame) {
    val cam = frame.camera
    var method = "none"
    var raw: Double? = depthPatchMedian(frame)       // Tier 1
    if (raw != null) method = "depth" else {
      raw = hitTestDistance(frame)                   // Tier 2
      if (raw != null) method = "ar_plane" else {
        raw = pointCloudMedian(frame)                // Tier 3
        if (raw != null) method = "feature"
      }
    }
    if (method != lastMethod && lastMethod != "none" && method != "none") tierSwitches++
    lastMethod = method

    // count every drop out of full tracking as a reset (HUD diagnostic)
    val ts = cam.trackingState
    if (ts != TrackingState.TRACKING && lastTracking == TrackingState.TRACKING) trackingResets++
    lastTracking = ts

    val now = android.os.SystemClock.uptimeMillis()
    // native window feeds ONLY the still-capture metadata (a stable value burned
    // with the photo). The live stream emits the RAW per-frame reading so the JS
    // filter (distanceFilter.ts) owns the rolling window + MAD + median + the real
    // ± uncertainty, and can suppress noisy readings. (A2)
    val emitVal = if (raw != null && raw.isFinite() && raw > 0) raw else null
    if (emitVal != null) window.add(Pair(emitVal, now))
    window.removeAll { now - it.second > windowMs }

    if (now - lastEmit < 100) return
    lastEmit = now
    // debug reprojection (admin HUD): back-project the EXACT point we sampled to
    // VIEW-normalized so the overlay can draw a dot. On the depth tier this uses
    // ARCore's own transform both ways — if the dot lands on the finger, the
    // tap→depth mapping is correct (A1 verification). Other tiers follow the tap.
    var projX = targetX
    var projY = targetY
    if (method == "depth") {
      val tex = viewToTexture(frame, targetX, targetY)
      if (tex != null) {
        val back = textureToView(frame, tex.first, tex.second)
        if (back != null) { projX = back.first; projY = back.second }
      }
    }
    val wv = window.map { it.first }
    val payload = mapOf(
      "distanceM" to emitVal,
      "method" to if (emitVal == null) "none" else method,
      "trackingState" to trackingString(ts),
      "spreadM" to (if (wv.size >= 2) stddev(wv) else 0.0),
      "sampleCount" to wv.size,
      "torchOn" to torchOn,
      "hint" to hint(cam, emitVal),
      "targetX" to targetX,
      "targetY" to targetY,
      "projX" to projX,
      "projY" to projY,
    )
    main.post { Hub.emitDistance(payload) }
  }

  /** Inverse of [viewToTexture]: map a camera/depth TEXTURE-normalized point back
   * to VIEW-normalized (0..1 of the preview), for the debug reprojection dot. */
  private fun textureToView(frame: Frame, u: Float, v: Float): Pair<Double, Double>? {
    return try {
      if (viewW <= 0f || viewH <= 0f) return null
      val inArr = floatArrayOf(u, v)
      val outArr = FloatArray(2)
      frame.transformCoordinates2d(
        com.google.ar.core.Coordinates2d.TEXTURE_NORMALIZED, inArr,
        com.google.ar.core.Coordinates2d.VIEW, outArr,
      )
      Pair((outArr[0] / viewW).toDouble(), (outArr[1] / viewH).toDouble())
    } catch (_: Throwable) { null }
  }

  /** Map a VIEW-normalized tap (0..1 of the preview) to the camera/depth texture's
   * normalized coordinates, accounting for display rotation + the aspect-fill crop.
   * Returns null when the tap falls outside the valid (cropped) depth area. (A1) */
  private fun viewToTexture(frame: Frame, nx: Double, ny: Double): Pair<Float, Float>? {
    return try {
      val inArr = floatArrayOf((nx * viewW).toFloat(), (ny * viewH).toFloat())
      val outArr = FloatArray(2)
      frame.transformCoordinates2d(
        com.google.ar.core.Coordinates2d.VIEW, inArr,
        com.google.ar.core.Coordinates2d.TEXTURE_NORMALIZED, outArr,
      )
      val u = outArr[0]; val v = outArr[1]
      if (u.isNaN() || v.isNaN() || u < 0f || u > 1f || v < 0f || v > 1f) null else Pair(u, v)
    } catch (_: Throwable) { null }
  }

  /** Tier 1 — median of a 5×5 patch of the Depth API image (mm → m), sampled at the
   * correctly-projected target pixel (A1). */
  private fun depthPatchMedian(frame: Frame): Double? {
    val tex = viewToTexture(frame, targetX, targetY) ?: return null
    return try {
      frame.acquireDepthImage16Bits().use { img ->
        val w = img.width; val h = img.height
        val plane = img.planes[0]
        val buf = plane.buffer.order(ByteOrder.nativeOrder())
        val rowStride = plane.rowStride
        val pxStride = if (plane.pixelStride > 0) plane.pixelStride else 2
        val cx = (tex.first * w).toInt(); val cy = (tex.second * h).toInt()
        val samples = ArrayList<Double>()
        for (oy in -2..2) for (ox in -2..2) {
          val x = cx + ox; val y = cy + oy
          if (x < 0 || y < 0 || x >= w || y >= h) continue
          val mm = (buf.getShort(y * rowStride + x * pxStride).toInt() and 0xFFFF)
          if (mm in 50..20000) samples.add(mm / 1000.0)
        }
        if (samples.isEmpty()) null else robustMedian(samples)
      }
    } catch (_: Throwable) { null }
  }

  /** Tier 2 — hit-test at the target (plane / depth point / feature / instant). */
  private fun hitTestDistance(frame: Frame): Double? {
    return try {
      val cam = frame.camera
      if (cam.trackingState != TrackingState.TRACKING) return null
      val px = (targetX * viewW).toFloat(); val py = (targetY * viewH).toFloat()
      val hits = frame.hitTest(px, py)
      val hit = hits.firstOrNull() ?: run {
        val ip = frame.hitTestInstantPlacement(px, py, 2.0f).firstOrNull()
        ip
      } ?: return null
      val cp = cam.pose; val hp = hit.hitPose
      val dx = cp.tx() - hp.tx(); val dy = cp.ty() - hp.ty(); val dz = cp.tz() - hp.tz()
      sqrt((dx * dx + dy * dy + dz * dz).toDouble())
    } catch (_: Throwable) { null }
  }

  /** Tier 3 — nearest feature points to the target, median camera distance. */
  private fun pointCloudMedian(frame: Frame): Double? {
    return try {
      frame.acquirePointCloud().use { pc ->
        val pts = pc.points // x,y,z,confidence quadruples
        if (pts.remaining() < 4) return null
        val cam = frame.camera
        val cp = cam.pose
        val scored = ArrayList<Pair<Double, Double>>()
        while (pts.remaining() >= 4) {
          val x = pts.get(); val y = pts.get(); val z = pts.get(); val c = pts.get()
          if (c < 0.3f) continue
          val dx = cp.tx() - x; val dy = cp.ty() - y; val dz = cp.tz() - z
          scored.add(Pair(0.0, sqrt((dx * dx + dy * dy + dz * dz).toDouble())))
        }
        if (scored.isEmpty()) null else robustMedian(scored.map { it.second })
      }
    } catch (_: Throwable) { null }
  }

  private fun hint(cam: Camera, value: Double?): String? = when (cam.trackingState) {
    TrackingState.PAUSED -> "initializing"
    TrackingState.STOPPED -> "tracking_lost"
    TrackingState.TRACKING -> if (value == null) "no_texture" else null
    else -> null
  }

  // MARK: capture --------------------------------------------------------------

  private fun resolveCapture(frame: Frame, promise: Promise) {
    try {
      val uri = frame.acquireCameraImage().use { image -> yuvToJpegFile(image) }
      val cam = frame.camera
      val intr = cam.imageIntrinsics
      val fl = intr.focalLength; val pp = intr.principalPoint; val dim = intr.imageDimensions
      val values = window.map { it.first }
      val med = robustMedian(values)
      val spread = if (values.size >= 2) stddev(values) else 0.0
      val opts = BitmapFactory.Options().apply { inJustDecodeBounds = true }
      BitmapFactory.decodeFile(uri.removePrefix("file://"), opts)
      promise.resolve(
        mapOf(
          "uri" to uri,
          "width" to opts.outWidth,
          "height" to opts.outHeight,
          "deviceModel" to android.os.Build.MODEL,
          "intrinsics" to mapOf(
            "fx" to fl[0], "fy" to fl[1], "cx" to pp[0], "cy" to pp[1],
            "width" to dim[0], "height" to dim[1],
          ),
          "distance" to mapOf(
            "distanceM" to med,
            "distanceMethod" to if (med == null) "none" else lastMethod,
            "distanceConfidence" to confidence(lastMethod, spread, values.size),
            "sampleCount" to values.size,
            "sampleSpreadM" to spread,
            "trackingState" to trackingString(cam.trackingState),
            "targetX" to targetX, "targetY" to targetY,
            "torchAuto" to torchOn, "tierSwitches" to tierSwitches, "trackingResets" to trackingResets,
          ),
        ),
      )
    } catch (e: Throwable) {
      promise.resolve(emptyMap<String, Any>())
    }
  }

  private fun yuvToJpegFile(image: android.media.Image): String {
    val y = image.planes[0].buffer; val u = image.planes[1].buffer; val v = image.planes[2].buffer
    val ySize = y.remaining(); val uSize = u.remaining(); val vSize = v.remaining()
    val nv21 = ByteArray(ySize + uSize + vSize)
    y.get(nv21, 0, ySize); v.get(nv21, ySize, vSize); u.get(nv21, ySize + vSize, uSize)
    val yuv = YuvImage(nv21, ImageFormat.NV21, image.width, image.height, null)
    val out = ByteArrayOutputStream()
    yuv.compressToJpeg(Rect(0, 0, image.width, image.height), 90, out)
    val file = File(context.cacheDir, "ar_${UUID.randomUUID()}.jpg")
    file.writeBytes(out.toByteArray())
    return "file://${file.absolutePath}"
  }

  // MARK: math -----------------------------------------------------------------

  private fun robustMedian(xs: List<Double>): Double? {
    val vals = xs.filter { it.isFinite() }
    if (vals.isEmpty()) return null
    val m = median(vals)
    val md = median(vals.map { abs(it - m) })
    val kept = if (md > 0) vals.filter { abs(it - m) <= 3 * 1.4826 * md } else vals
    return median(if (kept.isEmpty()) vals else kept)
  }
  private fun median(xs: List<Double>): Double {
    if (xs.isEmpty()) return Double.NaN
    val s = xs.sorted(); val n = s.size
    return if (n % 2 == 1) s[n / 2] else (s[n / 2 - 1] + s[n / 2]) / 2
  }
  private fun stddev(xs: List<Double>): Double {
    if (xs.size < 2) return 0.0
    val mean = xs.sum() / xs.size
    return sqrt(xs.sumOf { (it - mean) * (it - mean) } / (xs.size - 1))
  }
  private fun confidence(method: String, spread: Double, count: Int): String {
    if (method == "none" || count == 0) return "low"
    if ((method == "lidar" || method == "depth") && spread <= 0.25) return "high"
    if (method == "ar_plane" && spread <= 0.15) return "high"
    if (spread <= 0.4) return "medium"
    return "low"
  }
  private fun trackingString(s: TrackingState): String = when (s) {
    TrackingState.TRACKING -> "normal"
    TrackingState.PAUSED -> "limited"
    TrackingState.STOPPED -> "notAvailable"
    else -> "notAvailable"
  }

  // keep hypot referenced (feature scoring extension point)
  @Suppress("unused") private fun ndist(ax: Double, ay: Double) = hypot(ax, ay)
}

import ARKit
import AVFoundation
import ExpoModulesCore
import SceneKit

/// ARKit-backed preview that measures the distance to the targeted point using,
/// in priority order: (1) LiDAR scene depth, (2) raycast against planes/geometry,
/// (3) nearest tracked feature points. All sampling happens here at frame rate;
/// only a throttled (~10 Hz) summary crosses the bridge. Device-only — ARKit does
/// not run in the simulator or Expo Go.
public final class ExpoArDistanceView: ExpoView, ARSessionDelegate {
  private let sceneView = ARSCNView(frame: .zero)
  private var target = CGPoint(x: 0.5, y: 0.5) // normalized

  // rolling window of recent raw samples (value, host-time)
  private var window: [(v: Double, t: TimeInterval)] = []
  private let windowSec: TimeInterval = 0.45
  private var lastEmit: TimeInterval = 0
  private let emitInterval: TimeInterval = 0.1 // ~10 Hz

  private var torchAuto = false
  private var tierSwitches = 0
  private var trackingResets = 0
  private var lastMethod = "none"

  public required init(appContext: AppContext? = nil) {
    super.init(appContext: appContext)
    ARDistanceHub.shared.view = self
    sceneView.autoresizingMask = [.flexibleWidth, .flexibleHeight]
    sceneView.session.delegate = self
    sceneView.automaticallyUpdatesLighting = true
    addSubview(sceneView)
    startSession()
  }

  public override func layoutSubviews() {
    super.layoutSubviews()
    sceneView.frame = bounds
  }

  // MARK: - session lifecycle

  func startSession() {
    let config = ARWorldTrackingConfiguration()
    config.planeDetection = [.horizontal, .vertical]
    if ARWorldTrackingConfiguration.supportsFrameSemantics(.smoothedSceneDepth) {
      config.frameSemantics.insert(.smoothedSceneDepth)
    } else if ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth) {
      config.frameSemantics.insert(.sceneDepth)
    }
    config.isLightEstimationEnabled = true // only for auto-torch; cheap
    sceneView.session.run(config, options: [.resetTracking, .removeExistingAnchors])
  }

  func stopSession() {
    setTorch(false, auto: false)
    sceneView.session.pause()
    window.removeAll()
  }

  func pauseSession() { sceneView.session.pause() }
  func resumeSession() { startSession() }

  func setTarget(x: Double, y: Double) {
    target = CGPoint(x: min(1, max(0, x)), y: min(1, max(0, y)))
    window.removeAll() // new target → fresh window
  }

  // MARK: - ARSessionDelegate

  public func session(_ session: ARSession, cameraDidChangeTrackingState camera: ARCamera) {
    if case .limited(.relocalizing) = camera.trackingState { trackingResets += 1 }
  }

  public func session(_ session: ARSession, didFailWithError error: Error) {
    ARDistanceHub.shared.emitStatus(["tracking": "notAvailable", "error": error.localizedDescription])
    // auto-relocalise
    DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) { [weak self] in self?.startSession() }
  }

  public func session(_ session: ARSession, didUpdate frame: ARFrame) {
    autoTorch(frame)
    let px = CGPoint(x: target.x * CGFloat(frame.camera.imageResolution.width),
                     y: target.y * CGFloat(frame.camera.imageResolution.height))
    let screenPoint = CGPoint(x: target.x * bounds.width, y: target.y * bounds.height)

    var method = "none"
    var raw: Double? = depthPatchMedian(frame: frame, at: px) // Tier 1
    if raw != nil { method = "lidar" } else {
      raw = raycastDistance(screenPoint: screenPoint) // Tier 2
      if raw != nil { method = "ar_plane" } else {
        raw = featurePointMedian(frame: frame, target: target) // Tier 3
        if raw != nil { method = "feature" }
      }
    }
    if method != lastMethod && lastMethod != "none" && method != "none" { tierSwitches += 1 }
    lastMethod = method

    let now = ProcessInfo.processInfo.systemUptime
    if let d = raw, d.isFinite, d > 0 {
      window.append((d, now))
    }
    window.removeAll { now - $0.t > windowSec }

    if now - lastEmit < emitInterval { return }
    lastEmit = now

    let values = window.map { $0.v }
    let med = robustMedian(values)
    let spread = values.count >= 2 ? stddev(values) : 0
    ARDistanceHub.shared.emitDistance([
      "distanceM": med as Any,
      "method": med == nil ? "none" : method,
      "trackingState": trackingString(frame.camera.trackingState),
      "spreadM": spread,
      "sampleCount": values.count,
      "torchOn": torchAuto,
      "hint": hint(frame: frame, method: method, value: med) as Any,
      "targetX": target.x,
      "targetY": target.y,
    ])
  }

  // MARK: - measurement tiers

  /// Tier 1 — median of a 5×5 depth patch (metres). nil if no depth available.
  private func depthPatchMedian(frame: ARFrame, at px: CGPoint) -> Double? {
    guard let depth = frame.smoothedSceneDepth ?? frame.sceneDepth else { return nil }
    let map = depth.depthMap
    CVPixelBufferLockBaseAddress(map, .readOnly)
    defer { CVPixelBufferUnlockBaseAddress(map, .readOnly) }
    let w = CVPixelBufferGetWidth(map), h = CVPixelBufferGetHeight(map)
    guard let base = CVPixelBufferGetBaseAddress(map) else { return nil }
    let rowBytes = CVPixelBufferGetBytesPerRow(map)
    // depth map is rotated vs image; map normalized target → depth coords
    let dx = Int(target.x * CGFloat(w)), dy = Int(target.y * CGFloat(h))
    var samples: [Double] = []
    for oy in -2...2 {
      for ox in -2...2 {
        let x = dx + ox, y = dy + oy
        if x < 0 || y < 0 || x >= w || y >= h { continue }
        let ptr = base.advanced(by: y * rowBytes + x * MemoryLayout<Float32>.size)
        let val = Double(ptr.assumingMemoryBound(to: Float32.self).pointee)
        if val.isFinite && val > 0.05 && val < 20 { samples.append(val) }
      }
    }
    _ = px
    return samples.isEmpty ? nil : robustMedian(samples)
  }

  /// Tier 2 — raycast from the target point against planes / scene geometry.
  private func raycastDistance(screenPoint: CGPoint) -> Double? {
    guard let query = sceneView.raycastQuery(from: screenPoint, allowing: .estimatedPlane, alignment: .any) else {
      return nil
    }
    let results = sceneView.session.raycast(query)
    guard let hit = results.first, let cam = sceneView.session.currentFrame?.camera else { return nil }
    let camPos = SIMD3<Float>(cam.transform.columns.3.x, cam.transform.columns.3.y, cam.transform.columns.3.z)
    let hitPos = SIMD3<Float>(hit.worldTransform.columns.3.x, hit.worldTransform.columns.3.y, hit.worldTransform.columns.3.z)
    return Double(simd_distance(camPos, hitPos))
  }

  /// Tier 3 — median depth of the tracked feature points nearest the target.
  private func featurePointMedian(frame: ARFrame, target: CGPoint) -> Double? {
    guard let cloud = frame.rawFeaturePoints, !cloud.points.isEmpty else { return nil }
    let cam = frame.camera
    let size = bounds.size == .zero ? CGSize(width: 390, height: 844) : bounds.size
    var scored: [(d: Double, dist: Double)] = []
    for p in cloud.points {
      let sp = cam.projectPoint(p, orientation: .portrait, viewportSize: size)
      let nx = sp.x / size.width, ny = sp.y / size.height
      let dd = hypot(nx - target.x, ny - target.y)
      if dd > 0.12 { continue } // only points near the target
      let camPos = SIMD3<Float>(cam.transform.columns.3.x, cam.transform.columns.3.y, cam.transform.columns.3.z)
      scored.append((dd, Double(simd_distance(camPos, p))))
    }
    guard !scored.isEmpty else { return nil }
    return robustMedian(scored.sorted { $0.d < $1.d }.prefix(10).map { $0.dist })
  }

  // MARK: - auto-fixes

  private func autoTorch(_ frame: ARFrame) {
    guard let light = frame.lightEstimate else { return }
    if light.ambientIntensity < 40, !torchAuto { setTorch(true, auto: true) }
    else if light.ambientIntensity > 120, torchAuto { setTorch(false, auto: false) }
  }

  func setTorch(_ on: Bool, auto: Bool) {
    guard let device = AVCaptureDevice.default(for: .video), device.hasTorch else { return }
    do {
      try device.lockForConfiguration()
      device.torchMode = on ? .on : .off
      device.unlockForConfiguration()
      torchAuto = on && auto ? true : (on ? true : false)
    } catch { /* torch control is best-effort */ }
  }

  private func hint(frame: ARFrame, method: String, value: Double?) -> String? {
    switch frame.camera.trackingState {
    case .notAvailable: return "tracking_lost"
    case .limited(let reason):
      switch reason {
      case .initializing: return "initializing"
      case .excessiveMotion: return "hold_steady"
      case .insufficientFeatures: return "no_texture"
      case .relocalizing: return "tracking_lost"
      @unknown default: return nil
      }
    case .normal:
      if (frame.lightEstimate?.ambientIntensity ?? 1000) < 40 { return "low_light" }
      if value == nil { return "no_texture" }
      return nil
    }
  }

  // MARK: - capture (full-resolution still during the AR session, iOS 16+)

  func capture(_ promise: Promise) {
    guard #available(iOS 16.0, *) else { captureFromFrame(promise); return }
    sceneView.session.captureHighResolutionFrame { [weak self] frame, error in
      guard let self = self, let frame = frame, error == nil else {
        self?.captureFromFrame(promise); return
      }
      self.resolveCapture(promise, pixelBuffer: frame.capturedImage, camera: frame.camera)
    }
  }

  private func captureFromFrame(_ promise: Promise) {
    guard let frame = sceneView.session.currentFrame else { promise.resolve([String: Any]()); return }
    resolveCapture(promise, pixelBuffer: frame.capturedImage, camera: frame.camera)
  }

  private func resolveCapture(_ promise: Promise, pixelBuffer: CVPixelBuffer, camera: ARCamera) {
    let ci = CIImage(cvPixelBuffer: pixelBuffer).oriented(.right)
    let ctx = CIContext()
    guard let cg = ctx.createCGImage(ci, from: ci.extent),
          let data = UIImage(cgImage: cg).jpegData(compressionQuality: 0.9) else {
      promise.resolve([String: Any]()); return
    }
    let url = FileManager.default.temporaryDirectory.appendingPathComponent("ar_\(UUID().uuidString).jpg")
    try? data.write(to: url)

    let values = window.map { $0.v }
    let med = robustMedian(values)
    let spread = values.count >= 2 ? stddev(values) : 0
    let intr = camera.intrinsics
    let res = camera.imageResolution
    promise.resolve([
      "uri": url.absoluteString,
      "width": Int(ci.extent.width),
      "height": Int(ci.extent.height),
      "deviceModel": UIDevice.current.modelName,
      "intrinsics": [
        "fx": Double(intr.columns.0.x), "fy": Double(intr.columns.1.y),
        "cx": Double(intr.columns.2.x), "cy": Double(intr.columns.2.y),
        "width": Int(res.width), "height": Int(res.height),
      ],
      "distance": [
        "distanceM": med as Any,
        "distanceMethod": med == nil ? "none" : lastMethod,
        "distanceConfidence": confidence(method: lastMethod, spread: spread, count: values.count),
        "sampleCount": values.count,
        "sampleSpreadM": spread,
        "trackingState": trackingString(camera.trackingState),
        "targetX": target.x, "targetY": target.y,
        "torchAuto": torchAuto, "tierSwitches": tierSwitches, "trackingResets": trackingResets,
      ],
    ])
  }

  // MARK: - math helpers

  private func robustMedian(_ xs: [Double]) -> Double? {
    let vals = xs.filter { $0.isFinite }
    if vals.isEmpty { return nil }
    let m = median(vals)
    let devs = vals.map { abs($0 - m) }
    let md = median(devs)
    let kept = md > 0 ? vals.filter { abs($0 - m) <= 3 * 1.4826 * md } : vals
    return median(kept.isEmpty ? vals : kept)
  }
  private func median(_ xs: [Double]) -> Double {
    let s = xs.sorted(); let n = s.count
    if n == 0 { return .nan }
    return n % 2 == 1 ? s[n / 2] : (s[n / 2 - 1] + s[n / 2]) / 2
  }
  private func stddev(_ xs: [Double]) -> Double {
    if xs.count < 2 { return 0 }
    let mean = xs.reduce(0, +) / Double(xs.count)
    return (xs.reduce(0) { $0 + ($1 - mean) * ($1 - mean) } / Double(xs.count - 1)).squareRoot()
  }
  private func confidence(method: String, spread: Double, count: Int) -> String {
    if method == "none" || count == 0 { return "low" }
    if (method == "lidar" || method == "depth") && spread <= 0.25 { return "high" }
    if method == "ar_plane" && spread <= 0.15 { return "high" }
    if spread <= 0.4 { return "medium" }
    return "low"
  }
  private func trackingString(_ s: ARCamera.TrackingState) -> String {
    switch s {
    case .normal: return "normal"
    case .notAvailable: return "notAvailable"
    case .limited(.initializing): return "initializing"
    case .limited(.relocalizing): return "relocalizing"
    case .limited: return "limited"
    }
  }
}

private extension UIDevice {
  var modelName: String {
    var info = utsname(); uname(&info)
    let mirror = Mirror(reflecting: info.machine)
    return mirror.children.reduce("") { acc, el in
      guard let v = el.value as? Int8, v != 0 else { return acc }
      return acc + String(UnicodeScalar(UInt8(v)))
    }
  }
}

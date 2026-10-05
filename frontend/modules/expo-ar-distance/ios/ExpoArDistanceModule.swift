import ARKit
import ExpoModulesCore

/// Shared hub so the module's imperative AsyncFunctions can reach the single
/// active AR view, and the view can emit throttled events through the module.
final class ARDistanceHub {
  static let shared = ARDistanceHub()
  weak var module: ExpoArDistanceModule?
  weak var view: ExpoArDistanceView?

  func emitDistance(_ payload: [String: Any]) { module?.sendEvent("onDistance", payload) }
  func emitStatus(_ payload: [String: Any]) { module?.sendEvent("onStatus", payload) }
}

public final class ExpoArDistanceModule: Module {
  public func definition() -> ModuleDefinition {
    Name("ExpoArDistance")

    Events("onDistance", "onStatus")

    OnCreate { ARDistanceHub.shared.module = self }

    AsyncFunction("getCapabilitiesAsync") { () -> [String: Any] in
      let supported = ARWorldTrackingConfiguration.isSupported
      let depth = ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth)
      return [
        "supported": supported,
        "hasHardwareDepth": depth,
        "reason": supported ? "ok" : "unsupported_device",
      ]
    }

    AsyncFunction("startAsync") { ARDistanceHub.shared.view?.startSession() }
    AsyncFunction("stopAsync") { ARDistanceHub.shared.view?.stopSession() }
    AsyncFunction("pauseAsync") { ARDistanceHub.shared.view?.pauseSession() }
    AsyncFunction("resumeAsync") { ARDistanceHub.shared.view?.resumeSession() }

    AsyncFunction("setTargetAsync") { (x: Double, y: Double) in
      ARDistanceHub.shared.view?.setTarget(x: x, y: y)
    }
    AsyncFunction("setTorchAsync") { (on: Bool) in
      ARDistanceHub.shared.view?.setTorch(on, auto: false)
    }

    AsyncFunction("captureAsync") { (promise: Promise) in
      guard let v = ARDistanceHub.shared.view else { promise.resolve([String: Any]()); return }
      v.capture(promise)
    }

    View(ExpoArDistanceView.self) {}
  }
}

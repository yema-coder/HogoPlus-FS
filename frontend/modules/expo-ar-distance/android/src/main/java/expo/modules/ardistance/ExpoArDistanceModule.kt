package expo.modules.ardistance

import com.google.ar.core.ArCoreApk
import com.google.ar.core.Config
import com.google.ar.core.Session
import expo.modules.kotlin.Promise
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition

/** Shared hub so the module's imperative functions can reach the single active
 *  AR view, and the view can emit throttled events through the module. */
object Hub {
  var module: ExpoArDistanceModule? = null
  var view: ExpoArDistanceView? = null

  fun emitDistance(payload: Map<String, Any?>) { module?.sendEvent("onDistance", payload) }
  fun emitStatus(payload: Map<String, Any?>) { module?.sendEvent("onStatus", payload) }
}

class ExpoArDistanceModule : Module() {
  override fun definition() = ModuleDefinition {
    Name("ExpoArDistance")

    Events("onDistance", "onStatus")

    OnCreate { Hub.module = this@ExpoArDistanceModule }

    AsyncFunction("getCapabilitiesAsync") { capabilities() }

    AsyncFunction("startAsync") { Hub.view?.resumeSession() }
    AsyncFunction("stopAsync") { Hub.view?.stopSession() }
    AsyncFunction("pauseAsync") { Hub.view?.pauseSession() }
    AsyncFunction("resumeAsync") { Hub.view?.resumeSession() }

    AsyncFunction("setTargetAsync") { x: Double, y: Double -> Hub.view?.setTarget(x, y) }
    AsyncFunction("setTorchAsync") { on: Boolean -> Hub.view?.setTorch(on, false) }

    AsyncFunction("captureAsync") { promise: Promise -> Hub.view?.capture(promise) ?: promise.resolve(emptyMap<String, Any>()) }

    View(ExpoArDistanceView::class) {}
  }

  private fun capabilities(): Map<String, Any> {
    val ctx = appContext.reactContext
      ?: return mapOf("supported" to false, "hasHardwareDepth" to false, "reason" to "no_native")
    return try {
      val avail = ArCoreApk.getInstance().checkAvailability(ctx)
      if (!avail.isSupported) {
        return mapOf("supported" to false, "hasHardwareDepth" to false, "reason" to "no_arcore")
      }
      // Depth support probe (requires a session; done cheaply)
      var depth = false
      try {
        val s = Session(ctx)
        depth = s.isDepthModeSupported(Config.DepthMode.AUTOMATIC)
        s.close()
      } catch (_: Throwable) { /* probe best-effort */ }
      mapOf("supported" to true, "hasHardwareDepth" to depth, "reason" to "ok")
    } catch (e: Throwable) {
      mapOf("supported" to false, "hasHardwareDepth" to false, "reason" to "error")
    }
  }
}

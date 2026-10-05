package expo.modules.ardistance

import android.opengl.GLES11Ext
import android.opengl.GLES20
import com.google.ar.core.Frame
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.FloatBuffer

/**
 * Minimal camera-background renderer (OES external texture full-screen quad).
 * Standard ARCore `hello_ar` boilerplate, condensed. Device-only.
 */
class BackgroundRenderer {
  private var program = 0
  private var textureId = -1
  private var positionAttrib = 0
  private var texCoordAttrib = 0
  private lateinit var quadCoords: FloatBuffer
  private lateinit var quadTexCoords: FloatBuffer

  private val vertexShader = """
    attribute vec4 a_Position;
    attribute vec2 a_TexCoord;
    varying vec2 v_TexCoord;
    void main() { gl_Position = a_Position; v_TexCoord = a_TexCoord; }
  """.trimIndent()

  private val fragmentShader = """
    #extension GL_OES_EGL_image_external : require
    precision mediump float;
    varying vec2 v_TexCoord;
    uniform samplerExternalOES u_Texture;
    void main() { gl_FragColor = texture2D(u_Texture, v_TexCoord); }
  """.trimIndent()

  private val quadVertices = floatArrayOf(-1f, -1f, -1f, 1f, 1f, -1f, 1f, 1f)

  fun createOnGlThread(): Int {
    val textures = IntArray(1)
    GLES20.glGenTextures(1, textures, 0)
    textureId = textures[0]
    GLES20.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, textureId)
    GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_WRAP_S, GLES20.GL_CLAMP_TO_EDGE)
    GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_WRAP_T, GLES20.GL_CLAMP_TO_EDGE)
    GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_MIN_FILTER, GLES20.GL_LINEAR)
    GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_MAG_FILTER, GLES20.GL_LINEAR)

    quadCoords = ByteBuffer.allocateDirect(quadVertices.size * 4).order(ByteOrder.nativeOrder()).asFloatBuffer()
    quadCoords.put(quadVertices); quadCoords.position(0)
    quadTexCoords = ByteBuffer.allocateDirect(quadVertices.size * 4).order(ByteOrder.nativeOrder()).asFloatBuffer()

    val vs = loadShader(GLES20.GL_VERTEX_SHADER, vertexShader)
    val fs = loadShader(GLES20.GL_FRAGMENT_SHADER, fragmentShader)
    program = GLES20.glCreateProgram()
    GLES20.glAttachShader(program, vs)
    GLES20.glAttachShader(program, fs)
    GLES20.glLinkProgram(program)
    positionAttrib = GLES20.glGetAttribLocation(program, "a_Position")
    texCoordAttrib = GLES20.glGetAttribLocation(program, "a_TexCoord")
    return textureId
  }

  fun draw(frame: Frame) {
    if (frame.hasDisplayGeometryChanged()) {
      val buf = ByteBuffer.allocateDirect(quadVertices.size * 4).order(ByteOrder.nativeOrder()).asFloatBuffer()
      buf.put(quadVertices); buf.position(0)
      frame.transformCoordinates2d(
        com.google.ar.core.Coordinates2d.OPENGL_NORMALIZED_DEVICE_COORDINATES, buf,
        com.google.ar.core.Coordinates2d.TEXTURE_NORMALIZED, quadTexCoords,
      )
    }
    if (frame.timestamp == 0L) return

    GLES20.glDisable(GLES20.GL_DEPTH_TEST)
    GLES20.glDepthMask(false)
    GLES20.glUseProgram(program)
    GLES20.glActiveTexture(GLES20.GL_TEXTURE0)
    GLES20.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, textureId)

    GLES20.glVertexAttribPointer(positionAttrib, 2, GLES20.GL_FLOAT, false, 0, quadCoords)
    GLES20.glVertexAttribPointer(texCoordAttrib, 2, GLES20.GL_FLOAT, false, 0, quadTexCoords)
    GLES20.glEnableVertexAttribArray(positionAttrib)
    GLES20.glEnableVertexAttribArray(texCoordAttrib)
    GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4)
    GLES20.glDisableVertexAttribArray(positionAttrib)
    GLES20.glDisableVertexAttribArray(texCoordAttrib)

    GLES20.glDepthMask(true)
    GLES20.glEnable(GLES20.GL_DEPTH_TEST)
  }

  private fun loadShader(type: Int, src: String): Int {
    val shader = GLES20.glCreateShader(type)
    GLES20.glShaderSource(shader, src)
    GLES20.glCompileShader(shader)
    return shader
  }
}

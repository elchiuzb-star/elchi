package uz.elchi.app.api

import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.util.concurrent.TimeUnit

/** What a K8 tracking socket reports; every call comes from OkHttp's thread, the caller hops to its own. */
interface LiveSocketListener {
    fun onOpen()
    fun onMessage(text: String)

    /** The socket is gone: the server's close code, or [ABNORMAL] when the connection broke without one. */
    fun onClosed(code: Int)

    companion object {
        const val ABNORMAL = 1006
    }
}

/** One open socket. */
interface LiveSocket {
    fun send(text: String): Boolean
    fun close()
}

/** Opens sockets; a fake stands in for it in tests. */
fun interface LiveSocketFactory {
    fun open(url: String, listener: LiveSocketListener): LiveSocket
}

/**
 * K8 over OkHttp's WebSocket. The access token never goes into the URL: it travels in the first frame (`subscribe`),
 * which the caller sends from [LiveSocketListener.onOpen].
 */
class OkHttpLiveSocketFactory(base: OkHttpClient) : LiveSocketFactory {
    // The server pushes every ~5 s; a ping keeps NATs open, and no read timeout cuts a quiet but healthy socket.
    private val client = base.newBuilder().readTimeout(0, TimeUnit.MILLISECONDS).pingInterval(20, TimeUnit.SECONDS).build()

    override fun open(url: String, listener: LiveSocketListener): LiveSocket {
        val socket = client.newWebSocket(
            Request.Builder().url(url).build(),
            object : WebSocketListener() {
                private var reported = false

                private fun closed(code: Int) {
                    if (reported) return
                    reported = true
                    listener.onClosed(code)
                }

                override fun onOpen(webSocket: WebSocket, response: Response) = listener.onOpen()

                override fun onMessage(webSocket: WebSocket, text: String) = listener.onMessage(text)

                override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                    webSocket.close(code.takeIf { it in 1000..4999 && it != LiveSocketListener.ABNORMAL } ?: NORMAL, null)
                    closed(code)
                }

                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = closed(code)

                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) = closed(LiveSocketListener.ABNORMAL)
            },
        )
        return object : LiveSocket {
            override fun send(text: String): Boolean = socket.send(text)
            override fun close() {
                socket.close(NORMAL, null)
            }
        }
    }

    private companion object {
        const val NORMAL = 1000
    }
}

/** K8: `ws(s)://<api host>/api/v2/ws`, derived from the API base (http -> ws, https -> wss, same host and port). */
fun trackingSocketUrl(apiBase: String): String {
    val origin = Regex("^(https?)://([^/]+)").find(apiBase.trim()) ?: throw IllegalArgumentException("not an http(s) base: $apiBase")
    val scheme = if (origin.groupValues[1] == "https") "wss" else "ws"
    return "$scheme://${origin.groupValues[2]}/api/v2/ws"
}

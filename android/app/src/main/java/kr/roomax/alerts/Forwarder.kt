package kr.roomax.alerts

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 고른 문자·알림을 ROOMAX 연결 주소(계좌별 비밀 주소)로 보낸다.
 * - 보낼 수 없으면(인터넷 끊김·서버 오류) 휴대폰에 쌓아 두었다가 다음 알림·앱 열 때 다시 보낸다.
 * - 같은 알림이 10분 안에 또 오면(알림 갱신) 한 번만 보낸다.
 * - 기록에는 시각·출처·결과만 남기고 문자 내용은 남기지 않는다.
 */
object Forwarder {
    private const val PENDING = "pending"
    private const val LOG = "log"
    private const val MAX_PENDING = 50
    private const val MAX_LOG = 30
    private const val DEDUPE_MS = 10 * 60 * 1000L
    private val lock = Any()
    private val recent = LinkedHashMap<Int, Long>()

    fun isHookUrl(url: String): Boolean =
        url.startsWith("https://") && url.contains("/api/v1/bank-alerts/hook/")

    fun wanted(ctx: Context, text: String): Boolean =
        text.isNotBlank() && (!Prefs.depositOnly(ctx) || text.contains("입금"))

    /** 대기열에 넣고 바로 보낸다 (호출한 스레드에서 — 메인 스레드에서는 부르지 말 것) */
    fun submit(ctx: Context, source: String, text: String) {
        if (!wanted(ctx, text)) return
        val now = System.currentTimeMillis()
        synchronized(lock) {
            recent.entries.removeAll { now - it.value > DEDUPE_MS }
            val key = (source + "|" + text).hashCode()
            if (recent.containsKey(key)) return
            recent[key] = now
            val pending = Prefs.readList(ctx, PENDING)
            pending.put(JSONObject().put("source", source).put("text", text).put("at", now))
            while (pending.length() > MAX_PENDING) pending.remove(0)
            Prefs.writeList(ctx, PENDING, pending)
        }
        flush(ctx)
    }

    fun pendingCount(ctx: Context): Int = Prefs.readList(ctx, PENDING).length()

    fun log(ctx: Context): List<String> {
        val list = Prefs.readList(ctx, LOG)
        return (list.length() - 1 downTo 0).map { list.getString(it) }
    }

    /** 쌓인 것을 차례로 보낸다. 서버가 받지 않는 것(주소 틀림 등 4xx)은 버리고 기록만 남긴다. */
    fun flush(ctx: Context) {
        synchronized(lock) {
            val url = Prefs.hookUrl(ctx)
            if (!isHookUrl(url)) return
            val pending = Prefs.readList(ctx, PENDING)
            val keep = JSONArray()
            for (i in 0 until pending.length()) {
                val item = pending.getJSONObject(i)
                val code = post(url, item.getString("text"))
                val source = item.optString("source")
                when {
                    code in 200..299 -> addLog(ctx, "$source 보냄")
                    code == 429 || code >= 500 || code < 0 -> {
                        keep.put(item)
                        addLog(ctx, "$source 대기 (${if (code < 0) "연결 안 됨" else "서버 $code"})")
                    }
                    code == 404 -> addLog(ctx, "$source 버림 — 연결 주소가 끊겼습니다. ROOMAX 에서 새 주소를 받아 넣으세요")
                    else -> addLog(ctx, "$source 버림 (서버 $code)")
                }
            }
            Prefs.writeList(ctx, PENDING, keep)
        }
    }

    private fun post(url: String, text: String): Int = try {
        val conn = URL(url).openConnection() as HttpURLConnection
        conn.requestMethod = "POST"
        conn.connectTimeout = 10_000
        conn.readTimeout = 15_000
        conn.doOutput = true
        conn.setRequestProperty("Content-Type", "application/json; charset=utf-8")
        conn.outputStream.use { it.write(JSONObject().put("text", text).toString().toByteArray(Charsets.UTF_8)) }
        val code = conn.responseCode
        conn.disconnect()
        code
    } catch (e: Exception) {
        -1
    }

    private fun addLog(ctx: Context, line: String) {
        val at = SimpleDateFormat("MM.dd HH:mm", Locale.KOREA).format(Date())
        val log = Prefs.readList(ctx, LOG)
        log.put("$at  $line")
        while (log.length() > MAX_LOG) log.remove(0)
        Prefs.writeList(ctx, LOG, log)
    }
}

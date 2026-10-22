package kr.roomax.alerts

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Durable encrypted outbox. No notification bodies, tokens or names in history. */
object Forwarder {
    private val lock = Any()
    fun isHookUrl(url: String) = DeliveryPolicy.isHookUrl(url)
    fun wanted(ctx: Context, text: String) = DeliveryPolicy.wanted(text, Prefs.depositOnly(ctx))

    fun submit(ctx: Context, source: String, text: String) {
        if (!wanted(ctx, text)) return
        synchronized(lock) {
            val url = Prefs.hookUrl(ctx)
            if (!isHookUrl(url)) return // no collection before configuration
            val now = System.currentTimeMillis()
            val pending = prune(ctx, now)
            val key = DeliveryPolicy.fingerprint(url + "\n" + text.trim())
            val recent = Prefs.readList(ctx, "recent")
            val live = JSONArray()
            for (i in 0 until recent.length()) {
                val item = recent.getJSONObject(i)
                if (now - item.getLong("at") in 0 until DeliveryPolicy.DEDUPE_MS) live.put(item)
            }
            if ((0 until live.length()).any { live.getJSONObject(it).getString("key") == key } ||
                (0 until pending.length()).any { pending.getJSONObject(it).getString("key") == key }) return
            // Only fixed source categories are retained, never labels, sender numbers or content.
            pending.put(JSONObject().put("source", if (source.startsWith("문자")) "문자" else "앱 알림")
                .put("text", text).put("at", now).put("key", key)
                .put("destination", DeliveryPolicy.fingerprint(url)))
            while (pending.length() > DeliveryPolicy.MAX_PENDING) {
                pending.remove(0)
                addLog(ctx, "대기 한도 초과 — 가장 오래된 항목 삭제")
            }
            Prefs.writeList(ctx, "pending", pending)
            live.put(JSONObject().put("key", key).put("at", now))
            while (live.length() > 200) live.remove(0)
            Prefs.writeList(ctx, "recent", live)
        }
        RetryWorker.schedule(ctx)
    }

    fun configure(ctx: Context, url: String) = synchronized(lock) {
        if (Prefs.hookUrl(ctx) != url) {
            // Old account's queued data must never be sent to a newly configured account.
            Prefs.writeList(ctx, "pending", JSONArray())
            Prefs.writeList(ctx, "recent", JSONArray())
        }
        Prefs.saveHookUrl(ctx, url)
    }

    private fun prune(ctx: Context, now: Long): JSONArray {
        val old = Prefs.readList(ctx, "pending")
        val live = JSONArray()
        for (i in 0 until old.length()) {
            val item = old.getJSONObject(i)
            if (!DeliveryPolicy.expired(item.getLong("at"), now)) live.put(item)
            else addLog(ctx, "보관 기간 만료 — 대기 항목 삭제")
        }
        Prefs.writeList(ctx, "pending", live)
        return live
    }
    fun pendingCount(ctx: Context): Int = synchronized(lock) { prune(ctx, System.currentTimeMillis()).length() }
    fun log(ctx: Context): List<String> = synchronized(lock) {
        val list = Prefs.readList(ctx, "log")
        (list.length() - 1 downTo 0).map { list.getString(it) }
    }

    /** Returns true when transient failures remain. Injectable transport for regression tests. */
    fun flush(ctx: Context, transport: (String, String) -> Int = ::post): Boolean = synchronized(lock) {
        val pending = prune(ctx, System.currentTimeMillis())
        val url = Prefs.hookUrl(ctx)
        if (!isHookUrl(url)) return@synchronized false
        val keep = JSONArray()
        for (i in 0 until pending.length()) {
            val item = pending.getJSONObject(i)
            if (item.optString("destination") != DeliveryPolicy.fingerprint(url)) continue
            val code = transport(url, item.getString("text"))
            when {
                code in 200..299 -> addLog(ctx, "${item.getString("source")} 보냄")
                DeliveryPolicy.retry(code) -> keep.put(item)
                else -> addLog(ctx, "전송 거부 — 삭제 (HTTP $code)")
            }
            // Checkpoint each response to avoid replaying a whole batch after process death.
            val checkpoint = JSONArray(keep.toString())
            for (j in i + 1 until pending.length()) checkpoint.put(pending.getJSONObject(j))
            Prefs.writeList(ctx, "pending", checkpoint)
            if (DeliveryPolicy.retry(code)) return@synchronized true
        }
        Prefs.writeList(ctx, "pending", keep)
        keep.length() > 0
    }

    private fun post(url: String, text: String): Int {
        var conn: HttpURLConnection? = null
        return try {
            conn = URL(url).openConnection() as HttpURLConnection
            conn.instanceFollowRedirects = false // never forward bank data/token through redirects
            conn.requestMethod = "POST"
            conn.connectTimeout = 10_000
            conn.readTimeout = 15_000
            conn.doOutput = true
            conn.setRequestProperty("Content-Type", "application/json; charset=utf-8")
            conn.outputStream.use { it.write(JSONObject().put("text", text).toString().toByteArray(Charsets.UTF_8)) }
            conn.responseCode
        } catch (_: Exception) { -1 } finally { conn?.disconnect() }
    }
    private fun addLog(ctx: Context, line: String) {
        val at = SimpleDateFormat("MM.dd HH:mm", Locale.KOREA).format(Date())
        val log = Prefs.readList(ctx, "log")
        log.put("$at  $line")
        while (log.length() > 30) log.remove(0)
        Prefs.writeList(ctx, "log", log)
    }
}

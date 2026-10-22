package kr.roomax.alerts

import android.content.Context
import android.content.SharedPreferences
import org.json.JSONArray

/** 설정과 '못 보낸 알림' 대기열. 휴대폰 안에만 저장한다. */
object Prefs {
    private const val NAME = "roomax_alerts"
    const val DEFAULT_SENDERS = "15885000"  // 우리은행 입출금 문자 (다른 은행 번호는 화면에서 추가)

    fun of(ctx: Context): SharedPreferences = ctx.getSharedPreferences(NAME, Context.MODE_PRIVATE)

    fun hookUrl(ctx: Context): String {
        val p = of(ctx)
        // Upgrade an earlier test APK without retaining a plaintext token or queue.
        if (p.contains("hook_url")) {
            val old = p.getString("hook_url", "").orEmpty()
            check(p.edit().putString("hook_secret", SecretStore.encrypt(old))
                .remove("hook_url").remove("pending").commit())
        }
        if (p.contains("pending")) check(p.edit().remove("pending").commit())
        return p.getString("hook_secret", null)?.let { SecretStore.decrypt(it) }.orEmpty()
    }

    fun saveHookUrl(ctx: Context, value: String) {
        check(of(ctx).edit().putString("hook_secret", SecretStore.encrypt(value)).remove("hook_url").commit())
    }

    fun smsEnabled(ctx: Context): Boolean = of(ctx).getBoolean("sms_enabled", true)

    /** 문자 발신번호 — 숫자만 비교 */
    fun smsSenders(ctx: Context): Set<String> =
        (of(ctx).getString("sms_senders", DEFAULT_SENDERS) ?: "")
            .split(",", " ", "\n").map { digits(it) }.filter { it.isNotEmpty() }.toSet()

    fun apps(ctx: Context): Set<String> = of(ctx).getStringSet("apps", emptySet()) ?: emptySet()

    /** 켜 두면 '입금'이 들어간 문자·알림만 보낸다 (출금·광고·인증번호는 휴대폰 밖으로 안 나감) */
    fun depositOnly(ctx: Context): Boolean = of(ctx).getBoolean("deposit_only", true)

    fun digits(s: String): String = s.filter { it.isDigit() }

    fun readList(ctx: Context, key: String): JSONArray =
        if (key == "pending") {
            of(ctx).getString("pending_secret", null)?.let { JSONArray(SecretStore.decrypt(it)) } ?: JSONArray()
        } else JSONArray(of(ctx).getString(key, "[]"))

    fun writeList(ctx: Context, key: String, list: JSONArray) {
        val editor = of(ctx).edit()
        if (key == "pending") {
            editor.remove("pending")
            if (list.length() == 0) editor.remove("pending_secret")
            else editor.putString("pending_secret", SecretStore.encrypt(list.toString()))
        } else editor.putString(key, list.toString())
        check(editor.commit()) { "Could not persist delivery state" }
    }
}

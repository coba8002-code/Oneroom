package kr.roomax.alerts

import java.net.URI
import java.security.MessageDigest

/** No Android dependency: privacy and retry decisions can be tested on the JVM. */
object DeliveryPolicy {
    const val MAX_PENDING = 50
    const val MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000L
    const val DEDUPE_MS = 10 * 60 * 1000L

    fun isHookUrl(url: String): Boolean = try {
        val u = URI(url)
        u.scheme == "https" && !u.host.isNullOrBlank() && u.userInfo == null &&
            u.query == null && u.fragment == null &&
            Regex("/api/v1/bank-alerts/hook/[A-Za-z0-9_-]+").matches(u.rawPath ?: "")
    } catch (_: Exception) { false }

    fun wanted(text: String, depositOnly: Boolean): Boolean = text.isNotBlank() &&
        text.length <= 2_000 &&
        listOf("(광고)", "인증번호", "인증코드", "일회용", "OTP").none { text.contains(it, true) } &&
        (!depositOnly || (text.contains("입금") && !text.contains("출금")))

    fun smsAllowed(enabled: Boolean, sender: String, selected: Set<String>): Boolean =
        enabled && sender.filter { it.isDigit() }.let { it.isNotEmpty() && it in selected }
    fun appAllowed(pkg: String, selected: Set<String>, groupSummary: Boolean): Boolean =
        pkg in selected && !groupSummary

    fun fingerprint(text: String): String = MessageDigest.getInstance("SHA-256")
        .digest(text.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }
    fun retry(code: Int): Boolean = code < 0 || code == 408 || code == 429 || code in 500..599
    fun expired(at: Long, now: Long): Boolean = at > now || now - at >= MAX_AGE_MS
}

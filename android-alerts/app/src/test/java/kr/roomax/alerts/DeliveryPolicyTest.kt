package kr.roomax.alerts

import org.junit.Assert.*
import org.junit.Test

class DeliveryPolicyTest {
    @Test fun filtersSensitiveAndNonDepositContent() {
        assertTrue(DeliveryPolicy.wanted("입금 100,000원", true))
        listOf("", "출금 100,000원", "입금 인증번호 123456", "(광고) 입금 이벤트", "입금 OTP 123", "입금/출금 안내")
            .forEach { assertFalse(it, DeliveryPolicy.wanted(it, true)) }
        assertFalse(DeliveryPolicy.wanted("인증번호 123", false))
        assertTrue(DeliveryPolicy.wanted("은행 안내", false))
        assertFalse(DeliveryPolicy.wanted("입금".repeat(6000), true))
    }
    @Test fun exactHttpsEndpointOnly() {
        assertTrue(DeliveryPolicy.isHookUrl("https://example.com/api/v1/bank-alerts/hook/token_123-abc"))
        listOf("http://example.com/api/v1/bank-alerts/hook/x", "https://example.com/?next=/api/v1/bank-alerts/hook/x",
            "https://user:pass@example.com/api/v1/bank-alerts/hook/x", "https://example.com/api/v1/bank-alerts/hook/",
            "https://example.com/api/v1/bank-alerts/hook/x#secret", "https://example.com/api/v1/bank-alerts/hook/x/other")
            .forEach { assertFalse(it, DeliveryPolicy.isHookUrl(it)) }
    }
    @Test fun onlySelectedSendersAndApps() {
        assertTrue(DeliveryPolicy.smsAllowed(true, "1588-5000", setOf("15885000")))
        assertFalse(DeliveryPolicy.smsAllowed(false, "15885000", setOf("15885000")))
        assertFalse(DeliveryPolicy.smsAllowed(true, "01012345678", setOf("15885000")))
        assertTrue(DeliveryPolicy.appAllowed("bank", setOf("bank"), false))
        assertFalse(DeliveryPolicy.appAllowed("other", setOf("bank"), false))
        assertFalse(DeliveryPolicy.appAllowed("bank", setOf("bank"), true))
    }
    @Test fun transientFailuresOnly() {
        listOf(-1, 408, 429, 500, 503).forEach { assertTrue(DeliveryPolicy.retry(it)) }
        listOf(200, 204, 301, 400, 401, 404).forEach { assertFalse(DeliveryPolicy.retry(it)) }
    }
    @Test fun retentionAndCollisionResistantKeys() {
        assertFalse(DeliveryPolicy.expired(100, 100 + DeliveryPolicy.MAX_AGE_MS - 1))
        assertTrue(DeliveryPolicy.expired(100, 100 + DeliveryPolicy.MAX_AGE_MS))
        assertTrue(DeliveryPolicy.expired(200, 100))
        assertNotEquals(DeliveryPolicy.fingerprint("Aa"), DeliveryPolicy.fingerprint("BB"))
    }
}

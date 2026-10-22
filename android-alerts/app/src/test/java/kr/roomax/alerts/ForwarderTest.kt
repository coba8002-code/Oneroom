package kr.roomax.alerts

import android.content.Context
import io.mockk.*
import org.json.JSONArray
import org.junit.*
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28])
class ForwarderTest {
    private lateinit var ctx: Context
    private val url = "https://example.com/api/v1/bank-alerts/hook/test"
    @Before fun setup() {
        ctx = RuntimeEnvironment.getApplication()
        Prefs.of(ctx).edit().clear().commit()
        // AndroidKeyStore requires a device. Mock only this boundary, not queue/storage/transport.
        mockkObject(SecretStore)
        every { SecretStore.encrypt(any()) } answers { "sealed:" + java.util.Base64.getEncoder().encodeToString(firstArg<String>().toByteArray()) }
        every { SecretStore.decrypt(any()) } answers { String(java.util.Base64.getDecoder().decode(firstArg<String>().removePrefix("sealed:"))) }
        mockkObject(RetryWorker.Companion)
        every { RetryWorker.schedule(any()) } just Runs
        Forwarder.configure(ctx, url)
    }
    @After fun teardown() { unmockkAll() }
    @Test fun filtersBeforePersistenceAndDedupesAcrossSources() {
        Forwarder.submit(ctx, "문자 15885000", "입금 인증번호 123")
        assertEquals(0, Forwarder.pendingCount(ctx))
        Forwarder.submit(ctx, "문자 15885000", "입금 100원")
        Forwarder.submit(ctx, "알림 은행", "입금 100원")
        assertEquals(1, Forwarder.pendingCount(ctx))
        assertFalse(Prefs.of(ctx).contains("pending"))
        assertFalse(Prefs.of(ctx).contains("hook_url"))
        assertFalse(Prefs.of(ctx).all.toString().contains("입금 100원"))
        assertFalse(Forwarder.flush(ctx) { _, body -> assertEquals("입금 100원", body); 200 })
        assertEquals(0, Forwarder.pendingCount(ctx))
        assertFalse(Prefs.of(ctx).contains("pending_secret"))
        assertFalse(Forwarder.log(ctx).joinToString().contains("100원"))
        assertFalse(Forwarder.log(ctx).joinToString().contains("15885000"))
        // Dedupe information is persisted, not held in an in-memory map.
        assertEquals(1, Prefs.readList(ctx, "recent").length())
        Forwarder.submit(ctx, "알림 은행", "입금 100원")
        assertEquals(0, Forwarder.pendingCount(ctx))
    }
    @Test fun offlineRetryAndPermanentRejection() {
        Forwarder.submit(ctx, "알림", "입금 200원")
        listOf(-1, 408, 429, 503).forEach { code ->
            assertTrue(Forwarder.flush(ctx) { _, _ -> code })
            assertEquals(1, Forwarder.pendingCount(ctx))
        }
        assertFalse(Forwarder.flush(ctx) { _, _ -> 200 })
        assertEquals(0, Forwarder.pendingCount(ctx))
        Forwarder.submit(ctx, "알림", "입금 300원")
        assertFalse(Forwarder.flush(ctx) { _, _ -> 404 })
        assertEquals(0, Forwarder.pendingCount(ctx))
    }
    @Test fun pendingDedupesEvenAfterRecentWindowAndAccountChangeClearsQueue() {
        Forwarder.submit(ctx, "알림", "입금 400원")
        Prefs.writeList(ctx, "recent", JSONArray())
        Forwarder.submit(ctx, "알림", "입금 400원")
        assertEquals(1, Forwarder.pendingCount(ctx))
        Forwarder.configure(ctx, url + "new")
        assertEquals(0, Forwarder.pendingCount(ctx))
        Forwarder.flush(ctx) { _, _ -> fail("Old account data must not be sent"); 200 }
    }
    @Test fun queueIsBoundedAndExpiredContentIsDeleted() {
        repeat(51) { Forwarder.submit(ctx, "알림", "입금 ${it}원") }
        assertEquals(50, Forwarder.pendingCount(ctx))
        val pending = Prefs.readList(ctx, "pending")
        for (i in 0 until pending.length()) pending.getJSONObject(i).put("at", 1L)
        Prefs.writeList(ctx, "pending", pending)
        assertEquals(0, Forwarder.pendingCount(ctx))
        assertFalse(Prefs.of(ctx).contains("pending_secret"))
    }
}

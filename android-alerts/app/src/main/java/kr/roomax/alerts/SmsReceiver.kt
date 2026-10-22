package kr.roomax.alerts

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony
import kotlin.concurrent.thread

/** 고른 발신번호(은행)의 문자만 보낸다. 나머지 문자는 읽지도 저장하지도 않는다. */
class SmsReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return
        if (!Prefs.smsEnabled(context)) return
        val senders = Prefs.smsSenders(context)
        val bySender = LinkedHashMap<String, StringBuilder>()
        for (msg in Telephony.Sms.Intents.getMessagesFromIntent(intent) ?: return) {
            val from = Prefs.digits(msg.originatingAddress ?: continue)
            if (from !in senders) continue
            bySender.getOrPut(from) { StringBuilder() }.append(msg.messageBody ?: "")  // 긴 문자는 여러 조각
        }
        if (bySender.isEmpty()) return
        val app = context.applicationContext
        val done = goAsync()
        thread {
            try {
                bySender.forEach { (from, body) -> Forwarder.submit(app, "문자 $from", body.toString()) }
            } finally {
                done.finish()
            }
        }
    }
}

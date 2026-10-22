package kr.roomax.alerts

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import kotlin.concurrent.thread

/** 고른 앱(은행 앱)의 알림만 보낸다. 다른 앱 알림은 무시한다. */
class BankNotificationListener : NotificationListenerService() {
    override fun onNotificationPosted(sbn: StatusBarNotification) {
        if (sbn.packageName !in Prefs.apps(this)) return
        val n = sbn.notification ?: return
        if (n.flags and Notification.FLAG_GROUP_SUMMARY != 0) return  // 묶음 요약은 건너뜀 (개별 알림이 따로 옴)
        val extras = n.extras ?: return
        val title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString().orEmpty()
        val body = (extras.getCharSequence(Notification.EXTRA_BIG_TEXT)
            ?: extras.getCharSequence(Notification.EXTRA_TEXT))?.toString().orEmpty()
        val text = listOf(title, body).filter { it.isNotBlank() }.joinToString("\n")
        val app = applicationContext
        val label = try {
            packageManager.getApplicationLabel(packageManager.getApplicationInfo(sbn.packageName, 0)).toString()
        } catch (e: Exception) {
            sbn.packageName
        }
        thread { Forwarder.submit(app, "알림 $label", text) }
    }
}

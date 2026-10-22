package com.roomax.app.alerts

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.ComponentName
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.provider.Settings
import android.text.InputType
import android.view.View
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import kotlin.concurrent.thread

/** 설정 화면 하나: 연결 주소 · 문자(발신번호) · 앱 알림(앱 고르기) · '입금'만 · 보낸 기록 */
class AlertSettingsActivity : Activity() {
    private lateinit var url: EditText
    private lateinit var senders: EditText
    private lateinit var smsOn: CheckBox
    private lateinit var depositOnly: CheckBox
    private lateinit var listenerStatus: TextView
    private lateinit var appsLabel: TextView
    private lateinit var pending: TextView
    private lateinit var log: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val p = Prefs.of(this)
        val col = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(40, 40, 40, 80) }

        col.addView(head("1. ROOMAX 연결 주소"))
        col.addView(note("ROOMAX → 설정 → 입금 알림에서 '연결 주소 만들기'로 받은 주소를 붙여 넣으세요. 이 주소가 비밀번호 역할을 합니다."))
        url = EditText(this).apply {
            hint = "https://…/api/v1/bank-alerts/hook/…"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            setText(Prefs.hookUrl(this@AlertSettingsActivity))
        }
        col.addView(url)

        col.addView(head("2. 은행 문자"))
        smsOn = CheckBox(this).apply { text = "은행 문자 보내기"; isChecked = Prefs.smsEnabled(this@AlertSettingsActivity) }
        col.addView(smsOn)
        col.addView(note("발신번호 (쉼표로 여러 개). 우리은행 기본값 ${Prefs.DEFAULT_SENDERS} — 실제 입금 문자의 번호를 확인해 고치세요."))
        senders = EditText(this).apply {
            inputType = InputType.TYPE_CLASS_TEXT
            setText(p.getString("sms_senders", Prefs.DEFAULT_SENDERS))
        }
        col.addView(senders)

        col.addView(head("3. 은행 앱 알림"))
        listenerStatus = TextView(this)
        col.addView(listenerStatus)
        col.addView(button("알림 접근 허용하기") {
            startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        })
        col.addView(note("허용 목록에 안 보이거나 '제한된 설정'이라고 나오면: 설정 → 앱 → ROOMAX → 오른쪽 위 ⋮ → '제한된 설정 허용' 뒤 다시 시도하세요."))
        appsLabel = TextView(this)
        col.addView(appsLabel)
        col.addView(button("알림 보낼 앱 고르기") { pickApps() })

        col.addView(head("4. 보내는 범위"))
        depositOnly = CheckBox(this).apply { text = "'입금'이 들어간 것만 보내기 (권장)"; isChecked = Prefs.depositOnly(this@AlertSettingsActivity) }
        col.addView(depositOnly)

        col.addView(button("저장") { save() })

        col.addView(head("보낸 기록"))
        pending = TextView(this)
        col.addView(pending)
        col.addView(button("못 보낸 것 다시 보내기") { thread { Forwarder.flush(applicationContext); runOnUiThread { refresh() } } })
        log = TextView(this).apply { textSize = 13f }
        col.addView(log)

        setContentView(ScrollView(this).apply { addView(col) })
    }

    override fun onResume() {
        super.onResume()
        refresh()
        thread { Forwarder.flush(applicationContext); runOnUiThread { refresh() } }
    }

    private fun save() {
        val u = url.text.toString().trim()
        if (u.isNotEmpty() && !Forwarder.isHookUrl(u)) {
            toast("연결 주소가 아닙니다 — https:// 로 시작하고 /api/v1/bank-alerts/hook/ 이 들어 있어야 합니다")
            return
        }
        Prefs.of(this).edit()
            .putString("hook_url", u)
            .putString("sms_senders", senders.text.toString().trim())
            .putBoolean("sms_enabled", smsOn.isChecked)
            .putBoolean("deposit_only", depositOnly.isChecked)
            .apply()
        if (smsOn.isChecked && checkSelfPermission(Manifest.permission.RECEIVE_SMS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.RECEIVE_SMS), 1)
        }
        toast("저장했습니다")
        refresh()
    }

    private fun pickApps() {
        val launcher = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        val apps = packageManager.queryIntentActivities(launcher, 0)
            .map { it.activityInfo.packageName to it.loadLabel(packageManager).toString() }
            .distinctBy { it.first }
            .filter { it.first != packageName }
            .sortedWith(compareByDescending<Pair<String, String>> { looksLikeBank(it) }.thenBy { it.second })
        val chosen = Prefs.apps(this).toMutableSet()
        val checked = BooleanArray(apps.size) { apps[it].first in chosen }
        AlertDialog.Builder(this)
            .setTitle("알림을 보낼 앱")
            .setMultiChoiceItems(apps.map { it.second }.toTypedArray(), checked) { _, i, on ->
                if (on) chosen.add(apps[i].first) else chosen.remove(apps[i].first)
            }
            .setPositiveButton("확인") { _, _ ->
                Prefs.of(this).edit().putStringSet("apps", chosen).apply()
                refresh()
            }
            .setNegativeButton("취소", null)
            .show()
    }

    private fun looksLikeBank(app: Pair<String, String>): Boolean =
        listOf("bank", "woori", "은행", "뱅크", "뱅킹", "SOL", "원큐", "콕").any {
            app.first.contains(it, ignoreCase = true) || app.second.contains(it, ignoreCase = true)
        }

    private fun refresh() {
        listenerStatus.text = if (listenerEnabled()) "알림 접근: 허용됨" else "알림 접근: 아직 허용 안 됨"
        val labels = Prefs.apps(this).map { pkg ->
            try { packageManager.getApplicationLabel(packageManager.getApplicationInfo(pkg, 0)).toString() } catch (e: Exception) { pkg }
        }
        appsLabel.text = if (labels.isEmpty()) "고른 앱: 없음" else "고른 앱: " + labels.joinToString(", ")
        val n = Forwarder.pendingCount(this)
        pending.text = if (n == 0) "못 보낸 알림 없음" else "못 보낸 알림 ${n}건 (인터넷이 되면 다시 보냄)"
        log.text = Forwarder.log(this).joinToString("\n").ifEmpty { "아직 보낸 것이 없습니다" }
    }

    private fun listenerEnabled(): Boolean {
        val me = ComponentName(this, BankNotificationListener::class.java).flattenToString()
        return (Settings.Secure.getString(contentResolver, "enabled_notification_listeners") ?: "").contains(me)
    }

    private fun head(t: String) = TextView(this).apply { text = t; textSize = 18f; setPadding(0, 40, 0, 8) }
    private fun note(t: String) = TextView(this).apply { text = t; textSize = 13f; alpha = 0.7f }
    private fun button(t: String, onClick: () -> Unit) = Button(this).apply {
        text = t
        setOnClickListener(View.OnClickListener { onClick() })
    }
    private fun toast(t: String) = Toast.makeText(this, t, Toast.LENGTH_LONG).show()
}

# ROOMAX: independent Android applications

| App | Project | Application ID / namespace | Workflow | APK artifact |
| --- | --- | --- | --- | --- |
| Web TWA | `android/` | `com.roomax.app` | `android-apk.yml` / Android TWA APK | `roomax-apk` (signed) / `roomax-apk-unsigned` |
| Bank alert forwarding | `android-alerts/` | `kr.roomax.alerts` | `android.yml` / Android Alerts APK | `roomax-alerts-apk` (debug), `roomax-alerts-release` (signed, when configured) |

Both use JDK 17, Gradle 8.14.3, AGP 8.7.3 and SDK 35. Alerts additionally uses Kotlin 2.0.21 and WorkManager 2.9.1 (minimum Android 8). TWA minimum Android 6 and Chrome. Each root has its own settings, dependencies, manifest and build directory; no bank permission or Kotlin source is added to the TWA.

## Build and checks

Install JDK 17, Gradle 8.14.3 and Android SDK command-line tools. Set ANDROID_HOME, accept SDK licenses, then:

```sh
sdkmanager 'platforms;android-35' 'build-tools;35.0.0'
gradle -p android --no-daemon :app:lintRelease :app:assembleRelease
gradle -p android-alerts --no-daemon :app:testDebugUnitTest :app:lintDebug :app:assembleDebug :app:assembleRelease
cd backend
python -m pip install -r requirements-dev.txt pyflakes
python -m pyflakes app tests api
python -m pytest -q
cd ../frontend
npm ci
npm run lint
ROOMAX_API_ORIGIN=http://127.0.0.1:8000 npm run build
cd ../e2e
npm ci
npx playwright install --with-deps chromium
# Start a disposable PostgreSQL database first; never point E2E at production.
ROOMAX_DATABASE_URL=postgresql://roomax:roomax@127.0.0.1:5432/roomax_e2e npx playwright test
```

Do not use the obsolete setup-android `sdkmanager tools` step. CI uses the runner's command-line tools and explicitly installs SDK packages.

## Signing and downloads

TWA retains existing ANDROID_KEYSTORE_BASE64 / ANDROID_KEYSTORE_PASSWORD, alias `roomax`, digital asset links and `ROOMAX.apk` URL. Never replace its signing key.

Alerts uses separate ANDROID_ALERTS_KEYSTORE_BASE64 / ANDROID_ALERTS_KEYSTORE_PASSWORD, alias `roomax-alerts`. Release signing variables are ROOMAX_ALERTS_KEYSTORE / ROOMAX_ALERTS_KEYSTORE_PASSWORD. Keep this key stable for upgrades. Without it, CI verifies debug and unsigned release builds but does not publish a debug build as a release. Debug builds can require uninstall/reconfiguration between runners; use only for testing. Existing debug alerts installations may need uninstall before installing the signed build.

Alerts release stays at `releases/download/android-latest/roomax-alerts.apk`, explicitly prerelease and never `latest`, so it does not replace the TWA download. No secrets are passed to pull-request builds. No release is published from the repair branch.

## Data handling

- Only selected SMS senders / selected notification packages, no notification group summaries.
- Default deposit-only mode; deny OTP/authentication and advertising text even when broad forwarding is selected. This is a conservative text filter, not a guarantee that every bank template is recognized. Validate anonymized real examples before deployment.
- No collection without a configured HTTPS hook; reject userinfo/query/fragment and redirects.
- Keystore AES-GCM encrypts webhook token and pending bodies. Auto backup / device transfer excluded.
- Pending max 50, seven-day TTL; remove after successful delivery or permanent rejection. Expiry is enforced on app/worker execution, not while Android has force-stopped the app. Queue saturation discards oldest with a content-free status entry.
- Durable SHA-256 dedupe for 10 minutes; pending duplicates remain blocked until delivered/removed. Identical text from SMS and notification is deduped; differing bank templates can still reach the server, whose existing transaction dedupe remains essential. Identical genuine deposits inside the window may also be suppressed: verify bank timestamps/template behavior on device.
- WorkManager retries connectivity failures, 408, 429, 5xx with backoff; persists across process death/reboot. Android battery restrictions/force-stop can delay delivery. Periodic recovery is best effort, not exact-time delivery.
- Endpoint change clears old queue/dedupe so an old account's data cannot go to a new account.
- History stores only timestamp, source category and outcome, max 30 entries. No message body, sender number, token or app label.
- Transport is at-least-once: a crash after server acceptance but before checkpoint may replay; backend idempotency is required.

## Verification limits

JVM policy tests exercise filtering, allowlists, endpoint validation, retry classification and TTL. Robolectric tests exercise real SharedPreferences/outbox behavior with mocked transport, scheduler and encryption boundary. They do **not** verify hardware Keystore, real SMS permissions, actual notification delivery, OS reboot/battery policy or a signed upgrade. Run these on a test phone using synthetic bank messages before enabling live forwarding. Verify both app IDs install side by side, TWA opens the intended domain, offline queue survives restart, reconnection delivers once, and no plaintext remains in preferences/backups/history.

## Concurrent PR #22

During work, #22 changed to a single-APK implementation. This PR is the requested separate-app alternative based on main including #21/#23/#24 and the original #22 forwarding feature. Do not merge both alternatives blindly. If #22 is merged first, rebase this branch, preserve unrelated changes and retain the two-app structure specified above.

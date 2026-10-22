# 안드로이드 설치 파일(APK)

ROOMAX 화면(https://oneroom-ten.vercel.app)을 주소창 없이 띄우는 **껍데기 앱(TWA)** 입니다.
장부·연락처는 앱 안에 저장하지 않고 늘 서버에서 새로 받습니다 (홈 화면 앱(PWA) 정책과 같음).
화면을 고치면 APK 를 다시 만들 필요 없이 바로 반영됩니다.

같은 APK 에 두 번째 아이콘 **ROOMAX 입금 알림**이 있습니다 — 고른 은행 문자·은행 앱 알림 중 '입금'이 들어간 것만
ROOMAX 연결 주소(설정 → 입금 알림 자동 연결)로 보냅니다. 설정 방법은 그 카드의 '2단계 — 안드로이드' 안내를 따르세요.

## 1. 처음 한 번 — 서명 키를 GitHub 에 넣기

서명 키(`roomax-release.p12`)와 비밀번호는 저장소에 넣지 않습니다. **잃어버리면 이 앱을 업데이트할 수 없으니**
비밀번호 관리자나 USB 등 두 곳에 보관하세요.

GitHub 저장소 → Settings → Secrets and variables → Actions → New repository secret

| 이름 | 값 |
|---|---|
| `ANDROID_KEYSTORE_BASE64` | 키 파일을 base64 로 바꾼 글자 (`base64 -w0 roomax-release.p12`) |
| `ANDROID_KEYSTORE_PASSWORD` | 키 비밀번호 |

키의 지문(SHA-256)은 `frontend/public/.well-known/assetlinks.json` 에 들어 있습니다. 키를 바꾸면 이 지문도 바꿔야
주소창이 숨겨집니다 (`keytool -list -v -keystore roomax-release.p12` 의 SHA256).

## 2. APK 만들기

GitHub → Actions → **Android APK** → Run workflow → 끝나면 실행 화면 아래 Artifacts 의 `roomax-apk` 를 내려받아 압축을 풉니다.

'Run workflow' 로 만든 것은 Release 에도 올라갑니다 — 휴대폰 브라우저에서 로그인 없이 바로 받는 주소:
<https://github.com/coba8002-code/Oneroom/releases/latest/download/ROOMAX.apk>

## 3. 휴대폰에 설치

1. `app-release.apk` 를 휴대폰으로 옮겨 엽니다 (카카오톡 '나에게 보내기'·구글 드라이브 등).
2. "출처를 알 수 없는 앱" 설치를 그 앱(파일 관리자·드라이브)에 한 번 허용합니다.
3. 설치 → ROOMAX 아이콘으로 엽니다. 휴대폰에 **크롬**이 있어야 합니다.

화면 위에 주소창이 보이면 사이트의 `/.well-known/assetlinks.json` 이 아직 배포되지 않았거나 지문이 다른 것입니다.

## 바꿀 때

- 주소가 바뀌면: `android/app/src/main/res/values/strings.xml` 의 host·launch_url·asset_statements
- 새 APK 는 실행 번호로 버전이 올라가므로 그대로 덮어 설치됩니다 (같은 키로 서명해야 함).

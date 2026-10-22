plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")  // 입금 알림 전달(문자·은행 앱 알림) — com/roomax/app/alerts
}

// 서명 키는 저장소에 두지 않는다 — CI(GitHub Actions)가 비밀값에서 꺼내 경로·비밀번호를 환경 변수로 넘김
val keystorePath: String? = System.getenv("ROOMAX_KEYSTORE")
val keystorePassword: String? = System.getenv("ROOMAX_KEYSTORE_PASSWORD")

android {
    namespace = "com.roomax.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.roomax.app"
        minSdk = 23
        targetSdk = 35
        // 새 APK 를 덮어 설치하려면 versionCode 가 커야 함 — CI 실행 번호를 씀
        versionCode = (System.getenv("GITHUB_RUN_NUMBER") ?: "1").toInt()
        versionName = "1.0.${System.getenv("GITHUB_RUN_NUMBER") ?: "0"}"
    }

    signingConfigs {
        if (keystorePath != null && keystorePassword != null) {
            create("release") {
                storeFile = file(keystorePath)
                storePassword = keystorePassword
                keyAlias = "roomax"
                keyPassword = keystorePassword
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.findByName("release")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    implementation("com.google.androidbrowserhelper:androidbrowserhelper:2.5.0")
}

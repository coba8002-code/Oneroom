plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "kr.roomax.alerts"
    compileSdk = 35

    defaultConfig {
        applicationId = "kr.roomax.alerts"
        minSdk = 26
        targetSdk = 35
        versionCode = (System.getenv("GITHUB_RUN_NUMBER") ?: "1").toInt()
        versionName = "1.0.${System.getenv("GITHUB_RUN_NUMBER") ?: "0"}"
    }

    testOptions { unitTests.isIncludeAndroidResources = true }

    buildTypes {
        release { isMinifyEnabled = false }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}


dependencies {
    implementation("androidx.work:work-runtime-ktx:2.9.1")
    testImplementation("junit:junit:4.13.2")
    testImplementation("io.mockk:mockk:1.13.13")
    testImplementation("org.robolectric:robolectric:4.14.1")
    testImplementation("androidx.work:work-testing:2.9.1")
}

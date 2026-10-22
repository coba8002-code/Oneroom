// ROOMAX 안드로이드 앱 (TWA) — 화면은 웹(oneroom-ten.vercel.app)을 그대로 띄우고, 앱은 껍데기만
pluginManagement {
    repositories { google(); mavenCentral(); gradlePluginPortal() }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories { google(); mavenCentral() }
}
rootProject.name = "roomax-android"
include(":app")

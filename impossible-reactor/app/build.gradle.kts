plugins { id("com.android.application") }

android {
    namespace = "com.oryx.impossiblereactor"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.oryx.impossiblereactor.fixed"
        minSdk = 24
        targetSdk = 35
        versionCode = 1
        versionName = "3.1-fixed"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }
}

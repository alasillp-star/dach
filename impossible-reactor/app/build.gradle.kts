plugins { id("com.android.application") }

android {
    namespace = "com.oryx.impossiblereactor"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.oryx.impossiblereactor"
        minSdk = 24
        targetSdk = 35
        versionCode = 3
        versionName = "3.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }
}

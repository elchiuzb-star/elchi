import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
    // Reads app/google-services.json (gitignored; Firebase project with clients for uz.elchi.app and .dev).
    alias(libs.plugins.google.services)
}

// Developer overrides live in local.properties (not committed), e.g. `elchi.apiBaseUrl=http://192.168.0.170:8000/api/v1`
// for a real phone on the same Wi-Fi.
val localProps = Properties().apply {
    rootProject.file("local.properties").takeIf { it.exists() }?.inputStream()?.use { load(it) }
}

// The web hosts whose `/r/<code>` links open the app (App Links, Q107). The one place they are named: the manifest
// placeholders and `BuildConfig.LINK_HOSTS` (the link parser) are both filled from here. Exactly two, primary first.
val linkHosts = listOf("www.elchigo.uz", "elchigo.uz")

android {
    namespace = "uz.elchi.app"
    compileSdk = 37

    defaultConfig {
        // Kept from the first Android app: referral App Links (Q107) and the Play listing are bound to it.
        applicationId = "uz.elchi.app"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "2.0.0"
        // Q137: the backend decides the OTP length and refuses any other.
        buildConfigField("int", "OTP_LENGTH", "4")
        buildConfigField("String", "LINK_HOSTS", "\"${linkHosts.joinToString(",")}\"")
        manifestPlaceholders["linkHost"] = linkHosts[0]
        manifestPlaceholders["linkHostAlt"] = linkHosts[1]
        // Yandex MapKit key from local.properties `elchi.mapkitKey` (never committed). Empty = the map shows its
        // placeholder and the point picker works through search and district centres.
        buildConfigField("String", "MAPKIT_KEY", "\"${localProps.getProperty("elchi.mapkitKey") ?: ""}\"")
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    androidResources {
        // Only the app's two languages; library translations for other locales are dropped.
        localeFilters += listOf("uz", "ru")
    }

    buildTypes {
        debug {
            // 10.0.2.2 is the host machine as seen from the Android emulator.
            val api = localProps.getProperty("elchi.apiBaseUrl") ?: "http://10.0.2.2:8000/api/v1"
            buildConfigField("String", "API_BASE_URL", "\"$api\"")
            applicationIdSuffix = ".dev"
            resValue("string", "app_name", "Elchi dev")
        }
        release {
            buildConfigField("String", "API_BASE_URL", "\"https://api.elchigo.uz/api/v1\"")
            resValue("string", "app_name", "Elchi")
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    buildFeatures {
        compose = true
        buildConfig = true
        resValues = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

kotlin {
    jvmToolchain(17)
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.core.splashscreen)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.navigation.compose)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.datastore.preferences)
    implementation(libs.androidx.exifinterface)

    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.material3)
    implementation(libs.compose.ui.tooling.preview)
    debugImplementation(libs.compose.ui.tooling)

    implementation(libs.kotlinx.serialization.json)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.okhttp)
    implementation(libs.yandex.mapkit)
    // FCM push (ADR-0022): data-only messages, the app builds the notification itself. No Analytics.
    implementation(platform(libs.firebase.bom))
    implementation(libs.firebase.messaging)
    // Driver GPS publishing (Stage 09): fused location for the foreground service.
    implementation(libs.play.services.location)

    testImplementation(libs.junit)
    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.okhttp.mockwebserver)
}

import com.google.protobuf.gradle.id
import com.google.protobuf.gradle.proto
import java.security.MessageDigest
import com.google.protobuf.gradle.*

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.google.protobuf")
}

val appVersion = providers.environmentVariable("TELEMACHUS_VERSION").getOrElse("0.0.0")
val protobufVersion = "4.32.1"
val versionParts = appVersion.split(".")
require(versionParts.size == 3 && versionParts.all { part -> part.toIntOrNull() != null }) {
    "TELEMACHUS_VERSION must be a semantic version, got '$appVersion'."
}
val computedVersionCode =
    100_000 +
        (
            versionParts[0].toInt() * 10000 +
                versionParts[1].toInt() * 100 +
                versionParts[2].toInt()
        )
val releaseStoreFile = providers.environmentVariable("TELEMACHUS_KEYSTORE_FILE")
val releaseStorePassword = providers.environmentVariable("TELEMACHUS_KEYSTORE_PASSWORD")
val releaseKeyAlias = providers.environmentVariable("TELEMACHUS_KEY_ALIAS")
val releaseKeyPassword = providers.environmentVariable("TELEMACHUS_KEY_PASSWORD")
val releaseSigningConfigured =
    listOf(releaseStoreFile, releaseStorePassword, releaseKeyAlias, releaseKeyPassword)
        .all { it.isPresent && it.get().isNotBlank() }
val releasePackagingRequested =
    gradle.startParameter.taskNames.any {
        it.substringAfterLast(":") == "assembleRelease" || it.substringAfterLast(":") == "bundleRelease"
    }

if (releasePackagingRequested && !releaseSigningConfigured) {
    throw GradleException(
        "Release signing is not configured. Set TELEMACHUS_KEYSTORE_FILE, " +
            "TELEMACHUS_KEYSTORE_PASSWORD, TELEMACHUS_KEY_ALIAS, and " +
            "TELEMACHUS_KEY_PASSWORD.",
    )
}

android {
    namespace = "dev.telemachus.display"
    compileSdk = 34

    // AGP reads this experimental property (values: "4k" | "16k" | "64k").
    // The obsolete gradle.properties key android.nativeLibrary.alignment is ignored.
    experimentalProperties["android.nativeLibraryAlignmentPageSize"] = "16k"

    defaultConfig {
        applicationId = "dev.telemachus.display"
        minSdk = 26
        //noinspection OldTargetApi
        targetSdk = 34 // Match the currently installed SDK; API compatibility is covered in CI.
        versionCode = computedVersionCode
        versionName = appVersion
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    signingConfigs {
        if (releaseSigningConfigured) {
            create("release") {
                storeFile = file(releaseStoreFile.get())
                storePassword = releaseStorePassword.get()
                keyAlias = releaseKeyAlias.get()
                keyPassword = releaseKeyPassword.get()
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = if (releaseSigningConfigured) signingConfigs.getByName("release") else null
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }

    kotlinOptions {
        jvmTarget = "11"
    }

    buildFeatures {
        viewBinding = true
    }

    sourceSets {
        getByName("main").assets.srcDir(layout.buildDirectory.dir("generated/oss-notices"))
        getByName("main").proto {
            srcDir(rootProject.projectDir.parentFile.parentFile.resolve("contracts/proto"))
        }
    }

    testOptions {
        unitTests.isReturnDefaultValues = true
    }
}

protobuf {
    protoc {
        artifact = "com.google.protobuf:protoc:$protobufVersion"
    }
    generateProtoTasks {
        all().configureEach {
            builtins {
                id("java") {
                    option("lite")
                }
            }
        }
    }
}

val syncOpenSourceNotices by tasks.registering(Sync::class) {
    from(rootProject.projectDir.parentFile) {
        include("LICENSE", "NOTICE", "licenses/Apache-2.0.txt")
    }
    from(rootProject.projectDir.parentFile.parentFile.resolve("third_party/gson")) {
        include("LICENSE", "METADATA.json")
        into("licenses/gson")
    }
    from(rootProject.projectDir.parentFile.parentFile.resolve("third_party/webrtc-android")) {
        include("METADATA.json", "PATENTS", "WEBRTC_LICENSE", "WEBRTC_THIRD_PARTY_LICENSES.md", "WRAPPER_LICENSE")
        into("licenses/webrtc-android")
    }
    from(rootProject.projectDir.resolve("licenses/protobuf")) {
        include("LICENSE")
        into("licenses/protobuf")
    }
    into(layout.buildDirectory.dir("generated/oss-notices"))
}

val generateReleaseDependencyLicenses by tasks.registering {
    val outputFile =
        layout.buildDirectory.file(
            "generated/dependency-license-report/ANDROID_RUNTIME_DEPENDENCY_LICENSES.md",
        )
    outputs.file(outputFile)

    doLast {
        val permittedApacheGroups =
            listOf(
                "androidx.",
                "com.google.android.material",
                "com.google.auto.value",
                "com.google.errorprone",
                "com.google.guava",
                "com.google.zxing",
                "org.jetbrains",
            )
        val permittedApacheDependencies =
            setOf("com.google.code.gson:gson:2.13.1")
        val permittedBsdDependencies =
            setOf("io.github.webrtc-sdk:android:144.7559.09")
        val permittedProtobufDependencies =
            setOf("com.google.protobuf:protobuf-javalite:$protobufVersion")
        val dependencies =
            configurations
                .getByName("releaseRuntimeClasspath")
                .resolvedConfiguration
                .resolvedArtifacts
                .map { artifact ->
                    val id = artifact.moduleVersion.id
                    Triple(id.group, artifact.name, id.version)
                }.distinct()
                .sortedWith(compareBy({ it.first }, { it.second }, { it.third }))
        val unknown =
            dependencies.filter { dependency ->
                val coordinate = "${dependency.first}:${dependency.second}:${dependency.third}"
                permittedApacheGroups.none { prefix -> dependency.first.startsWith(prefix) } &&
                    coordinate !in permittedApacheDependencies &&
                    coordinate !in permittedBsdDependencies &&
                    coordinate !in permittedProtobufDependencies
            }
        check(unknown.isEmpty()) {
            "Review and classify new runtime dependency licenses: " +
                unknown.joinToString { "${it.first}:${it.second}:${it.third}" }
        }

        val report =
            buildString {
                appendLine("# Android Runtime Dependency Licenses")
                appendLine()
                appendLine("Generated from `releaseRuntimeClasspath`; test-only dependencies are excluded.")
                appendLine()
                appendLine("| Dependency | License |")
                appendLine("| --- | --- |")
                dependencies.forEach { (group, name, version) ->
                    val coordinate = "$group:$name:$version"
                    val license =
                        when {
                            coordinate == "io.github.webrtc-sdk:android:144.7559.09" ->
                                "WebRTC BSD-3-Clause plus bundled third-party terms " +
                                    "(`licenses/webrtc-android/WEBRTC_THIRD_PARTY_LICENSES.md`); " +
                                    "release wrapper MIT and patent grant are bundled beside it"
                            coordinate in permittedProtobufDependencies ->
                                "BSD-3-Clause (`licenses/protobuf/LICENSE`)"
                            coordinate in permittedApacheDependencies ->
                                "Apache License 2.0 ([source](https://github.com/google/gson/tree/gson-parent-2.13.1), bundled as `licenses/gson/LICENSE`)"
                            else -> "Apache License 2.0"
                        }
                    appendLine("| `$coordinate` | $license |")
                }
                appendLine()
                appendLine("See `licenses/Apache-2.0.txt` and each linked upstream license for complete terms.")
            }
        val destination = outputFile.get().asFile
        destination.parentFile.mkdirs()
        destination.writeText(report)
    }
}

val generateReleaseSbom by tasks.registering {
    val outputFile = layout.buildDirectory.file("generated/sbom/android-runtime.spdx.json")
    outputs.file(outputFile)

    doLast {
        val dependencies =
            configurations
                .getByName("releaseRuntimeClasspath")
                .resolvedConfiguration
                .resolvedArtifacts
                .map { artifact ->
                    val id = artifact.moduleVersion.id
                    Triple(id.group, artifact.name, id.version)
                }.distinct()
                .sortedWith(compareBy({ it.first }, { it.second }, { it.third }))
        val packages =
            dependencies.joinToString(",\n") { (group, name, version) ->
                val coordinate = "$group:$name:$version"
                val licenses =
                    when (coordinate) {
                        "com.google.code.gson:gson:2.13.1" -> "Apache-2.0" to "Apache-2.0"
                        "io.github.webrtc-sdk:android:144.7559.09" -> "NOASSERTION" to "BSD-3-Clause"
                        "com.google.protobuf:protobuf-javalite:$protobufVersion" ->
                            "BSD-3-Clause" to "BSD-3-Clause"
                        else -> "Apache-2.0" to "Apache-2.0"
                    }
                """    {"SPDXID":"SPDXRef-Package-${group.replace('.', '-')}-${name.replace('.', '-')}","name":"$coordinate","versionInfo":"$version","downloadLocation":"https://repo1.maven.org/maven2/${group.replace('.', '/')}/$name/$version/","licenseConcluded":"${licenses.first}","licenseDeclared":"${licenses.second}","externalRefs":[{"referenceCategory":"PACKAGE-MANAGER","referenceType":"purl","referenceLocator":"pkg:maven/$group/$name@$version"}]}"""
            }
        val document =
            """{"spdxVersion":"SPDX-2.3","dataLicense":"CC0-1.0","SPDXID":"SPDXRef-DOCUMENT","name":"vibe-screen-android-runtime","documentNamespace":"https://vibe-screen.dev/sbom/android-runtime/$appVersion","creationInfo":{"created":"2026-08-04T00:00:00Z","creators":["Tool: vibe-screen-gradle-sbom-v1"]},"packages":[
$packages
]}"""
        val destination = outputFile.get().asFile
        destination.parentFile.mkdirs()
        destination.writeText(document + "\n")
    }
}

val auditReleaseDependencies by tasks.registering {
    dependsOn(generateReleaseDependencyLicenses, generateReleaseSbom)
    doLast {
        val repositoryRoot = rootProject.projectDir.parentFile.parentFile
        val gsonLicense = repositoryRoot.resolve("third_party/gson/LICENSE")
        val gsonMetadata = repositoryRoot.resolve("third_party/gson/METADATA.json")
        check(gsonLicense.isFile && gsonMetadata.isFile) {
            "Gson license or metadata is missing under third_party/gson"
        }
        val digest =
            MessageDigest
                .getInstance("SHA-256")
                .digest(gsonLicense.readBytes())
                .joinToString("") { "%02x".format(it) }
        check(digest == "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30") {
            "Gson Apache-2.0 license hash changed: $digest"
        }
        val runtimeArtifacts =
            configurations
                .getByName("releaseRuntimeClasspath")
                .resolvedConfiguration
                .resolvedArtifacts
        val gsonCoordinate = "com.google.code.gson:gson:2.13.1"
        val gsonArtifacts =
            runtimeArtifacts.filter {
                "${it.moduleVersion.id.group}:${it.name}:${it.moduleVersion.id.version}" == gsonCoordinate
            }
        check(gsonArtifacts.size == 1) { "Exactly $gsonCoordinate must be present in releaseRuntimeClasspath" }
        val gsonArtifactDigest =
            MessageDigest
                .getInstance("SHA-256")
                .digest(gsonArtifacts.single().file.readBytes())
                .joinToString("") { "%02x".format(it) }
        check(gsonArtifactDigest == "94855942d4992f112946d3de1c334e709237b8126d8130bf07807c018a4a2120") {
            "Gson JAR digest changed: $gsonArtifactDigest"
        }
        val webRtcCoordinate = "io.github.webrtc-sdk:android:144.7559.09"
        val webRtcArtifacts =
            runtimeArtifacts.filter {
                "${it.moduleVersion.id.group}:${it.name}:${it.moduleVersion.id.version}" == webRtcCoordinate
            }
        check(webRtcArtifacts.size == 1) { "Exactly $webRtcCoordinate must be present in releaseRuntimeClasspath" }
        val webRtcDigest =
            MessageDigest
                .getInstance("SHA-256")
                .digest(webRtcArtifacts.single().file.readBytes())
                .joinToString("") { "%02x".format(it) }
        check(webRtcDigest == "34cf91dd7497e5fe88adb76ba29ccae35db42dd6614ce548b79ce037b6d634d5") {
            "WebRTC AAR digest changed: $webRtcDigest"
        }
        val protobufCoordinate = "com.google.protobuf:protobuf-javalite:$protobufVersion"
        val protobufArtifacts =
            runtimeArtifacts.filter {
                "${it.moduleVersion.id.group}:${it.name}:${it.moduleVersion.id.version}" == protobufCoordinate
            }
        check(protobufArtifacts.size == 1) {
            "Exactly $protobufCoordinate must be present in releaseRuntimeClasspath"
        }
        val protobufArtifactDigest =
            MessageDigest
                .getInstance("SHA-256")
                .digest(protobufArtifacts.single().file.readBytes())
                .joinToString("") { "%02x".format(it) }
        check(protobufArtifactDigest == "55b046d3213f1046a2172e28e32a2bc72bbd49aebc66a4e44b99db9fff6def8e") {
            "Protobuf Java Lite JAR digest changed: $protobufArtifactDigest"
        }
        val protobufLicense = rootProject.projectDir.resolve("licenses/protobuf/LICENSE")
        check(protobufLicense.isFile) { "Protobuf BSD-3-Clause license is missing" }
        val protobufLicenseDigest =
            MessageDigest
                .getInstance("SHA-256")
                .digest(protobufLicense.readBytes())
                .joinToString("") { "%02x".format(it) }
        check(protobufLicenseDigest == "6e5e117324afd944dcf67f36cf329843bc1a92229a8cd9bb573d7a83130fea7d") {
            "Protobuf BSD-3-Clause license hash changed: $protobufLicenseDigest"
        }
        val webRtcLicenseDirectory = repositoryRoot.resolve("third_party/webrtc-android")
        val requiredWebRtcNotices =
            mapOf(
                "WRAPPER_LICENSE" to "e6b282fe6c0fb353928923470457f31b44cbab203effd60c0cde4a5bb96c8aec",
                "WEBRTC_LICENSE" to "ab00a482b6a3902e40211b43c5d0441962ea99b6cc7c25c0f243fa270b78d482",
                "PATENTS" to "01462e2068d1a04c2274f3389773014c14ed9bc3446b28303543bd3e3c064145",
                "WEBRTC_THIRD_PARTY_LICENSES.md" to "d1f9382c6878ac024155fd6d44a5977329108bb8b0a01cea40e4a2f1d7de252e",
            )
        requiredWebRtcNotices.forEach { (name, expectedDigest) ->
            val notice = webRtcLicenseDirectory.resolve(name)
            check(notice.isFile) { "Required WebRTC notice is missing: $name" }
            val noticeDigest =
                MessageDigest
                    .getInstance("SHA-256")
                    .digest(notice.readBytes())
                    .joinToString("") { "%02x".format(it) }
            check(noticeDigest == expectedDigest) { "WebRTC notice digest changed for $name: $noticeDigest" }
        }
        val licenseReport =
            layout.buildDirectory
                .file("generated/dependency-license-report/ANDROID_RUNTIME_DEPENDENCY_LICENSES.md")
                .get()
                .asFile
                .readText()
        check("com.google.code.gson:gson:2.13.1" in licenseReport) {
            "Gson is absent from the generated Android runtime license inventory"
        }
        check(webRtcCoordinate in licenseReport) {
            "WebRTC is absent from the generated Android runtime license inventory"
        }
        check(protobufCoordinate in licenseReport) {
            "Protobuf Java Lite is absent from the generated Android runtime license inventory"
        }
        val sbom = layout.buildDirectory.file("generated/sbom/android-runtime.spdx.json").get().asFile.readText()
        check("pkg:maven/com.google.code.gson/gson@2.13.1" in sbom) {
            "Gson is absent from the generated SPDX SBOM"
        }
        check("pkg:maven/io.github.webrtc-sdk/android@144.7559.09" in sbom) {
            "WebRTC is absent from the generated SPDX SBOM"
        }
        check("pkg:maven/com.google.protobuf/protobuf-javalite@$protobufVersion" in sbom) {
            "Protobuf Java Lite is absent from the generated SPDX SBOM"
        }
    }
}

syncOpenSourceNotices {
    dependsOn(generateReleaseDependencyLicenses, generateReleaseSbom)
    from(generateReleaseDependencyLicenses.map { it.outputs.files.singleFile })
    from(generateReleaseSbom.map { it.outputs.files.singleFile }) {
        into("sbom")
    }
}

tasks.named("preBuild").configure {
    dependsOn(syncOpenSourceNotices)
}

tasks
    .matching { it.name == "assembleRelease" || it.name == "bundleRelease" }
    .configureEach {
        dependsOn(auditReleaseDependencies)
        doFirst {
            check(releaseSigningConfigured) {
                "Release signing is not configured. Set TELEMACHUS_KEYSTORE_FILE, " +
                    "TELEMACHUS_KEYSTORE_PASSWORD, TELEMACHUS_KEY_ALIAS, and " +
                    "TELEMACHUS_KEY_PASSWORD."
            }
        }
    }

dependencies {
    //noinspection GradleDependency
    implementation("androidx.core:core-ktx:1.12.0")
    //noinspection GradleDependency
    implementation("androidx.appcompat:appcompat:1.6.1")
    //noinspection GradleDependency
    implementation("com.google.android.material:material:1.11.0")
    //noinspection GradleDependency
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")
    //noinspection GradleDependency
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.7.0")

    // Wireless mode (0.8.0)
    // CameraX 1.4.0+ ships a 16 KB-aligned libimage_processing_util_jni.so.
    // 1.3.x triggers Android 15+ "LOAD segment not aligned" warnings.
    //noinspection GradleDependency
    implementation("androidx.camera:camera-core:1.4.2")
    //noinspection GradleDependency
    implementation("androidx.camera:camera-camera2:1.4.2")
    //noinspection GradleDependency
    implementation("androidx.camera:camera-lifecycle:1.4.2")
    //noinspection GradleDependency
    implementation("androidx.camera:camera-view:1.4.2")
    implementation("com.google.zxing:core:3.5.3")

    // WebRTC M144 Android AAR, pinned for reproducible native packaging.
    implementation("io.github.webrtc-sdk:android:144.7559.09")
    implementation("com.google.code.gson:gson:2.13.1")
    implementation("com.google.protobuf:protobuf-javalite:$protobufVersion")

    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test:core:1.6.1")
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation("androidx.test:rules:1.6.1")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.6.1")
}

import org.jetbrains.kotlin.gradle.tasks.KotlinCompile

plugins {
    `java-library`
    id("org.jetbrains.kotlin.jvm")
}

java {
    sourceCompatibility = JavaVersion.VERSION_11
    targetCompatibility = JavaVersion.VERSION_11
}

tasks.withType<KotlinCompile>().configureEach {
    kotlinOptions.jvmTarget = "11"
}

val verifyTransportModuleBoundary by tasks.registering {
    val sources = fileTree("src/main/kotlin") { include("**/*.kt") }
    inputs.files(sources)
    doLast {
        val forbiddenImports =
            listOf(
                "android.",
                "androidx.",
                "com.google.protobuf.",
                "dev.telemachus.display.",
                "dev.vibescreen.protocol.",
            )
        val violations =
            sources.files.flatMap { source ->
                source.readLines().mapIndexedNotNull { index, line ->
                    val imported = line.removePrefix("import ").takeIf { line.startsWith("import ") }
                    if (imported != null && forbiddenImports.any(imported::startsWith)) {
                        "${source.relativeTo(projectDir)}:${index + 1}: $line"
                    } else {
                        null
                    }
                }
            }
        check(violations.isEmpty()) {
            "Transport module imports product, protocol, or platform APIs:\n${violations.joinToString("\n")}"
        }
    }
}

tasks.named("check").configure {
    dependsOn(verifyTransportModuleBoundary)
}

dependencies {
    testImplementation("junit:junit:4.13.2")
}

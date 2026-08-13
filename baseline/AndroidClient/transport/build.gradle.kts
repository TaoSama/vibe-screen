import org.gradle.api.artifacts.ExternalModuleDependency
import org.gradle.api.artifacts.ProjectDependency
import org.gradle.api.artifacts.component.ModuleComponentIdentifier
import org.gradle.api.artifacts.component.ProjectComponentIdentifier
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

data class SourceBoundaryViolation(
    val line: Int,
    val detail: String,
)

fun decodeJavaUnicodeEscapes(source: String): String =
    Regex("\\\\u+([0-9a-fA-F]{4})").replace(source) { match ->
        match.groupValues[1].toInt(16).toChar().toString()
    }

fun stripComments(source: String): String {
    val result = StringBuilder(source.length)
    var index = 0
    var blockCommentDepth = 0
    var inLineComment = false
    var inString = false
    var inTripleString = false
    var inCharacter = false
    var escaped = false

    fun blank(character: Char) {
        result.append(if (character == '\n' || character == '\r') character else ' ')
    }

    while (index < source.length) {
        val current = source[index]
        val next = source.getOrNull(index + 1)
        val third = source.getOrNull(index + 2)
        when {
            inLineComment -> {
                blank(current)
                if (current == '\n') inLineComment = false
                index++
            }
            blockCommentDepth > 0 -> {
                when {
                    current == '/' && next == '*' -> {
                        blank(current)
                        blank(next)
                        blockCommentDepth++
                        index += 2
                    }
                    current == '*' && next == '/' -> {
                        blank(current)
                        blank(next)
                        blockCommentDepth--
                        index += 2
                    }
                    else -> {
                        blank(current)
                        index++
                    }
                }
            }
            inTripleString -> {
                result.append(current)
                if (current == '"' && next == '"' && third == '"') {
                    result.append(next)
                    result.append(third)
                    inTripleString = false
                    index += 3
                } else {
                    index++
                }
            }
            inString || inCharacter -> {
                result.append(current)
                when {
                    escaped -> escaped = false
                    current == '\\' -> escaped = true
                    inString && current == '"' -> inString = false
                    inCharacter && current == '\'' -> inCharacter = false
                }
                index++
            }
            current == '/' && next == '/' -> {
                blank(current)
                blank(next)
                inLineComment = true
                index += 2
            }
            current == '/' && next == '*' -> {
                blank(current)
                blank(next)
                blockCommentDepth = 1
                index += 2
            }
            current == '"' && next == '"' && third == '"' -> {
                result.append(current)
                result.append(next)
                result.append(third)
                inTripleString = true
                index += 3
            }
            current == '"' -> {
                result.append(current)
                inString = true
                index++
            }
            current == '\'' -> {
                result.append(current)
                inCharacter = true
                index++
            }
            else -> {
                result.append(current)
                index++
            }
        }
    }
    return result.toString()
}

fun sourceBoundaryViolations(source: String): List<SourceBoundaryViolation> {
    val normalized =
        stripComments(decodeJavaUnicodeEscapes(source))
            .replace(Regex("`([A-Za-z_][A-Za-z0-9_]*)`")) { match -> match.groupValues[1] }
            .replace(Regex("[\\t ]+"), " ")
            .replace(Regex("\\s*\\.\\s*"), ".")
    val forbiddenRoot =
        Regex(
            "(?<![A-Za-z0-9_])(?:" +
                "android(?:\\.[A-Za-z_][A-Za-z0-9_]*)+|" +
                "androidx(?:\\.[A-Za-z_][A-Za-z0-9_]*)+|" +
                "com\\.google\\.protobuf(?:\\.[A-Za-z_][A-Za-z0-9_]*)*|" +
                "dev\\.vibescreen\\.protocol(?:\\.[A-Za-z_][A-Za-z0-9_]*)*|" +
                "dev\\.telemachus\\.display(?:\\.[A-Za-z_][A-Za-z0-9_]*)+" +
                ")",
        )
    val violations = mutableListOf<SourceBoundaryViolation>()
    forbiddenRoot.findAll(normalized).forEach { match ->
        val reference = match.value
        val isOwnedTransportReference =
            reference == "dev.telemachus.display.transport" ||
                reference.startsWith("dev.telemachus.display.transport.")
        if (!isOwnedTransportReference) {
            violations +=
                SourceBoundaryViolation(
                    line = normalized.take(match.range.first).count { it == '\n' } + 1,
                    detail = "forbidden reference `$reference`",
                )
        }
    }

    val packageDeclaration =
        Regex("(?m)^\\s*package\\s+([A-Za-z_][A-Za-z0-9_]*(?:\\.[A-Za-z_][A-Za-z0-9_]*)*)")
            .find(normalized)
    if (packageDeclaration == null) {
        violations += SourceBoundaryViolation(1, "missing transport package declaration")
    } else {
        val packageName = packageDeclaration.groupValues[1]
        if (packageName != "dev.telemachus.display.transport" &&
            !packageName.startsWith("dev.telemachus.display.transport.")
        ) {
            violations +=
                SourceBoundaryViolation(
                    line = normalized.take(packageDeclaration.range.first).count { it == '\n' } + 1,
                    detail = "package `$packageName` is outside the transport module namespace",
                )
        }
    }
    return violations.distinct()
}

val allowedKotlinRuntimeModules =
    setOf("kotlin-stdlib", "kotlin-stdlib-common", "kotlin-stdlib-jdk7", "kotlin-stdlib-jdk8")

fun isAllowedRuntimeModule(
    group: String?,
    name: String,
): Boolean = group == "org.jetbrains.kotlin" && name in allowedKotlinRuntimeModules

fun isKotlinCompilerSupportModule(identifier: ModuleComponentIdentifier): Boolean =
    identifier.group == "org.jetbrains" &&
        identifier.module == "annotations" &&
        identifier.version == "13.0"

fun dependencyFixtureViolation(parts: List<String>): String? =
    when (parts.getOrNull(1)) {
        "external" ->
            if (isAllowedRuntimeModule(parts.getOrNull(2), parts.getOrNull(3).orEmpty())) {
                null
            } else {
                "external dependency ${parts.drop(2).joinToString(":")}"
            }
        "project" -> "project dependency ${parts.getOrNull(2)}"
        "file" -> "file dependency ${parts.getOrNull(2)}"
        else -> "unknown dependency kind ${parts.getOrNull(1)}"
    }

val mainBoundarySources =
    fileTree("src/main") {
        include("**/*.kt", "**/*.kts", "**/*.java")
    }
val boundaryFixtures = layout.projectDirectory.dir("src/boundaryTest/fixtures")

val testTransportBoundaryVerifier by tasks.registering {
    inputs.dir(boundaryFixtures)
    doLast {
        val forbidden =
            boundaryFixtures.dir("forbidden").asFileTree.matching {
                include("**/*.kt", "**/*.kts", "**/*.java")
            }.files
        val allowed =
            boundaryFixtures.dir("allowed").asFileTree.matching {
                include("**/*.kt", "**/*.kts", "**/*.java")
            }.files
        check(forbidden.isNotEmpty() && allowed.isNotEmpty()) { "Boundary verifier fixtures are missing" }
        forbidden.forEach { fixture ->
            check(sourceBoundaryViolations(fixture.readText()).isNotEmpty()) {
                "Negative boundary fixture was not rejected: ${fixture.name}"
            }
        }
        allowed.forEach { fixture ->
            val violations = sourceBoundaryViolations(fixture.readText())
            check(violations.isEmpty()) {
                "Allowed boundary fixture was rejected: ${fixture.name}: ${violations.joinToString { it.detail }}"
            }
        }
        boundaryFixtures.file("dependency-cases.txt").asFile.readLines()
            .filter { it.isNotBlank() && !it.startsWith("#") }
            .forEach { fixture ->
                val parts = fixture.split('|')
                val violation = dependencyFixtureViolation(parts)
                when (parts.firstOrNull()) {
                    "forbidden" -> check(violation != null) { "Negative dependency fixture was accepted: $fixture" }
                    "allowed" -> check(violation == null) { "Allowed dependency fixture was rejected: $fixture" }
                    else -> error("Unknown dependency fixture expectation: $fixture")
                }
            }
    }
}

val verifyTransportModuleBoundary by tasks.registering {
    inputs.files(mainBoundarySources)
    doLast {
        val sourceViolations =
            mainBoundarySources.files.flatMap { source ->
                sourceBoundaryViolations(source.readText()).map { violation ->
                    "${source.relativeTo(projectDir)}:${violation.line}: ${violation.detail}"
                }
            }
        check(sourceViolations.isEmpty()) {
            "Transport source boundary violations:\n${sourceViolations.joinToString("\n")}"
        }

        val productionDependencyBuckets =
            listOf("api", "implementation", "compileOnly", "runtimeOnly", "annotationProcessor")
        val declaredViolations =
            productionDependencyBuckets.flatMap { name ->
                val configuration = configurations.getByName(name)
                configuration.dependencies.mapNotNull { dependency ->
                    when (dependency) {
                        is ProjectDependency -> "$name declares project dependency ${dependency.dependencyProject.path}"
                        is ExternalModuleDependency -> {
                            val allowed = isAllowedRuntimeModule(dependency.group, dependency.name)
                            if (allowed) null else "$name declares external dependency ${dependency.group}:${dependency.name}"
                        }
                        else -> "$name declares unsupported dependency ${dependency.javaClass.name}"
                    }
                } +
                    configuration.dependencyConstraints.mapNotNull { constraint ->
                        if (isAllowedRuntimeModule(constraint.group, constraint.name)) {
                            null
                        } else {
                            "$name declares dependency constraint ${constraint.group}:${constraint.name}"
                        }
                    }
            }
        check(declaredViolations.isEmpty()) {
            "Transport production dependency declarations are not isolated:\n${declaredViolations.joinToString("\n")}"
        }

        // Gradle plugin/buildscript and Kotlin compiler classpaths are build tools, not
        // transport runtime dependencies, so only the two production classpaths are resolved.
        // Kotlin 1.9.22 needs the exact annotations:13.0 artifact while emitting nullability
        // metadata. It is allowed here only as compiler support; a direct declaration fails above.
        val resolvedViolations =
            listOf("compileClasspath", "runtimeClasspath").flatMap { name ->
                configurations.getByName(name).incoming.resolutionResult.allComponents.mapNotNull { component ->
                    when (val identifier = component.id) {
                        is ProjectComponentIdentifier ->
                            if (identifier.projectPath == project.path) null else "$name resolves project ${identifier.projectPath}"
                        is ModuleComponentIdentifier -> {
                            val allowed =
                                isAllowedRuntimeModule(identifier.group, identifier.module) ||
                                    isKotlinCompilerSupportModule(identifier)
                            if (allowed) null else "$name resolves external module $identifier"
                        }
                        else -> "$name resolves unsupported component $identifier"
                    }
                }
            }
        check(resolvedViolations.isEmpty()) {
            "Transport production resolution graph is not isolated:\n${resolvedViolations.joinToString("\n")}"
        }
    }
}

tasks.named("check").configure {
    dependsOn(testTransportBoundaryVerifier, verifyTransportModuleBoundary)
}

dependencies {
    testImplementation("junit:junit:4.13.2")
}

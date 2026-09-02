package dev.telemachus.display

import java.io.File
import org.junit.Assert.assertTrue
import org.junit.Test

class MainActivityInternetLeaseReceiverContractTest {
    @Test
    fun internetProductSessionWrapsCallbacksWithAuthenticatedSessionLeaseReceiver() {
        val source = mainActivitySource()
        val connectInternet = extractMethod(source, "private fun connectInternet(")

        assertContains(source, "import dev.telemachus.display.internet.AuthenticatedSessionLeaseReceiver")
        assertContains(connectInternet, "val callbacks =")
        assertContains(connectInternet, "val authenticatedSessionLeaseReceiver =")
        assertContains(connectInternet, "AuthenticatedSessionLeaseReceiver(")
        assertContains(connectInternet, "internetProfileStore,")
        assertContains(connectInternet, "internetStoredSessionFactory,")
        assertContains(connectInternet, "internetRevocationCoordinator,")
        assertContains(connectInternet, "isActive = ::isCurrentInternetSession")
        assertContains(connectInternet, "val productCallbacks = authenticatedSessionLeaseReceiver.importingCallbacks(callbacks)")
        assertContains(connectInternet, "codec,\n                    productCallbacks,")
        assertBefore(connectInternet, "val productCallbacks", "InternetProductSession.create(")
        assertBefore(connectInternet, "productCallbacks", "object : InternetProductRevocationStore")
    }

    private fun assertContains(source: String, target: String) {
        assertTrue("Missing '$target'", source.contains(target))
    }

    private fun assertBefore(source: String, first: String, second: String) {
        val firstIndex = source.indexOf(first)
        val secondIndex = source.indexOf(second)
        assertTrue("Missing '$first'", firstIndex >= 0)
        assertTrue("Missing '$second'", secondIndex >= 0)
        assertTrue("Expected '$first' before '$second'", firstIndex < secondIndex)
    }

    private fun extractMethod(source: String, signature: String): String {
        val start = source.indexOf(signature)
        require(start >= 0) { "Method not found: $signature" }
        var i = start
        var braceDepth = 0
        var inString = false
        var escaped = false
        var methodStarted = false
        while (i < source.length) {
            val current = source[i]
            when {
                inString -> {
                    if (escaped) {
                        escaped = false
                    } else if (current == '\\') {
                        escaped = true
                    } else if (current == '"') {
                        inString = false
                    }
                    i++
                }
                current == '"' -> {
                    inString = true
                    i++
                }
                current == '{' -> {
                    methodStarted = true
                    braceDepth++
                    i++
                }
                current == '}' -> {
                    braceDepth--
                    if (methodStarted && braceDepth == 0) return source.substring(start, i + 1)
                    i++
                }
                else -> i++
            }
        }
        error("Closing brace not found for $signature")
    }

    private fun mainActivitySource(): String {
        var current = File(requireNotNull(System.getProperty("user.dir"))).canonicalFile
        repeat(8) {
            MAIN_ACTIVITY_PATHS
                .map(current::resolve)
                .firstOrNull(File::isFile)
                ?.let { return it.readText() }
            current = current.parentFile?.canonicalFile ?: current
        }
        error("MainActivity.kt not found from " + System.getProperty("user.dir"))
    }

    private companion object {
        val MAIN_ACTIVITY_PATHS =
            listOf(
                "app/src/main/java/dev/telemachus/display/MainActivity.kt",
                "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/MainActivity.kt",
            )
    }
}

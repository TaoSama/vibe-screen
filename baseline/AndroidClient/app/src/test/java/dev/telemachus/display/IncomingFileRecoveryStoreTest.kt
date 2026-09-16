package dev.telemachus.display

import com.google.protobuf.ByteString
import dev.telemachus.display.protocol.CompletedIncomingFile
import dev.telemachus.display.protocol.sha256
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.StandardCopyOption
import java.security.MessageDigest
import java.util.UUID

class IncomingFileRecoveryStoreTest {
    @Test
    fun adoptPublishesVerifiedPayloadAndReloadsAfterRestart() = withFixture { fixture ->
        val payload = "recover-after-restart".toByteArray()
        val staging = fixture.stagingFile(payload)

        val adopted = fixture.store().adopt(completed(staging, payload), "report.txt")
        val restarted = fixture.store().load()

        assertEquals(adopted, restarted)
        assertArrayEquals(payload, adopted.payloadFile.readBytes())
        assertTrue("adoption must not delete protocol-owned staging", staging.exists())
        assertEquals(payload.size.toLong(), adopted.byteLength)
        assertEquals("text/plain", adopted.mimeType)
        assertFalse(fixture.recoveryDirectory.containsTemporaryFiles())
    }

    @Test
    fun adoptBeforeAcknowledgementReturnsDurablePayloadAndReleasesProtocolStaging() = withFixture { fixture ->
        val payload = "durable-before-ack".toByteArray()
        val staging = fixture.stagingFile(payload)

        val durable =
            fixture.store().adoptBeforeAcknowledgement(
                completed = completed(staging, payload),
                maxDisplayNameLength = 120,
                fallbackDisplayName = "transfer.bin",
            )

        assertFalse(staging.exists())
        assertTrue(durable.stagingFile.exists())
        assertArrayEquals(payload, durable.stagingFile.readBytes())
        assertEquals(durable.stagingFile, fixture.store().load()?.payloadFile)
    }

    @Test
    fun persistFailureLeavesProtocolStagingAndRemovesRecoveryArtifacts() = withFixture { fixture ->
        val payload = "commit-failure".toByteArray()
        val staging = fixture.stagingFile(payload)
        fixture.persistence.failPersist = true

        assertThrows(IOException::class.java) {
            fixture.store().adopt(completed(staging, payload), "report.txt")
        }

        assertTrue(staging.exists())
        assertTrue(fixture.persistence.values.isEmpty())
        assertTrue(fixture.recoveryDirectory.listFiles().orEmpty().isEmpty())
    }

    @Test
    fun persistFailureRollsBackInProcessMetadataBeforeDeletingPayload() = withFixture { fixture ->
        val payload = "commit-failure-after-write".toByteArray()
        fixture.persistence.failPersistAfterWrite = true

        assertThrows(IOException::class.java) {
            fixture.store().adopt(completed(fixture.stagingFile(payload), payload), "report.txt")
        }

        assertTrue(fixture.persistence.values.isEmpty())
        assertTrue(fixture.recoveryDirectory.listFiles().orEmpty().isEmpty())
    }

    @Test
    fun loadFailsClosedWhenPayloadBytesAreTampered() = withFixture { fixture ->
        val payload = "verified-payload".toByteArray()
        val recovery = fixture.store().adopt(completed(fixture.stagingFile(payload), payload), "report.txt")
        val tampered = payload.copyOf().also { it[0] = (it[0].toInt() xor 0x01).toByte() }
        recovery.payloadFile.writeBytes(tampered)

        assertNull(fixture.store().load())
        assertTrue(fixture.persistence.values.isEmpty())
        assertFalse(recovery.payloadFile.exists())
    }

    @Test
    fun loadFailsClosedWhenPayloadLengthChanges() = withFixture { fixture ->
        val payload = "verified-length".toByteArray()
        val recovery = fixture.store().adopt(completed(fixture.stagingFile(payload), payload), "report.txt")
        recovery.payloadFile.appendText("extra")

        assertNull(fixture.store().load())
        assertTrue(fixture.persistence.values.isEmpty())
        assertFalse(recovery.payloadFile.exists())
    }

    @Test
    fun transientDigestFailurePreservesRecoveryForRetry() = withFixture { fixture ->
        val payload = "retry-after-transient-read".toByteArray()
        val recovery = fixture.store().adopt(completed(fixture.stagingFile(payload), payload), "report.txt")
        fixture.fileOperations.failNextDigest = true

        assertThrows(IOException::class.java) { fixture.store().load() }

        assertTrue(recovery.payloadFile.exists())
        assertTrue(fixture.persistence.values.isNotEmpty())
        assertEquals(recovery, fixture.store().load())
        assertArrayEquals(payload, recovery.payloadFile.readBytes())
    }

    @Test
    fun loadRejectsEscapingPathWithoutDeletingExternalFile() = withFixture { fixture ->
        val payload = "safe-payload".toByteArray()
        val recovery = fixture.store().adopt(completed(fixture.stagingFile(payload), payload), "report.txt")
        val external = File(fixture.root, "outside.bin").apply { writeText("outside") }
        fixture.persistence.values[IncomingFileRecoveryStore.PAYLOAD_FILE_KEY] = "../outside.bin"

        assertNull(fixture.store().load())
        assertEquals("outside", external.readText())
        assertFalse(recovery.payloadFile.exists())
        assertTrue(fixture.persistence.values.isEmpty())
    }

    @Test
    fun discardDoesNotDeletePayloadWhenMarkerClearFails() = withFixture { fixture ->
        val payload = "retry-discard".toByteArray()
        val recovery = fixture.store().adopt(completed(fixture.stagingFile(payload), payload), "report.txt")
        fixture.persistence.failClear = true

        assertThrows(IOException::class.java) { fixture.store().discard(recovery) }

        assertTrue(recovery.payloadFile.exists())
        assertTrue(fixture.persistence.values.isNotEmpty())
        fixture.persistence.failClear = false
        fixture.store().discard(recovery)
        assertFalse(recovery.payloadFile.exists())
        assertNull(fixture.store().load())
    }

    @Test
    fun clearAfterSavedClearsMarkerAndPayload() = withFixture { fixture ->
        val payload = "saved-payload".toByteArray()
        val recovery = fixture.store().adopt(completed(fixture.stagingFile(payload), payload), "report.txt")

        fixture.store().clearAfterSaved(recovery)
        assertFalse(recovery.payloadFile.exists())
        assertNull(fixture.store().load())
    }

    @Test
    fun publicationLeaseIsProcessWideAcrossStoreInstancesAndReleasesOnClose() = withFixture { fixture ->
        val payload = "single-flight".toByteArray()
        val recovery = fixture.store().adopt(completed(fixture.stagingFile(payload), payload), "report.txt")
        val lease = fixture.store().beginPublication(recovery)

        assertTrue(lease != null)
        assertNull(fixture.store().beginPublication(recovery))
        lease!!.close()
        val reacquired = fixture.store().beginPublication(recovery)
        assertTrue(reacquired != null)
        reacquired!!.close()
    }

    @Test
    fun publicationStateSurvivesRestartAndPublishedRecordLoadsWithoutPayload() = withFixture { fixture ->
        val payload = "publication-state".toByteArray()
        val recovery = fixture.store().adopt(completed(fixture.stagingFile(payload), payload), "report.txt")
        val pending = fixture.store().markMediaStorePending(recovery, "content://downloads/41")
        assertEquals(IncomingFilePublicationState.MEDIASTORE_PENDING, fixture.store().load()?.publicationState)

        val published = fixture.store().markPublished(pending, "content://downloads/41")
        assertTrue(published.payloadFile.delete())
        val restarted = fixture.store().load()

        assertEquals(IncomingFilePublicationState.PUBLISHED, restarted?.publicationState)
        assertEquals("content://downloads/41", restarted?.publishedUri)
    }

    @Test
    fun publishedCleanupFailureRetainsMarkerForCleanupOnlyRetry() = withFixture { fixture ->
        val payload = "cleanup-retry".toByteArray()
        val recovery = fixture.store().adopt(completed(fixture.stagingFile(payload), payload), "report.txt")
        val pending = fixture.store().markMediaStorePending(recovery, "content://downloads/42")
        val published = fixture.store().markPublished(pending, "content://downloads/42")
        fixture.persistence.failClear = true

        assertThrows(IOException::class.java) { fixture.store().clearPublished(published) }
        assertFalse(published.payloadFile.exists())
        assertEquals(IncomingFilePublicationState.PUBLISHED, fixture.store().load()?.publicationState)

        fixture.persistence.failClear = false
        fixture.store().clearPublished(requireNotNull(fixture.store().load()))
        assertNull(fixture.store().load())
    }

    @Test
    fun existingRecoveryPreventsReplacement() = withFixture { fixture ->
        val firstPayload = "first".toByteArray()
        val first = fixture.store().adopt(completed(fixture.stagingFile(firstPayload), firstPayload), "first.txt")
        val secondPayload = "second".toByteArray()

        assertThrows(IOException::class.java) {
            fixture.store().adopt(completed(fixture.stagingFile(secondPayload), secondPayload), "second.txt")
        }

        assertEquals(first, fixture.store().load())
        assertArrayEquals(firstPayload, first.payloadFile.readBytes())
    }

    @Test
    fun staleRecordCannotDiscardReplacement() = withFixture { fixture ->
        val firstPayload = "first".toByteArray()
        val first = fixture.store().adopt(completed(fixture.stagingFile(firstPayload), firstPayload), "first.txt")
        fixture.store().discard(first)
        val secondPayload = "second".toByteArray()
        val second = fixture.store().adopt(completed(fixture.stagingFile(secondPayload), secondPayload), "second.txt")

        assertThrows(IOException::class.java) { fixture.store().discard(first) }

        assertEquals(second, fixture.store().load())
        assertArrayEquals(secondPayload, second.payloadFile.readBytes())
    }

    @Test
    fun failedAtomicMoveCleansTemporaryFileWithoutPersistingMarker() = withFixture { fixture ->
        val payload = "move-failure".toByteArray()
        fixture.fileOperations.failAtomicMove = true

        assertThrows(IOException::class.java) {
            fixture.store().adopt(completed(fixture.stagingFile(payload), payload), "report.txt")
        }

        assertTrue(fixture.persistence.values.isEmpty())
        assertTrue(fixture.recoveryDirectory.listFiles().orEmpty().isEmpty())
    }

    @Test
    fun emptyStoreRemovesControlledDanglingLinkWithoutFollowingIt() = withFixture { fixture ->
        fixture.recoveryDirectory.mkdirs()
        val external = File(fixture.root, "missing-external-target")
        val link = File(fixture.recoveryDirectory, ".payload-00000000-0000-0000-0000-000000000001.tmp")
        Files.createSymbolicLink(link.toPath(), external.toPath())

        assertNull(fixture.store().load())

        assertFalse(Files.exists(link.toPath(), LinkOption.NOFOLLOW_LINKS))
        assertFalse(external.exists())
    }

    private fun completed(
        staging: File,
        payload: ByteArray,
    ): CompletedIncomingFile =
        CompletedIncomingFile(
            transferId = ByteString.copyFromUtf8("transfer-${staging.name}"),
            fileName = "remote.txt",
            mimeType = "text/plain",
            stagingFile = staging,
            sha256 = sha256(payload),
        )

    private fun withFixture(block: (Fixture) -> Unit) {
        val root = Files.createTempDirectory("incoming-recovery-store").toFile()
        try {
            block(Fixture(root))
        } finally {
            root.deleteRecursively()
        }
    }

    private class Fixture(
        val root: File,
    ) {
        val recoveryDirectory = File(root, "recovery")
        val persistence = MemoryPersistence()
        val fileOperations = TestFileOperations()
        private var nextId = 0L

        fun store(): IncomingFileRecoveryStore =
            IncomingFileRecoveryStore(
                directory = recoveryDirectory,
                persistence = persistence,
                fileOperations = fileOperations,
                newRecoveryId = { UUID(0L, ++nextId).toString() },
            )

        fun stagingFile(payload: ByteArray): File =
            File(root, "staging-${UUID.randomUUID()}.partial").apply { writeBytes(payload) }
    }

    private class MemoryPersistence : IncomingFileRecoveryMetadataPersistence {
        val values = linkedMapOf<String, Any>()
        var failPersist = false
        var failPersistAfterWrite = false
        var failClear = false

        override fun read(): Map<String, *> = values.toMap()

        override fun persist(values: Map<String, Any>): Boolean {
            if (failPersist) return false
            this.values.clear()
            this.values.putAll(values)
            if (failPersistAfterWrite) return false
            return true
        }

        override fun clear(): Boolean {
            if (failClear) return false
            values.clear()
            return true
        }
    }

    private class TestFileOperations : IncomingFileRecoveryFileOperations {
        var failAtomicMove = false
        var failNextDigest = false

        override fun ensureDirectory(directory: File) {
            if (!directory.exists() && !directory.mkdirs()) throw IOException("mkdir failed")
            if (Files.isSymbolicLink(directory.toPath()) || !directory.isDirectory) throw IOException("not a directory")
        }

        override fun copyAndSync(
            source: File,
            destination: File,
        ): IncomingFileRecoveryCopy {
            if (!destination.createNewFile() || !isRegularFile(destination)) throw IOException("create failed")
            val digest = MessageDigest.getInstance("SHA-256")
            var length = 0L
            BufferedInputStream(source.inputStream()).use { input ->
                FileOutputStream(destination).use { rawOutput ->
                    val output = BufferedOutputStream(rawOutput)
                    val buffer = ByteArray(1024)
                    while (true) {
                        val read = input.read(buffer)
                        if (read < 0) break
                        if (read > 0) {
                            output.write(buffer, 0, read)
                            digest.update(buffer, 0, read)
                            length += read
                        }
                    }
                    output.flush()
                    rawOutput.fd.sync()
                }
            }
            return IncomingFileRecoveryCopy(length, ByteString.copyFrom(digest.digest()))
        }

        override fun atomicMove(
            source: File,
            destination: File,
        ) {
            if (failAtomicMove) throw IOException("injected move failure")
            Files.move(source.toPath(), destination.toPath(), StandardCopyOption.ATOMIC_MOVE)
        }

        override fun delete(file: File): Boolean = file.delete()

        override fun exists(file: File): Boolean = Files.exists(file.toPath(), LinkOption.NOFOLLOW_LINKS)

        override fun listFiles(directory: File): List<File> =
            directory.listFiles()?.toList() ?: throw IOException("list failed")

        override fun isRegularFile(file: File): Boolean =
            !Files.isSymbolicLink(file.toPath()) && Files.isRegularFile(file.toPath(), LinkOption.NOFOLLOW_LINKS)

        override fun digest(file: File): ByteString {
            if (failNextDigest) {
                failNextDigest = false
                throw IOException("injected transient digest failure")
            }
            return sha256(file.readBytes())
        }
    }

    private fun File.containsTemporaryFiles(): Boolean =
        listFiles().orEmpty().any { it.name.startsWith(".payload-") }
}

package dev.telemachus.display.internet

import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class InternetCredentialOwnershipPolicyTest {
    @Test
    fun existingPairingCannotBeOverwrittenAtAnyRevocationStage() {
        val stages =
            listOf(
                RevocationStage(),
                RevocationStage(pending = true),
                RevocationStage(tombstone = "pair-1"),
                RevocationStage(tombstone = "pair-1", cleanup = true),
            )

        stages.forEach { stage ->
            var verifiedPairing = "pair-1"
            var secretWritten = false
            assertTrue(
                InternetCredentialOwnershipPolicy.blocksMutation(
                    targetPairingIdentifier = "pair-2",
                    verifiedPairingIdentifier = "pair-1",
                    profilePairingIdentifier = "pair-1",
                    revokedPairingIdentifier = stage.tombstone,
                    hasPendingAuthenticatedRevocation = stage.pending,
                    hasPendingRevocationCleanup = stage.cleanup,
                ),
            )
            assertThrows(IllegalStateException::class.java) {
                InternetProductRevocationCoordinator().withCredentialMutationAdmission(
                    durableBlock = {
                        InternetCredentialOwnershipPolicy.blocksMutation(
                            targetPairingIdentifier = "pair-2",
                            verifiedPairingIdentifier = verifiedPairing,
                            profilePairingIdentifier = "pair-1",
                            revokedPairingIdentifier = stage.tombstone,
                            hasPendingAuthenticatedRevocation = stage.pending,
                            hasPendingRevocationCleanup = stage.cleanup,
                        )
                    },
                ) {
                    secretWritten = true
                    verifiedPairing = "pair-2"
                }
            }
            assertFalse(secretWritten)
            assertTrue(verifiedPairing == "pair-1")
        }
    }

    @Test
    fun replacementIsAllowedOnlyAfterOldPairingCleanupIsComplete() {
        assertTrue(
            InternetCredentialOwnershipPolicy.blocksMutation(
                targetPairingIdentifier = "pair-2",
                verifiedPairingIdentifier = null,
                profilePairingIdentifier = null,
                revokedPairingIdentifier = "pair-1",
                hasPendingAuthenticatedRevocation = false,
                hasPendingRevocationCleanup = true,
            ),
        )
        val cleanupCompleteBlock =
            InternetCredentialOwnershipPolicy.blocksMutation(
                targetPairingIdentifier = "pair-2",
                verifiedPairingIdentifier = null,
                profilePairingIdentifier = null,
                revokedPairingIdentifier = "pair-1",
                hasPendingAuthenticatedRevocation = false,
                hasPendingRevocationCleanup = false,
            )
        assertFalse(cleanupCompleteBlock)
        var replacementCommitted = false
        InternetProductRevocationCoordinator().withCredentialMutationAdmission(
            durableBlock = { cleanupCompleteBlock },
        ) {
            replacementCommitted = true
        }
        assertTrue(replacementCommitted)
    }

    private data class RevocationStage(
        val pending: Boolean = false,
        val tombstone: String? = null,
        val cleanup: Boolean = false,
    )
}

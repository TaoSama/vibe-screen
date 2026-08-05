# Phase 4 sources and dependency provenance

Audit date: 2026-08-04

| Source | Immutable version | License | Use | Copied code |
| --- | --- | --- | --- | --- |
| SideScreen, `https://github.com/tranvuongquocdat/SideScreen` | `a651a81b7d6468c7a564c038551872d3346a2d55` | MIT | Reviewed repository architecture and existing host/client behavior | No |
| Telemachus, `https://github.com/aaditagrawal/telemachus` | `a5dd1298870846d749175812f936ceebfd8b6b69` | MIT | Audited the imported legacy host protocol for compatibility limits | No new Phase 4 copy; existing snapshot retains LICENSE/NOTICE |
| TypeScript, `https://github.com/microsoft/TypeScript` | npm `5.9.3`, integrity `sha512-jl1vZzPDinLr9eUt3J/t7V6FgNEw9QjvBPdysz9KfQDD41fQrC2Y4vKQdiaUpFT4bXlb1RHhLpp8wtm6M5TgSw==` | Apache-2.0 | Test-only compiler | No |
| JSON5, `https://github.com/json5/json5` | npm `2.2.3`, integrity `sha512-XmOWe7eyHYH14cLdVPoyg+GOH3rYX++KpzrylJwSW98t3Nk+U8XOl8FWKOgwtzdb8lXGf6zYwDUzeHMWfxasyg==` | MIT | Static project-manifest parser used only by portable checks | No |
| HarmonyOS NEXT SDK / Hvigor | DevEco-managed API 12+; exact installed version must be captured by release CI | Vendor SDK/tool license | Build-time platform APIs and packaging; not redistributed | No |
| OpenHarmony interface SDK JS | `85c68ed2a9ea8437377ce0a168db747629446b0a` (`OpenHarmony-v5.0.0-Release`) | Apache-2.0 | Read-only audit of public API 12 Asset Store, ArkUI, Ability, and network declarations | No |

No code or implementation detail was taken from node-mac-virtual-display,
FreeDisplay, Sunshine, Moonlight, Weylus, or RustDesk in this change. No GPL or
AGPL code was copied. The ArkTS implementation was written directly against the
repository's Protocol v1 schemas and platform API contracts.

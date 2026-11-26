# Cross-repository investigation protocol

This is mandatory repository guidance for maintainers and coding agents investigating LiveContainer, embedded or standalone SideStore, sideloading, signing, refresh, authentication, networking, SideTap, WebDriverAgent (WDA), and related failures. Apply it before changing source, packaging, dependency revisions, or release artifacts.

## 1. Investigate the implementation, not merely the wrapper

LiveContainer is not the source of truth for every error displayed inside it. Embedded SideStore is an independently developed application with its own libraries and upstream history. An error shown in LiveContainer may originate in SideStore, a nested dependency, the desktop signer, the device service, or a remote endpoint.

**For every SideStore/LiveContainer integration incident, inspect all three repositories directly:**
1. This fork: [thelabcorner/LiveContainer](https://github.com/thelabcorner/LiveContainer) at the affected branch and build commit.
2. Upstream [LiveContainer/LiveContainer](https://github.com/LiveContainer/LiveContainer), plus the actual embedded SideStore source fork [LiveContainer/SideStore](https://github.com/LiveContainer/SideStore) (historically the LiveContainerSupport branch).
3. Canonical [SideStore/SideStore](https://github.com/SideStore/SideStore), including the relevant upstream implementation, current applicable branch, issues, PRs, commits, releases and regressions. The canonical project and the LiveContainer-compatible fork are not interchangeable.

Inspect actual files and relevant history in each, not just a README, issue title, search snippet, or the LiveContainer wrapper. Compare the exact shipped revisions with corresponding canonical upstream revisions and candidate fixes; do not assume either latest HEAD or a closed issue represents the installed build. Record full SHAs, source paths/line ranges, permalinks and the reason each layer is relevant or ruled out. If a repository is unavailable, record that limitation and do not claim it was examined.

Expand into every dependency and service along the observed failure path. This is a minimum scope, not a closed list.

| Failure boundary | Sources to inspect as applicable |
| --- | --- |
| Embedded app loading, runtime identity, keychain/app groups, URL schemes, widget/intents | This fork; upstream LiveContainer; LiveContainer/SideStore; SideStore/SideStore; SideStoreSupport, dylibify, packaging scripts, actual app/framework plists, entitlements and runtime hooks; fishhook/litehook if the failing path uses them |
| Account authentication, 2FA, Anisette, GSA, developer portal | SideStore/SideStore and LiveContainer/SideStore; [SideStore/SideSign](https://github.com/SideStore/SideSign); [AnisetteKit](https://github.com/mahee96/AnisetteKit); [GSACryptoKit](https://github.com/mahee96/GSACryptoKit); relevant keychain and service code; actual Apple response and protocol stage; on-device or remote Anisette implementation only as implicated by evidence |
| Provisioning, app IDs, signing, installation, refresh, pairing/VPN/tunnel | Actual desktop installer (e.g. iLoader) and its resolved iSideload source; SideSign; [SideStore/minimuxer](https://github.com/SideStore/minimuxer); [CodeSignKit](https://github.com/mahee96/CodeSignKit); [RemotePairingKit](https://github.com/mahee96/RemotePairingKit); actual pairing/tunnel implementation, device service, signing and provisioning results |
| SideTap/WDA/XCTest | Relevant SideTap host and client repositories, [Appium WebDriverAgent](https://github.com/appium/WebDriverAgent), signer, go-ios/pymobiledevice3 or other actual USB tooling, device developer services and runner launch logs |
| Build/release/IPA mismatch | Workflow YAML, build logs, build and patch scripts, git submodules, dependency lockfiles, binary release assets and checksums, archive layout, actual artifact and installation provenance |

Discover dependency URLs and revisions from the affected source's submodule gitlinks, .gitmodules, Package.resolved, Cargo.lock and other manifests, CI checkout commands, and release metadata. Follow transitive dependencies to the code actually executing. For external services with unavailable source, use documented contracts and safe observable evidence; distinguish a black-box observation from a verified implementation claim.

## 2. Freeze the failing baseline before editing

- Capture the exact error text, code, domain, underlying error chain, failing operation/stage, reproducibility, build/version, device OS, signer version, branch/commit, and relevant configuration. Use timestamps and distinguish first failure from subsequent errors. Do not conflate separate incidents.
- Inspect the actual distributed IPA (and signed/installed metadata when available), not just the intended source: artifact SHA-256, build run, principal app count, bundle IDs, executable names, nested frameworks/extensions/test bundles, entitlements, signing identity and dependency provenance as relevant.
- Establish what is working, the last known working build, the first known failing build, recent changes, and invariants. Compare against existing incident notes and regression tests.
- Capture redacted evidence only. Never collect or publish passwords, 2FA codes, cookies, tokens, private keys, Apple account identifiers, device identifiers, pairing records, ADI blobs or raw sensitive headers. Do not add such material to CI, issue trackers, commits or artifacts.
- Do not delete/reinstall the app, reset ADI/keychain, switch Anisette providers, revoke certificates, change accounts or device pairing, or alter existing user state as a speculative diagnostic. Require a demonstrated reason, explain impact and obtain explicit authorization for destructive/account-affecting actions.

## 3. Trace the actual error and compare upstream

Start at the observed error, find the exact originating throw/check/response parser, then follow its callers, data transformations and dependencies through to the relevant host/device/server boundary. Trace the error domain as well as its numeric code. Read the surrounding implementations, call sites and tests; identify the exact failing condition and distinguish the originating error from translated UI messages.

Use exact error strings, numeric codes, endpoint names, types and symbols to search canonical upstream issues/PRs, release notes and code history. Examine linked fixes and their diffs, compatibility prerequisites, dependency changes and regressions; compare them to the pinned embedding fork. A superficially similar issue is a lead, not evidence of identical causation. Prefer the upstream fix when its mechanism and compatibility are established; otherwise justify a minimal integration adaptation or backport. Do not indiscriminately upgrade dependencies.

For each plausible hypothesis write down the mechanism, competing/null explanation, predicted observations, a discriminating test and falsifier, controls, and confounders. Run the smallest safe test that separates the hypotheses. Change one relevant variable at a time. Record negative results too. If there is insufficient access or evidence to discriminate, say so rather than inventing a root cause.

Examples:
- A server HTML HTTP 503 is not itself evidence that on-device Anisette is broken. Determine who returned the response and at which stage; compare request construction and the error mapping in the actual pinned client and dependencies.
- A different authentication error after a 503 disappears is a new diagnostic state, not proof of successful sign-in. Trace that error through SideStore and SideSign, inspect the protocol stage and the response classification; do not automatically repeat the previous repair.
- A desktop signing tool's nested-bundle identifier rejection must be traced into that tool's actual version and validation code, not attributed solely to the embedded application. Compare the final archive's metadata with the signer's expected input and signed output.

## 4. Patch the responsible layer, preserving invariants

- Produce a concise pre-edit finding: source owner, exact failure mechanism, evidence, competing explanations, proposed patch boundary, regression test, risks and rollback. Explicitly distinguish proved facts, supported hypotheses and unknowns.
- Fix the underlying responsible implementation or correct the integration contract; do not hide the error, silence validation, disable security checks, falsify success, or stack unverified workarounds. Do not replace an on-device provider with a remote provider merely because that changes the symptom.
- Preserve host bundle identity, ordinary signing/provisioning, saved app data, existing account and Anisette state, refresh behavior, and relevant entitlements/extension contracts. On the one-slot branch, preserve the single principal LiveContainer app and embedded SideStore; do not install a separate WDA runner or change the agreed one-slot design without authorization.
- Preserve unrelated work and inspect the branch and working tree before editing. Limit changes to the confirmed mechanism. If upstream changes are needed, use a reviewed source pin or deterministic patch against the pinned version; fail closed when expected source anchors or lockfiles drift. Do not silently fall back to a stale prebuilt IPA. Avoid unrelated refactors or moving dependency pins together without necessity.
- Follow branch-specific build policy. The one-slot branch builds patched SideStore and validates packages on GitHub Actions, not with ad hoc local compilation. Ensure actual compiler inputs contain the changes and the final IPA embeds the compiled output, not an old nightly or cached binary.

## 5. Verification and release gates

Write a regression test that fails on the affected baseline and passes with the intended patch, including negative cases when feasible. Preserve baseline parity. Record commands, exit codes and results. Validate actual artifacts against the originating failure contract and compare unaffected functionality. A successful hosted build is only one level of evidence:

| Gate | Required evidence |
| --- | --- |
| Source | Exact source/revision confirmed; patch and dependency contract reviewed; baseline/repaired tests and negative controls |
| CI/build | Correct source and locks compiled, logs reviewed, no hidden fallback, run tied to commit |
| Package | Actual IPA checksum and metadata; expected bundle identity, layout, executable and dependency provenance; signer compatibility checks |
| Device installation | Actual successful signing and provisioning, installation/upgrade, identity and user-data continuity; record only if observed |
| Runtime | Reproduce the originally failing action successfully on device; for authentication include applicable 2FA and sign-in; for refresh include actual renewal; for WDA include launch and functional checks, as applicable |
| Regression | Previously working paths still work, scoped to the change; mark untested paths explicitly |

Do not call an issue fixed solely because static tests pass, the IPA builds, an unauthenticated endpoint returns a different HTTP status, or a new error appears. Report the highest verified gate, the exact remaining device/service checks and blockers. Do not publish or promote a candidate as proven working without the relevant runtime evidence. When requested to deliver a build, provide the actual verified workflow run, commit, artifact URL and checksum if available, not a guessed download link.

## 6. Required investigation record and handoff

Before implementation and again before completion, keep a concise incident record in the repository's appropriate docs location (or the existing incident document). It must contain:

- Symptom and baseline: exact redacted failure, operation, versions, installed artifact/build identity, working behavior and invariants.
- Repository/dependency coverage: source URLs, full SHAs, files/symbols, upstream issue/PR links and relevant diffs; explain any missing access or excluded layers.
- Error trace: origin, boundary transitions and causal evidence. Hypothesis/test table with predictions, controls, actual outcomes, conclusions and unresolved uncertainties.
- Patch: owning layer, rationale, affected paths, source pins, scope, regression tests, compatibility and rollback.
- Verification: source/CI/package/device/runtime status separately, logs and artifact provenance, next decisive test and any required user action. Do not log secrets.

No investigation is complete with only a LiveContainer-side code search, a plausible explanation, a green CI result or a new IPA. If the original failure persists, resume from the new evidence and revisit the actual upstream source and dependencies, rather than repeating an exhausted hypothesis.

## 7. Historical reference cases (not current dependency pins)

The 2026-11-26 one-slot work illustrates the policy. These are historical anchors, not permission to assume that future builds use these versions or that every device issue was resolved.

- [98f2ad2: WDA bundle identifier repair](https://github.com/thelabcorner/LiveContainer/commit/98f2ad293626b018eced39a48f7d7f013d252ee7). iLoader 2.4.2 / isideload 0.5.2 rejected a PlugIns child whose identifier did not have the host prefix. The package repair and tests covered the known pre-signing rejection; device provisioning, refresh and XCTest startup remained separate verification gates.
- [73f2d74: SideStore GSA 503 source repair](https://github.com/thelabcorner/LiveContainer/commit/73f2d74049d1d00f9851242c14ff0187e8d95544). The pinned LiveContainer-compatible SideStore was `044bd72ad4eb270c3900bd04dc6f508d0ac474db`, SideSign `752d1ef602aa792a432ffa1e71646dc1ecf7363c`, and AnisetteKit `db8b41022697b6c19be8a5f01a1ce834145a2a26`. The repair normalized client-info at the config and authentication boundaries and compiled the pinned source, preserving on-device Anisette and persisted ADI. See [incident report](https://github.com/thelabcorner/LiveContainer/blob/73f2d74049d1d00f9851242c14ff0187e8d95544/docs/SIDESTORE-AUTH-503-REPAIR-20261126.md), [canonical upstream issue #1745](https://github.com/SideStore/SideStore/issues/1745), and the linked upstream comparison in that report. This did not establish successful device account sign-in.
- **Subsequent Apple sign-in failure (`-22410`): OPEN / not root-caused.** After the client-info normalization build, the user reported that the previous HTTP 503 disappeared but Apple sign-in still failed with `-22410`. This is a reported device observation, not a verified cause or a successful authentication. Recover the complete redacted error domain, underlying error, endpoint and authentication phase; trace the exact origin through the canonical SideStore implementation, the shipped LiveContainer/SideStore fork, SideSign and the resolved authentication dependencies. Compare source and upstream issue/PR history at the applicable revisions, not just issue #1745 or the wrapper. Test competing explanations without resetting ADI, switching away from on-device Anisette, or treating disappearance of the 503 as closure. Require successful on-device sign-in (including 2FA where applicable) before marking this incident resolved.
- [One-slot installation and verification notes](https://github.com/thelabcorner/LiveContainer/blob/98f2ad293626b018eced39a48f7d7f013d252ee7/docs/SIDETAP_WDA_ONE_SLOT_INSTALL.md).

Apply this protocol to subsequent errors independently of the historical patch: preserve verified progress, locate the newly failing mechanism, and verify the relevant boundary before declaring success.

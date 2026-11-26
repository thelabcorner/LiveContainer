#!/usr/bin/env python3
"""Small, fail-closed source patch for the pinned LiveContainer-compatible SideStore.

Patch the pinned SideStore + SideSign Swift sources, not LiveContainer UI.
Normalize Apple's client header, type the -22410 stage, and provide a
single user-consented, rollback-safe stale-ADI recovery without server switches.
CPU validation and Swift compilation run only in GitHub Actions.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

SIDESTORE_COMMIT = "044bd72ad4eb270c3900bd04dc6f508d0ac474db"
SIDESIGN_COMMIT = "752d1ef602aa792a432ffa1e71646dc1ecf7363c"
ANISETTEKIT_COMMIT = "db8b41022697b6c19be8a5f01a1ce834145a2a26"
MARKETING_VERSION = "0.7.0-20261126.2+044bd72a-authfix2"

CONFIG_PATH = "SideStore/Core/Anisette/AnisetteConfigManager.swift"
AUTH_PATH = "Dependencies/SideSign/Sources/DeveloperPortal/Authentication.swift"

# Exact once-only changes, against the pinned upstream source.
EDIT_MAP = {
    "SideStore/Core/Anisette/AnisetteConfigManager.swift": (
        ("$0.clientInfo = config.clientInfo.isEmpty ? AppConstants.Anisette.defaultClientInfo : config.clientInfo", "$0.clientInfo = (config.clientInfo.isEmpty ? AppConstants.Anisette.defaultClientInfo : config.clientInfo).replacingOccurrences(of: \"<macOS;\", with: \"<Mac OS X;\")"),
    ),
    "Dependencies/SideSign/Sources/DeveloperPortal/Authentication.swift": (
        ("\"X-MMe-Client-Info\": anisetteData.clientInfo,", "\"X-MMe-Client-Info\": anisetteData.clientInfo.replacingOccurrences(of: \"<macOS;\", with: \"<Mac OS X;\"),"),
        ("\"X-MMe-Client-Info\": a.clientInfo,", "\"X-MMe-Client-Info\": a.clientInfo.replacingOccurrences(of: \"<macOS;\", with: \"<Mac OS X;\"),"),
        ("let errorCode = status[\"ec\"] as? Int ?? 0\n        if errorCode != 0 {", "let errorCode = status[\"ec\"] as? Int ?? 0\n        let authPhase = requestParameters[\"o\"] as? String ?? \"unknown\"\n        if errorCode != 0 {"),
        ("            default:\n                throw ServerError.underlyingError(code: errorCode, message: errorDesc ?? \"Authentication failed\")", "            default:\n                // Only a typed SRP init -22410 can trigger stale-ADI recovery.\n                if errorCode == -22410 {\n                    debugLog(\"[SideSign] GSA rejected authentication phase=\\(authPhase) ec=-22410\")\n                    throw ServerError.grandSlamRejection(code: errorCode, phase: authPhase, message: errorDesc ?? \"Authentication failed\")\n                }\n                throw ServerError.underlyingError(code: errorCode, message: errorDesc ?? \"Authentication failed\")"),
    ),
    "Dependencies/SideSign/Sources/Models/Errors.swift": (
        ("    case underlyingError(code: Int, message: String)\n", "    case underlyingError(code: Int, message: String)\n    case grandSlamRejection(code: Int, phase: String, message: String)\n"),
        ("        case .underlyingError(let code, let message):         return \"underlyingError(code: \\(code), message: \\\"\\(message)\\\")\"", "        case .underlyingError(let code, let message):         return \"underlyingError(code: \\(code), message: \\\"\\(message)\\\")\"\n        case .grandSlamRejection(let code, let phase, let message): return \"grandSlamRejection(code: \\(code), phase: \\(phase), message: \\\"\\(message)\\\")\""),
        ("        case .underlyingError(let code, let message):         return \"\\(message) (\\(code))\"", "        case .underlyingError(let code, let message):         return \"\\(message) (\\(code))\"\n        case .grandSlamRejection(let code, let phase, let message): return \"\\(message) (\\(code); GrandSlam \\(phase))\""),
    ),
    "SideStore/Core/Operations/StandaloneExecutionHandler.swift": (
        ("    func handleSignInResult(_ result: Result<(ALTAccount, ALTAppleAPISession), Error>) async", "    func handleSignInResult(_ result: Result<(ALTAccount, ALTAppleAPISession), Error>) async\n    func confirmStaleAnisetteRecovery() async -> Bool"),
    ),
    "SideStore/Handlers/SignInFlowHandler.swift": (
        ("    @MainActor\n    func credentials() async throws -> (String, String) {", "    @MainActor\n    func confirmStaleAnisetteRecovery() async -> Bool {\n        guard let presenter = self.activePresenter else { return false }\n        return await withCheckedContinuation { continuation in\n            let alert = UIAlertController(\n                title: NSLocalizedString(\"Apple rejected this Anisette identity (-22410)\", comment: \"\"),\n                message: NSLocalizedString(\n                    \"SideStore can attempt fresh provisioning with your CURRENT Anisette provider. \" +\n                    \"The previous provisioning data will be restored if the attempt fails. \" +\n                    \"Your signing certificate will be preserved. Continue?\",\n                    comment: \"\"\n                ),\n                preferredStyle: .alert\n            )\n            alert.addAction(UIAlertAction(\n                title: NSLocalizedString(\"Keep Current Identity\", comment: \"\"),\n                style: .cancel\n            ) { _ in continuation.resume(returning: false) })\n            alert.addAction(UIAlertAction(\n                title: NSLocalizedString(\"Try Fresh Provisioning\", comment: \"\"),\n                style: .default\n            ) { _ in continuation.resume(returning: true) })\n            presenter.present(alert, animated: true)\n        }\n    }\n\n    @MainActor\n    func credentials() async throws -> (String, String) {"),
    ),
    "SideStore/Core/Operations/StandaloneOperations/SignInOperation.swift": (
        ("import CoreData\nimport SideSign\n", "import CoreData\nimport SideSign\nimport CryptoKit\n"),
        ("final class SignInOperation: BaseStandaloneOperation<StandaloneOperationContext, SignInResult>, @unchecked Sendable {", "private actor StaleAnisetteRecoveryGate {\n    static let shared = StaleAnisetteRecoveryGate()\n    private let attemptKey = \"SideStore.GrandSlamInit22410Recovery.v1\"\n\n    // Store a SHA-256 marker, not the original ADI blob or account identity.\n    nonisolated static func fingerprint(blob: String, clientInfo: String,\n                                        userAgent: String, provider: String) -> String {\n        let context = [blob, clientInfo, userAgent, provider].joined(separator: \"\\u{0}\")\n        return Data(SHA256.hash(data: Data(context.utf8))).base64EncodedString()\n    }\n\n    func canAttempt(_ fingerprint: String) -> Bool {\n        UserDefaults.standard.string(forKey: attemptKey) != fingerprint\n    }\n\n    func claim(_ fingerprint: String) -> Bool {\n        guard canAttempt(fingerprint) else { return false }\n        UserDefaults.standard.set(fingerprint, forKey: attemptKey)\n        return true\n    }\n}\n\nfinal class SignInOperation: BaseStandaloneOperation<StandaloneOperationContext, SignInResult>, @unchecked Sendable {"),
        ("                await AuthManager.shared.signOut()", "                // Authentication failure must not delete an existing signing certificate.\n                await AuthManager.shared.signOut(keepCertificate: true)"),
        ("    private func signIn(appleID: String, password: String) async throws -> (ALTAccount, ALTAppleAPISession) {\n        self.appleIDEmailAddress = appleID\n        \n        let anisetteData = try await self.getAnisetteData()\n        let handler = self.signInHandler\n        \n        let xcodeVersion = await AnisetteConfigManager.shared.resolvedXcodeVersion()\n\n        let (account, session) = try await AuthManager.shared.signIn(\n            appleID: appleID,\n            password: password,\n            anisetteData: anisetteData,\n            xcodeVersion: xcodeVersion,\n            accountRepairHandler: { url, message in\n                await handler.accountRepair(url: url, message: message)\n            },\n            verificationHandler: { request in\n                try await handler.verificationCode(for: request)\n            }\n        )\n        \n        AuthManager.shared.adsid = session.dsid\n        AuthManager.shared.xcodeToken = session.authToken\n        AuthManager.shared.currentAppleID = appleID\n        AuthManager.shared.password = password\n        \n        return (account, session)\n    }\n\n\n", "    private func performAppleSignIn(\n        appleID: String, password: String,\n        anisetteData: ALTAnisetteData, xcodeVersion: String\n    ) async throws -> (ALTAccount, ALTAppleAPISession) {\n        let handler = self.signInHandler\n        return try await AuthManager.shared.signIn(\n            appleID: appleID,\n            password: password,\n            anisetteData: anisetteData,\n            xcodeVersion: xcodeVersion,\n            accountRepairHandler: { url, message in\n                await handler.accountRepair(url: url, message: message)\n            },\n            verificationHandler: { request in\n                try await handler.verificationCode(for: request)\n            }\n        )\n    }\n\n    private func signIn(appleID: String, password: String) async throws -> (ALTAccount, ALTAppleAPISession) {\n        self.appleIDEmailAddress = appleID\n\n        // Preserve current provisioning unless a real GSA SRP init rejection occurs.\n        let previouslyStoredAdi = AnisetteConfigManager.shared.anisetteAdiBlob\n        let anisetteData = try await self.getAnisetteData()\n        let xcodeVersion = await AnisetteConfigManager.shared.resolvedXcodeVersion()\n        let result: (ALTAccount, ALTAppleAPISession)\n\n        do {\n            result = try await self.performAppleSignIn(\n                appleID: appleID, password: password,\n                anisetteData: anisetteData, xcodeVersion: xcodeVersion\n            )\n        } catch {\n            guard let apiError = error as? ServerError,\n                  case let .grandSlamRejection(code, phase, _) = apiError,\n                  code == -22410, phase == \"init\",\n                  let oldBlob = previouslyStoredAdi, !oldBlob.isEmpty else {\n                throw error\n            }\n\n            let config = await AnisetteConfigManager.shared.loadConfig()\n            let normalizedClientInfo = config.clientInfo.replacingOccurrences(\n                of: \"<macOS;\", with: \"<Mac OS X;\"\n            )\n            let useOnDevice = UserDefaults.standard.useOnDeviceAnisette\n            let provider = useOnDevice ? \"on-device\" : \"remote:\" + UserDefaults.standard.menuAnisetteURL\n            let fingerprint = StaleAnisetteRecoveryGate.fingerprint(\n                blob: oldBlob,\n                clientInfo: normalizedClientInfo,\n                userAgent: config.userAgent,\n                provider: provider\n            )\n            guard await StaleAnisetteRecoveryGate.shared.canAttempt(fingerprint) else {\n                self.debugLog(\"[SignInOperation] -22410 init: recovery previously attempted for this identity\")\n                throw error\n            }\n            // Explicit device-side consent for modifying Anisette provisioning.\n            guard await self.signInHandler.confirmStaleAnisetteRecovery() else {\n                self.debugLog(\"[SignInOperation] User declined fresh ADI provisioning\")\n                throw error\n            }\n            guard await StaleAnisetteRecoveryGate.shared.claim(fingerprint) else {\n                throw error\n            }\n            if self.isCancelled { throw OperationError.cancelled }\n\n            self.debugLog(\"[SignInOperation] GSA init -22410 with cached ADI; one opted-in reprovision\")\n            AnisetteConfigManager.shared.anisetteAdiBlob = nil\n            AnisetteDataManager.shared.clearCache()\n            do {\n                let freshAnisette = try await self.getAnisetteData()\n                if self.isCancelled { throw OperationError.cancelled }\n                result = try await self.performAppleSignIn(\n                    appleID: appleID, password: password,\n                    anisetteData: freshAnisette, xcodeVersion: xcodeVersion\n                )\n                self.debugLog(\"[SignInOperation] Fresh ADI authentication succeeded\")\n            } catch {\n                AnisetteConfigManager.shared.anisetteAdiBlob = oldBlob\n                AnisetteDataManager.shared.clearCache()\n                self.debugLog(\"[SignInOperation] Fresh ADI attempt failed; previous blob restored\")\n                throw error\n            }\n        }\n\n        let (account, session) = result\n        AuthManager.shared.adsid = session.dsid\n        AuthManager.shared.xcodeToken = session.authToken\n        AuthManager.shared.currentAppleID = appleID\n        AuthManager.shared.password = password\n        return (account, session)\n    }\n\n"),
    ),
}

class PatchError(RuntimeError):
    pass


def _check_source(root: Path) -> None:
    def git_sha(directory: Path) -> str:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=directory, text=True
        ).strip()

    if git_sha(root) != SIDESTORE_COMMIT:
        raise PatchError("SideStore source revision changed: refuse unreviewed build")
    if git_sha(root / "Dependencies" / "SideSign") != SIDESIGN_COMMIT:
        raise PatchError("SideSign source revision changed: refuse unreviewed build")
    resolved = json.loads(
        (root / "AltStore.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved").read_text()
    )
    matches = [
        pin for pin in resolved.get("pins", [])
        if pin.get("identity") == "anisettekit"
    ]
    if len(matches) != 1 or matches[0].get("state", {}).get("revision") != ANISETTEKIT_COMMIT:
        raise PatchError("AnisetteKit dependency revision changed: refuse unreviewed build")


def patch_sources(root: Path, *, verify_git: bool = True) -> dict[str, int]:
    """Modify six pinned source files. Fail before writing if any anchor drifts."""
    root = Path(root)
    if verify_git:
        _check_source(root)
    updates = {}
    counts = {}
    for relative, edits in EDIT_MAP.items():
        path = root / relative
        original = path.read_text(encoding="utf-8")
        patched = original
        for old, new in edits:
            count = patched.count(old)
            if count != 1:
                raise PatchError(f"{relative}: expected one exact source anchor, found {count}")
            patched = patched.replace(old, new, 1)
        if patched == original:
            raise PatchError(f"{relative}: unexpectedly unchanged")
        updates[path] = patched
        counts[relative] = len(edits)

    # One-shot commit only after every file has passed the preconditions.
    for path, patched in updates.items():
        path.write_text(patched, encoding="utf-8")
    return counts

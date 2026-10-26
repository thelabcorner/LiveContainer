// The SideTap icon opens the actual SideTap web application, not a status sheet.
// A verified workstation pairing is required because SideTap controls the phone.
import SwiftUI
import WebKit
import CryptoKit
import Security

struct SideTapAppView: View {
    @Binding var isPresented: Bool
    @AppStorage("LCSideTapViewerURL") private var savedURL = ""
    @AppStorage("LCSideTapTLSFingerprint") private var savedFingerprint = ""
    @State private var editing = false
    @State private var urlInput = ""
    @State private var fingerprintInput = ""
    @State private var connectionError: String?
    @State private var reloadIdentity = UUID()

    private var verifiedConnection: (URL, String)? {
        Self.validate(url: savedURL, fingerprint: savedFingerprint)
    }

    static func validate(url text: String, fingerprint: String) -> (URL, String)? {
        let normalized = fingerprint.lowercased().filter { $0 != ":" && !$0.isWhitespace }
        guard normalized.count == 64,
              normalized.unicodeScalars.allSatisfy({ CharacterSet(charactersIn: "0123456789abcdef").contains($0) }),
              let url = URL(string: text.trimmingCharacters(in: .whitespacesAndNewlines)),
              let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
              components.scheme?.lowercased() == "https",
              let host = components.host, !host.isEmpty,
              components.user == nil, components.password == nil,
              components.query == nil, components.fragment == nil,
              url.path.isEmpty || url.path == "/"
        else { return nil }
        return (url, normalized)
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                Image("SideTap")
                    .resizable()
                    .interpolation(.high)
                    .aspectRatio(contentMode: .fit)
                    .frame(width: 32, height: 32)
                    .clipShape(RoundedRectangle(cornerRadius: 7))
                Text("SideTap").font(.headline)
                Spacer()
                if verifiedConnection != nil {
                    Button {
                        urlInput = savedURL
                        fingerprintInput = savedFingerprint
                        connectionError = nil
                        editing = true
                    } label: {
                        Image(systemName: "gearshape")
                    }
                    .accessibilityLabel("SideTap connection settings")
                }
                Button("Done") { isPresented = false }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(Color(.secondarySystemBackground))

            if !editing, let (url, fingerprint) = verifiedConnection {
                // Uses the REAL SideTap viewer served by the Windows companion.
                // Web content can never navigate to another host or a plaintext URL.
                ZStack {
                    SideTapVerifiedWebView(url: url, fingerprint: fingerprint) { message in
                        connectionError = message
                    }
                    .id(reloadIdentity)
                    .ignoresSafeArea(edges: .bottom)

                    if let connectionError {
                        VStack(spacing: 16) {
                            Image(systemName: "wifi.exclamationmark")
                                .font(.largeTitle)
                            Text("SideTap connection unavailable")
                                .font(.headline)
                            Text(connectionError)
                                .font(.footnote)
                                .multilineTextAlignment(.center)
                            Button("Retry") {
                                self.connectionError = nil
                                reloadIdentity = UUID()
                            }
                            .buttonStyle(.borderedProminent)
                            Button("Connection settings") {
                                urlInput = savedURL
                                fingerprintInput = savedFingerprint
                                self.connectionError = nil
                                editing = true
                            }
                        }
                        .padding(24)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .background(Color(.systemBackground))
                    }
                }
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        Image("SideTap")
                            .resizable()
                            .interpolation(.high)
                            .aspectRatio(contentMode: .fit)
                            .frame(width: 86, height: 86)
                            .clipShape(RoundedRectangle(cornerRadius: 18))
                        Text("Connect SideTap").font(.largeTitle.bold())
                        Text("Open the real SideTap application running on your Windows workstation. SideTap uses the existing LiveContainer installation and does not need another iOS app slot.")
                            .foregroundStyle(.secondary)
                        TextField("https://your-workstation:8781/", text: $urlInput)
                            .textContentType(.URL)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .keyboardType(.URL)
                            .textFieldStyle(.roundedBorder)
                            .accessibilityLabel("SideTap workstation HTTPS address")
                        TextField("TLS certificate SHA-256 fingerprint", text: $fingerprintInput)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .textFieldStyle(.roundedBorder)
                            .accessibilityLabel("Verified workstation certificate fingerprint")
                        Text("Copy both values from the SideTap companion on your PC. The certificate fingerprint is required before any phone-control page can load. The actual application will ask you to pair securely.")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                        if let connectionError {
                            Text(connectionError)
                                .foregroundStyle(.red)
                                .font(.footnote)
                        }
                        Button {
                            guard let (url, fingerprint) = Self.validate(url: urlInput, fingerprint: fingerprintInput) else {
                                connectionError = "Enter an HTTPS address and the workstation's 64-digit certificate fingerprint."
                                return
                            }
                            savedURL = url.absoluteString
                            savedFingerprint = fingerprint
                            connectionError = nil
                            editing = false
                            reloadIdentity = UUID()
                        } label: {
                            Label("Open SideTap", systemImage: "arrow.up.right.square")
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.borderedProminent)
                        if !savedURL.isEmpty {
                            Button("Cancel") { editing = false }
                        }
                    }
                    .padding(24)
                    .frame(maxWidth: 540)
                    .frame(maxWidth: .infinity)
                }
            }
        }
        .onAppear {
            if savedURL.isEmpty || verifiedConnection == nil {
                editing = true
            }
            urlInput = savedURL
            fingerprintInput = savedFingerprint
        }
    }
}

private struct SideTapVerifiedWebView: UIViewRepresentable {
    let url: URL
    let fingerprint: String
    let onError: (String) -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(url: url, fingerprint: fingerprint, onError: onError)
    }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()
        let web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = context.coordinator
        web.allowsBackForwardNavigationGestures = false
        web.load(URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData))
        return web
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {}

    final class Coordinator: NSObject, WKNavigationDelegate {
        let url: URL
        let fingerprint: String
        let onError: (String) -> Void

        init(url: URL, fingerprint: String, onError: @escaping (String) -> Void) {
            self.url = url
            self.fingerprint = fingerprint
            self.onError = onError
        }

        private func report(_ error: Error) {
            DispatchQueue.main.async {
                self.onError(error.localizedDescription)
            }
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            report(error)
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            report(error)
        }

        func webView(_ webView: WKWebView,
                     decidePolicyFor action: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            // A paired viewer must never navigate to arbitrary sites or plain HTTP.
            guard let target = action.request.url,
                  target.scheme == "https",
                  target.host?.lowercased() == url.host?.lowercased(),
                  (target.port ?? 443) == (url.port ?? 443)
            else {
                decisionHandler(.cancel)
                return
            }
            decisionHandler(.allow)
        }

        func webView(_ webView: WKWebView,
                     didReceive challenge: URLAuthenticationChallenge,
                     completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
            guard challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust else {
                completionHandler(.performDefaultHandling, nil)
                return
            }
            guard challenge.protectionSpace.host.lowercased() == url.host?.lowercased(),
                  let trust = challenge.protectionSpace.serverTrust,
                  let certificate = SecTrustGetCertificateAtIndex(trust, 0)
            else {
                completionHandler(.cancelAuthenticationChallenge, nil)
                return
            }
            let bytes = SecCertificateCopyData(certificate) as Data
            let actual = SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
            guard actual == fingerprint else {
                DispatchQueue.main.async {
                    self.onError("Workstation TLS fingerprint does not match. Connection refused.")
                }
                completionHandler(.cancelAuthenticationChallenge, nil)
                return
            }
            completionHandler(.useCredential, URLCredential(trust: trust))
        }
    }
}

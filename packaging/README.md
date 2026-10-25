# Native release builds

Version tag pushes (`v*`) trigger the release workflow, which calls
`.github/workflows/native-build.yml`. Commits to `main` do not trigger builds.
An existing version tag can also be rebuilt through the release workflow's
manual **Run workflow** control.

The matrix builds on macOS ARM64, macOS Intel and Windows x64 runners using
Python 3.12, pinned PyInstaller/PySide6, and the Node version and CLI repository in
`runtime-versions.json`. The workflow selects GitHub's latest published stable
OCCS CLI release once before starting the platform builds. All platforms use
that release's exact commit; `npm ci --omit=dev` uses its lockfile on each OS.
Drafts and prereleases are excluded. A missing release or failed lookup stops
the build. Publish the OCCS CLI release before tagging ATool to include new CLI
fixes. Rebuilding an existing ATool tag selects the latest CLI release again.

The builder stages only CLI runtime directories, manifests and license notices.
It never copies a developer checkout's settings, sessions, `.env`, outputs or
Git metadata. The resulting runtime versions and source commits are written to
`RUNTIME_INFO.json`; About also receives `BUILD_INFO.txt`.

Each job archives the app, extracts that ZIP into a temporary directory, and
runs the extracted executable with isolated user settings and without installed
Python or Node on PATH. The check exercises the real Qt workspace, embedded
Qt WebEngine editor and bundled OCCS CLI's offline `--help`. Upload occurs only
after success. The release publication job waits for all three matrix jobs,
then uploads all native ZIPs/checksums along with the existing source ZIP.

Windows is a folder distribution: `ATool.exe` and `_internal` must stay together.
macOS is an application bundle with the name ATool and identifier
`com.calittle.ATool`. `ditto` preserves its signed framework symlinks and modes
when archiving and extracting. Release builds require Developer ID signing and
Apple notarization for both Mac architectures. Local builds use PyInstaller's
ad-hoc signing unless `ATOOL_CODESIGN_IDENTITY` is set to a signing identity.
Windows Authenticode is not configured.

## Mac release credentials

Add these repository secrets under Settings > Secrets and variables > Actions:

| Secret | Value |
| --- | --- |
| `MACOS_CERTIFICATE_P12_BASE64` | Base64 text of the exported Developer ID Application `.p12`, including its private key. |
| `MACOS_CERTIFICATE_PASSWORD` | Password set when exporting the `.p12`. |
| `APPLE_ID` | Apple Account email with access to the developer team. |
| `APPLE_TEAM_ID` | Team ID from Apple Developer > Membership details. |
| `APPLE_APP_SPECIFIC_PASSWORD` | App-specific password generated at account.apple.com for notarization. |

On your Mac, copy the certificate's encoded contents directly to the clipboard
with `base64 -i "/path/to/ATool-signing.p12" | pbcopy`, then paste into the
certificate secret. Do not commit signing files, export passwords, or Apple
credentials. Keep a password-protected backup of the identity outside the repo.

The release workflow passes secrets to its reusable native build workflow.
Each Mac runner imports the identity into a temporary keychain and checks that
it is a valid Developer ID Application identity for the configured Team ID.
PyInstaller signs the app and bundled binaries with Hardened Runtime and the
entitlements required by the bundled Qt WebEngine helper and Node JIT.
Signing failures stop the build. The app is then submitted to Apple's notary
service, which must return `Accepted`; its ticket is stapled and validated,
and Gatekeeper assessment must pass before the final ZIP/checksum are made.
The existing extracted-app UI, WebEngine, and CLI smoke checks run on that final
archive. Temporary signing files and the keychain are removed even on failure.

Apple notarization requires two-factor authentication and an app-specific
password for this Apple Account authentication method. If notarization exceeds
the 25-minute wait limit, the workflow fails rather than publishing an
unnotarized app; check the submission status before retrying.

For an artifact-only refresh, run Publish release artifact with the existing
`tag` and the packaging commit in `source_ref`. This builds from that exact
commit without moving the existing version tag. Leave `source_ref` empty for
the usual build from a version tag.

Setup references: [GitHub certificate import](https://docs.github.com/en/actions/how-tos/deploy/deploy-to-third-party-platforms/sign-xcode-applications),
[Apple notarization](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow),
and [Qt WebEngine deployment](https://doc.qt.io/qt-6/qtwebengine-deploying.html).

App artwork lives in `atool_qt/assets`. The ruby-red glass AT monogram sits
on a smoked-black glass tile. `atool-source.png` is the master artwork;
run `python tools/build_icons.py` with the Qt dependencies installed to regenerate
`atool.png`, the multiple-size Windows `atool.ico`, and macOS `atool.icns`.
The native build embeds the platform icon; both application launchers set the
runtime window icon, and Windows sets the ATool taskbar identity before opening
windows. The extracted-bundle check verifies that the running app has an icon.

Optional local validation, on the target operating system:

1. Install `requirements-build.txt` in a development environment.
2. Check out the latest published stable OCCS CLI release and run
   `npm ci --omit=dev` there.
3. Provide the target Node executable, its LICENSE, and `Python-LICENSE.txt`
   and `Qt-LGPL-3.0.txt` beside the Node LICENSE (the workflow retrieves these
   from the exact upstream Python and Qt versions).
4. Run `tools/build_native.py --occs-dir PATH --node PATH --node-license PATH`.
5. Run `tools/check_native_bundle.py dist/native/ATool.app` on macOS, or
   `tools/check_native_bundle.py dist/native/ATool` on Windows.

The bundle includes Node.js, OCCS CLI and its npm dependencies. It does not
include Graphviz (`dot`), Poppler (`pdftoppm`, `pdfinfo`), ImageMagick (`identify`,
`compare`), or a standalone Chrome/Chromium executable. Qt WebEngine's embedded
Chromium supports ATool's editor and is not a browser executable for CLI smoke
tests.

Users can install these external tools and run the bundled CLI directly using
the bundled Node.js. The
[OCCS CLI prerequisites](https://github.com/calittle/OCCS-CLI#prerequisites)
provide platform installation instructions; bundled-CLI users can skip the
Node.js/npm and `npm install`/`npm link` steps. The CLI finds Graphviz, Poppler and ImageMagick through
the terminal's `PATH`; Chrome/Chromium uses common installation locations or
the `OCCS_SMOKE_BROWSER` executable path. Graphviz supports SVG graphs, Poppler
supports PDF thumbnails/page counts and comparison rasterization, ImageMagick
supports PDF/HTML visual comparisons, and Chrome/Chromium supports HTML
thumbnails and comparisons. See
[Using the bundled OCCS CLI directly](../README.md#using-the-bundled-occs-cli-directly)
for Mac and Windows commands.

The optional CLI graph/smoke commands are not used by ATool's interface. All CLI
operations exposed by ATool use the included runtime. OCCS service access still
requires the user's network connection and credentials; these are not bundled.

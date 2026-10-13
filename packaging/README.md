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
when archiving and extracting. PyInstaller's default ad-hoc macOS signing is
used; Developer ID/notarization and Windows Authenticode require signing
credentials and are not configured by this workflow.

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

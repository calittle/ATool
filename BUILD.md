# BUILD Notes

For automated builds.

## Distribution

Share the ATool folder or a zip containing:

- `ATool.py`
- `atool_web_editor.py`
- `atool_core/` (the application support package)
- `tools/resolve_layout.py`
- `Run_ATool.bat`
- `Run_ATool.zsh`
- `README.md`
- `requirements.txt`
- `NOTES.MD`

Do not include local cache or generated folders such as `.venv`, `__pycache__`,
or user-specific files under `~/.atool/`.

## Automated Build Artifact

Version-tag pushes (`v*`) trigger the release workflow. Commits to `main` do
not trigger builds. The workflow builds native applications and the source ZIP,
then publishes the release artifacts after the required checks pass. A manual
workflow run can rebuild an existing tag. See [native packaging](packaging/README.md).

The build writes:

- `dist/ATool-<timestamp>-<commit>.zip`

Each release zip includes a generated `NOTES.MD` file with commit details and a
short change summary for the packaged snapshot.

The app's **File -> About ATool** dialog displays the release tag when the
packaged commit has one; otherwise it displays the short commit ID recorded in
`BUILD_INFO.txt`. Dirty worktree builds add `-dirty`. The dialog also shows the
source snapshot, build timestamp, artifact name, and support contact. For local
development runs without `BUILD_INFO.txt`, ATool uses an exact tag on `HEAD`
when available and otherwise falls back to the current repo's short git hash.

To publish a release, create and push an annotated version tag:

```bash
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin v1.0.0
```

For an existing tag whose release needs an asset added later, open the
**Publish release artifact** workflow in GitHub Actions, select **Run
workflow**, and provide the tag name. The workflow packages that exact tag.

## Local development

Do not create release ZIPs locally. GitHub Actions is the only artifact build
environment. Local development should run focused checks such as Python syntax
validation and tests instead.

## SSO release requirements

The SSO action needs both the ATool Qt UI changes and OCCS CLI 1.4.0 or later.
Native builds select the latest published stable OCCS release once and use its
exact commit on all platforms. OCCS v1.4.0 is published; verify the version and
commit actually bundled in `RUNTIME_INFO.json` before describing a dependency
update in release notes. An older installed ATool keeps its original runtime.
A custom CLI Path overrides the bundled CLI, so validate both selections.

Chrome, Edge or Chromium must be installed separately for SSO. Qt WebEngine is
not a replacement for this executable. SSO timeout and browser-path preferences
live in the user profile. Never include sessions, credential keys, HAR files or
preview inputs/outputs in a source or native artifact.

Before releasing the ATool UI, run the focused synthetic checks:

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -p 'test_qt_sso_login.py'
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -p 'test_qt_settings_config.py'
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -p 'test_qt_comms.py'
```

Native runtime/package checks and the extracted-app offline CLI smoke check do
not prove live SSO. With a user available for phone/passkey approval, check the
Settings sign-in action in the built app, cancellation and timeout, a read and
PDF preview using the selected alias, and the expired-session sign-in guidance.
The CLI's core SSO flow has been verified live; the new ATool browser/phone flow
has not. Keep those validation claims separate in release notes.

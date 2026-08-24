# BUILD Notes

For automated builds.

## Distribution

Shar the ATool folder or a zip containing:

- `ATool.py`
- `atool_core/` (the application support package)
- `Run_ATool.bat`
- `Run_ATool.zsh`
- `README.md`
- `NOTES.MD`

Do not include local cache or generated folders such as `.venv`, `__pycache__`,
or user-specific files under `~/.atool/`.

## Automated Build Artifact

This repo includes a local post-commit build hook. When enabled, each commit
builds a zip artifact from the committed `HEAD` snapshot and writes it to:

- `dist/ATool-<timestamp>-<commit>.zip`

If a local SharePoint/OneDrive sync folder is configured, the same artifact is
also copied there, along with a stable `ATool-latest.zip` file.

Each release zip includes a generated `NOTES.MD` file with commit details and a
short change summary for the packaged snapshot.

The app's **File -> About ATool** dialog displays the build number and support
contact. For packaged releases, the build number is the short form of the git
commit recorded in `BUILD_INFO.txt`; dirty worktree builds add `-dirty`. The
dialog also shows the source snapshot, build timestamp, and artifact name. For
local development runs without `BUILD_INFO.txt`, ATool falls back to the current
repo's short git hash and adds `-dirty` when there are uncommitted changes.

### Enable the Git Hook

Run this once from the repo root:

```bash
git config core.hooksPath .githooks
chmod +x .githooks/post-commit tools/build_artifact.py
```

### Configure the SharePoint Destination

Use either an environment variable:

```bash
export ATOOL_ARTIFACT_DIR="/path/to/local/SharePoint/folder"
```

Or create a local, ignored `.atool-build.local.json` file:

```json
{
  "sharepoint_dir": "/path/to/local/SharePoint/folder"
}
```

The checked-in `.atool-build.local.json.example` shows the expected shape.

### Build Manually

Build from the latest committed snapshot:

```bash
python3 tools/build_artifact.py --source head
```

Build from the current working tree:

```bash
python3 tools/build_artifact.py --source worktree
```

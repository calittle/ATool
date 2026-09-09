# BUILD Notes

For automated builds.

## Distribution

Share the ATool folder or a zip containing:

- `ATool.py`
- `atool_core/` (the application support package)
- `Run_ATool.bat`
- `Run_ATool.zsh`
- `README.md`
- `NOTES.MD`

Do not include local cache or generated folders such as `.venv`, `__pycache__`,
or user-specific files under `~/.atool/`.

## Automated Build Artifact

GitHub Actions builds a ZIP from every push to `main`. The ZIP is available
from the corresponding Actions run as an artifact. On a pushed version tag
such as `v1.0.1`, GitHub Actions builds the same ZIP and attaches it to a
GitHub Release, creating that release with generated notes if needed.

The build writes:

- `dist/ATool-<timestamp>-<commit>.zip`

Each release zip includes a generated `NOTES.MD` file with commit details and a
short change summary for the packaged snapshot.

The app's **File -> About ATool** dialog displays the build number and support
contact. For packaged releases, the build number is the short form of the git
commit recorded in `BUILD_INFO.txt`; dirty worktree builds add `-dirty`. The
dialog also shows the source snapshot, build timestamp, and artifact name. For
local development runs without `BUILD_INFO.txt`, ATool falls back to the current
repo's short git hash and adds `-dirty` when there are uncommitted changes.

To publish a release, create and push an annotated version tag:

```bash
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin v1.0.0
```

For an existing tag whose release needs an asset added later, open the
**Publish release artifact** workflow in GitHub Actions, select **Run
workflow**, and provide the tag name. The workflow packages that exact tag.

### Build Manually

Build locally from the latest committed snapshot:

```bash
python3 tools/build_artifact.py --source head
```

Build from the current working tree:

```bash
python3 tools/build_artifact.py --source worktree
```

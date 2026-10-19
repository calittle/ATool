# Repository workflow

- Work directly on `main` for all changes to this repository.
- Do not create or switch to a feature branch or a separate worktree for this repository.
- Keep any requested commits on `main`; do not use a pull request as the normal path for changes.

# Release notes and tagging

- Before preparing a release, check the latest published GitHub release and
  compare its tag with the proposed release commit. An old local build does
  not establish that the published release is out of date.
- Release notes must describe concrete user-visible changes since that previous
  published release: new behavior, fixes, and their practical effect. Base each
  claim on the intervening commits and diffs. Do not repeat earlier release
  features as new or substitute generic build/rebuild wording for a changelog.
- For bundled dependency updates, verify the old and new versions or commits
  and describe the relevant changes. Do not claim an update merely because the
  workflow selects the latest release.
- If there are no functional changes, say so explicitly. Report that finding
  before creating a new tag; use the existing release's rebuild workflow when
  the goal is only to refresh its artifacts, unless the user requests a new tag
  after learning there are no functional changes.
- Ensure the matching NOTES.MD section accurately covers the verified release
  delta before pushing a release tag.

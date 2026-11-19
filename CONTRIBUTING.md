# Contributing to ATool

Contributions are welcome through pull requests. Fork `calittle/ATool`, create
a branch in your fork, and submit your pull request against the upstream `main`
branch. Contributors do not need write access to the upstream repository.

Describe the problem, the resulting behavior, and how you verified your change.
Include screenshots for visible UI changes. Run checks relevant to the change
and report their results in the pull request. Use synthetic or redacted data in
examples, screenshots, and tests; do not include credentials or customer data.

The repository owner, `@calittle`, reviews and approves contributions before
merging. New commits after approval require another review. The owner's local
checkout uses a direct-to-main workflow; that exception does not apply to
external contributions.

## Releases

Only the repository owner creates, updates, or deletes upstream release tags
and starts release builds or manual artifact rebuilds. Merging a contribution
does not publish a release. The owner selects the release commit, verifies the
changes since the previous published release, updates NOTES.MD, and pushes a
`v*` tag when ready. Contributors should not change release versions or tags
unless requested by the owner.

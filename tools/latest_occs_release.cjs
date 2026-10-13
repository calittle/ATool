// Select GitHub's latest published stable release once for the whole build.
async function latestOccsRelease(github, repository) {
  const [owner, repo, extra] = repository.split('/');
  if (!owner || !repo || extra) throw new Error('Expected an OCCS CLI repository in owner/repo form.');
  let release;
  try {
    ({ data: release } = await github.rest.repos.getLatestRelease({ owner, repo }));
  } catch (error) {
    throw new Error(`Cannot resolve the latest published OCCS CLI release for ${repository}: ${error.message}`);
  }
  if (!release.tag_name || release.draft || release.prerelease) {
    throw new Error('OCCS CLI must have a published stable release before building ATool.');
  }
  const { data: reference } = await github.rest.git.getRef({ owner, repo, ref: `tags/${release.tag_name}` });
  let object = reference.object;
  const visited = new Set();
  while (object.type === 'tag') {
    if (visited.has(object.sha)) throw new Error('Cyclic OCCS CLI release tag.');
    visited.add(object.sha);
    const { data: tag } = await github.rest.git.getTag({ owner, repo, tag_sha: object.sha });
    object = tag.object;
  }
  if (object.type !== 'commit' || !/^[a-f0-9]{40}$/.test(object.sha)) {
    throw new Error('The OCCS CLI release tag must identify a Git commit.');
  }
  return { repository, tag: release.tag_name, revision: object.sha, url: release.html_url };
}

module.exports = { latestOccsRelease };

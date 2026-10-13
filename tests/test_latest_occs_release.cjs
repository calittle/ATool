const assert = require('node:assert/strict');
const test = require('node:test');
const { latestOccsRelease } = require('../tools/latest_occs_release.cjs');

const revision = 'a'.repeat(40);
const repository = 'calittle/OCCS-CLI';

function fixture({ release = {}, object = { type: 'commit', sha: revision }, tags = {} } = {}) {
  return {
    rest: {
      repos: {
        async getLatestRelease(args) {
          assert.deepEqual(args, { owner: 'calittle', repo: 'OCCS-CLI' });
          return { data: { tag_name: 'v1.2.4', html_url: 'https://github.com/calittle/OCCS-CLI/releases/tag/v1.2.4', ...release } };
        },
      },
      git: {
        async getRef(args) {
          assert.equal(args.ref, `tags/${release.tag_name || 'v1.2.4'}`);
          return { data: { object } };
        },
        async getTag(args) {
          assert.ok(tags[args.tag_sha], 'Only annotated tags should be dereferenced');
          return { data: { object: tags[args.tag_sha] } };
        },
      },
    },
  };
}

test('latest published release resolves to its commit, including lightweight tags', async () => {
  const selected = await latestOccsRelease(fixture(), repository);
  assert.equal(selected.repository, repository);
  assert.equal(selected.tag, 'v1.2.4');
  assert.equal(selected.revision, revision);
  const newer = await latestOccsRelease(fixture({
    release: { tag_name: 'v1.2.5' }, object: { type: 'commit', sha: 'b'.repeat(40) },
  }), repository);
  assert.equal(newer.tag, 'v1.2.5');
  assert.equal(newer.revision, 'b'.repeat(40));
});

test('annotated release tags are peeled to a commit shared by all platform builds', async () => {
  const selected = await latestOccsRelease(fixture({
    object: { type: 'tag', sha: 'first' },
    tags: { first: { type: 'tag', sha: 'second' }, second: { type: 'commit', sha: revision } },
  }), repository);
  assert.equal(selected.revision, revision);
});

test('missing, draft, or prerelease releases fail without falling back to main', async () => {
  for (const release of [{ tag_name: '' }, { draft: true }, { prerelease: true }]) {
    await assert.rejects(latestOccsRelease(fixture({ release }), repository), /published stable release/);
  }
  const github = fixture();
  github.rest.repos.getLatestRelease = async () => { throw new Error('Not Found'); };
  await assert.rejects(latestOccsRelease(github, repository), /latest published OCCS CLI release.*Not Found/);
});

test('invalid tag targets and cycles fail rather than selecting an arbitrary revision', async () => {
  for (const object of [{ type: 'tree', sha: revision }, { type: 'commit', sha: 'not-a-commit' }]) {
    await assert.rejects(latestOccsRelease(fixture({ object }), repository), /Git commit/);
  }
  await assert.rejects(latestOccsRelease(fixture({
    object: { type: 'tag', sha: 'loop' }, tags: { loop: { type: 'tag', sha: 'loop' } },
  }), repository), /Cyclic/);
});

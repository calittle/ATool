#!/usr/bin/env node
// Download only the named Comms content items required by a TD profile.
import fs from 'fs';
import path from 'path';
import { loadSession } from '/Users/clittle/Documents/dev/ccs-tools/OCCS-CLI/lib/session.js';
import { get } from '/Users/clittle/Documents/dev/ccs-tools/OCCS-CLI/lib/api.js';
import { downloadBlob } from '/Users/clittle/Documents/dev/ccs-tools/OCCS-CLI/lib/download.js';
import { parseContentBlobs } from '/Users/clittle/Documents/dev/ccs-tools/OCCS-CLI/lib/blobUtils.js';

const [namesFile, outputDir] = process.argv.slice(2);
if (!namesFile || !outputDir) throw new Error('Usage: fetch_content_blobs.mjs <names.json> <output-dir>');
const names = [...new Set(JSON.parse(fs.readFileSync(namesFile, 'utf8')).map(String).filter(Boolean))];
const session = loadSession();
const safe = (value) => String(value).replace(/[^A-Za-z0-9._ -]/g, '_');
const fetched = [];
const attempted = new Set();
let pending = names;
while (pending.length) {
  const batch = pending.filter((name) => !attempted.has(name));
  pending = [];
  for (const name of batch) {
    attempted.add(name);
  const whr = JSON.stringify({ a: [{ t: ['CommunicationContentConfigInfo.ShortName', 'eq', name] }] });
  const listed = await get(session, '/api/CommunicationContent/v1/CommunicationContentConfigRec', { depth: true, whr, limit: 5 }, false, { throwOnError: true });
  const item = (listed.Items || []).find((row) => row?.CommunicationContentConfigInfo?.ShortName === name);
    if (!item) { fetched.push({ name, found: false }); continue; }
    const uuid = item.CommunicationContentConfigUuid;
    const master = await get(session, `/api/CommunicationContent/v1/CommunicationContentMasterConfig/${uuid}`, {}, false, { throwOnError: true });
    const folder = path.join(outputDir, safe(name));
    fs.mkdirSync(folder, { recursive: true });
    fs.writeFileSync(path.join(folder, `${safe(name)}_master.json`), JSON.stringify(master, null, 2));
    for (const version of master.CommunicationContentMasterVersions || []) {
      const record = version.CommunicationContentVersionConfigRec;
      const info = record?.CommunicationContentVersionConfigInfo || {};
      const versionName = safe(info.ShortName || record?.CommunicationContentVersionConfigUuid || 'version');
      const versionFolder = path.join(folder, 'versions', versionName);
      fs.mkdirSync(versionFolder, { recursive: true });
      fs.writeFileSync(path.join(versionFolder, `${versionName}.json`), JSON.stringify(record, null, 2));
      for (const data of info.CommunicationContentVersionConfigData?.Items || []) {
        const location = `CommunicationContent/v1/${data.ContentData?.Location || ''}`;
        const fileId = data.ContentData?.FileId;
        if (fileId) await downloadBlob(session, location, path.join(versionFolder, `${fileId}.blob`));
      }
    }
    fetched.push({ name, found: true });
  }

  // A conditional include is a real descendant of this content item. Fetch it
  // before producing the catalogue, then repeat until the scoped graph closes.
  const { contentRefs } = parseContentBlobs(outputDir, { contentRoot: outputDir });
  pending = [...new Set(contentRefs.map((ref) => ref.targetContentId).filter((name) => name && !attempted.has(name)))];
}
const { usageMap, contentRefs } = parseContentBlobs(outputDir, { contentRoot: outputDir });
const contentUsage = {};
for (const [field, usages] of Object.entries(usageMap)) {
  for (const usage of usages) {
    (contentUsage[usage.contentId] ||= []).push(field);
  }
}
for (const fields of Object.values(contentUsage)) fields.sort();
const contentReferences = {};
for (const ref of contentRefs) {
  (contentReferences[ref.contentId] ||= []).push(ref.targetContentId);
}
for (const [source, targets] of Object.entries(contentReferences)) contentReferences[source] = [...new Set(targets)].sort();
fs.writeFileSync(path.join(outputDir, 'content-usage.json'), JSON.stringify(contentUsage, null, 2) + '\n');
fs.writeFileSync(path.join(outputDir, 'content-references.json'), JSON.stringify(contentReferences, null, 2) + '\n');
console.log(JSON.stringify({ requested: names.length, fetched, contentReferences }, null, 2));

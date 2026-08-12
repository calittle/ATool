#!/usr/bin/env node
// Build field and conditional-content indexes from an already downloaded OCCS cache.
import fs from 'fs';
import path from 'path';
import { parseContentBlobs } from '/Users/clittle/Documents/dev/ccs-tools/OCCS-CLI/lib/blobUtils.js';

const [contentRoot, outputDir, effectiveDate] = process.argv.slice(2);
if (!contentRoot || !outputDir || !effectiveDate) throw new Error('Usage: build_content_catalog.mjs <contents-cache> <output-dir> <effective-date>');
const { usageMap, contentRefs } = parseContentBlobs(contentRoot, { contentRoot });
const activeVersions = new Set();
for (const folder of fs.readdirSync(contentRoot)) {
  const versions = path.join(contentRoot, folder, 'versions');
  if (!fs.existsSync(versions)) continue;
  const candidates = [];
  for (const versionFolder of fs.readdirSync(versions)) {
    const recordPath = path.join(versions, versionFolder, `${versionFolder}.json`);
    try {
      const record = JSON.parse(fs.readFileSync(recordPath, 'utf8'));
      const version = record.CommunicationContentVersionConfigRec || record;
      const status = version.Status?.Items || [];
      const active = status.filter((item) => item.StatusCode === 'Active' && String(item.EffDtTm || '').slice(0, 10) <= effectiveDate).map((item) => String(item.EffDtTm));
      if (active.length) candidates.push([active.sort().at(-1), version.CommunicationContentVersionConfigInfo?.ShortName || versionFolder]);
    } catch { /* an incomplete cache record is not eligible */ }
  }
  if (candidates.length) {
    const [, version] = candidates.sort((a, b) => a[0].localeCompare(b[0])).at(-1);
    activeVersions.add(`${folder}\u0000${version}`);
  }
}
const selected = (entry) => activeVersions.has(`${entry.contentId}\u0000${entry.versionId}`);
const usage = {};
const details = {};
const styleClasses = {};
for (const folder of fs.readdirSync(contentRoot)) {
  const masterPath = path.join(contentRoot, folder, `${folder}_master.json`);
  let contentId = folder;
  try { contentId = JSON.parse(fs.readFileSync(masterPath, 'utf8')).CommunicationContentConfigRec?.CommunicationContentConfigInfo?.ShortName || folder; } catch { /* retain folder */ }
  const versions = path.join(contentRoot, folder, 'versions');
  if (!fs.existsSync(versions)) continue;
  for (const versionFolder of fs.readdirSync(versions)) {
    const recordPath = path.join(versions, versionFolder, `${versionFolder}.json`);
    try {
      const record = JSON.parse(fs.readFileSync(recordPath, 'utf8'));
      const version = record.CommunicationContentVersionConfigRec || record;
      const shortName = version.CommunicationContentVersionConfigInfo?.ShortName || versionFolder;
      if (!activeVersions.has(`${folder}\u0000${shortName}`)) continue;
      for (const item of version.CommunicationContentVersionConfigInfo?.CommunicationContentVersionConfigData?.Items || []) {
        for (const className of item.StyleClassName || []) if (className) (styleClasses[className] ||= []).push(contentId);
      }
    } catch { /* ignore incomplete cache record */ }
  }
}
for (const [field, locations] of Object.entries(usageMap)) {
  for (const location of locations.filter(selected)) {
    (usage[location.contentId] ||= []).push(field);
    const fragments = [...String(location.raw || '').matchAll(/\$Data\s*(\{[^}]*\})/g)];
    for (const fragment of fragments) {
      try {
        const value = JSON.parse(fragment[1]);
        if (value.Id !== field) continue;
        const attributes = Object.entries(value).filter(([key]) => key !== 'Id').map(([key, value]) => `${key}: ${JSON.stringify(value)}`);
        const transform = String(location.raw || '').match(/<comms-transform\b([^>]*)>([\s\S]*?)<\/comms-transform>/i);
        if (transform) attributes.push(`Transform: ${transform[1].trim() || 'configured'}`);
        if (attributes.length) ((details[location.contentId] ||= {})[field] ||= []).push(attributes.join('; '));
      } catch { /* malformed $Data is still indexed by its ID */ }
    }
  }
}
for (const [content, names] of Object.entries(usage)) usage[content] = [...new Set(names)].sort();
const refs = {};
for (const ref of contentRefs.filter(selected)) (refs[ref.contentId] ||= []).push(ref.targetContentId);
for (const [name, targets] of Object.entries(refs)) refs[name] = [...new Set(targets)].sort();
fs.mkdirSync(outputDir, { recursive: true });
fs.writeFileSync(path.join(outputDir, 'content-usage.json'), JSON.stringify(usage, null, 2) + '\n');
fs.writeFileSync(path.join(outputDir, 'content-references.json'), JSON.stringify(refs, null, 2) + '\n');
fs.writeFileSync(path.join(outputDir, 'content-field-details.json'), JSON.stringify(details, null, 2) + '\n');
for (const [className, contents] of Object.entries(styleClasses)) styleClasses[className] = [...new Set(contents)].sort();
fs.writeFileSync(path.join(outputDir, 'content-style-classes.json'), JSON.stringify(styleClasses, null, 2) + '\n');

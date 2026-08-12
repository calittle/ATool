#!/usr/bin/env node
import fs from 'fs';
import { loadSession } from '/Users/clittle/Documents/dev/ccs-tools/OCCS-CLI/lib/session.js';
import { get } from '/Users/clittle/Documents/dev/ccs-tools/OCCS-CLI/lib/api.js';

const [namesFile, outputFile] = process.argv.slice(2);
const names = JSON.parse(fs.readFileSync(namesFile, 'utf8'));
const session = loadSession();
const nodes = {};
async function resolveByName(name) {
  const whr = JSON.stringify({ a: [{ t: ['CommunicationLayoutConfigRec.CommunicationLayoutConfigInfo.ShortName', 'eq', name] }] });
  const listed = await get(session, '/api/CommunicationDocument/v1/CommunicationLayoutConfigRec', { depth: true, whr, limit: 5 }, false, { throwOnError: true });
  return (listed.Items || []).find((item) => item.CommunicationLayoutConfigInfo?.ShortName === name);
}
async function visit(uuid, fallbackName = '') {
  if (!uuid || nodes[uuid]) return;
  const master = await get(session, `/api/CommunicationDocument/v1/CommunicationLayoutMasterConfig/${uuid}`, { depth: true }, false, { throwOnError: true });
  const info = master.CommunicationLayoutConfigRec?.CommunicationLayoutConfigInfo || {};
  const childLayouts = (master.CommunicationLayoutLayouts || []).map((item) => ({
    name: item.ShortName || '',
    uuid: item.CommunicationLayoutConfigCommunicationLayoutConfigRelRec?.CommunicationLayoutConfigCommunicationLayoutConfigRelInfo?.RelCommunicationLayoutConfigUuid || '',
    index: item.CommunicationLayoutConfigCommunicationLayoutConfigRelRec?.CommunicationLayoutConfigCommunicationLayoutConfigRelInfo?.LayoutRelIndex ?? null,
    area: item.CommunicationLayoutConfigCommunicationLayoutConfigRelRec?.CommunicationLayoutConfigCommunicationLayoutConfigRelInfo?.StyleAreaName || '',
  })).sort((a,b) => (a.index ?? 0) - (b.index ?? 0));
  const contents = (master.CommunicationLayoutContents || []).map((item) => ({ name: item.ShortName || '', index: item.CommunicationLayoutConfigCommunicationContentConfigRelRec?.CommunicationLayoutConfigCommunicationContentConfigRelInfo?.ContentRelIndex ?? null, area: item.CommunicationLayoutConfigCommunicationContentConfigRelRec?.CommunicationLayoutConfigCommunicationContentConfigRelInfo?.StyleAreaName || '' })).sort((a,b) => (a.index ?? 0) - (b.index ?? 0));
  nodes[uuid] = { uuid, name: info.ShortName || fallbackName, type: info.LayoutType || 'Unknown', childLayouts, contents };
  for (const child of childLayouts) await visit(child.uuid, child.name);
}
for (const name of names) { const item = await resolveByName(name); if (item) await visit(item.CommunicationLayoutConfigUuid, name); }
fs.writeFileSync(outputFile, JSON.stringify({ nodes }, null, 2));

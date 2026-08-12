#!/usr/bin/env node
import fs from 'fs';
import { loadSession } from '/Users/clittle/Documents/dev/ccs-tools/OCCS-CLI/lib/session.js';
import { get } from '/Users/clittle/Documents/dev/ccs-tools/OCCS-CLI/lib/api.js';
const [associationsFile, outputFile, namesFile] = process.argv.slice(2);
const associations = JSON.parse(fs.readFileSync(associationsFile, 'utf8')).associations;
const wanted = namesFile ? new Set(JSON.parse(fs.readFileSync(namesFile, 'utf8')).map(String)) : new Set(['CO-G1-CO1','CO-G1-CO2','CO-G1-CO3','CO-G1-CO4','CO-G1-CO5','CO-G1-CO6']);
const session = loadSession(), nodes = {}, documents = {};
const number = (v) => Number.parseFloat(String(v || '').match(/^\d+(?:\.\d+)?/)?.[0] || '-1');
const styleRefs = (items = []) => items.map((item) => {
  const rel = item.CommunicationDocumentVersionConfigCommunicationStyleConfigRelRec?.CommunicationDocumentVersionConfigCommunicationStyleConfigRelInfo
    || item.CommunicationLayoutConfigCommunicationStyleConfigRelRec?.CommunicationLayoutConfigCommunicationStyleConfigRelInfo || {};
  return {name: item.ShortName || item.CommunicationStyleConfigRec?.CommunicationStyleConfigInfo?.ShortName || '', className: rel.StyleClassName || ''};
}).filter((item) => item.name || item.className);
async function visit(uuid) {
  if (!uuid || nodes[uuid]) return;
  const master = await get(session, `/api/CommunicationDocument/v1/CommunicationLayoutMasterConfig/${uuid}`, {depth:true}, false, {throwOnError:true});
  const info = master.CommunicationLayoutConfigRec?.CommunicationLayoutConfigInfo || {};
  const rel = (item) => item.CommunicationLayoutConfigCommunicationLayoutConfigRelRec?.CommunicationLayoutConfigCommunicationLayoutConfigRelInfo || {};
  const contentRel = (item) => item.CommunicationLayoutConfigCommunicationContentConfigRelRec?.CommunicationLayoutConfigCommunicationContentConfigRelInfo || {};
  const children = (master.CommunicationLayoutLayouts || []).map(x => ({uuid:rel(x).RelCommunicationLayoutConfigUuid,name:x.ShortName||'',index:rel(x).LayoutRelIndex??0,area:rel(x).StyleAreaName||''})).sort((a,b)=>a.index-b.index);
  nodes[uuid] = {uuid,name:info.ShortName||'',type:info.LayoutType||'Unknown',styles:styleRefs(master.CommunicationLayoutStyles),contents:(master.CommunicationLayoutContents||[]).map(x=>({name:x.ShortName||'',index:contentRel(x).ContentRelIndex??0,area:contentRel(x).StyleAreaName||''})).sort((a,b)=>a.index-b.index),childLayouts:children};
  for (const child of children) await visit(child.uuid);
}
for (const association of associations.filter(x => wanted.has(String(x.documentShortName || '')))) {
  const master = await get(session, `/api/CommunicationDocument/v1/CommunicationDocumentMasterConfig/${association.documentConfigUuid}`, {depth:true}, false, {throwOnError:true});
  const versions = master.CommunicationDocumentMasterVersions || [];
  const selected = [...versions].sort((a,b)=>number(b.CommunicationDocumentVersionConfigRec?.CommunicationDocumentVersionConfigInfo?.ShortName)-number(a.CommunicationDocumentVersionConfigRec?.CommunicationDocumentVersionConfigInfo?.ShortName))[0]?.CommunicationDocumentVersionConfigRec;
  if (!selected) continue;
  const version = await get(session, `/api/CommunicationDocument/v1/CommunicationDocumentVersionMasterConfig/${selected.CommunicationDocumentVersionConfigUuid}`, {depth:true}, false, {throwOnError:true});
  const roots = (version.CommunicationDocumentVersionLayouts||[]).map(x=>({uuid:x.CommunicationLayoutConfigRec?.CommunicationLayoutConfigUuid,name:x.CommunicationLayoutConfigRec?.CommunicationLayoutConfigInfo?.ShortName||'',index:x.CommunicationDocumentVersionConfigCommunicationLayoutConfigRelRec?.CommunicationDocumentVersionConfigCommunicationLayoutConfigRelInfo?.LayoutRelIndex??0,placement:x.CommunicationDocumentVersionConfigCommunicationLayoutConfigRelRec?.CommunicationDocumentVersionConfigCommunicationLayoutConfigRelInfo?.LayoutPlacement||''})).sort((a,b)=>a.index-b.index);
  documents[association.documentShortName]={description:master.CommunicationDocumentConfigRec?.CommunicationDocumentConfigInfo?.Desc||'',version:selected.CommunicationDocumentVersionConfigInfo?.ShortName||'',styles:styleRefs(version.CommunicationDocumentVersionStyles),roots};
  for (const root of roots) await visit(root.uuid);
}
fs.writeFileSync(outputFile, JSON.stringify({documents,nodes},null,2));

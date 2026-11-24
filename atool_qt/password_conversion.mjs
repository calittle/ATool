// Run the existing converter against a disposable session, never the user's SSO store.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

let secrets = [];
function redact(value) {
  let text = String(value);
  for (const secret of secrets.filter(Boolean)) text = text.split(secret).join('[redacted]');
  return text.replace(/Bearer\s+[^\s"',}]+/gi, 'Bearer [redacted]');
}
const stdout = process.stdout.write.bind(process.stdout);
const stderr = process.stderr.write.bind(process.stderr);
process.stdout.write = chunk => stdout(redact(chunk));
process.stderr.write = chunk => stderr(redact(chunk));

try {
  let raw = '';
  for await (const chunk of process.stdin) raw += chunk;
  const { username, password, source, options } = JSON.parse(raw);
  raw = '';
  secrets = [password];
  // This private home is supplied and removed by CommandJob, including on cancellation.
  // Only environment metadata is written here before the converter runs.
  const home = os.homedir();
  fs.mkdirSync(home, { recursive: true, mode: 0o700 });
  fs.writeFileSync(path.join(home, '.occs-session.json'), JSON.stringify({
    currentSessionKey: source.sessionKey, aliases: { [options.session]: source.sessionKey },
    sessions: { [source.sessionKey]: { ...source, authType: 'password' } },
  }), { mode: 0o600, flag: 'wx' });
  const lib = process.argv[2];
  const axios = (await import(pathToFileURL(path.join(lib, '..', 'node_modules', 'axios', 'index.js')).href)).default;
  // Conversion obtains and refreshes its own tokens. Keep each one out of diagnostics.
  axios.interceptors.response.use(response => {
    if (response.data?.AccessToken) secrets.push(response.data.AccessToken);
    return response;
  }, error => {
    const status = error.response?.status;
    const url=String(error.config?.url || '');
    const stage=url.includes('/api/oauth2/v1/access') ? 'Password authentication'
      : url.includes('/api/CommunicationFileTransfer/v1/XmlToJsonConverter') ? 'Oracle XML converter' : 'XML conversion request';
    throw new Error(status ? `${stage} failed (HTTP ${status}). `+
      (stage==='Oracle XML converter' ? 'Password authentication succeeded. Check the selected environment and converter access.' : 'Check the password login and conversion permissions.')
      : `${stage} failed. Check connectivity and retry.`);
  });
  const { convertXmlCommand } = await import(pathToFileURL(path.join(lib, 'preview.js')).href);
  await convertXmlCommand({ ...options, username, password, verbose: false });
} catch (error) {
  process.stderr.write(redact(error.message) + '\n');
  process.exitCode = 1;
}

// Private stdin bridge to the bundled CLI. Never save or replace normal sessions.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const [cli, command, ...args] = process.argv.slice(2);
const option = (name) => args.includes(name) ? args[args.indexOf(name) + 1] : undefined;
const emit = (value) => process.stdout.write(JSON.stringify(value) + '\n');
let stage = 'setup';
let secrets = [];
function safeMessage(message) {
  let text = String(message);
  for (const secret of secrets.filter(Boolean)) text = text.split(secret).join('[redacted]');
  return text.replace(/Bearer\s+[^\s"',}]+/gi, 'Bearer [redacted]');
}

try {
  const lib = path.resolve(path.dirname(cli), '..', 'lib');
  if (!fs.existsSync(path.join(lib, 'credentials.js'))) {
    throw new Error('Select an OCCS CLI installation with encrypted credential support in User Settings → Comms → CLI Path.');
  }
  const credential = await import(pathToFileURL(path.join(lib, 'credentials.js')).href);
  const directory = path.join(os.homedir(), '.occs-cli');
  const filename = path.join(directory, 'atool-migration-logins.json');
  const action = command === 'migrate' ? 'migrate' : args[0];
  const alias = option('--source-session') || option('--session');
  if (!['test', 'forget', 'migrate'].includes(action) || !alias) throw new Error('Select a migration source session.');
  let raw = '';
  for await (const chunk of process.stdin) raw += chunk;
  const input = raw ? JSON.parse(raw) : {};
  raw = '';
  secrets = [input.password];
  const { loadSession } = await import(pathToFileURL(path.join(lib, 'session.js')).href);
  const source = loadSession({ sessionName: alias });
  const key = source.sessionKey;
  // Only environment identity comes from SSO. Its token/credentials are never used here.
  const readStore = () => {
    if (!fs.existsSync(filename)) return { version: 1, logins: {} };
    const store = JSON.parse(fs.readFileSync(filename, 'utf8'));
    if (store.version !== 1 || !store.logins || typeof store.logins !== 'object' || Array.isArray(store.logins)) {
      throw new Error('Invalid migration credential store.');
    }
    return store;
  };
  const updateStore = (entry) => {
    const store = readStore();
    if (entry) store.logins[key] = entry;
    else delete store.logins[key];
    fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
    const temporary = filename + '.' + process.pid + '.tmp';
    try {
      fs.writeFileSync(temporary, JSON.stringify(store, null, 2) + '\n', { mode: 0o600, flag: 'wx' });
      fs.renameSync(temporary, filename);
    } finally {
      fs.rmSync(temporary, { force: true });
    }
  };
  if (action === 'forget') {
    updateStore(null);
    emit({ ok: true });
  } else {
    stage = 'credentials';
    const stored = readStore().logins[key];
    const username = String(input.username || '').trim();
    const password = input.password || (stored?.username === username && stored?.passwordEnc
      ? credential.decryptStoredCredentialValue(stored.passwordEnc) : '');
    secrets.push(password);
    if (!username || !password) throw new Error('Enter the migration username and password, or use its remembered login.');
    stage = 'authentication';
    const axios = (await import(pathToFileURL(path.join(lib, '..', 'node_modules', 'axios', 'index.js')).href)).default;
    const response = await axios.post(`${String(source.baseUrl).replace(/\/$/, '')}/api/oauth2/v1/access`, {
      User: username, Password: password,
    }, { timeout: Number(option('--timeout') || 360000), headers: { Accept: 'application/json', 'Content-Type': 'application/json' } });
    const token = response.data?.AccessToken;
    if (!token) throw new Error('The source did not return an access token.');
    secrets.push(token);
    stage = 'storage';
    if (input.remember) updateStore({ username, passwordEnc: credential.encryptStoredCredentialValue(password) });
    else if (stored) updateStore(null);
    if (action === 'test') {
      emit({ ok: true, username, remembered: Boolean(input.remember) });
    } else {
      stage = 'migration';
      const { migrateCommand } = await import(pathToFileURL(path.join(lib, 'migration.js')).href);
      // CLI errors can contain HTTP response bodies. Emit only the message, with secrets removed.
      const write = process.stdout.write.bind(process.stdout);
      process.stdout.write = (chunk) => {
        const result = JSON.parse(String(chunk));
        if (result.ok === false) result.error = { message: safeMessage(result.error?.message || 'Migration failed.') };
        write(JSON.stringify(result, (key, value) => {
          if (/password|credential|token|authorization/i.test(key)) return '[redacted]';
          return typeof value === 'string' ? safeMessage(value) : value;
        }) + '\n');
        return true;
      };
      await migrateCommand(option('--config-id'), {
        json: true, sourceSession: alias, targetSession: option('--target-session'), sourceToken: token,
        configId: option('--config-id'), timeout: Number(option('--timeout') || 360000), dryRun: args.includes('--dry-run'),
      });
    }
  }
} catch (error) {
  // Never serialize Axios errors: they contain the submitted password and token.
  const message = stage === 'authentication'
    ? `Migration source login failed${error.response?.status ? ` (HTTP ${error.response.status})` : ''}. Check the credentials and source environment, then test again.`
    : stage === 'storage' ? 'Could not save the migration login. Check access to the CLI credential folder.'
    : stage === 'credentials' ? 'Enter the migration login again. Its saved credentials may be missing or unreadable.'
    : safeMessage(error.message);
  emit({ ok: false, error: { message } });
  process.exitCode = 1;
}

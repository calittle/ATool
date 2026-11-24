// Private password pathway. Normal SSO sessions are preserved when adding Password.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';

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
  const action = ['migrate', 'convertxml'].includes(command) ? command : args[0];
  const alias = option('--source-session') || option('--session');
  if (!['test', 'forget', 'preserve', 'signin', 'migrate', 'convertxml'].includes(action) || !alias) throw new Error('Select a Comms environment for the password login.');
  let raw = '';
  for await (const chunk of process.stdin) raw += chunk;
  const input = raw ? JSON.parse(raw) : {};
  raw = '';
  secrets = [input.password];
  const { loadSession, saveSession } = await import(pathToFileURL(path.join(lib, 'session.js')).href);
  let source;
  let existing;
  if (action === 'signin') {
    const customer=option('--customer'), region=option('--region'), tenancy=option('--tenancy');
    if (![customer,region,tenancy].every(value => /^[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?$/.test(value || ''))) {
      throw new Error('Enter a customer, region and tenancy for the password pathway.');
    }
    const sessionKey=`${customer}.${region}/${tenancy}`;
    source={customer,region,tenancy,sessionKey,baseUrl:`https://${customer}.${region}.oraclecloud.com/${tenancy}`};
    try { existing=loadSession({sessionName:sessionKey}); }
    catch (error) {
      // A new environment has no session yet. Do not overwrite an unreadable store.
      if (fs.existsSync(path.join(os.homedir(),'.occs-session.json')) &&
          !/saved session not found|session not found/i.test(error.message)) throw error;
    }
  } else {
    source = loadSession({ sessionName: alias, includeCredentials: action === 'preserve' });
  }
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
  const clearNormalSavedPassword = () => {
    const sessionPath=path.join(os.homedir(),'.occs-session.json');
    if (!fs.existsSync(sessionPath)) return;
    const lock=sessionPath+'.lock';
    fs.mkdirSync(lock,{mode:0o700});
    const temporary=sessionPath+'.'+process.pid+'.tmp';
    try {
      const store=JSON.parse(fs.readFileSync(sessionPath,'utf8'));
      const native=store.sessions?.[key] || (store.customer===source.customer && store.region===source.region && store.tenancy===source.tenancy ? store : null);
      if (native && native.authType !== 'sso') {
        delete native.credentials; delete native.username; delete native.password;
        fs.writeFileSync(temporary,JSON.stringify(store,null,2)+'\n',{mode:0o600,flag:'wx'});
        fs.renameSync(temporary,sessionPath);
      }
    } finally {
      fs.rmSync(temporary,{force:true});
      fs.rmdirSync(lock);
    }
  };
  if (action === 'preserve') {
    secrets.push(source.password);
    if (source.authType !== 'sso' && source.username && source.password && !readStore().logins[key]) {
      updateStore({username:source.username,passwordEnc:credential.encryptStoredCredentialValue(source.password)});
    }
    emit({ok:true});
  } else if (action === 'forget') {
    updateStore(null);
    clearNormalSavedPassword();
    emit({ ok: true });
  } else {
    stage = 'credentials';
    const stored = readStore().logins[key];
    let legacy = {};
    if (action === 'convertxml' && !input.username && !stored && source.authType !== 'sso') {
      legacy = loadSession({sessionName:alias,includeCredentials:true});
    }
    const remember = input.remember ?? Boolean(stored || legacy.password);
    const username = String(input.username || stored?.username || legacy.username || '').trim();
    const password = input.password || (stored?.username === username && stored?.passwordEnc
      ? credential.decryptStoredCredentialValue(stored.passwordEnc) : '') || (legacy.username === username ? legacy.password : '');
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
    if (remember) updateStore({ username, passwordEnc: credential.encryptStoredCredentialValue(password) });
    else if (stored) updateStore(null);
    if (action !== 'signin' && source.authType !== 'sso') {
      // A Password-only environment has one identity for normal and token-required work.
      saveSession({...source,authType:'password',token,savedAt:new Date().toISOString(),
        ...(remember ? {username,password} : {})}, {sessionName:alias,makeCurrent:false});
      if (!remember) clearNormalSavedPassword();
    }
    if (action === 'signin') {
      if (existing?.authType !== 'sso') {
        saveSession({...source,authType:'password',token,savedAt:new Date().toISOString(),
          ...(remember ? {username,password} : {})}, {sessionName:alias,makeCurrent:true});
      } else {
        // Register a new alias only when necessary; keep the existing SSO identity and cookies.
        let selected;
        try { selected=loadSession({sessionName:alias}); } catch {}
        if (selected?.sessionKey !== key) saveSession(existing,{sessionName:alias,makeCurrent:true});
      }
      if (!remember) clearNormalSavedPassword();
      emit({ok:true,username,remembered:Boolean(remember),normalAuthType:existing?.authType === 'sso'?'sso':'password'});
    } else if (action === 'test') {
      emit({ ok: true, username, remembered: Boolean(remember) });
    } else if (action === 'convertxml') {
      stage = 'conversion';
      if (!input.conversion_home) throw new Error('The private conversion session could not be prepared.');
      const worker = new URL('password_conversion.mjs', import.meta.url);
      const child = spawn(process.execPath, [fileURLToPath(worker), lib], {
        env: { ...process.env, HOME: input.conversion_home, USERPROFILE: input.conversion_home, OCCS_HTTP_DEBUG: '0' },
        stdio: ['pipe', 'pipe', 'pipe'],
      });
      child.stdout.on('data', chunk => process.stdout.write(chunk));
      child.stderr.on('data', chunk => process.stderr.write(chunk));
      const completed = new Promise((resolve, reject) => {
        child.on('error', reject);
        child.on('exit', code => resolve(code ?? 1));
      });
      child.stdin.on('error', () => {}); // A cancelled worker may close its input early.
      child.stdin.end(JSON.stringify({
        username, password, source: {
          sessionKey: key, baseUrl: source.baseUrl, customer: source.customer, region: source.region, tenancy: source.tenancy,
        },
        options: { session: alias, input: option('--input'), output: option('--output'),
          timeout: option('--timeout'), reroot: option('--reroot'), extract: option('--extract') },
      }));
      process.exitCode = await completed;
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
    ? `Password login failed${error.response?.status ? ` (HTTP ${error.response.status})` : ''}. Check the credentials and selected environment, then test again.`
    : stage === 'storage' ? 'Could not save the password login. Check access to the CLI credential folder.'
    : stage === 'credentials' ? 'Enter the password login again. Its saved credentials may be missing or unreadable.'
    : safeMessage(error.message);
  emit({ ok: false, error: { message } });
  process.exitCode = 1;
}

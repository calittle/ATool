"""Exercise the real bridge/transport with isolated CLI modules and no network calls."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from atool_qt.migration_login import migration_login_key, remembered_migration_login


@unittest.skipUnless(shutil.which('node'), 'Node.js is required')
class MigrationLoginBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.cli = self.root / 'cli'
        (self.cli / 'lib').mkdir(parents=True)
        (self.cli / 'bin').mkdir()
        (self.cli / 'bin' / 'occs.js').write_text('')
        (self.cli / 'package.json').write_text('{"type":"module"}')
        # Only these external CLI contracts are stubbed. The actual ATool bridge,
        # private stdin transport, and persistent file handling run unchanged.
        (self.cli / 'lib' / 'credentials.js').write_text('''
import crypto from 'node:crypto'; import fs from 'node:fs'; import os from 'node:os'; import path from 'node:path';
function key() {
  const folder = path.join(os.homedir(), '.occs-cli'); fs.mkdirSync(folder, {recursive:true});
  const file = path.join(folder, 'credential-key');
  if (!fs.existsSync(file)) fs.writeFileSync(file, crypto.randomBytes(32).toString('base64'), {mode:0o600});
  return Buffer.from(fs.readFileSync(file, 'utf8').trim(), 'base64');
}
export function encryptStoredCredentialValue(value) {
  const iv = crypto.randomBytes(12), cipher = crypto.createCipheriv('aes-256-gcm', key(), iv);
  const data = Buffer.concat([cipher.update(value, 'utf8'), cipher.final()]);
  return ['v2', iv.toString('base64'), cipher.getAuthTag().toString('base64'), data.toString('base64')].join(':');
}
export function decryptStoredCredentialValue(value) {
  const [, iv, tag, data] = value.split(':'), decipher = crypto.createDecipheriv('aes-256-gcm', key(), Buffer.from(iv, 'base64'));
  decipher.setAuthTag(Buffer.from(tag, 'base64'));
  return Buffer.concat([decipher.update(Buffer.from(data, 'base64')), decipher.final()]).toString('utf8');
}
''')
        (self.cli / 'lib' / 'session.js').write_text('''
import fs from 'node:fs'; import os from 'node:os'; import path from 'node:path';
export function loadSession({sessionName}) {
  const store = JSON.parse(fs.readFileSync(path.join(os.homedir(), '.occs-session.json'), 'utf8'));
  const key = store.aliases[sessionName] || sessionName;
  if (!store.sessions[key]) throw new Error('Session not found.');
  return {...store.sessions[key], sessionKey:key};
}
''')
        (self.cli / 'lib' / 'migration.js').write_text('''
export async function migrateCommand(id, opts) {
  if (opts.sourceToken !== 'MIGRATION_TOKEN' || opts.sourceSession !== 'np' || opts.targetSession !== 'pp') throw new Error('Wrong migration routing');
  if (id === 'fail') {
    console.log(JSON.stringify({ok:false,error:{message:'Rejected MIGRATION_TOKEN',details:{password:'temporary-secret'}}}));
    process.exitCode=1; return;
  }
  console.log(JSON.stringify({ok:true, dryRun:opts.dryRun, initiated:!opts.dryRun, eligible:[{id}],
    accessToken:opts.sourceToken, initiationResponse:{detail:'MIGRATION_TOKEN'}}));
}
''')
        axios = self.cli / 'node_modules' / 'axios'
        axios.mkdir(parents=True)
        (axios / 'package.json').write_text('{"type":"module"}')
        (axios / 'index.js').write_text('''
export default {async post(url, body, options) {
  if (url !== 'https://customer.region.oraclecloud.com/non-prod/api/oauth2/v1/access') throw new Error('Wrong source environment');
  if (body.User !== 'migration-user' || body.Password !== 'temporary-secret') {
    const error=new Error('Leaked password: '+body.Password); error.response={status:401,data:body}; throw error;
  }
  return {data:{AccessToken:'MIGRATION_TOKEN'}};
}};
''')
        self.session = self.home / '.occs-session.json'
        self.session.write_text(json.dumps({
            'currentSessionKey': 'customer.region/non-prod',
            'aliases': {'np': 'customer.region/non-prod', 'pp': 'customer.region/pre-prod'},
            'sessions': {
                'customer.region/non-prod': {'authType': 'sso', 'token': 'NP_SSO_TOKEN',
                                            'customer': 'customer', 'region': 'region', 'tenancy': 'non-prod',
                                            'baseUrl': 'https://customer.region.oraclecloud.com/non-prod'},
                'customer.region/pre-prod': {'authType': 'sso', 'token': 'PP_SSO_TOKEN',
                                            'customer': 'customer', 'region': 'region', 'tenancy': 'pre-prod',
                                            'baseUrl': 'https://customer.region.oraclecloud.com/pre-prod'},
            }}))
        self.original_session = self.session.read_bytes()
        self.bridge = Path(__file__).resolve().parents[1] / 'atool_qt' / 'migration_login.mjs'
        self.store = self.home / '.occs-cli' / 'atool-migration-logins.json'

    def invoke(self, args, credentials=None):
        environment = dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home))
        result = subprocess.run(['node', str(self.bridge), str(self.cli / 'bin' / 'occs.js'), *args],
                                input=json.dumps(credentials or {}), text=True, capture_output=True,
                                env=environment, timeout=10)
        self.assertEqual('', result.stderr)
        self.assertNotIn('temporary-secret', result.stdout)
        self.assertNotIn('MIGRATION_TOKEN', result.stdout)
        self.assertEqual(self.original_session, self.session.read_bytes())
        return result, json.loads(result.stdout)

    def test_remember_reuse_and_forget_leave_sso_sessions_unchanged(self):
        result, value = self.invoke(['migration-login', 'test', '--session', 'np'],
                                   dict(username='migration-user', password='temporary-secret', remember=True))
        self.assertEqual(0, result.returncode)
        self.assertTrue(value['remembered'])
        contents = self.store.read_text()
        self.assertNotIn('temporary-secret', contents)
        self.assertNotIn('TOKEN', contents)
        entry = json.loads(contents)['logins']['customer.region/non-prod']
        self.assertTrue(entry['passwordEnc'].startswith('v2:'))
        if os.name != 'nt':
            self.assertEqual(0o600, self.store.stat().st_mode & 0o777)
        result, value = self.invoke(['migrate', '--source-session', 'np', '--target-session', 'pp',
                                    '--config-id', '10', '--dry-run'], dict(username='migration-user', remember=True))
        self.assertEqual(0, result.returncode)
        self.assertTrue(value['dryRun'])
        self.assertFalse(value['initiated'])
        self.assertEqual('[redacted]', value['accessToken'])
        self.assertEqual('[redacted]', value['initiationResponse']['detail'])
        result, value = self.invoke(['migrate', '--source-session', 'np', '--target-session', 'pp',
                                    '--config-id', '10'], dict(username='migration-user', remember=True))
        self.assertEqual(0, result.returncode)
        self.assertTrue(value['initiated'])
        self.invoke(['migration-login', 'forget', '--session', 'np'])
        self.assertEqual({}, json.loads(self.store.read_text())['logins'])

    def test_unremembered_and_rejected_login_do_not_store_password(self):
        result, value = self.invoke(['migration-login', 'test', '--session', 'np'],
                                   dict(username='migration-user', password='temporary-secret', remember=False))
        self.assertEqual(0, result.returncode)
        self.assertFalse(value['remembered'])
        self.assertFalse(self.store.exists())
        result, value = self.invoke(['migration-login', 'test', '--session', 'np'],
                                   dict(username='migration-user', password='wrong-secret', remember=True))
        self.assertNotEqual(0, result.returncode)
        self.assertIn('HTTP 401', value['error']['message'])
        self.assertNotIn('wrong-secret', result.stdout)
        self.assertFalse(self.store.exists())

    def test_failed_movement_does_not_return_http_details_or_token(self):
        result, value = self.invoke(['migrate', '--source-session', 'np', '--target-session', 'pp', '--config-id', 'fail'],
                                   dict(username='migration-user', password='temporary-secret'))
        self.assertNotEqual(0, result.returncode)
        self.assertEqual({'message': 'Rejected [redacted]'}, value['error'])

    def test_failed_replacement_preserves_saved_login_and_unremember_removes_it(self):
        credentials=dict(username='migration-user', password='temporary-secret', remember=True)
        self.invoke(['migration-login', 'test', '--session', 'np'], credentials)
        before=self.store.read_bytes()
        result, _=self.invoke(['migration-login', 'test', '--session', 'np'],
                             dict(credentials, password='wrong-secret'))
        self.assertNotEqual(0,result.returncode)
        self.assertEqual(before,self.store.read_bytes())
        result, _=self.invoke(['migration-login', 'test', '--session', 'np'],dict(credentials,remember=False))
        self.assertEqual(0,result.returncode)
        self.assertEqual({},json.loads(self.store.read_text())['logins'])

    def test_save_and_forget_preserve_other_environment_credentials(self):
        self.store.parent.mkdir()
        other={'username':'other-user','passwordEnc':'unrelated-encrypted-password'}
        self.store.write_text(json.dumps({'version':1,'logins':{'other.region/non-prod':other}}))
        self.invoke(['migration-login', 'test', '--session', 'np'],
                    dict(username='migration-user',password='temporary-secret',remember=True))
        self.assertEqual(other,json.loads(self.store.read_text())['logins']['other.region/non-prod'])
        self.invoke(['migration-login','forget','--session','np'])
        self.assertEqual({'other.region/non-prod':other},json.loads(self.store.read_text())['logins'])

    def test_existing_cli_encryption_and_migration_command_compatibility(self):
        project=Path(__file__).resolve().parents[1]
        candidates=[project.parent/'ccs-tools'/'OCCS-CLI',project/'build'/'native'/'stage'/'occs-cli']
        actual=next((root for root in candidates if (root/'lib'/'credentials.js').exists()
                     and (root/'node_modules'/'axios'/'index.js').exists()),None)
        if actual is None:
            self.skipTest('A local OCCS CLI installation is needed for the compatibility check')
        for name in ('credentials','migration'):
            target=(actual/'lib'/f'{name}.js').as_uri()
            (self.cli/'lib'/f'{name}.js').write_text(f'export * from {json.dumps(target)};')
        credentials=dict(username='migration-user',password='temporary-secret',remember=True)
        result, _=self.invoke(['migration-login','test','--session','np'],credentials)
        self.assertEqual(0,result.returncode)
        modern_sso=(actual/'lib'/'sessionHttp.js').exists()
        if modern_sso:
            cookies=subprocess.run(['node','--input-type=module','-e',
                "import {createRequire} from 'node:module'; "
                f"const {{CookieJar}}=createRequire({json.dumps((actual/'package.json').as_uri())})('tough-cookie'); "
                "const jar=new CookieJar(); jar.setCookieSync('sessionid=TARGET_COOKIE; Path=/pre-prod/; Secure',"
                "'https://customer.region.oraclecloud.com/pre-prod/'); console.log(JSON.stringify(jar.serializeSync()));"],
                capture_output=True,text=True,timeout=10)
            self.assertEqual(0,cookies.returncode,cookies.stderr)
            store=json.loads(self.session.read_text())
            store['sessions']['customer.region/pre-prod']['cookieJar']=json.loads(cookies.stdout)
            self.session.write_text(json.dumps(store))
            self.original_session=self.session.read_bytes()
        wrapper='''
const axios=(await import(AXIOS)).default;
axios.get=async (url, options) => {
  if (url.includes('/non-prod/')) {
    if (options.headers.Authorization !== 'Bearer MIGRATION_TOKEN') throw new Error('Wrong source token');
    return {data:{Items:[{ConfigurationId:'10',ConfigurationInfo:{ShortName:'BillsFix'},
      ConfigurationStatus:{ConfigurationStatusCode:'Closed'}}],HasMore:false}};
  }
  if (options.headers.Authorization !== 'Bearer PP_SSO_TOKEN' && options.headers.Cookie !== 'sessionid=TARGET_COOKIE') throw new Error('Wrong target authentication');
  if (options.params.RequestList) {
    if (options.params.SourceTenantAuthToken !== 'Bearer MIGRATION_TOKEN') throw new Error('Wrong movement token');
    return {data:[{ShortName:'BillsFix'}]};
  }
  return {data:{Response:'Ready'}};
};
process.argv=['node', BRIDGE, CLI, 'migrate','--source-session','np','--target-session','pp','--config-id','10','--dry-run'];
await import(BRIDGE_URL);
'''
        replacements=dict(AXIOS=(actual/'node_modules'/'axios'/'index.js').as_uri(),BRIDGE=str(self.bridge),
                          CLI=str(self.cli/'bin'/'occs.js'),BRIDGE_URL=self.bridge.as_uri())
        import re
        wrapper=re.sub(r'\b(AXIOS|BRIDGE|CLI|BRIDGE_URL)\b',lambda match:json.dumps(replacements[match.group()]),wrapper)
        result=subprocess.run(['node','--input-type=module','-e',wrapper],
                              input=json.dumps(dict(username='migration-user',remember=True)),text=True,capture_output=True,
                              env=dict(os.environ,HOME=str(self.home),USERPROFILE=str(self.home)),timeout=10)
        self.assertEqual(0,result.returncode,result.stdout+result.stderr)
        value=json.loads(result.stdout)
        self.assertTrue(value['ok'])
        self.assertTrue(value['dryRun'])
        self.assertEqual('BillsFix',value['eligible'][0]['shortName'])
        self.assertEqual(self.original_session,self.session.read_bytes())
        self.assertNotIn('MIGRATION_TOKEN',result.stdout+result.stderr)

    def test_metadata_uses_environment_key_and_never_returns_password(self):
        self.invoke(['migration-login', 'test', '--session', 'np'],
                    dict(username='migration-user', password='temporary-secret', remember=True))
        with patch('pathlib.Path.home', return_value=self.home), \
                patch('atool_qt.migration_login.saved_login_targets', return_value=(
                    {'np': {'customer': 'customer', 'region': 'region', 'tenancy': 'non-prod'}}, 'np')):
            key = migration_login_key('np')
            self.assertEqual('customer.region/non-prod', key)
            self.assertEqual('migration-user', remembered_migration_login(key))

    def test_private_qprocess_input_is_not_in_arguments_or_output(self):
        import time
        from PySide6.QtWidgets import QApplication
        from atool_qt.occs import CommsService, CommsSettings
        app = QApplication.instance() or QApplication([])
        settings = CommsSettings(self.root / 'settings.json')
        settings.payload = {'occs': {'cli_path': str(self.cli / 'bin' / 'occs.js')}, 'diagnostics': {'debug_logging': True}}
        service = CommsService(settings)
        self.addCleanup(service.shutdown)
        results = []
        with patch.dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home)):
            job = service.submit(['migration-login', 'test', '--session', 'np', '--json'], results.append,
                                 private_input=dict(username='migration-user', password='temporary-secret', remember=True))
            deadline = time.monotonic() + 10
            while not results and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.005)
        self.assertTrue(results)
        self.assertTrue(results[0].successful, results[0].message)
        self.assertNotIn('temporary-secret', ' '.join(job.process.arguments()))
        self.assertNotIn('temporary-secret', results[0].stdout + results[0].stderr)
        self.assertIsNone(job.private_input)
        self.assertEqual('0', job.process.processEnvironment().value('OCCS_HTTP_DEBUG'))
        self.assertEqual(self.original_session, self.session.read_bytes())
        sign_ins=[]
        service.sign_in_required.connect(sign_ins.append)
        with patch.dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home)):
            failed=service.submit(['migration-login', 'test', '--session', 'np', '--json'], results.append,
                                  private_input=dict(username='migration-user', password='wrong-secret', remember=True))
            deadline=time.monotonic()+10
            while len(results)<2 and time.monotonic()<deadline:
                app.processEvents()
                time.sleep(0.005)
        self.assertEqual(2,len(results))
        self.assertFalse(results[1].successful)
        self.assertFalse(failed.login_attempted)
        self.assertEqual([],sign_ins)
        self.assertNotIn('wrong-secret',results[1].stdout+results[1].stderr)
        self.assertEqual(self.original_session,self.session.read_bytes())

    def test_config_login_dialog_tests_remembers_reopens_and_forgets(self):
        import time
        from PySide6.QtWidgets import QApplication, QMainWindow
        from atool_qt.migration_login import MigrationLoginDialog
        from atool_qt.occs import CommsService, CommsSettings
        app=QApplication.instance() or QApplication([])
        workspace=QMainWindow()
        self.addCleanup(workspace.close)
        settings=CommsSettings(self.root/'settings.json')
        settings.payload={'occs':{'cli_path':str(self.cli/'bin'/'occs.js')}}
        workspace.comms=CommsService(settings)
        self.addCleanup(workspace.comms.shutdown)
        def until_idle(dialog):
            deadline=time.monotonic()+10
            while dialog.busy and time.monotonic()<deadline:
                app.processEvents()
                time.sleep(0.005)
            self.assertFalse(dialog.busy)
        with patch('pathlib.Path.home',return_value=self.home), \
                patch.dict(os.environ,HOME=str(self.home),USERPROFILE=str(self.home)):
            dialog=MigrationLoginDialog(workspace,'np','pp',source_uses_sso=True)
            self.assertTrue(dialog.separate_migration_login.isChecked())
            dialog.migration_username.setText('migration-user')
            dialog.migration_password.setText('temporary-secret')
            dialog.remember_migration_login.setChecked(True)
            dialog.test_migration_login_button.click()
            until_idle(dialog)
            self.assertIn('Login remembered',dialog.status.text())
            self.assertTrue(self.store.exists())
            dialog.close()
            workspace.comms.migration_logins.clear()
            reopened=MigrationLoginDialog(workspace,'np','pp',source_uses_sso=True)
            self.assertEqual('migration-user',reopened.migration_username.text())
            self.assertEqual('',reopened.migration_password.text())
            self.assertTrue(reopened.remember_migration_login.isChecked())
            reopened.guard(reopened.submit)()
            self.assertEqual({'username':'migration-user','password':'','remember':True},reopened.credentials)
            reopened.forget_migration_login_button.click()
            until_idle(reopened)
            self.assertEqual('',reopened.migration_username.text())
            self.assertEqual({},json.loads(self.store.read_text())['logins'])
            reopened.close()
        self.assertEqual(self.original_session,self.session.read_bytes())

import test from 'node:test';
import assert from 'node:assert/strict';
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { validateProject } from '../scripts/validate-project.mjs';

const harmonyRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const repositoryRoot = resolve(harmonyRoot, '../..');

function projectFixture(t) {
  const temporaryRoot = mkdtempSync(resolve(tmpdir(), 'vibe-screen-harmony-validator-'));
  const fixtureRepository = resolve(temporaryRoot, 'repository');
  const fixtureHarmony = resolve(fixtureRepository, 'apps/harmony');
  mkdirSync(resolve(fixtureRepository, 'apps'), { recursive: true });
  cpSync(harmonyRoot, fixtureHarmony, {
    recursive: true,
    filter: (source) => !['node_modules', '.test-dist', 'dist', 'build'].includes(source.split('/').at(-1))
  });
  cpSync(resolve(repositoryRoot, 'LICENSE'), resolve(fixtureRepository, 'LICENSE'));
  cpSync(resolve(repositoryRoot, 'THIRD_PARTY.md'), resolve(fixtureRepository, 'THIRD_PARTY.md'));
  t.after(() => rmSync(temporaryRoot, { recursive: true, force: true }));
  return { fixtureHarmony, fixtureRepository };
}

const validateFixture = (fixture) => validateProject(fixture.fixtureHarmony, fixture.fixtureRepository);
const overwrite = (fixture, relative, content) => writeFileSync(resolve(fixture.fixtureHarmony, relative), content);

test('semantic validator accepts the checked-in Harmony project', () => {
  assert.deepEqual(validateProject(harmonyRoot, repositoryRoot), []);
});

test('semantic validator rejects malformed JSON5 even when expected tokens remain', (t) => {
  const fixture = projectFixture(t);
  overwrite(fixture, 'AppScope/app.json5', "broken { app: { versionName: '0.1.0', icon: '$media:app_icon' }");
  assert(validateFixture(fixture).some((failure) => failure.includes('AppScope/app.json5: invalid JSON5')));
});

test('semantic validator rejects extra permissions', (t) => {
  const fixture = projectFixture(t);
  const path = resolve(fixture.fixtureHarmony, 'entry/src/main/module.json5');
  const source = readFileSync(path, 'utf8').replace(
    "{ name: 'ohos.permission.INTERNET' }",
    "{ name: 'ohos.permission.INTERNET' }, { name: 'ohos.permission.CAMERA' }"
  );
  writeFileSync(path, source);
  assert(validateFixture(fixture).some((failure) => failure.includes('permissions must be exactly')));
});

test('semantic validator rejects comment-only Hvigor and Makefile tokens', (t) => {
  const fixture = projectFixture(t);
  overwrite(fixture, 'hvigorfile.ts', "// import { appTasks } from '@ohos/hvigor-ohos-plugin';\n// export default { system: appTasks };\n");
  overwrite(fixture, 'Makefile', '.PHONY: release\n# ohpm assembleHap signed.hap\nrelease:\n\t@true\n');
  const failures = validateFixture(fixture);
  assert(failures.some((failure) => failure.includes('must import and export appTasks')));
  assert(failures.some((failure) => failure.includes('exact release assembleHap command')));
});

test('semantic validator rejects broken resource and pages references', (t) => {
  const fixture = projectFixture(t);
  const modulePath = resolve(fixture.fixtureHarmony, 'entry/src/main/module.json5');
  writeFileSync(modulePath, readFileSync(modulePath, 'utf8').replace('$string:module_desc', '$string:missing_desc'));
  overwrite(fixture, 'entry/src/main/resources/base/profile/main_pages.json', '{ "src": ["pages/Missing"] }\n');
  const failures = validateFixture(fixture);
  assert(failures.some((failure) => failure.includes('missing string resource missing_desc')));
  assert(failures.some((failure) => failure.includes('src must contain only pages/Index')));
});

test('semantic validator rejects package version drift', (t) => {
  const fixture = projectFixture(t);
  const packagePath = resolve(fixture.fixtureHarmony, 'package.json');
  writeFileSync(packagePath, readFileSync(packagePath, 'utf8').replace('"version": "0.1.0"', '"version": "0.2.0"'));
  assert(validateFixture(fixture).some((failure) => failure.includes('package versions must both be 0.1.0')));
});

test('semantic validator rejects a disconnected production capability gate', (t) => {
  const fixture = projectFixture(t);
  const controllerPath = resolve(fixture.fixtureHarmony,
    'entry/src/main/ets/platform/HarmonySessionController.ets');
  writeFileSync(controllerPath, readFileSync(controllerPath, 'utf8').replaceAll('canSend', 'capabilityCheckRemoved'));
  assert(validateFixture(fixture).some((failure) => failure.includes('missing identifier canSend')));
});

test('semantic validator rejects removal of atomic Asset Store update wiring', (t) => {
  const fixture = projectFixture(t);
  const storePath = resolve(fixture.fixtureHarmony, 'entry/src/main/ets/platform/PairingStore.ets');
  writeFileSync(storePath, readFileSync(storePath, 'utf8').replaceAll('asset.update', 'asset.add'));
  assert(validateFixture(fixture).some((failure) => failure.includes('missing identifier update')));
});

test('semantic validator rejects removal of the bounded control backlog', (t) => {
  const fixture = projectFixture(t);
  const writerPath = resolve(fixture.fixtureHarmony,
    'entry/src/main/ets/core/protocol/OutboundControlWriter.ts');
  writeFileSync(writerPath, readFileSync(writerPath, 'utf8').replaceAll('MAX_PENDING_CONTROLS', 'UNBOUNDED_CONTROLS'));
  assert(validateFixture(fixture).some((failure) => failure.includes('missing identifier MAX_PENDING_CONTROLS')));
});

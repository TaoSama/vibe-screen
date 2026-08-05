#!/usr/bin/env node
import { parseArgs } from 'node:util';
import { readFileSync, statSync } from 'node:fs';
import { resolve } from 'node:path';

const { values } = parseArgs({
  options: {
    root: { type: 'string', default: resolve(import.meta.dirname, '..') },
    help: { type: 'boolean', short: 'h', default: false }
  }, strict: true
});

if (values.help) {
  process.stdout.write('Usage: node scripts/validate-project.mjs [--root PATH]\n');
  process.exit(0);
}

const root = resolve(values.root);
const requiredFiles = [
  'AppScope/app.json5', 'build-profile.json5', 'hvigorfile.ts', 'oh-package.json5',
  'entry/build-profile.json5', 'entry/hvigorfile.ts', 'entry/oh-package.json5',
  'entry/src/main/module.json5', 'entry/src/main/ets/entryability/EntryAbility.ets',
  'entry/src/main/ets/pages/Index.ets', 'entry/src/main/resources/base/profile/main_pages.json',
  'PRIVACY.md', 'UPGRADE.md'
];

const failures = [];
const read = (relative) => {
  const path = resolve(root, relative);
  try { return readFileSync(path, 'utf8'); }
  catch (error) { failures.push(`${relative}: ${error.message}`); return ''; }
};
const requireText = (relative, expected) => {
  const source = read(relative);
  for (const pattern of expected) if (!pattern.test(source)) failures.push(`${relative}: missing ${pattern}`);
};

for (const relative of requiredFiles) {
  try { if (!statSync(resolve(root, relative)).isFile()) failures.push(`${relative}: not a file`); }
  catch { failures.push(`${relative}: missing`); }
}

requireText('hvigorfile.ts', [/appTasks/, /@ohos\/hvigor-ohos-plugin/]);
requireText('entry/hvigorfile.ts', [/hapTasks/, /@ohos\/hvigor-ohos-plugin/]);
requireText('build-profile.json5', [/compatibleSdkVersion:\s*'5\.0\.0\(12\)'/, /srcPath:\s*'\.\/entry'/]);
requireText('entry/src/main/module.json5', [/type:\s*'entry'/, /srcEntry:\s*'\.\/ets\/entryability\/EntryAbility\.ets'/,
  /ohos\.permission\.INTERNET/]);
requireText('entry/src/main/ets/pages/Index.ets', [/HarmonyOS NEXT/, /XComponentController/, /sessionRuntime/, /onTouch/, /onMouse/, /onKeyEvent/]);
requireText('entry/src/main/ets/entryability/EntryAbility.ets', [/onForeground/, /onBackground/, /onDestroy/]);
requireText('Makefile', [/assembleHap/, /ohpm/, /signed\.hap/]);

const appProfile = read('AppScope/app.json5');
const rootPackage = read('package.json');
const modulePackage = read('entry/oh-package.json5');
const version = rootPackage.match(/"version"\s*:\s*"([^"]+)"/)?.[1];
if (version === undefined || !appProfile.includes(`versionName: '${version}'`) || !modulePackage.includes(`version: '${version}'`) ||
  !read('Makefile').includes(`VERSION := ${version}`)) {
  failures.push('versionName must match root and entry package versions');
}

const forbiddenSource = ['kotlin', 'androidx', 'kmp'];
for (const relative of ['entry/src/main/ets/pages/Index.ets', 'entry/src/main/ets/platform/HarmonySessionController.ets',
  'entry/src/main/ets/core/session/ProductSession.ts']) {
  const lower = read(relative).toLowerCase();
  for (const token of forbiddenSource) if (lower.includes(token)) failures.push(`${relative}: unsupported dependency token ${token}`);
}

if (read('entry/src/main/module.json5').includes('KEEP_BACKGROUND_RUNNING')) {
  failures.push('KEEP_BACKGROUND_RUNNING requires a real continuous-task implementation and must not be declaration-only');
}

for (const relative of ['entry/src/main/ets/core/protocol/ProtobufReader.ts',
  'entry/src/main/ets/core/protocol/ProtobufWriter.ts', 'entry/src/main/ets/platform/PairingStore.ets']) {
  if (/new\s+(TextEncoder|TextDecoder|URL)\b/.test(read(relative))) {
    failures.push(`${relative}: browser global hides an ArkTS API dependency`);
  }
}

if (failures.length > 0) {
  failures.forEach((failure) => process.stderr.write(`project validation: ${failure}\n`));
  process.exit(1);
}
process.stdout.write(`Validated ${requiredFiles.length} HarmonyOS project files (static only; no ArkTS/HAP claim).\n`);

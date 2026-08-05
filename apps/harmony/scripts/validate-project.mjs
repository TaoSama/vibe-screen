#!/usr/bin/env node
import { spawnSync } from 'node:child_process';
import { readFileSync, statSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { isDeepStrictEqual, parseArgs } from 'node:util';
import JSON5 from 'json5';
import ts from 'typescript';

const EXPECTED_PERMISSION = 'ohos.permission.INTERNET';
const EXPECTED_VERSION = '0.1.0';
const REQUIRED_FILES = [
  'AppScope/app.json5', 'AppScope/resources/base/element/string.json', 'AppScope/resources/base/media/app_icon.svg',
  'build-profile.json5', 'hvigorfile.ts', 'oh-package.json5', 'package.json', 'Makefile',
  'entry/build-profile.json5', 'entry/hvigorfile.ts', 'entry/oh-package.json5',
  'entry/src/main/module.json5', 'entry/src/main/ets/entryability/EntryAbility.ets',
  'entry/src/main/ets/pages/Index.ets', 'entry/src/main/resources/base/element/color.json',
  'entry/src/main/ets/core/media/LatestFrameQueue.ts',
  'entry/src/main/ets/core/protocol/OutboundControlWriter.ts',
  'entry/src/main/ets/core/session/ClientCapabilities.ts',
  'entry/src/main/ets/core/session/HeartbeatMonitor.ts',
  'entry/src/main/ets/core/session/ProgressWatchdog.ts',
  'entry/src/main/ets/core/session/ProductSession.ts',
  'entry/src/main/ets/platform/HarmonySessionController.ets',
  'entry/src/main/ets/platform/HarmonyVideoDecoder.ets',
  'entry/src/main/resources/base/element/string.json', 'entry/src/main/resources/base/profile/main_pages.json',
  'entry/src/main/resources/rawfile/license.txt', 'entry/src/main/resources/rawfile/third_party_notices.md',
  'PRIVACY.md', 'UPGRADE.md'
];

const own = (value, key) => Object.prototype.hasOwnProperty.call(value, key);

export function validateProject(rootValue, repositoryRootValue = resolve(rootValue, '../..')) {
  const root = resolve(rootValue);
  const repositoryRoot = resolve(repositoryRootValue);
  const failures = [];
  const sources = new Map();

  const fail = (message) => failures.push(message);
  const check = (condition, message) => { if (!condition) fail(message); };
  const read = (relative) => {
    if (sources.has(relative)) return sources.get(relative);
    try {
      const source = readFileSync(resolve(root, relative), 'utf8');
      sources.set(relative, source);
      return source;
    } catch (error) {
      fail(`${relative}: ${error.message}`);
      sources.set(relative, '');
      return '';
    }
  };
  const parseJson5 = (relative) => {
    const source = read(relative);
    try { return JSON5.parse(source); }
    catch (error) { fail(`${relative}: invalid JSON5: ${error.message}`); return undefined; }
  };

  for (const relative of REQUIRED_FILES) {
    try { if (!statSync(resolve(root, relative)).isFile()) fail(`${relative}: not a file`); }
    catch { fail(`${relative}: missing`); }
  }

  const appProfile = parseJson5('AppScope/app.json5');
  const buildProfile = parseJson5('build-profile.json5');
  const entryBuildProfile = parseJson5('entry/build-profile.json5');
  const moduleProfile = parseJson5('entry/src/main/module.json5');
  const rootOhPackage = parseJson5('oh-package.json5');
  const entryPackage = parseJson5('entry/oh-package.json5');
  const rootPackage = parseJson5('package.json');
  const appStrings = parseJson5('AppScope/resources/base/element/string.json');
  const entryStrings = parseJson5('entry/src/main/resources/base/element/string.json');
  const entryColors = parseJson5('entry/src/main/resources/base/element/color.json');
  const pagesProfile = parseJson5('entry/src/main/resources/base/profile/main_pages.json');

  const resourceNames = (document, property, relative) => {
    if (!Array.isArray(document?.[property])) { fail(`${relative}: ${property} must be an array`); return new Set(); }
    const names = new Set();
    for (const item of document[property]) {
      if (typeof item?.name !== 'string' || typeof item?.value !== 'string') {
        fail(`${relative}: every ${property} resource needs string name/value`);
      } else if (names.has(item.name)) {
        fail(`${relative}: duplicate ${property} resource ${item.name}`);
      } else names.add(item.name);
    }
    return names;
  };
  const appStringNames = resourceNames(appStrings, 'string', 'AppScope/resources/base/element/string.json');
  const entryStringNames = resourceNames(entryStrings, 'string', 'entry/src/main/resources/base/element/string.json');
  const entryColorNames = resourceNames(entryColors, 'color', 'entry/src/main/resources/base/element/color.json');

  const checkReference = (value, kind, names, owner) => {
    const match = typeof value === 'string' ? /^\$([a-z]+):([a-z][a-z0-9_]*)$/.exec(value) : undefined;
    check(match !== undefined && match[1] === kind, `${owner}: expected a $${kind}: resource reference`);
    if (match !== undefined && match[1] === kind) check(names.has(match[2]), `${owner}: missing ${kind} resource ${match[2]}`);
  };

  if (appProfile !== undefined) {
    const app = appProfile.app;
    check(app?.bundleName === 'dev.vibescreen.harmony', 'AppScope/app.json5: unexpected bundleName');
    check(Number.isInteger(app?.versionCode) && app.versionCode > 0, 'AppScope/app.json5: versionCode must be positive integer');
    check(app?.versionName === EXPECTED_VERSION, `AppScope/app.json5: versionName must be ${EXPECTED_VERSION}`);
    checkReference(app?.label, 'string', appStringNames, 'AppScope/app.json5 app.label');
    checkReference(app?.icon, 'media', new Set(['app_icon']), 'AppScope/app.json5 app.icon');
  }

  if (buildProfile !== undefined) {
    check(isDeepStrictEqual(buildProfile.modules, [{ name: 'entry', srcPath: './entry', targets: [{ name: 'default', applyToProducts: ['default'] }] }]),
      'build-profile.json5: modules must wire entry/default exactly');
    check(Array.isArray(buildProfile.app?.products) && buildProfile.app.products.length === 1 &&
      buildProfile.app.products[0]?.name === 'default' && buildProfile.app.products[0]?.compatibleSdkVersion === '5.0.0(12)',
      'build-profile.json5: default product must target API 12');
    check(isDeepStrictEqual(buildProfile.app?.buildModeSet, [{ name: 'debug' }, { name: 'release' }]),
      'build-profile.json5: debug/release build modes must be explicit');
  }
  if (entryBuildProfile !== undefined) {
    check(isDeepStrictEqual(entryBuildProfile.targets, [{ name: 'default' }]), 'entry/build-profile.json5: expected only default target');
    check(entryBuildProfile.buildOption?.arkOptions?.obfuscation?.ruleOptions?.enable === true,
      'entry/build-profile.json5: release obfuscation must remain enabled');
    check(isDeepStrictEqual(entryBuildProfile.buildOption?.arkOptions?.obfuscation?.ruleOptions?.files, ['./obfuscation-rules.txt']),
      'entry/build-profile.json5: obfuscation rules path mismatch');
  }

  if (moduleProfile !== undefined) {
    const module = moduleProfile.module;
    check(module?.name === 'entry' && module?.type === 'entry', 'entry/src/main/module.json5: module must be named/type entry');
    check(module?.mainElement === 'EntryAbility', 'entry/src/main/module.json5: mainElement must be EntryAbility');
    check(module?.deliveryWithInstall === true && module?.installationFree === false,
      'entry/src/main/module.json5: install delivery flags mismatch');
    check(isDeepStrictEqual(module?.deviceTypes, ['2in1', 'tablet']), 'entry/src/main/module.json5: deviceTypes mismatch');
    check(module?.pages === '$profile:main_pages', 'entry/src/main/module.json5: pages must reference main_pages');
    check(Array.isArray(module?.requestPermissions) && isDeepStrictEqual(module.requestPermissions.map((item) => item?.name), [EXPECTED_PERMISSION]),
      `entry/src/main/module.json5: permissions must be exactly ${EXPECTED_PERMISSION}`);
    check(Array.isArray(module?.abilities) && module.abilities.length === 1, 'entry/src/main/module.json5: exactly one ability is required');
    const ability = module?.abilities?.[0];
    check(ability?.name === module?.mainElement, 'entry/src/main/module.json5: ability must match mainElement');
    check(ability?.srcEntry === './ets/entryability/EntryAbility.ets', 'entry/src/main/module.json5: EntryAbility srcEntry mismatch');
    check(ability?.exported === true, 'entry/src/main/module.json5: EntryAbility must be exported');
    check(isDeepStrictEqual(ability?.skills, [{ entities: ['entity.system.home'], actions: ['ohos.want.action.home'] }]),
      'entry/src/main/module.json5: home skill wiring mismatch');
    checkReference(module?.description, 'string', entryStringNames, 'entry/src/main/module.json5 module.description');
    checkReference(ability?.description, 'string', entryStringNames, 'entry/src/main/module.json5 ability.description');
    checkReference(ability?.label, 'string', entryStringNames, 'entry/src/main/module.json5 ability.label');
    checkReference(ability?.icon, 'media', new Set(['app_icon']), 'entry/src/main/module.json5 ability.icon');
    checkReference(ability?.startWindowIcon, 'media', new Set(['app_icon']), 'entry/src/main/module.json5 ability.startWindowIcon');
    checkReference(ability?.startWindowBackground, 'color', entryColorNames, 'entry/src/main/module.json5 ability.startWindowBackground');
  }

  check(isDeepStrictEqual(pagesProfile?.src, ['pages/Index']),
    'entry/src/main/resources/base/profile/main_pages.json: src must contain only pages/Index');

  if (rootPackage !== undefined && entryPackage !== undefined && rootOhPackage !== undefined) {
    check(rootPackage.version === EXPECTED_VERSION && entryPackage.version === EXPECTED_VERSION,
      `package versions must both be ${EXPECTED_VERSION}`);
    check(entryPackage.license === 'MIT', 'entry/oh-package.json5: license must be MIT');
    check(isDeepStrictEqual(entryPackage.dependencies, {}), 'entry/oh-package.json5: runtime dependencies must be empty');
    check(rootOhPackage.modelVersion === '5.0.0', 'oh-package.json5: modelVersion mismatch');
    check(isDeepStrictEqual(rootOhPackage.dependencies, {}), 'oh-package.json5: runtime dependencies must be empty');
    check(isDeepStrictEqual(rootOhPackage.devDependencies,
      { '@ohos/hvigor': '5.0.2', '@ohos/hvigor-ohos-plugin': '5.0.2' }),
      'oh-package.json5: Hvigor dependencies must be pinned exactly');
    check(rootPackage.devDependencies?.json5 === '2.2.3' && rootPackage.devDependencies?.typescript === '5.9.3',
      'package.json: validator dependencies must be pinned exactly');
  }

  const validateHvigor = (relative, taskName) => {
    const source = read(relative);
    const sourceFile = ts.createSourceFile(relative, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
    const imported = sourceFile.statements.some((statement) => ts.isImportDeclaration(statement) &&
      statement.moduleSpecifier.text === '@ohos/hvigor-ohos-plugin' && statement.importClause?.namedBindings?.elements
        .some((element) => element.name.text === taskName));
    const exported = sourceFile.statements.some((statement) => ts.isExportAssignment(statement) &&
      ts.isObjectLiteralExpression(statement.expression) && statement.expression.properties.some((property) =>
        ts.isPropertyAssignment(property) && property.name.getText(sourceFile) === 'system' && property.initializer.getText(sourceFile) === taskName));
    check(imported && exported, `${relative}: must import and export ${taskName} as the Hvigor system task`);
  };
  validateHvigor('hvigorfile.ts', 'appTasks');
  validateHvigor('entry/hvigorfile.ts', 'hapTasks');

  const requireIdentifiers = (relative, identifiers) => {
    const sourceFile = ts.createSourceFile(relative, read(relative), ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
    const found = new Set();
    const visit = (node) => { if (ts.isIdentifier(node)) found.add(node.text); ts.forEachChild(node, visit); };
    visit(sourceFile);
    for (const identifier of identifiers) check(found.has(identifier), `${relative}: missing identifier ${identifier}`);
  };
  requireIdentifiers('entry/src/main/ets/pages/Index.ets',
    ['XComponentController', 'sessionRuntime', 'onTouch', 'onMouse', 'onKeyEvent']);
  requireIdentifiers('entry/src/main/ets/entryability/EntryAbility.ets', ['onForeground', 'onBackground', 'onDestroy']);
  requireIdentifiers('entry/src/main/ets/platform/HarmonySessionController.ets',
    ['OutboundControlWriter', 'HARMONY_ADVERTISED_CAPABILITIES', 'canSend', 'heartbeatTimedOut',
      'completeVideoConfiguration', 'onKeyframeRequired', 'runAllCleanup', 'armSessionWatchdog', 'ProgressWatchdog']);
  requireIdentifiers('entry/src/main/ets/core/protocol/OutboundControlWriter.ts',
    ['MAX_PENDING_CONTROLS', 'nextMessageId', 'drain']);
  requireIdentifiers('entry/src/main/ets/core/session/ProductSession.ts',
    ['bitDepth', 'bitrateKbps', 'CONFIGURING_VIDEO', 'heartbeatTimedOut']);
  requireIdentifiers('entry/src/main/ets/core/session/ClientCapabilities.ts',
    ['HARMONY_ADVERTISED_CAPABILITIES', 'HARMONY_REQUIRED_CAPABILITIES', 'acceptNegotiated']);
  requireIdentifiers('entry/src/main/ets/core/media/LatestFrameQueue.ts',
    ['WAITING_FOR_KEYFRAME', 'KEYFRAME_PENDING', 'DECODABLE', 'requestKeyframe']);
  requireIdentifiers('entry/src/main/ets/platform/PairingStore.ets',
    ['serialized', 'upsert', 'update', 'decodeIdentity', 'legacy']);

  for (const relative of ['entry/src/main/ets/core/protocol/ProtobufReader.ts',
    'entry/src/main/ets/core/protocol/ProtobufWriter.ts', 'entry/src/main/ets/platform/PairingStore.ets']) {
    const sourceFile = ts.createSourceFile(relative, read(relative), ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
    const visit = (node) => {
      if (ts.isNewExpression(node) && ts.isIdentifier(node.expression) && ['TextEncoder', 'TextDecoder', 'URL'].includes(node.expression.text)) {
        fail(`${relative}: browser global ${node.expression.text} hides an ArkTS API dependency`);
      }
      ts.forEachChild(node, visit);
    };
    visit(sourceFile);
  }

  const rootLicense = (() => {
    try { return readFileSync(resolve(repositoryRoot, 'LICENSE'), 'utf8'); }
    catch (error) { fail(`LICENSE: ${error.message}`); return ''; }
  })();
  check(read('entry/src/main/resources/rawfile/license.txt') === rootLicense,
    'entry/src/main/resources/rawfile/license.txt: must exactly match repository LICENSE');
  const notices = read('entry/src/main/resources/rawfile/third_party_notices.md');
  check(notices.includes('no third-party runtime') && notices.includes('not compiled into or distributed'),
    'entry/src/main/resources/rawfile/third_party_notices.md: runtime/build boundary notice missing');

  const makeResult = spawnSync('make', ['-n', '--no-print-directory', '-f', resolve(root, 'Makefile'), 'release',
    'HVIGOR=__HVIGOR__', 'OHPM=__OHPM__'], { cwd: root, encoding: 'utf8' });
  if (makeResult.error !== undefined) fail(`Makefile: unable to inspect release target: ${makeResult.error.message}`);
  else if (makeResult.status !== 0) fail(`Makefile: release dry-run failed: ${(makeResult.stderr || makeResult.stdout).trim()}`);
  else {
    const output = makeResult.stdout;
    const ohpmIndex = output.indexOf('__OHPM__ install');
    const hvigorCommand = '__HVIGOR__ --mode module -p module=entry@default -p product=default -p buildMode=release assembleHap';
    const hvigorIndex = output.indexOf(hvigorCommand);
    check(ohpmIndex >= 0 && hvigorIndex > ohpmIndex, 'Makefile: release must run OHPM install before the exact release assembleHap command');
    check(output.includes('rm -rf entry/build') && output.includes("find entry/build -name '*signed.hap' -type f"),
      'Makefile: release must clear stale output and select one signed HAP');
    for (const expected of [
      `cp ../../LICENSE dist/${EXPECTED_VERSION}/LICENSE.txt`,
      `cp ../../THIRD_PARTY.md dist/${EXPECTED_VERSION}/THIRD_PARTY.md`,
      `cp entry/src/main/resources/rawfile/third_party_notices.md dist/${EXPECTED_VERSION}/HARMONY_THIRD_PARTY_NOTICES.md`,
      `dist/${EXPECTED_VERSION}/vibe-screen-harmony-${EXPECTED_VERSION}.hap`,
      `cd dist/${EXPECTED_VERSION} && shasum -a 256 vibe-screen-harmony-${EXPECTED_VERSION}.hap LICENSE.txt THIRD_PARTY.md`,
      'HARMONY_THIRD_PARTY_NOTICES.md > SHA256SUMS'
    ]) check(output.includes(expected), `Makefile: release plan missing ${expected}`);
  }

  return failures;
}

function main() {
  const { values } = parseArgs({
    options: {
      root: { type: 'string', default: resolve(dirname(fileURLToPath(import.meta.url)), '..') },
      'repository-root': { type: 'string' },
      help: { type: 'boolean', short: 'h', default: false }
    }, strict: true
  });
  if (values.help) {
    process.stdout.write('Usage: node scripts/validate-project.mjs [--root PATH] [--repository-root PATH]\n');
    return;
  }
  const root = resolve(values.root);
  const failures = validateProject(root, values['repository-root'] ?? resolve(root, '../..'));
  if (failures.length > 0) {
    failures.forEach((failure) => process.stderr.write(`project validation: ${failure}\n`));
    process.exitCode = 1;
    return;
  }
  process.stdout.write(`Validated ${REQUIRED_FILES.length} HarmonyOS project files and semantic release boundaries (static only; no ArkTS/HAP claim).\n`);
}

const invokedPath = process.argv[1] === undefined ? undefined : pathToFileURL(resolve(process.argv[1])).href;
if (invokedPath === import.meta.url) main();

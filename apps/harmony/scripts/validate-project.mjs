#!/usr/bin/env node
import { spawnSync } from 'node:child_process';
import { readFileSync, readdirSync, statSync } from 'node:fs';
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
  'entry/src/main/ets/core/media/DecoderLifecycle.ts',
  'entry/src/main/ets/core/protocol/OutboundControlWriter.ts',
  'entry/src/main/ets/core/session/ClientCapabilities.ts',
  'entry/src/main/ets/core/session/HeartbeatMonitor.ts',
  'entry/src/main/ets/core/session/ProgressWatchdog.ts',
  'entry/src/main/ets/core/session/ProductSession.ts',
  'entry/src/main/ets/core/security/PairingSecurity.ts',
  'entry/src/main/ets/core/transport/TransportCloseOwner.ts',
  'entry/src/main/ets/platform/HarmonySessionController.ets',
  'entry/src/main/ets/platform/PairingStore.ets',
  'entry/src/main/ets/platform/HarmonyTransport.ets',
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

  const productionSourceFiles = ['hvigorfile.ts', 'entry/hvigorfile.ts'];
  const collectProductionSources = (directory, prefix) => {
    const entries = readdirSync(resolve(root, directory), { withFileTypes: true });
    for (const entry of entries) {
      const relative = `${prefix}/${entry.name}`;
      if (entry.isDirectory()) collectProductionSources(`${directory}/${entry.name}`, relative);
      else if (entry.isFile() && (entry.name.endsWith('.ts') || entry.name.endsWith('.ets'))) productionSourceFiles.push(relative);
    }
  };
  collectProductionSources('entry/src/main/ets', 'entry/src/main/ets');
  productionSourceFiles.sort();

  const normalizeArkUiForPortableParse = (relative, source) => {
    if (relative !== 'entry/src/main/ets/pages/Index.ets') return source;
    const builderOffset = source.indexOf('\n  @Builder');
    const scriptSection = builderOffset < 0 ? source : `${source.slice(0, builderOffset)}\n}`;
    return scriptSection
      .replace(/^\s*@(Entry|Component)\s*$/gm, (match) => ' '.repeat(match.length))
      .replace(/\bstruct\b/, 'class ')
      .replace(/@State\s+/g, (match) => ' '.repeat(match.length));
  };

  const portableSourceFiles = new Map();
  for (const relative of productionSourceFiles) {
    const sourceFile = ts.createSourceFile(relative, normalizeArkUiForPortableParse(relative, read(relative)),
      ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
    portableSourceFiles.set(relative, sourceFile);
    for (const diagnostic of sourceFile.parseDiagnostics) {
      const position = sourceFile.getLineAndCharacterOfPosition(diagnostic.start ?? 0);
      fail(`${relative}:${position.line + 1}:${position.character + 1}: portable parse error: ${ts.flattenDiagnosticMessageText(diagnostic.messageText, ' ')}`);
    }
  }

  const relationshipSourceFile = (relative) => {
    if (relative !== 'entry/src/main/ets/pages/Index.ets') return portableSourceFiles.get(relative);
    const source = read(relative)
      .replace(/^\s*@(Entry|Component)\s*$/gm, (match) => ' '.repeat(match.length))
      .replace(/\bstruct\b/, 'class ')
      .replace(/@State\s+/g, (match) => ' '.repeat(match.length));
    return ts.createSourceFile(relative, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
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

  const visitSource = (relative, visitor) => {
    const sourceFile = relationshipSourceFile(relative);
    if (sourceFile === undefined) { fail(`${relative}: source was not parsed`); return; }
    const visit = (node) => { visitor(node, sourceFile); ts.forEachChild(node, visit); };
    visit(sourceFile);
  };
  const hasNamedImport = (relative, moduleName, importedName) => {
    let found = false;
    visitSource(relative, (node) => {
      if (!ts.isImportDeclaration(node) || node.moduleSpecifier.text !== moduleName) return;
      const bindings = node.importClause?.namedBindings;
      if (bindings !== undefined && ts.isNamedImports(bindings) && bindings.elements.some((element) =>
        (element.propertyName?.text ?? element.name.text) === importedName)) found = true;
    });
    return found;
  };
  const classMethod = (relative, className, methodName) => {
    const sourceFile = portableSourceFiles.get(relative);
    if (sourceFile === undefined) return undefined;
    for (const statement of sourceFile.statements) {
      if (ts.isClassDeclaration(statement) && statement.name?.text === className) {
        return statement.members.find((member) => ts.isMethodDeclaration(member) && member.name.getText(sourceFile) === methodName);
      }
    }
    return undefined;
  };
  const constantBoolean = (node) => {
    if (node === undefined) return undefined;
    if (node.kind === ts.SyntaxKind.TrueKeyword) return true;
    if (node.kind === ts.SyntaxKind.FalseKeyword) return false;
    if (ts.isParenthesizedExpression(node)) return constantBoolean(node.expression);
    if (ts.isPrefixUnaryExpression(node) && node.operator === ts.SyntaxKind.ExclamationToken) {
      const operand = constantBoolean(node.operand);
      return operand === undefined ? undefined : !operand;
    }
    if (ts.isBinaryExpression(node)) {
      const left = constantBoolean(node.left);
      const right = constantBoolean(node.right);
      if (node.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken) {
        if (left === false || right === false) return false;
        if (left === true && right === true) return true;
      }
      if (node.operatorToken.kind === ts.SyntaxKind.BarBarToken) {
        if (left === true || right === true) return true;
        if (left === false && right === false) return false;
      }
    }
    return undefined;
  };
  const containsNode = (container, target) => target.pos >= container.pos && target.end <= container.end;
  const statementAlwaysTerminates = (statement) => {
    if (ts.isReturnStatement(statement) || ts.isThrowStatement(statement)) return true;
    if (ts.isBlock(statement)) return statement.statements.some((candidate) => statementAlwaysTerminates(candidate));
    if (ts.isIfStatement(statement)) {
      const condition = constantBoolean(statement.expression);
      if (condition === true) return statementAlwaysTerminates(statement.thenStatement);
      if (condition === false) return statement.elseStatement !== undefined && statementAlwaysTerminates(statement.elseStatement);
      return statement.elseStatement !== undefined && statementAlwaysTerminates(statement.thenStatement) &&
        statementAlwaysTerminates(statement.elseStatement);
    }
    return false;
  };
  const isReachableInMethod = (node, method) => {
    let child = node;
    for (let parent = node.parent; parent !== undefined && parent !== method; parent = parent.parent) {
      if (ts.isBinaryExpression(parent) && containsNode(parent.right, child)) {
        const left = constantBoolean(parent.left);
        if ((parent.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken && left === false) ||
          (parent.operatorToken.kind === ts.SyntaxKind.BarBarToken && left === true)) return false;
      }
      if (ts.isIfStatement(parent)) {
        const condition = constantBoolean(parent.expression);
        if (containsNode(parent.thenStatement, child) && condition === false) return false;
        if (parent.elseStatement !== undefined && containsNode(parent.elseStatement, child) && condition === true) return false;
      }
      if (ts.isConditionalExpression(parent)) {
        const condition = constantBoolean(parent.condition);
        if (containsNode(parent.whenTrue, child) && condition === false) return false;
        if (containsNode(parent.whenFalse, child) && condition === true) return false;
      }
      if ((ts.isWhileStatement(parent) || ts.isDoStatement(parent)) && containsNode(parent.statement, child) &&
        constantBoolean(parent.expression) === false) return false;
      if (ts.isBlock(parent)) {
        const directStatement = parent.statements.find((statement) => containsNode(statement, child));
        if (directStatement !== undefined) {
          const index = parent.statements.indexOf(directStatement);
          if (parent.statements.slice(0, index).some((statement) => statementAlwaysTerminates(statement))) return false;
        }
      }
      child = parent;
    }
    return true;
  };
  const nodeHasMethodCall = (node, sourceFile, receiver, methodName) => {
    let found = false;
    const visit = (candidate) => {
      if (ts.isCallExpression(candidate) && ts.isPropertyAccessExpression(candidate.expression) &&
        candidate.expression.name.text === methodName && candidate.expression.expression.getText(sourceFile) === receiver &&
        isReachableInMethod(candidate, node)) found = true;
      ts.forEachChild(candidate, visit);
    };
    visit(node);
    return found;
  };
  const methodHasCall = (relative, className, containerMethod, receiver, calledMethod) => {
    const sourceFile = portableSourceFiles.get(relative);
    const method = classMethod(relative, className, containerMethod);
    return sourceFile !== undefined && method !== undefined && nodeHasMethodCall(method, sourceFile, receiver, calledMethod);
  };
  const methodHasDirectCall = (relative, className, containerMethod, functionName) => {
    const sourceFile = portableSourceFiles.get(relative);
    const method = classMethod(relative, className, containerMethod);
    if (sourceFile === undefined || method === undefined) return false;
    let found = false;
    const visit = (node) => {
      if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === functionName &&
        isReachableInMethod(node, method)) found = true;
      ts.forEachChild(node, visit);
    };
    visit(method);
    return found;
  };
  const methodHasConstructorCall = (relative, className, containerMethod, constructedClass) => {
    const method = classMethod(relative, className, containerMethod);
    if (method === undefined) return false;
    let found = false;
    const visit = (node) => {
      if (ts.isNewExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === constructedClass &&
        isReachableInMethod(node, method)) found = true;
      ts.forEachChild(node, visit);
    };
    visit(method);
    return found;
  };
  const methodAwaitsExpression = (relative, className, containerMethod, expressionText) => {
    const sourceFile = portableSourceFiles.get(relative);
    const method = classMethod(relative, className, containerMethod);
    if (sourceFile === undefined || method === undefined) return false;
    let found = false;
    const visit = (node) => {
      if (ts.isAwaitExpression(node) && node.expression.getText(sourceFile) === expressionText &&
        isReachableInMethod(node, method)) found = true;
      ts.forEachChild(node, visit);
    };
    visit(method);
    return found;
  };
  const methodHasOrderedCreationReservation = (relative, className, containerMethod) => {
    const sourceFile = portableSourceFiles.get(relative);
    const method = classMethod(relative, className, containerMethod);
    if (sourceFile === undefined || method === undefined) return false;
    let creation;
    let install;
    let start;
    const visit = (node) => {
      if (ts.isNewExpression(node) && ts.isIdentifier(node.expression) &&
        node.expression.text === 'DecoderCandidateLease' && isReachableInMethod(node, method)) creation = node;
      if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression) &&
        node.expression.expression.getText(sourceFile) === 'this.candidates' && node.expression.name.text === 'install' &&
        isReachableInMethod(node, method)) install = node;
      if (ts.isAwaitExpression(node) && ts.isCallExpression(node.expression) &&
        ts.isPropertyAccessExpression(node.expression.expression) &&
        node.expression.expression.expression.getText(sourceFile) === 'creation' &&
        node.expression.expression.name.text === 'start' && isReachableInMethod(node, method)) start = node;
      ts.forEachChild(node, visit);
    };
    visit(method);
    return creation !== undefined && install !== undefined && start !== undefined &&
      creation.end <= install.pos && install.end <= start.pos;
  };
  const methodHasDominatingCapabilityGuard = (relative, className, methodName, capability, protectedCall) => {
    const sourceFile = portableSourceFiles.get(relative);
    const method = classMethod(relative, className, methodName);
    if (sourceFile === undefined || method === undefined) return false;
    const guard = method.body?.statements.find((statement) => {
      if (!ts.isIfStatement(statement) || !isReachableInMethod(statement, method)) return false;
      const exits = ts.isReturnStatement(statement.thenStatement) ||
        (ts.isBlock(statement.thenStatement) && statement.thenStatement.statements.some(ts.isReturnStatement));
      if (!exits || constantBoolean(statement.expression) === false) return false;
      const unwrap = (node) => ts.isParenthesizedExpression(node) ? unwrap(node.expression) : node;
      const orTerms = (node) => {
        const expression = unwrap(node);
        return ts.isBinaryExpression(expression) && expression.operatorToken.kind === ts.SyntaxKind.BarBarToken
          ? [...orTerms(expression.left), ...orTerms(expression.right)] : [expression];
      };
      return orTerms(statement.expression).some((term) => {
        const expression = unwrap(term);
        return ts.isPrefixUnaryExpression(expression) && expression.operator === ts.SyntaxKind.ExclamationToken &&
          ts.isCallExpression(expression.operand) && ts.isPropertyAccessExpression(expression.operand.expression) &&
          expression.operand.expression.expression.getText(sourceFile) === 'active' &&
          expression.operand.expression.name.text === 'canSend' && expression.operand.arguments.length === 1 &&
          expression.operand.arguments[0].getText(sourceFile) === capability;
      });
    });
    if (guard === undefined) return false;
    const protectedCalls = [];
    const visit = (node) => {
      if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression) &&
        node.expression.expression.getText(sourceFile) === 'active' && node.expression.name.text === protectedCall &&
        isReachableInMethod(node, method)) protectedCalls.push(node);
      ts.forEachChild(node, visit);
    };
    visit(method);
    return protectedCalls.length > 0 && protectedCalls.every((call) => guard.end <= call.pos);
  };
  const methodHasBoundedQueueGuard = (relative, className, methodName) => {
    const sourceFile = portableSourceFiles.get(relative);
    const method = classMethod(relative, className, methodName);
    if (sourceFile === undefined || method === undefined) return false;
    return method.body?.statements.some((statement) => {
      if (!ts.isIfStatement(statement) || constantBoolean(statement.expression) === false ||
        !isReachableInMethod(statement, method)) return false;
      const expression = ts.isParenthesizedExpression(statement.expression)
        ? statement.expression.expression : statement.expression;
      const bounded = ts.isBinaryExpression(expression) &&
        expression.operatorToken.kind === ts.SyntaxKind.GreaterThanEqualsToken &&
        ts.isCallExpression(expression.left) && ts.isPropertyAccessExpression(expression.left.expression) &&
        expression.left.expression.expression.kind === ts.SyntaxKind.ThisKeyword &&
        expression.left.expression.name.text === 'queuedCount' && expression.left.arguments.length === 0 &&
        ts.isIdentifier(expression.right) && expression.right.text === 'MAX_PENDING_CONTROLS';
      return bounded && nodeHasMethodCall(statement.thenStatement, sourceFile, 'this', 'fail') &&
        (ts.isReturnStatement(statement.thenStatement) ||
          (ts.isBlock(statement.thenStatement) && statement.thenStatement.statements.some(ts.isReturnStatement)));
    }) === true;
  };
  const hasConstructorCall = (relative, className) => {
    let found = false;
    visitSource(relative, (node) => {
      if (ts.isNewExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === className) found = true;
    });
    return found;
  };
  const hasClassMethod = (relative, className, methodName) => {
    let found = false;
    visitSource(relative, (node) => {
      if (ts.isClassDeclaration(node) && node.name?.text === className && node.members.some((member) =>
        ts.isMethodDeclaration(member) && member.name.getText() === methodName)) found = true;
    });
    return found;
  };
  const classPropertyUsesCleanupOwner = (relative, className, propertyName) => {
    const sourceFile = portableSourceFiles.get(relative);
    if (sourceFile === undefined) return false;
    const declaration = sourceFile.statements.find((statement) =>
      ts.isClassDeclaration(statement) && statement.name?.text === className);
    if (declaration === undefined || !ts.isClassDeclaration(declaration)) return false;
    const property = declaration.members.find((member) => ts.isPropertyDeclaration(member) &&
      member.name.getText(sourceFile) === propertyName);
    if (property === undefined || !ts.isPropertyDeclaration(property) ||
      property.initializer === undefined || !ts.isNewExpression(property.initializer) ||
      !ts.isIdentifier(property.initializer.expression) ||
      property.initializer.expression.text !== 'DecoderTransitionOwner' || property.initializer.arguments.length !== 1) return false;
    const cleanup = property.initializer.arguments[0];
    if (!ts.isArrowFunction(cleanup) || !ts.isCallExpression(cleanup.body) ||
      !ts.isPropertyAccessExpression(cleanup.body.expression)) return false;
    return cleanup.body.expression.expression.kind === ts.SyntaxKind.ThisKeyword &&
      cleanup.body.expression.name.text === 'releaseDetached' && cleanup.body.arguments.length === 1 &&
      cleanup.body.arguments[0].getText(sourceFile) === 'candidate';
  };
  const hasEnumMembers = (relative, enumName, members) => {
    let found = false;
    visitSource(relative, (node) => {
      if (ts.isEnumDeclaration(node) && node.name.text === enumName) {
        const names = new Set(node.members.map((member) => member.name.getText().replaceAll("'", '')));
        found = members.every((member) => names.has(member));
      }
    });
    return found;
  };
  const requireImport = (relative, moduleName, importedName) => check(hasNamedImport(relative, moduleName, importedName),
    `${relative}: must import ${importedName} from ${moduleName}`);
  const requireCallInMethod = (relative, className, containerMethod, receiver, calledMethod) =>
    check(methodHasCall(relative, className, containerMethod, receiver, calledMethod),
      `${relative}: ${className}.${containerMethod}() must call ${receiver}.${calledMethod}()`);
  const requireConstructorCall = (relative, className) => check(hasConstructorCall(relative, className),
    `${relative}: production path must construct ${className}`);

  const indexPath = 'entry/src/main/ets/pages/Index.ets';
  requireImport(indexPath, '../platform/SessionRuntime', 'sessionRuntime');
  requireCallInMethod(indexPath, 'Index', 'aboutToAppear', 'sessionRuntime', 'attachUi');
  requireCallInMethod(indexPath, 'Index', 'aboutToAppear', 'sessionRuntime', 'restoreHost');
  requireCallInMethod(indexPath, 'Index', 'aboutToDisappear', 'sessionRuntime', 'detachUi');
  requireCallInMethod(indexPath, 'Index', 'connect', 'sessionRuntime', 'connect');
  requireCallInMethod(indexPath, 'Index', 'importLink', 'sessionRuntime', 'importPairingLink');
  requireCallInMethod(indexPath, 'Index', 'handleTouch', 'sessionRuntime', 'sendTouch');
  requireCallInMethod(indexPath, 'Index', 'handleTouch', 'sessionRuntime', 'sendStylus');
  check(read(indexPath).includes('pressure: event.pressure') && !read(indexPath).includes('touch.pressure'),
    `${indexPath}: API 12 stylus pressure must come from TouchEvent.pressure, not TouchObject`);
  requireCallInMethod(indexPath, 'Index', 'handleMouse', 'sessionRuntime', 'sendPointer');
  requireCallInMethod(indexPath, 'Index', 'handleKey', 'sessionRuntime', 'sendKey');
  check(read(indexPath).includes('.onLoad(() => sessionRuntime.setSurface(') &&
    read(indexPath).includes('.onDestroy(() => sessionRuntime.clearSurface())'),
    `${indexPath}: XComponent lifecycle must call sessionRuntime.setSurface()/clearSurface()`);
  requireConstructorCall(indexPath, 'XComponentController');

  const abilityPath = 'entry/src/main/ets/entryability/EntryAbility.ets';
  requireImport(abilityPath, '../platform/SessionRuntime', 'sessionRuntime');
  requireCallInMethod(abilityPath, 'EntryAbility', 'onForeground', 'sessionRuntime', 'onForeground');
  requireCallInMethod(abilityPath, 'EntryAbility', 'onBackground', 'sessionRuntime', 'onBackground');
  requireCallInMethod(abilityPath, 'EntryAbility', 'onDestroy', 'sessionRuntime', 'disconnect');

  const controllerPath = 'entry/src/main/ets/platform/HarmonySessionController.ets';
  requireImport(controllerPath, '../core/protocol/OutboundControlWriter', 'OutboundControlWriter');
  requireImport(controllerPath, '../core/session/ClientCapabilities', 'HARMONY_ADVERTISED_CAPABILITIES');
  requireImport(controllerPath, '../core/session/CleanupCoordinator', 'runAllCleanup');
  requireImport(controllerPath, '../core/session/ProgressWatchdog', 'ProgressWatchdog');
  requireConstructorCall(controllerPath, 'OutboundControlWriter');
  requireConstructorCall(controllerPath, 'ProgressWatchdog');
  check(methodHasDominatingCapabilityGuard(controllerPath, 'HarmonySessionController', 'sendTouch', 'Capability.TOUCH', 'touch'),
    `${controllerPath}: HarmonySessionController.sendTouch() must use a dominating TOUCH early-return guard`);
  requireCallInMethod(controllerPath, 'HarmonySessionController', 'sendTouch', 'active', 'touch');
  check(methodHasDominatingCapabilityGuard(controllerPath, 'HarmonySessionController', 'sendPointer', 'Capability.POINTER', 'pointer'),
    `${controllerPath}: HarmonySessionController.sendPointer() must use a dominating POINTER early-return guard`);
  requireCallInMethod(controllerPath, 'HarmonySessionController', 'sendPointer', 'active', 'pointer');
  check(methodHasDominatingCapabilityGuard(controllerPath, 'HarmonySessionController', 'sendScroll', 'Capability.POINTER', 'scroll'),
    `${controllerPath}: HarmonySessionController.sendScroll() must use a dominating POINTER early-return guard`);
  requireCallInMethod(controllerPath, 'HarmonySessionController', 'sendScroll', 'active', 'scroll');
  check(methodHasDominatingCapabilityGuard(controllerPath, 'HarmonySessionController', 'sendKey', 'Capability.KEYBOARD', 'key'),
    `${controllerPath}: HarmonySessionController.sendKey() must use a dominating KEYBOARD early-return guard`);
  requireCallInMethod(controllerPath, 'HarmonySessionController', 'sendKey', 'active', 'key');
  requireCallInMethod(controllerPath, 'HarmonySessionController', 'sendStylus', 'active', 'stylus');
  requireCallInMethod(controllerPath, 'HarmonySessionController', 'sendStylus', 'active', 'touch');
  check(methodHasDominatingCapabilityGuard(controllerPath, 'HarmonySessionController', 'sendControllerSamples',
    'Capability.CONTROLLER', 'controller'),
  `${controllerPath}: HarmonySessionController.sendControllerSamples() must use a dominating CONTROLLER early-return guard`);
  requireCallInMethod(controllerPath, 'HarmonySessionController', 'sendControllerSamples', 'active', 'controller');
  requireCallInMethod(controllerPath, 'HarmonySessionController', 'sendAction', 'writer', 'enqueue');
  requireCallInMethod(controllerPath, 'HarmonySessionController', 'configureVideo', 'this.videoDecoder', 'configure');
  requireCallInMethod(controllerPath, 'HarmonySessionController', 'configureVideo', 'active', 'completeVideoConfiguration');
  requireCallInMethod(controllerPath, 'HarmonySessionController', 'startHeartbeat', 'active', 'heartbeatTimedOut');
  requireCallInMethod(controllerPath, 'HarmonySessionController', 'onTransportReady', 'this', 'armSessionWatchdog');
  requireCallInMethod(controllerPath, 'HarmonySessionController', 'onTransportLost', 'this.session', 'resumableSnapshot');
  check(methodHasDirectCall(controllerPath, 'HarmonySessionController', 'cleanupResources', 'runAllCleanup'),
    `${controllerPath}: HarmonySessionController.cleanupResources() must call runAllCleanup()`);
  requireCallInMethod(controllerPath, 'HarmonySessionController', 'cleanupResources', 'this.transport', 'close');
  requireCallInMethod(controllerPath, 'HarmonySessionController', 'cleanupResources', 'this.videoDecoder', 'release');

  const decoderPath = 'entry/src/main/ets/platform/HarmonyVideoDecoder.ets';
  requireImport(decoderPath, '../core/media/DecoderLifecycle', 'DecoderLifecycle');
  requireImport(decoderPath, '../core/media/DecoderLifecycle', 'DecoderCandidateLease');
  requireImport(decoderPath, '../core/media/DecoderLifecycle', 'DecoderTransitionOwner');
  check(classPropertyUsesCleanupOwner(decoderPath, 'HarmonyVideoDecoder', 'candidates'),
    `${decoderPath}: HarmonyVideoDecoder.candidates must construct DecoderTransitionOwner with releaseDetached cleanup`);
  check(methodHasConstructorCall(decoderPath, 'HarmonyVideoDecoder', 'configure', 'DecoderLifecycle'),
    `${decoderPath}: HarmonyVideoDecoder.configure() must construct a reachable per-candidate DecoderLifecycle`);
  check(methodHasOrderedCreationReservation(decoderPath, 'HarmonyVideoDecoder', 'configure'),
    `${decoderPath}: HarmonyVideoDecoder.configure() must reserve DecoderCandidateLease before awaiting native creation`);
  requireCallInMethod(decoderPath, 'HarmonyVideoDecoder', 'configure', 'this.candidates', 'detachAndCleanup');
  check(methodAwaitsExpression(decoderPath, 'HarmonyVideoDecoder', 'configure', 'transition.completion'),
    `${decoderPath}: HarmonyVideoDecoder.configure() must await the decoder cleanup transition`);
  requireCallInMethod(decoderPath, 'HarmonyVideoDecoder', 'configure', 'lifecycle', 'initialize');
  requireCallInMethod(decoderPath, 'HarmonyVideoDecoder', 'configure', 'this', 'clearCandidateIfCurrent');
  requireCallInMethod(decoderPath, 'HarmonyVideoDecoder', 'release', 'this.candidates', 'detachAndCleanup');
  check(methodAwaitsExpression(decoderPath, 'HarmonyVideoDecoder', 'release', 'transition.completion'),
    `${decoderPath}: HarmonyVideoDecoder.release() must await the decoder cleanup transition`);
  requireCallInMethod(decoderPath, 'HarmonyVideoDecoder', 'releaseDetached', 'detached.lease', 'cancelAndCleanup');

  const transportPath = 'entry/src/main/ets/platform/HarmonyTransport.ets';
  requireImport(transportPath, '../core/transport/TransportCloseOwner', 'TransportCloseOwner');
  requireConstructorCall(transportPath, 'TransportCloseOwner');
  requireCallInMethod(transportPath, 'HarmonyTransport', 'connect', 'this', 'terminate');
  requireCallInMethod(transportPath, 'HarmonyTransport', 'close', 'this', 'terminate');
  requireCallInMethod(transportPath, 'HarmonyTransport', 'terminate', 'this.closeOwner', 'claim');
  requireCallInMethod(transportPath, 'HarmonyTransport', 'terminate', 'candidate', 'close');
  requireCallInMethod(transportPath, 'HarmonyTransport', 'terminate', 'listener', 'onDisconnected');

  const writerPath = 'entry/src/main/ets/core/protocol/OutboundControlWriter.ts';
  check(methodHasBoundedQueueGuard(writerPath, 'OutboundControlWriter', 'enqueue'),
    `${writerPath}: enqueue() must use a reachable MAX_PENDING_CONTROLS fail-closed guard`);
  check(hasClassMethod(writerPath, 'OutboundControlWriter', 'drain'), `${writerPath}: OutboundControlWriter.drain() is required`);

  const sessionPath = 'entry/src/main/ets/core/session/ProductSession.ts';
  requireImport(sessionPath, './ClientCapabilities', 'ClientCapabilities');
  requireImport(sessionPath, './HeartbeatMonitor', 'HeartbeatMonitor');
  requireCallInMethod(sessionPath, 'ProductSession', 'onSessionAccepted', 'this.capabilityState', 'acceptNegotiated');
  requireCallInMethod(sessionPath, 'ProductSession', 'heartbeatTimedOut', 'this.heartbeatMonitor', 'timedOut');
  requireCallInMethod(sessionPath, 'ProductSession', 'onResumeResult', 'this.decoder', 'resumeSessionResult');

  const securityPath = 'entry/src/main/ets/core/security/PairingSecurity.ts';
  requireCallInMethod(securityPath, 'PairingClient', 'begin', 'this.crypto', 'ephemeral');
  requireCallInMethod(securityPath, 'PendingPairing', 'complete', 'this.crypto', 'verify');
  requireCallInMethod(securityPath, 'CredentialLifecycle', 'install', 'this.store', 'save');
  requireCallInMethod(securityPath, 'CredentialLifecycle', 'revoke', 'this.store', 'save');

  const pairingStorePath = 'entry/src/main/ets/platform/PairingStore.ets';
  requireCallInMethod(pairingStorePath, 'PairingStore', 'save', 'this', 'upsert');
  check(hasEnumMembers(sessionPath, 'ProductSessionState', ['CONFIGURING_VIDEO']),
    `${sessionPath}: ProductSessionState.CONFIGURING_VIDEO is required`);

  const capabilitiesPath = 'entry/src/main/ets/core/session/ClientCapabilities.ts';
  check(hasClassMethod(capabilitiesPath, 'ClientCapabilities', 'acceptNegotiated'),
    `${capabilitiesPath}: ClientCapabilities.acceptNegotiated() is required`);

  const queuePath = 'entry/src/main/ets/core/media/LatestFrameQueue.ts';
  check(hasEnumMembers(queuePath, 'FrameQueueState', ['WAITING_FOR_KEYFRAME', 'KEYFRAME_PENDING', 'DECODABLE']),
    `${queuePath}: FrameQueueState must retain wait/keyframe/decodable states`);

  const pairingPath = 'entry/src/main/ets/platform/PairingStore.ets';
  requireImport(pairingPath, '@kit.AssetStoreKit', 'asset');
  requireCallInMethod(pairingPath, 'PairingStore', 'saveTrustedHost', 'this', 'serialized');
  requireCallInMethod(pairingPath, 'PairingStore', 'clientId', 'this', 'decodeIdentity');
  requireCallInMethod(pairingPath, 'PairingStore', 'upsert', 'asset', 'update');

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

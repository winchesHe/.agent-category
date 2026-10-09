import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, readFileSync, readdirSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { installSharedDependencies } from "../templates/sites/scripts/shared-deps.mjs";

function fixture(t) {
  const root = mkdtempSync(path.join(tmpdir(), "acceptance-shared-deps-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const cacheRoot = path.join(root, "cache");
  const npmPath = path.join(root, "npm.mjs");
  writeFileSync(npmPath, `
    import { mkdirSync, readFileSync, writeFileSync, chmodSync } from 'node:fs';
    mkdirSync('node_modules/.bin', { recursive: true });
    const bin = 'node_modules/.bin/' + (process.platform === 'win32' ? 'vinext.cmd' : 'vinext');
    writeFileSync(bin, 'test executable');
    chmodSync(bin, 0o755);
    writeFileSync('node_modules/installed-version', JSON.parse(readFileSync('package-lock.json')).version ?? '1');
  `);
  function project(name) {
    const directory = path.join(root, name);
    mkdirSync(directory);
    writeFileSync(path.join(directory, "package.json"), JSON.stringify({ name: "report", private: true }));
    writeFileSync(path.join(directory, "package-lock.json"), JSON.stringify({ lockfileVersion: 3, packages: {} }));
    return directory;
  }
  return { root, cacheRoot, npmPath, project };
}

test("不同报告只复用一份依赖，重复连接不产生备份", (t) => {
  const f = fixture(t);
  const a = f.project("a"), b = f.project("b");
  const first = installSharedDependencies(a, f);
  writeFileSync(path.join(b, "package-lock.json"), JSON.stringify({ lockfileVersion: 3, packages: {}, version: "older" }));
  writeFileSync(f.npmPath, "process.exit(9)");
  const second = installSharedDependencies(b, f);
  assert.equal(realpathSync(path.join(a, "node_modules")), realpathSync(path.join(b, "node_modules")));
  assert.equal(first.modules, second.modules);
  assert.equal(installSharedDependencies(a, f).backup, null);
  assert.deepEqual(readdirSync(f.cacheRoot), ["node_modules"]);
});

test("刷新替换唯一共享依赖，旧报告使用新依赖且不会按旧锁文件降级", (t) => {
  const f = fixture(t);
  const a = f.project("a"), b = f.project("b");
  const first = installSharedDependencies(a, f);
  writeFileSync(path.join(b, "package-lock.json"), JSON.stringify({ lockfileVersion: 3, packages: {}, version: "2" }));
  const second = installSharedDependencies(b, { ...f, refresh: true });
  assert.equal(first.modules, second.modules);
  assert.equal(realpathSync(path.join(a, "node_modules")), realpathSync(first.modules));
  writeFileSync(f.npmPath, "process.exit(9)");
  installSharedDependencies(a, f);
  for (const project of [a, b]) {
    assert.equal(readFileSync(path.join(project, "node_modules", "installed-version"), "utf8"), "2");
  }
  assert.deepEqual(readdirSync(f.cacheRoot), ["node_modules"]);
});

test("迁移保留原安装，失败安装不替换本地依赖或留下半成品", (t) => {
  const f = fixture(t);
  const a = f.project("a");
  mkdirSync(path.join(a, "node_modules"));
  writeFileSync(path.join(a, "node_modules", "original"), "keep");
  const installed = installSharedDependencies(a, f);
  assert.equal(readFileSync(path.join(installed.backup, "original"), "utf8"), "keep");
  const b = f.project("b");
  mkdirSync(path.join(b, "node_modules"));
  writeFileSync(path.join(b, "node_modules", "original"), "keep");
  writeFileSync(path.join(b, "package.json"), JSON.stringify({ name: "changed" }));
  writeFileSync(f.npmPath, "process.exit(7)");
  assert.throws(() => installSharedDependencies(b, { ...f, refresh: true }), /安装失败/);
  assert.equal(readFileSync(path.join(b, "node_modules", "original"), "utf8"), "keep");
  assert.equal(readFileSync(path.join(a, "node_modules", "installed-version"), "utf8"), "1");
  assert.deepEqual(readdirSync(f.cacheRoot), ["node_modules"]);
});

test("安装命令成功但缺少预览入口时，不发布半成品或替换原依赖", (t) => {
  const f = fixture(t);
  const a = f.project("a");
  mkdirSync(path.join(a, "node_modules"));
  writeFileSync(path.join(a, "node_modules", "original"), "keep");
  writeFileSync(f.npmPath, "import { mkdirSync } from 'node:fs'; mkdirSync('node_modules');");
  assert.throws(() => installSharedDependencies(a, f), { code: "ENOENT" });
  assert.equal(readFileSync(path.join(a, "node_modules", "original"), "utf8"), "keep");
  assert.deepEqual(readdirSync(f.cacheRoot), []);
});

test("刷新结果缺少预览入口时，所有已连接的报告继续使用原依赖", (t) => {
  const f = fixture(t);
  const a = f.project("a"), b = f.project("b");
  installSharedDependencies(a, f);
  installSharedDependencies(b, f);
  writeFileSync(f.npmPath, "import { mkdirSync } from 'node:fs'; mkdirSync('node_modules');");
  assert.throws(() => installSharedDependencies(b, { ...f, refresh: true }), { code: "ENOENT" });
  for (const project of [a, b]) {
    assert.equal(readFileSync(path.join(project, "node_modules", "installed-version"), "utf8"), "1");
  }
  assert.deepEqual(readdirSync(f.cacheRoot), ["node_modules"]);
});

test("已有共享依赖缺少预览入口时，不替换项目原依赖", (t) => {
  const f = fixture(t);
  const a = f.project("a"), b = f.project("b");
  const installed = installSharedDependencies(a, f);
  rmSync(path.join(installed.modules, ".bin"), { recursive: true });
  mkdirSync(path.join(b, "node_modules"));
  writeFileSync(path.join(b, "node_modules", "original"), "keep");
  writeFileSync(f.npmPath, "process.exit(9)");
  assert.throws(() => installSharedDependencies(b, f), { code: "ENOENT" });
  assert.equal(readFileSync(path.join(b, "node_modules", "original"), "utf8"), "keep");
});

test("安装锁保护首次安装与刷新，已有依赖仍可直接复用", (t) => {
  const f = fixture(t);
  const a = f.project("a"), b = f.project("b");
  const installed = installSharedDependencies(a, f);
  const lock = path.join(f.cacheRoot, ".install-lock");
  mkdirSync(lock);
  writeFileSync(f.npmPath, "process.exit(9)");
  assert.equal(installSharedDependencies(b, f).modules, installed.modules);
  assert.throws(() => installSharedDependencies(b, { ...f, refresh: true }), /正在安装/);
  assert.deepEqual(readdirSync(f.cacheRoot).sort(), [".install-lock", "node_modules"]);
  rmSync(installed.modules, { recursive: true });
  assert.throws(() => installSharedDependencies(f.project("c"), f), /正在安装/);
  assert.deepEqual(readdirSync(f.cacheRoot), [path.basename(lock)]);
});

test("已有依赖备份不会被覆盖", (t) => {
  const f = fixture(t);
  const a = f.project("a"), b = f.project("b");
  installSharedDependencies(a, f);
  mkdirSync(path.join(b, "node_modules"));
  mkdirSync(path.join(b, ".sites-runtime", "node_modules.previous"), { recursive: true });
  writeFileSync(path.join(b, ".sites-runtime", "node_modules.previous", "original"), "keep");
  assert.throws(() => installSharedDependencies(b, f), /备份已存在/);
  assert.equal(readFileSync(path.join(b, ".sites-runtime", "node_modules.previous", "original"), "utf8"), "keep");
});

test("本地依赖和其他包管理器保留原安装方式", (t) => {
  const f = fixture(t);
  const a = f.project("a");
  writeFileSync(path.join(a, "package-lock.json"), JSON.stringify({ packages: { "node_modules/local": { resolved: "file:../local" } } }));
  assert.throws(() => installSharedDependencies(a, f), /共享依赖仅支持 npm/);
  const b = f.project("b");
  writeFileSync(path.join(b, "pnpm-lock.yaml"), "lockfileVersion: 9");
  assert.throws(() => installSharedDependencies(b, f), /共享依赖仅支持 npm/);
});

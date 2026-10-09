import { spawnSync } from "node:child_process";
import {
  accessSync, constants, copyFileSync, existsSync, lstatSync, mkdirSync,
  mkdtempSync, readFileSync, readlinkSync, renameSync, rmSync, symlinkSync,
} from "node:fs";
import { homedir } from "node:os";
import path from "node:path";

function dependencyFiles(projectRoot) {
  const files = ["package.json", "package-lock.json"];
  if (existsSync(path.join(projectRoot, ".npmrc"))) files.push(".npmrc");
  const manifest = JSON.parse(readFileSync(path.join(projectRoot, "package.json")));
  const lock = JSON.parse(readFileSync(path.join(projectRoot, "package-lock.json")));
  const hasOtherLockfile = ["pnpm-lock.yaml", "yarn.lock", "bun.lock", "bun.lockb"]
    .some((name) => existsSync(path.join(projectRoot, name)));
  const hasLocalDependencies = Object.values(lock.packages ?? {})
    .some((pkg) => pkg.link || /^(file:|link:|workspace:)/.test(pkg.resolved ?? ""));
  if (manifest.workspaces || hasOtherLockfile || hasLocalDependencies ||
      (manifest.packageManager && !manifest.packageManager.startsWith("npm@"))) {
    throw new Error("共享依赖仅支持 npm 锁定的非 workspace 项目；保留当前包管理器和本地依赖的安装方式。");
  }
  return files;
}

function verifyModules(directory) {
  accessSync(path.join(directory, ".bin", process.platform === "win32" ? "vinext.cmd" : "vinext"),
    process.platform === "win32" ? constants.F_OK : constants.X_OK);
}

function linkModules(projectRoot, target) {
  const local = path.join(projectRoot, "node_modules");
  const current = lstatSync(local, { throwIfNoEntry: false });
  if (current?.isSymbolicLink() && path.resolve(projectRoot, readlinkSync(local)) === target) return null;
  const backup = path.join(projectRoot, ".sites-runtime", "node_modules.previous");
  if (current && lstatSync(backup, { throwIfNoEntry: false })) throw new Error(`旧依赖备份已存在，请先核对并处理：${backup}`);
  if (current) {
    mkdirSync(path.dirname(backup), { recursive: true });
    renameSync(local, backup);
  }
  try {
    symlinkSync(target, local, process.platform === "win32" ? "junction" : "dir");
  } catch (error) {
    if (current) renameSync(backup, local);
    throw error;
  }
  return current ? backup : null;
}

export function installSharedDependencies(projectRoot, {
  cacheRoot = path.join(homedir(), ".config", "moego", "moe-acceptance", ".shared-deps"),
  npmPath = process.env.npm_execpath,
  refresh = false,
} = {}) {
  if (!npmPath) throw new Error("请通过 npm run install:ci 安装共享依赖。");
  const files = dependencyFiles(projectRoot);
  const modules = path.join(cacheRoot, "node_modules");
  if (refresh || !existsSync(modules)) {
    mkdirSync(cacheRoot, { recursive: true, mode: 0o700 });
    const lock = path.join(cacheRoot, ".install-lock");
    try {
      mkdirSync(lock);
    } catch (error) {
      if (error.code === "EEXIST") throw new Error(`共享依赖正在安装；若前次进程已退出，确认后移除锁目录再重试：${lock}`);
      throw error;
    }
    let stage;
    try {
      // 从检查目录到获取锁之间，其他进程可能已经完成首次安装。
      if (refresh || !existsSync(modules)) {
        stage = mkdtempSync(path.join(cacheRoot, ".install-"));
        for (const name of files) copyFileSync(path.join(projectRoot, name), path.join(stage, name));
        // 先完成安装和校验，再替换唯一的共享依赖；失败时仍保留原依赖。
        const installed = spawnSync(process.execPath, [
          npmPath, "ci", "--prefix", stage, "--workspaces=false",
          "--include=dev", "--include=optional", "--prefer-offline", "--no-audit", "--no-fund",
        ], { cwd: stage, stdio: "inherit" });
        if (installed.error) throw installed.error;
        if (installed.status !== 0) throw new Error(`共享依赖安装失败（退出码 ${installed.status ?? installed.signal}），原项目依赖保留。`);
        verifyModules(path.join(stage, "node_modules"));
        const previous = path.join(stage, "previous");
        if (existsSync(modules)) renameSync(modules, previous);
        try {
          renameSync(path.join(stage, "node_modules"), modules);
        } catch (error) {
          if (existsSync(previous)) renameSync(previous, modules);
          throw error;
        }
        rmSync(previous, { recursive: true, force: true });
      }
    } finally {
      // 如果回滚本身失败，保留暂存目录里的原依赖供恢复。
      if (stage && !existsSync(path.join(stage, "previous"))) rmSync(stage, { recursive: true, force: true });
      rmSync(lock, { recursive: true });
    }
  } else {
    verifyModules(modules);
  }
  const backup = linkModules(projectRoot, modules);
  return { modules, backup };
}

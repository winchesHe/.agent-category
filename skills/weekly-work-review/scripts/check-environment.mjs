#!/usr/bin/env node
// 只读环境预检。采集前跑一次，避免每个来源各自重复探测。
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { loadConfig, isInside } from './lib/config.mjs';
import { resolveWeek, weekDirRelativePath } from './lib/week.mjs';

if (process.argv.includes('--help') || process.argv.includes('-h')) {
  console.log(`Usage: node check-environment.mjs [--week <YYYY-MM-DD>]

Read-only preflight for weekly-work-review. Reports vault / scratch / archive
paths, tool availability and degradation advice as JSON on stdout.
Exits 1 only on blocking configuration errors.`);
  process.exit(0);
}

function readOption(flag) {
  const index = process.argv.indexOf(flag);
  return index === -1 ? '' : process.argv[index + 1] || '';
}

const config = loadConfig();
const week = resolveWeek(readOption('--week') || new Date().toISOString().slice(0, 10));
const blocking = [];
const warnings = [];

function dirState(target) {
  if (!target) return { configured: false, exists: false, path: null };
  return { configured: true, exists: fs.existsSync(target), path: target };
}

const vault = dirState(config.vaultRoot);
if (!vault.configured) blocking.push('[ENV-001] WEEKLY_REVIEW_VAULT_ROOT 未配置');
else if (!vault.exists) blocking.push(`[ENV-002] vault 不存在: ${config.vaultRoot}`);
else if (!fs.existsSync(path.join(config.vaultRoot, '.obsidian'))) {
  warnings.push('[ENV-003] vault 根目录没有 .obsidian，确认路径是否为 Obsidian vault');
}

const scratch = dirState(config.scratchRoot);
if (!scratch.configured) blocking.push('[ENV-004] WEEKLY_REVIEW_SCRATCH_ROOT 未配置');
else if (config.vaultRoot && isInside(config.vaultRoot, config.scratchRoot)) {
  blocking.push('[ENV-005] scratch 位于 vault 内，原始证据必须留在 vault 外');
} else if (!scratch.exists) {
  warnings.push(`[ENV-006] scratch 目录尚不存在，首次采集时创建: ${config.scratchRoot}`);
}

const archiveDir = config.vaultRoot ? path.join(config.vaultRoot, config.archiveRelativeDir) : '';
const meetingsDir = config.vaultRoot ? path.join(config.vaultRoot, config.meetingsRelativeDir) : '';
const weekDirRelative = weekDirRelativePath(week.week_start, config.archiveRelativeDir);
const weekDir = config.vaultRoot ? path.join(config.vaultRoot, weekDirRelative) : '';

if (archiveDir && !fs.existsSync(archiveDir)) {
  warnings.push(`[ENV-007] 周报目录不存在: ${config.archiveRelativeDir}`);
}
if (meetingsDir && !fs.existsSync(meetingsDir)) {
  warnings.push(`[ENV-008] 会议目录不存在: ${config.meetingsRelativeDir}`);
}

// 旧式平铺周报会与新日期范围目录冲突，必须先迁移
const legacyWeeklies = [];
if (archiveDir && fs.existsSync(archiveDir)) {
  for (const entry of fs.readdirSync(archiveDir, { withFileTypes: true })) {
    if (entry.isFile() && /^\d{4}-W\d{2}/.test(entry.name)) legacyWeeklies.push(entry.name);
  }
}
if (legacyWeeklies.length > 0) {
  warnings.push(
    `[ENV-009] 发现 ${legacyWeeklies.length} 个旧式平铺周报，先运行 migrate-legacy-weeklies.mjs 预览`,
  );
}

function checkBinary(name) {
  const result = spawnSync('command', ['-v', name], { shell: true, encoding: 'utf8' });
  return { available: result.status === 0, path: (result.stdout || '').trim() || null };
}

const larkCli = checkBinary('lark-cli');
if (!larkCli.available) warnings.push('[ENV-010] lark-cli 不可用，飞书来源需标记 tool_unavailable');

const larkAuth = larkCli.available
  ? spawnSync('lark-cli', ['auth', 'status'], { encoding: 'utf8', timeout: 20000 })
  : null;
const larkAuthOk = Boolean(larkAuth && larkAuth.status === 0);
if (larkCli.available && !larkAuthOk) {
  warnings.push('[ENV-011] lark-cli 未登录或鉴权失败，会议来源可能只能部分采集');
}

const slackEntry = config.slackSkillDir ? path.join(config.slackSkillDir, 'scripts', 'slack.py') : '';
const slackAvailable = Boolean(slackEntry && fs.existsSync(slackEntry));
if (!slackAvailable) warnings.push('[ENV-012] Slack skill 入口缺失，Slack 来源需标记 tool_unavailable');
const slackEnvConfigured = Boolean(
  config.slackSkillDir && fs.existsSync(path.join(config.slackSkillDir, '.env')),
);
if (slackAvailable && !slackEnvConfigured) {
  warnings.push('[ENV-013] Slack skill 未配置 .env，搜索类命令可能失败');
}

// 预检必须保持只读：采集器默认会先 scan --all 写 ~/.memory-manager，
// 这里显式 --no-scan，避免"环境预检"这个只读动作产生数据库写入。
// 因此 ENV-015 报的是当前索引状态，正式采集时会先刷新。
const sessionProbe = spawnSync(
  process.execPath,
  [
    path.join(config.skillDir, 'scripts', 'collect-sessions.mjs'),
    '--week',
    week.week_start,
    '--no-scan',
    '--stdout',
  ],
  { encoding: 'utf8', maxBuffer: 256 * 1024 * 1024, timeout: 120000 },
);
let sessions = { status: 'tool_unavailable' };
if (sessionProbe.status === 0) {
  try {
    const parsed = JSON.parse(sessionProbe.stdout);
    sessions = {
      status: parsed.status,
      raw_count: parsed.raw_count ?? 0,
      agents: parsed.agents ?? {},
      indexed_total: parsed.indexed_total ?? 0,
      latest_indexed_at: parsed.latest_indexed_at ?? null,
      skipped_reason: parsed.skipped_reason ?? null,
    };
  } catch {
    sessions = { status: 'tool_unavailable', skipped_reason: 'unparsable collector output' };
  }
}
if (sessions.status === 'tool_unavailable') {
  warnings.push(`[ENV-014] session 采集不可用：${sessions.skipped_reason || 'unknown'}`);
} else if (sessions.latest_indexed_at && sessions.latest_indexed_at < week.week_end) {
  warnings.push(
    `[ENV-015] session 索引最新到 ${sessions.latest_indexed_at}，早于 ${week.week_end}：预检以 --no-scan 只读运行，正式采集会先扫描刷新`,
  );
}

const gh = checkBinary('gh');
if (!gh.available) warnings.push('[ENV-016] gh 不可用，GitHub 来源需标记 tool_unavailable');

const report = {
  ok: blocking.length === 0,
  checked_at: new Date().toISOString(),
  week: {
    week_start: week.week_start,
    week_end: week.week_end,
    iso_week: week.iso_week,
    week_label: week.week_label,
  },
  paths: {
    vault: { ...vault, has_obsidian_marker: vault.exists && fs.existsSync(path.join(config.vaultRoot, '.obsidian')) },
    scratch: { ...scratch, outside_vault: !config.vaultRoot || !isInside(config.vaultRoot, config.scratchRoot) },
    archive_relative_dir: config.archiveRelativeDir,
    meetings_relative_dir: config.meetingsRelativeDir,
    week_dir_relative: weekDirRelative,
    week_dir_exists: Boolean(weekDir && fs.existsSync(weekDir)),
  },
  timezone: config.timezone || 'machine-local',
  tools: {
    lark_cli: { ...larkCli, authenticated: larkAuthOk },
    slack_skill: { available: slackAvailable, entry: slackEntry || null, env_configured: slackEnvConfigured },
    sessions,
    github_cli: gh,
  },
  legacy_weeklies: legacyWeeklies,
  blocking,
  warnings,
};

console.log(JSON.stringify(report, null, 2));
process.exit(blocking.length === 0 ? 0 : 1);

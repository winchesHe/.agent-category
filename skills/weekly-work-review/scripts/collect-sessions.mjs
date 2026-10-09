#!/usr/bin/env node
// 从 memory-manager CLI 采集本周多 agent session 证据。
//
// 默认先扫描再采集：先跑 memory-manager scan --all 刷新索引，再查询。
// 只查旧索引会漏掉"本周有更新但更早创建"的 session（W32 实测漏过一整块方案设计）。
// scan 会写 ~/.memory-manager 数据库；显式 --no-scan 可跳过，此时索引可能滞后。
// 任何情况都不写 Vault。原始 JSONL 不进 Vault，只保留 source_path 引用。
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { resolveWeek } from './lib/week.mjs';
import { loadConfig, scratchWeekDir } from './lib/config.mjs';

const args = process.argv.slice(2);

if (args.includes('--help') || args.includes('-h')) {
  console.log(`Usage: node collect-sessions.mjs [--week <YYYY-MM-DD>] [--no-scan] [--out <file>] [--stdout]

Collects multi-agent AI session evidence for one review week via the
memory-manager CLI (claude / codex / opencode / pi / copilot / cursor).

Refreshes the index first by default: a stale index silently drops sessions
that were created earlier but updated inside the review week.

  --week <date>   any date inside the target week (default: today)
  --no-scan       skip the index refresh and query the existing index only.
                  Faster and leaves the memory-manager database untouched,
                  but coverage may lag; the caller must record that.
  --out <file>    write the evidence index here
                  (default: <scratch>/<YYYY>/<MM>/<week>/session-evidence/session-index.json)
  --stdout        print the index to stdout instead of writing a file

Never writes into the vault. Exits 0 with status=tool_unavailable when the CLI
or its workspace is missing, so the caller can record that in the manifest.`);
  process.exit(0);
}

function readOption(flag) {
  const index = args.indexOf(flag);
  return index === -1 ? '' : args[index + 1] || '';
}

const config = loadConfig();
const week = resolveWeek(readOption('--week') || new Date().toISOString().slice(0, 10));
// 默认先扫描。--no-scan 才跳过；保留 --scan 作为兼容别名（no-op，默认已开）。
const skipScan = args.includes('--no-scan');
const wantScan = !skipScan;
const toStdout = args.includes('--stdout');

function resolveCli() {
  if (config.memoryManagerCli && fs.existsSync(config.memoryManagerCli)) {
    return { kind: 'node', command: process.execPath, base: [config.memoryManagerCli] };
  }
  const onPath = spawnSync('command', ['-v', 'memory-manager'], { shell: true, encoding: 'utf8' });
  if (onPath.status === 0 && onPath.stdout.trim()) {
    return { kind: 'bin', command: onPath.stdout.trim(), base: [] };
  }
  const candidates = [
    path.join(process.env.HOME || '', 'Desktop/Company/AI-Agent/rules-manager/packages/core/dist/cli.js'),
  ];
  for (const candidate of candidates) {
    if (candidate && fs.existsSync(candidate)) {
      return { kind: 'node', command: process.execPath, base: [candidate] };
    }
  }
  return null;
}

function unavailable(reason, detail = '') {
  const payload = {
    status: 'tool_unavailable',
    source_key: 'sessions',
    week_start: week.week_start,
    week_end: week.week_end,
    iso_week: week.iso_week,
    skipped_reason: reason,
    detail,
    raw_count: 0,
    candidate_count: 0,
  };
  console.log(JSON.stringify(payload, null, 2));
  process.exit(0);
}

const cli = resolveCli();
if (!cli) {
  unavailable(
    'memory-manager CLI not found',
    'set WEEKLY_REVIEW_MEMORY_MANAGER_CLI to the cli.js path, or install memory-manager on PATH',
  );
}

function runCli(cliArgs, { allowFailure = false } = {}) {
  const result = spawnSync(cli.command, [...cli.base, ...cliArgs], {
    encoding: 'utf8',
    maxBuffer: 256 * 1024 * 1024,
  });
  if (result.status !== 0 && !allowFailure) {
    const output = `${result.stdout || ''}${result.stderr || ''}`.trim();
    unavailable('memory-manager command failed', `${cliArgs.join(' ')}: ${output.slice(0, 400)}`);
  }
  return result;
}

const status = runCli(['status'], { allowFailure: true });
if (status.status !== 0 || !/Database:\s*ready/i.test(status.stdout || '')) {
  unavailable('memory-manager workspace not initialized', 'run: memory-manager init');
}

// scan 失败不终止采集：仍产出旧索引证据，但把 ok=false 交给调用方写进 manifest，
// 由调用方按"索引滞后"口径约束正文，不得静默当成完整覆盖。
const scan = { requested: wantScan, skipped: skipScan, ran: false, ok: null };
if (wantScan) {
  const result = runCli(['scan', '--all'], { allowFailure: true });
  scan.ran = true;
  scan.ok = result.status === 0;
  if (!scan.ok) {
    scan.error = `${result.stdout || ''}${result.stderr || ''}`.trim().slice(0, 400);
  }
}

const listed = runCli(['projects', 'sessions']);
let parsed;
try {
  parsed = JSON.parse(listed.stdout);
} catch {
  unavailable('unparsable memory-manager output', 'projects sessions did not return JSON');
}

// 周边界与按日归属都用配置时区，不用 UTC。
// UTC 边界会把周一 00:00–08:00（Asia/Shanghai）的会话判到上一周，实测 W32 因此丢 5 条。
const timezone = config.timezone || 'UTC';

function tzOffsetMs(instantMs) {
  // 用 Intl 反解目标时区在该瞬间的 UTC 偏移，自动兼容 DST
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: timezone,
    hour12: false,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).formatToParts(new Date(instantMs));
  const get = (type) => Number(parts.find((p) => p.type === type)?.value);
  const asUtc = Date.UTC(
    get('year'),
    get('month') - 1,
    get('day'),
    get('hour') % 24,
    get('minute'),
    get('second'),
  );
  return asUtc - instantMs;
}

// 把"目标时区的墙上时间"换算为 UTC 瞬间；偏移需迭代一次以处理边界
function zonedWallTimeToMs(wallIso) {
  const naive = Date.parse(`${wallIso}Z`);
  let guess = naive - tzOffsetMs(naive);
  guess = naive - tzOffsetMs(guess);
  return guess;
}

function zonedDate(iso) {
  const ms = Date.parse(iso || '');
  if (!Number.isFinite(ms)) return '';
  return new Date(ms + tzOffsetMs(ms)).toISOString().slice(0, 10);
}

const weekStartMs = zonedWallTimeToMs(`${week.week_start}T00:00:00.000`);
const weekEndMs = zonedWallTimeToMs(`${week.week_end}T23:59:59.999`);
const allSessions = Array.isArray(parsed?.sessions) ? parsed.sessions : [];

const inWeek = allSessions.filter((session) => {
  const updated = Date.parse(session.updatedAt || '');
  return Number.isFinite(updated) && updated >= weekStartMs && updated <= weekEndMs;
});

// memory-manager 的规则提取会 spawn claude/codex session，再被自己的索引收回来（自我回灌）。
// 这些不是人的工作，计入工时会严重虚高：W31 实测 326 条里有 200 条属此类。
// 判据用会话正文里工具自身的 prompt，不用标题——标题缺失时会退化成 "<project> · <agent>"。
const TOOL_SPAWN_PATTERNS = [
  /根据 evidence 提取可复用的 agent 规则候选/,
  /置信度判断框架[:：]?\s*high=/,
  /evidence_refs 必须引用 locator/,
];

// JSONL 源（claude / codex）直接读文件。
// 非 JSONL 源（opencode 存 SQLite、copilot 存 workspace.yaml）走 `memory-manager sessions show`，
// 它内部有对应 reader。copilot 多数会话源端只存 metadata、没有对话正文，show 会以非 0 退出并说明原因，
// 这类才真正无法判定。
function isToolSpawned(session) {
  const sourcePath = session.sourcePath || '';
  if (sourcePath.endsWith('.jsonl')) {
    try {
      if (!fs.existsSync(sourcePath)) return null;
      return TOOL_SPAWN_PATTERNS.some((re) => re.test(fs.readFileSync(sourcePath, 'utf8')));
    } catch {
      return null;
    }
  }
  if (!session.id) return null;
  const shown = runCli(['sessions', 'show', session.id], { allowFailure: true });
  if (shown.status !== 0) return null;
  const body = String(shown.stdout || '');
  if (!body) return null;
  return TOOL_SPAWN_PATTERNS.some((re) => re.test(body));
}

function truncate(text, limit = 180) {
  const value = String(text || '').replace(/\s+/g, ' ').trim();
  return value.length > limit ? `${value.slice(0, limit)}…` : value;
}

// 分出人工 / 工具自产 / 无法判定。工时口径只用人工。
const toolSpawned = [];
const undetermined = [];
const humanSessions = [];
for (const session of inWeek) {
  const verdict = isToolSpawned(session);
  if (verdict === true) toolSpawned.push(session);
  else {
    if (verdict === null) undetermined.push(session);
    humanSessions.push(session);
  }
}

const byAgent = {};
const byProject = {};
const byDay = {};
const toolByDay = {};

for (const session of humanSessions) {
  const agent = session.agent || 'unknown';
  const project = session.slug || 'default';
  const day = zonedDate(session.updatedAt);
  byAgent[agent] = (byAgent[agent] || 0) + 1;
  byProject[project] = (byProject[project] || 0) + 1;
  byDay[day] = (byDay[day] || 0) + 1;
}
for (const session of toolSpawned) {
  const day = zonedDate(session.updatedAt);
  toolByDay[day] = (toolByDay[day] || 0) + 1;
}

const items = humanSessions
  .map((session) => ({
    id: session.id,
    agent: session.agent,
    project: session.slug,
    updated_at: session.updatedAt,
    date: zonedDate(session.updatedAt),
    title: truncate(session.displayName),
    // 原始 JSONL 路径只作引用，正文不进 vault
    source_path: session.sourcePath,
    content_hash: session.contentHash,
  }))
  .sort((a, b) => String(a.updated_at).localeCompare(String(b.updated_at)));

const index = {
  status: items.length > 0 ? 'scanned' : 'zero_result',
  source_key: 'sessions',
  tool: 'memory-manager',
  generated_at: new Date().toISOString(),
  week_start: week.week_start,
  week_end: week.week_end,
  iso_week: week.iso_week,
  week_label: week.week_label,
  scan,
  indexed_total: allSessions.length,
  // raw_count / sessions 均已剔除工具自产，可直接用作工时口径
  raw_count: items.length,
  candidate_count: items.length,
  index_hits_in_week: inWeek.length,
  tool_spawned_count: toolSpawned.length,
  tool_spawned_by_day: toolByDay,
  undetermined_count: undetermined.length,
  agents: byAgent,
  projects: byProject,
  days: byDay,
  latest_indexed_at: allSessions.reduce(
    (latest, session) => (String(session.updatedAt || '') > latest ? session.updatedAt : latest),
    '',
  ),
  timezone,
  coverage_note:
    `updatedAt filtered to the review week in ${timezone} (not UTC); a session created earlier but updated inside the week is included; the index is refreshed before querying unless --no-scan was passed — check scan.ok/scan.skipped before treating coverage as complete`,
  exclusion_note:
    `${toolSpawned.length} of ${inWeek.length} in-week index hits were memory-manager rule-extraction spawns (self-ingestion) and are excluded from sessions/raw_count; ${undetermined.length} could not be inspected (JSONL source missing, or "sessions show" failed — chiefly copilot sessions whose source persists metadata only) and are counted as human`,
  sessions: items,
};

if (toStdout) {
  console.log(JSON.stringify(index, null, 2));
  process.exit(0);
}

const defaultOut = config.scratchRoot
  ? path.join(scratchWeekDir(config, week), 'session-evidence', 'session-index.json')
  : '';
const outPath = readOption('--out') || defaultOut;

if (!outPath) {
  console.log(JSON.stringify(index, null, 2));
  process.exit(0);
}

if (config.vaultRoot && path.resolve(outPath).startsWith(path.resolve(config.vaultRoot) + path.sep)) {
  console.error('FAIL [SESSION-002] refusing to write session evidence inside the vault');
  process.exit(1);
}

fs.mkdirSync(path.dirname(outPath), { recursive: true });
fs.writeFileSync(outPath, `${JSON.stringify(index, null, 2)}\n`);

console.log(
  JSON.stringify(
    {
      status: index.status,
      out: outPath,
      week_label: index.week_label,
      raw_count: index.raw_count,
      agents: index.agents,
      latest_indexed_at: index.latest_indexed_at,
      scan,
    },
    null,
    2,
  ),
);

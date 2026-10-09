#!/usr/bin/env node
// 用 slack skill 的 CLI 采集本周 Slack 证据：出站 / 被别人 @ / 入站 DM。
//
// 两个实测坑，改动前先读：
//   1. `to:@me` 是 DM 作用域，不是"被提及"。实测 `to:@winches` 与 `to:@winches is:dm`
//      返回值完全相等（407），拿它当被提及数会虚高约 10 倍。被提及要用 `<@UID>`。
//   2. `is_bot` 不可靠。`canary release`、`moego_github_actions`、`gengar` 都是 false，
//      因此自动化要靠作者名匹配，不能只信这个字段。
//
// 只读：不写 vault，不发任何消息（只调用 search 子命令）。
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { resolveWeek } from './lib/week.mjs';
import { loadConfig, scratchWeekDir } from './lib/config.mjs';

const args = process.argv.slice(2);

if (args.includes('--help') || args.includes('-h')) {
  console.log(`Usage: node collect-slack.mjs [--week <YYYY-MM-DD>] [--handle <name>] [--out <file>] [--stdout]

Collects one review week of Slack evidence via the slack skill CLI:
  - outbound      from:@<handle>
  - mentions      <@UID> -from:@<handle>   (others @-ing me)
  - inbound DM    to:@<handle> -from:@<handle>

  --week <date>     any date inside the target week (default: today)
  --handle <name>   Slack handle without @ (default: from SLACK_SELF_HANDLE or "me")
  --user-id <UID>   skip handle resolution and use this user id
  --limit <n>       max matches per query (default: 400)
  --out <file>      default: <scratch>/<YYYY>/<MM>/<week>/slack-evidence/slack-activity.json
  --stdout          print summary to stdout instead of writing a file

Raw message bodies stay in scratch; only aggregates are meant for the vault.
Never writes into the vault. Exits 0 with status=tool_unavailable when the CLI
or its .env is missing, so the caller records that in the manifest.`);
  process.exit(0);
}

function readOption(flag) {
  const index = args.indexOf(flag);
  return index === -1 ? '' : args[index + 1] || '';
}

const config = loadConfig();
const week = resolveWeek(readOption('--week') || new Date().toISOString().slice(0, 10));
const toStdout = args.includes('--stdout');
const limit = readOption('--limit') || '400';

function unavailable(reason, detail = '') {
  console.log(JSON.stringify({
    status: 'tool_unavailable',
    source_key: 'slack',
    tool: 'slack skill',
    week_start: week.week_start,
    week_end: week.week_end,
    iso_week: week.iso_week,
    week_label: week.week_label,
    skipped_reason: detail ? `${reason}: ${detail}` : reason,
    outbound: null,
    mentions: null,
    inbound_dm: null,
  }, null, 2));
  process.exit(0);
}

const slackDir = config.slackSkillDir;
const slackScript = path.join(slackDir, 'scripts', 'slack.py');
if (!fs.existsSync(slackScript)) unavailable('slack skill CLI not found', slackScript);
if (!fs.existsSync(path.join(slackDir, '.env'))) unavailable('slack skill .env missing', path.join(slackDir, '.env'));

const scriptsDir = path.join(slackDir, 'scripts');

function slack(cliArgs) {
  const result = spawnSync('python3', ['slack.py', ...cliArgs], {
    cwd: scriptsDir,
    encoding: 'utf8',
    maxBuffer: 256 * 1024 * 1024,
  });
  if (result.error) return { ok: false, error: String(result.error.message || '').slice(0, 200) };
  if (result.status !== 0) {
    return { ok: false, error: String(result.stderr || result.stdout || '').trim().slice(0, 300) };
  }
  return { ok: true, stdout: result.stdout };
}

// 解析自己的 handle 与 user id
let handle = readOption('--handle') || process.env.SLACK_SELF_HANDLE || '';
let userId = readOption('--user-id');
if (!userId) {
  const probe = slack(['resolve', handle ? `@${handle}` : '@me']);
  if (!probe.ok) unavailable('cannot resolve own Slack identity', probe.error);
  try {
    const parsed = JSON.parse(probe.stdout);
    userId = parsed?.resolved?.id || '';
    handle = handle || parsed?.resolved?.name || '';
  } catch (err) {
    unavailable('unparsable resolve output', String(err.message).slice(0, 120));
  }
}
if (!userId || !handle) unavailable('missing Slack user id or handle', `id=${userId} handle=${handle}`);

// Slack search 的 after/before 是开区间，两端各外扩一天
const dayBefore = new Date(Date.parse(`${week.week_start}T00:00:00Z`) - 86400000).toISOString().slice(0, 10);
const dayAfter = new Date(Date.parse(`${week.week_end}T00:00:00Z`) + 86400000).toISOString().slice(0, 10);
const windowExpr = `after:${dayBefore} before:${dayAfter}`;

const outDir = path.dirname(readOption('--out')
  || path.join(scratchWeekDir(config, week), 'slack-evidence', 'slack-activity.json'));

// 与其他采集器同一条红线：原始内容不进 vault
if (config.vaultRoot && path.resolve(outDir).startsWith(path.resolve(config.vaultRoot) + path.sep)) {
  console.error('FAIL [SLACK-002] refusing to write slack evidence inside the vault');
  process.exit(1);
}
fs.mkdirSync(outDir, { recursive: true });

function runSearch(label, query) {
  const rawPath = path.join(outDir, `${label}.json`);
  const res = slack(['search', query, '--limit', String(limit), '--max-pages', '10', '--output', rawPath]);
  if (!res.ok) return { ok: false, error: res.error, query };
  let parsed;
  try {
    parsed = JSON.parse(fs.readFileSync(rawPath, 'utf8'));
  } catch (err) {
    return { ok: false, error: `unparsable output: ${String(err.message).slice(0, 120)}`, query };
  }
  return {
    ok: true,
    query,
    raw_path: rawPath,
    total: parsed?.total ?? null,
    returned: parsed?.returned ?? 0,
    matches: Array.isArray(parsed?.matches) ? parsed.matches : [],
  };
}

// is_bot 在多个 app 上是 false，只能按作者名兜底判断自动化
const AUTOMATION = /(bot|github|actions|jira|canary|release|gengar|alert|monitor|deploy|ci|pipeline|webhook|zapier|workflow)/i;
const isAutomation = (m) => Boolean(m.author?.is_bot) || AUTOMATION.test(String(m.author?.display_name || m.author?.name || ''));

const SUBSTANTIVE_MIN = 15;
const stripEmoji = (t) => String(t || '').replace(/:[a-z0-9_+-]+:/gi, '').trim();

function summarize(result) {
  if (!result.ok) return { ok: false, error: result.error, query: result.query };
  const byChannel = {};
  const byDay = {};
  const byAuthor = {};
  let automation = 0;
  let substantive = 0;
  for (const m of result.matches) {
    const auto = isAutomation(m);
    if (auto) automation += 1;
    if (stripEmoji(m.text_raw).length >= SUBSTANTIVE_MIN) substantive += 1;
    const isIm = m.raw?.channel?.is_im || m.raw?.db_message?.channel?.is_im;
    const name = m.raw?.channel?.name || m.raw?.db_message?.channel?.name || m.channel_id;
    const chan = isIm ? '(DM)' : name;
    byChannel[chan] = (byChannel[chan] || 0) + 1;
    const day = new Date(Number(m.ts) * 1000).toISOString().slice(0, 10);
    byDay[day] = (byDay[day] || 0) + 1;
    const who = m.author?.display_name || m.author?.name || 'unknown';
    if (!auto) byAuthor[who] = (byAuthor[who] || 0) + 1;
  }
  const sortDesc = (obj, n) => Object.fromEntries(Object.entries(obj).sort((a, b) => b[1] - a[1]).slice(0, n));
  return {
    ok: true,
    query: result.query,
    raw_path: result.raw_path,
    total: result.total,
    sampled: result.matches.length,
    automation_count: automation,
    human_count: result.matches.length - automation,
    substantive_count: substantive,
    low_signal_count: result.matches.length - substantive,
    by_day: Object.fromEntries(Object.keys(byDay).sort().map((k) => [k, byDay[k]])),
    top_channels: sortDesc(byChannel, 10),
    top_human_authors: sortDesc(byAuthor, 10),
  };
}

const outbound = summarize(runSearch('outbound', `from:@${handle} ${windowExpr}`));
// 被提及必须用 <@UID>：to:@me 是 DM 作用域
const mentions = summarize(runSearch('mentions', `<@${userId}> -from:@${handle} ${windowExpr}`));
const inboundDm = summarize(runSearch('inbound-dm', `to:@${handle} -from:@${handle} ${windowExpr}`));

const anyOk = [outbound, mentions, inboundDm].some((r) => r.ok);
if (!anyOk) unavailable('all slack searches failed', outbound.error || mentions.error || inboundDm.error);

const evidence = {
  status: 'scanned',
  source_key: 'slack',
  tool: 'slack skill',
  generated_at: new Date().toISOString(),
  week_start: week.week_start,
  week_end: week.week_end,
  iso_week: week.iso_week,
  week_label: week.week_label,
  self_handle: handle,
  self_user_id: userId,
  search_window: windowExpr,
  window_note: 'Slack after/before are exclusive, so the window is padded one day on each side',
  semantics_note:
    'mentions use <@UID>, NOT to:@handle — to: is DM-scoped (observed to:@handle == to:@handle is:dm), which would overstate mentions ~10x',
  automation_note:
    'is_bot is unreliable (observed false for canary release / moego_github_actions / gengar), so automation is also matched on author name',
  outbound,
  mentions,
  inbound_dm: inboundDm,
  coverage_note:
    'raw match bodies stay in scratch under slack-evidence/; only aggregates belong in the vault',
};

const outPath = readOption('--out') || path.join(outDir, 'slack-activity.json');
if (toStdout) {
  console.log(JSON.stringify(evidence, null, 2));
  process.exit(0);
}

fs.writeFileSync(outPath, `${JSON.stringify(evidence, null, 2)}\n`);

console.log(JSON.stringify({
  status: evidence.status,
  out: outPath,
  week_label: week.week_label,
  outbound_total: outbound.ok ? outbound.total : `FAILED: ${outbound.error}`,
  mentions_total: mentions.ok ? mentions.total : `FAILED: ${mentions.error}`,
  mentions_human: mentions.ok ? mentions.human_count : null,
  mentions_automation: mentions.ok ? mentions.automation_count : null,
  inbound_dm_total: inboundDm.ok ? inboundDm.total : `FAILED: ${inboundDm.error}`,
}, null, 2));

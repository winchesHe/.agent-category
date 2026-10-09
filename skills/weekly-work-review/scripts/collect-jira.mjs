#!/usr/bin/env node
// 用 jira skill 的 CLI 采集本周 Jira 证据：我创建的 / 我负责且有更新的 / 工时。
//
// 关键区分：worklog 查不到有两种含义，不能混。
//   - zero_result + 说明"字段无人填写"：JQL 跑通了，确实没人记工时（本人实测全历史仅 3 条）
//   - tool_unavailable：CLI 或凭证不可用
// 之前 manifest 里写 "not collected this run" 把两者糊在一起，等于把"我没做"记成缺口然后无人处理。
//
// 只读：不写 vault，不改任何 issue。
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { resolveWeek } from './lib/week.mjs';
import { loadConfig, scratchWeekDir } from './lib/config.mjs';

const args = process.argv.slice(2);

if (args.includes('--help') || args.includes('-h')) {
  console.log(`Usage: node collect-jira.mjs [--week <YYYY-MM-DD>] [--jira-dir <path>] [--out <file>] [--stdout]

Collects one review week of Jira evidence via the jira skill CLI:
  - issues I created (reporter = currentUser)
  - issues assigned to me with updates in the window
  - worklog entries (distinguishes "nobody logs time" from "not collected")

  --week <date>      any date inside the target week (default: today)
  --jira-dir <path>  jira skill dir (default: <skills-root>/jira)
  --limit <n>        max issues per query (default: 100)
  --out <file>       default: <scratch>/<YYYY>/<MM>/<week>/jira-evidence/jira-activity.json
  --stdout           print to stdout instead of writing a file

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
const limit = readOption('--limit') || '100';

function unavailable(reason, detail = '') {
  console.log(JSON.stringify({
    status: 'tool_unavailable',
    source_key: 'jira',
    tool: 'jira skill',
    week_start: week.week_start,
    week_end: week.week_end,
    iso_week: week.iso_week,
    week_label: week.week_label,
    skipped_reason: detail ? `${reason}: ${detail}` : reason,
    created: [],
    updated: [],
    worklog: [],
  }, null, 2));
  process.exit(0);
}

// jira skill 目录：默认取本 skill 的同级 jira/
const skillDir = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const jiraDir = readOption('--jira-dir') || path.join(path.dirname(skillDir), 'jira');
const jiraScript = path.join(jiraDir, 'scripts', 'jira.py');
if (!fs.existsSync(jiraScript)) unavailable('jira skill CLI not found', jiraScript);
if (!fs.existsSync(path.join(jiraDir, '.env'))) unavailable('jira skill .env missing', path.join(jiraDir, '.env'));

function jql(query, { fields = '' } = {}) {
  const cliArgs = ['jira.py', 'search', query, '--limit', String(limit), '--format', 'summary'];
  if (fields) cliArgs.push('--fields', fields);
  const result = spawnSync('python3', cliArgs, {
    cwd: path.join(jiraDir, 'scripts'),
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
  });
  if (result.error) return { ok: false, error: String(result.error.message || '').slice(0, 200) };
  if (result.status !== 0) {
    return { ok: false, error: `${String(result.stderr || result.stdout || '').trim().slice(0, 300)}` };
  }
  try {
    const parsed = JSON.parse(result.stdout);
    if (parsed && parsed.ok === false) return { ok: false, error: String(parsed.error || 'jira returned ok=false').slice(0, 300) };
    return { ok: true, issues: Array.isArray(parsed?.issues) ? parsed.issues : [], count: parsed?.count ?? 0 };
  } catch (err) {
    return { ok: false, error: `unparsable jira output: ${String(err.message).slice(0, 120)}` };
  }
}

const from = week.week_start;
const to = week.week_end;
// Jira 的日期比较是左闭右开语义更安全，右界 +1 天
const toExclusive = new Date(Date.parse(`${to}T00:00:00Z`) + 86400000).toISOString().slice(0, 10);

const FIELDS = 'summary,status,created,updated,assignee,reporter,priority,parent,issuetype';

const createdQ = jql(
  `reporter = currentUser() AND created >= "${from}" AND created < "${toExclusive}" ORDER BY created ASC`,
  { fields: FIELDS },
);
if (!createdQ.ok) unavailable('jira search failed', createdQ.error);

const updatedQ = jql(
  `assignee = currentUser() AND updated >= "${from}" AND updated < "${toExclusive}" ORDER BY updated DESC`,
  { fields: FIELDS },
);
const worklogQ = jql(
  `worklogAuthor = currentUser() AND worklogDate >= "${from}" AND worklogDate < "${toExclusive}"`,
  { fields: FIELDS },
);
// 判断"从来没人记工时" vs "本周恰好没记"
const worklogEverQ = jql('worklogAuthor = currentUser()', { fields: 'summary,updated' });

const slim = (issue) => ({
  key: issue.key,
  summary: String(issue.summary || '').slice(0, 200),
  status: issue.status,
  priority: issue.priority,
  issuetype: issue.issuetype,
  created: String(issue.created || '').slice(0, 10),
  updated: String(issue.updated || '').slice(0, 10),
  parent: issue.parent || null,
});

const created = (createdQ.issues || []).map(slim);
const updated = (updatedQ.ok ? updatedQ.issues : []).map(slim);
const worklog = (worklogQ.ok ? worklogQ.issues : []).map(slim);

// 子任务拆解识别：标题形如 [PARENT][Layer] ...
const SUBTASK = /^\[([A-Z]+-\d+)\]\[([^\]]+)\]/;
const breakdown = {};
for (const issue of created) {
  const m = String(issue.summary).match(SUBTASK);
  if (!m) continue;
  breakdown[m[1]] = breakdown[m[1]] || { parent: m[1], layers: [], keys: [] };
  breakdown[m[1]].layers.push(m[2]);
  breakdown[m[1]].keys.push(issue.key);
}

const byProject = (list) => {
  const out = {};
  for (const i of list) {
    const p = String(i.key).split('-')[0];
    out[p] = (out[p] || 0) + 1;
  }
  return out;
};
const byStatus = (list) => {
  const out = {};
  for (const i of list) out[i.status] = (out[i.status] || 0) + 1;
  return out;
};

const worklogEverCount = worklogEverQ.ok ? (worklogEverQ.issues || []).length : null;
const worklogStatus = !worklogQ.ok
  ? 'tool_unavailable'
  : worklog.length > 0 ? 'scanned' : 'zero_result';
const worklogReason = !worklogQ.ok
  ? `worklog query failed: ${worklogQ.error}`
  : worklog.length > 0 ? ''
    : worklogEverCount === 0
      ? 'JQL ran successfully; no worklog has ever been logged by this user — the field is unused, not uncollected'
      : `JQL ran successfully; no worklog inside the review week (${worklogEverCount} issue(s) with worklog across all time) — the field is effectively unused, not uncollected`;

const evidence = {
  status: 'scanned',
  source_key: 'jira',
  tool: 'jira skill',
  generated_at: new Date().toISOString(),
  week_start: week.week_start,
  week_end: week.week_end,
  iso_week: week.iso_week,
  week_label: week.week_label,
  queries_run: [
    `reporter = currentUser() AND created >= "${from}" AND created < "${toExclusive}"`,
    `assignee = currentUser() AND updated >= "${from}" AND updated < "${toExclusive}"`,
    `worklogAuthor = currentUser() AND worklogDate >= "${from}" AND worklogDate < "${toExclusive}"`,
    'worklogAuthor = currentUser()  (all-time, to tell "unused field" from "not collected")',
  ],
  created_count: created.length,
  updated_count: updated.length,
  created_by_project: byProject(created),
  updated_by_status: byStatus(updated),
  subtask_breakdown: Object.values(breakdown),
  worklog_status: worklogStatus,
  worklog_count: worklog.length,
  worklog_all_time_issue_count: worklogEverCount,
  worklog_reason: worklogReason,
  updated_query_ok: Boolean(updatedQ.ok),
  updated_query_error: updatedQ.ok ? '' : String(updatedQ.error || '').slice(0, 200),
  coverage_note:
    'issue-level evidence is available even when worklog is empty; an empty worklog means the field is unused, which is different from not querying it',
  created,
  updated,
  worklog,
};

if (toStdout) {
  console.log(JSON.stringify(evidence, null, 2));
  process.exit(0);
}

const outPath = readOption('--out')
  || path.join(scratchWeekDir(config, week), 'jira-evidence', 'jira-activity.json');

// 与其他采集器同一条红线
if (config.vaultRoot && path.resolve(outPath).startsWith(path.resolve(config.vaultRoot) + path.sep)) {
  console.error('FAIL [JIRA-002] refusing to write jira evidence inside the vault');
  process.exit(1);
}

fs.mkdirSync(path.dirname(outPath), { recursive: true });
fs.writeFileSync(outPath, `${JSON.stringify(evidence, null, 2)}\n`);

console.log(JSON.stringify({
  status: evidence.status,
  out: outPath,
  week_label: week.week_label,
  created_count: evidence.created_count,
  updated_count: evidence.updated_count,
  created_by_project: evidence.created_by_project,
  subtask_breakdown: evidence.subtask_breakdown.map((b) => `${b.parent}: ${b.keys.length} (${b.layers.join('/')})`),
  worklog_status: evidence.worklog_status,
  worklog_reason: evidence.worklog_reason,
}, null, 2));

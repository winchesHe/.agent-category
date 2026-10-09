#!/usr/bin/env node
// 用 gh CLI 采集本周 GitHub 活动证据：commits / PR created / PR merged / PR reviewed。
//
// 为什么不用本地 git：本地 clone 会过期、可能没 clone、也拿不到 PR 与 review。
// 实测 W32 本地只扫到 2 个仓库的提交，GitHub 上实际跨 6 个仓库，另有 9 个 PR 与 11 个 review 完全不可见。
// 仓库列表来自 API 搜索结果，不靠枚举本地目录。
//
// 只读：不写 vault，不改任何仓库。
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { resolveWeek } from './lib/week.mjs';
import { loadConfig, scratchWeekDir } from './lib/config.mjs';

const args = process.argv.slice(2);

if (args.includes('--help') || args.includes('-h')) {
  console.log(`Usage: node collect-github.mjs [--week <YYYY-MM-DD>] [--author <login>] [--out <file>] [--stdout]

Collects one review week of GitHub activity via the gh CLI:
  - commits authored (excludes automated backup repos)
  - PRs created / merged in the window
  - PRs reviewed (other people's work counts too)

  --week <date>     any date inside the target week (default: today)
  --author <login>  GitHub login (default: resolved from "gh api user")
  --exclude-repo <full_name>  repeatable; skip a repo (default: <author>/obsidian-vault)
  --out <file>      default: <scratch>/<YYYY>/<MM>/<week>/github-evidence/github-activity.json
  --stdout          print to stdout instead of writing a file

Never writes into the vault. Exits 0 with status=tool_unavailable when gh is
missing or unauthenticated, so the caller records that in the manifest.`);
  process.exit(0);
}

function readOption(flag) {
  const index = args.indexOf(flag);
  return index === -1 ? '' : args[index + 1] || '';
}
function readAll(flag) {
  const out = [];
  args.forEach((a, i) => { if (a === flag && args[i + 1]) out.push(args[i + 1]); });
  return out;
}

const config = loadConfig();
const week = resolveWeek(readOption('--week') || new Date().toISOString().slice(0, 10));
const toStdout = args.includes('--stdout');

function unavailable(reason, detail = '') {
  const payload = {
    status: 'tool_unavailable',
    source_key: 'github_activity',
    tool: 'gh',
    week_start: week.week_start,
    week_end: week.week_end,
    iso_week: week.iso_week,
    week_label: week.week_label,
    skipped_reason: detail ? `${reason}: ${detail}` : reason,
    commits: [],
    prs_created: [],
    prs_merged: [],
    prs_reviewed: [],
  };
  console.log(JSON.stringify(payload, null, 2));
  process.exit(0);
}

function gh(apiArgs, { allowFailure = false } = {}) {
  const result = spawnSync('gh', apiArgs, { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });
  if (result.error) {
    if (allowFailure) return null;
    unavailable('gh CLI not available', String(result.error.message || '').slice(0, 200));
  }
  if (result.status !== 0) {
    if (allowFailure) return null;
    unavailable('gh command failed', `${apiArgs.join(' ')}: ${String(result.stderr || '').trim().slice(0, 300)}`);
  }
  return result.stdout;
}

// 鉴权与身份
const whoami = gh(['api', 'user', '--jq', '.login'], { allowFailure: true });
if (whoami === null) unavailable('gh not installed or not authenticated', 'gh api user failed');
const author = readOption('--author') || String(whoami).trim();
if (!author) unavailable('cannot resolve GitHub login', 'gh api user returned empty');

const excluded = new Set(readAll('--exclude-repo'));
// vault 自动备份仓库每天几十条机器提交，不是人的工作
if (excluded.size === 0) excluded.add(`${author}/obsidian-vault`);

const from = week.week_start;
const to = week.week_end;

function search(endpoint, query, jq) {
  const out = gh(['api', `${endpoint}?q=${encodeURIComponent(query)}&per_page=100`, '--jq', jq], { allowFailure: true });
  if (out === null) return null;
  return String(out).split('\n').filter(Boolean).map((line) => JSON.parse(line));
}

const COMMIT_JQ = '.items[] | {repo: .repository.full_name, sha: .sha, date: .commit.author.date, message: (.commit.message | split("\\n")[0])}';
// 注意 search/issues 的 state 只有 open/closed，**closed 同时包含"已合并"和"关掉没合"**。
// pull_request.merged_at 才能区分。实测 W32 有 2 个 PR 是 closed 但未合并，
// 只看 state 会把它们当成已交付（CS-49309 与 moego-agent#21 都曾被我误记为已合并）。
const PR_JQ = '.items[] | {repo: (.repository_url | split("/")[-1]), number: .number, state: .state, merged_at: (.pull_request.merged_at // null), title: .title, created_at: .created_at, closed_at: .closed_at, url: .html_url, author: .user.login}';

const searchCommits = search('search/commits', `author:${author} author-date:${from}..${to}`, COMMIT_JQ);
if (searchCommits === null) unavailable('commit search failed', 'gh search/commits returned non-zero');

const prsCreated = search('search/issues', `author:${author} type:pr created:${from}..${to}`, PR_JQ) || [];
const prsMerged = search('search/issues', `author:${author} type:pr merged:${from}..${to}`, PR_JQ) || [];
// review 覆盖他人 PR，是本地 git 完全看不到的一类工作
const prsReviewed = search('search/issues', `reviewed-by:${author} type:pr updated:${from}..${to}`, PR_JQ) || [];

// search/commits 不可靠地索引私有仓库：实测 winchesHe/rules-manager 本周 73 条提交在 search 里 0 命中。
// 因此再对候选仓库逐个走 repo commits API 补齐。候选来源：本地 clone 的 remote、search 命中、PR 命中、--repo 指定。
function localRemoteRepos(roots) {
  const found = new Set();
  for (const root of roots) {
    if (!root || !fs.existsSync(root)) continue;
    let entries = [];
    try { entries = fs.readdirSync(root, { withFileTypes: true }); } catch { continue; }
    for (const entry of entries) {
      if (!entry.isDirectory()) continue;
      const gitDir = path.join(root, entry.name, '.git');
      if (!fs.existsSync(gitDir)) continue;
      const out = spawnSync('git', ['-C', path.join(root, entry.name), 'remote', 'get-url', 'origin'], { encoding: 'utf8' });
      if (out.status !== 0) continue;
      const m = String(out.stdout).trim().match(/github\.com[:/]([^/]+\/[^/.]+)/);
      if (m) found.add(m[1]);
    }
  }
  return found;
}

const scanRoots = readAll('--scan-root');
if (scanRoots.length === 0 && process.env.HOME) {
  scanRoots.push(
    path.join(process.env.HOME, 'Desktop/Company/Moe'),
    path.join(process.env.HOME, 'Desktop/Company/AI-Agent'),
    path.join(process.env.HOME, 'Desktop/Company/person'),
  );
}

const candidateRepos = new Set([
  ...readAll('--repo'),
  ...searchCommits.map((c) => c.repo),
  ...localRemoteRepos(scanRoots),
]);
for (const p of [...prsCreated, ...prsMerged]) {
  // PR 搜索只给短名，补全 owner 需要另查；短名匹配已有候选即可，不额外请求
  const match = [...candidateRepos].find((r) => r.endsWith(`/${p.repo}`));
  if (!match) candidateRepos.add(p.repo);
}

const commitMap = new Map();
const addCommit = (c) => {
  const key = `${c.repo}\0${c.sha}`;
  if (!commitMap.has(key)) commitMap.set(key, { ...c, date: String(c.date).slice(0, 10) });
};
for (const c of searchCommits) addCommit(c);

const perRepoProbed = [];
const perRepoFailed = [];
for (const repo of [...candidateRepos].sort()) {
  if (!repo.includes('/') || excluded.has(repo)) continue;
  const meta = gh(['api', `repos/${repo}`, '--jq', '.default_branch'], { allowFailure: true });
  if (meta === null) { perRepoFailed.push(repo); continue; }
  const defaultBranch = String(meta).trim();
  // 默认分支不一定是主干（实测 rules-manager 默认分支是 implement/workspace-state，提交都在 main）
  const branches = [...new Set([defaultBranch, 'main', 'master', 'production'])].filter(Boolean);
  let probed = false;
  for (const branch of branches) {
    const out = gh([
      'api',
      `repos/${repo}/commits?sha=${encodeURIComponent(branch)}&author=${encodeURIComponent(author)}&since=${from}T00:00:00Z&until=${to}T23:59:59Z&per_page=100`,
      '--jq', '.[] | {sha: .sha, date: .commit.author.date, message: (.commit.message | split("\\n")[0]), email: .commit.author.email}',
    ], { allowFailure: true });
    if (out === null) continue;
    probed = true;
    for (const line of String(out).split('\n').filter(Boolean)) {
      const c = JSON.parse(line);
      addCommit({ repo, sha: c.sha, date: c.date, message: c.message });
    }
  }
  if (probed) perRepoProbed.push(repo);
  else perRepoFailed.push(repo);
}

const commits = [...commitMap.values()]
  .filter((c) => !excluded.has(c.repo))
  .sort((a, b) => `${a.date}${a.repo}`.localeCompare(`${b.date}${b.repo}`));

const excludedCommitCount = commitMap.size - commits.length;
const searchOnlyCount = searchCommits.filter((c) => !excluded.has(c.repo)).length;

const byRepo = {};
for (const c of commits) byRepo[c.repo] = (byRepo[c.repo] || 0) + 1;
const byDay = {};
for (const c of commits) byDay[c.date] = (byDay[c.date] || 0) + 1;

const TICKET = /\b(GRM|CS|MER|IFRFE|OPS)-\d+\b/g;
const tickets = {};
for (const text of [...commits.map((c) => c.message), ...prsCreated.map((p) => p.title), ...prsMerged.map((p) => p.title)]) {
  for (const t of String(text).match(TICKET) || []) tickets[t] = (tickets[t] || 0) + 1;
}

const reviewedForOthers = prsReviewed.filter((p) => p.author !== author);

// 按真实结局给我创建的 PR 分桶：merged / closed_unmerged / open
const prOutcome = (p) => {
  if (p.merged_at) return 'merged';
  if (p.state === 'closed') return 'closed_unmerged';
  return 'open';
};
const createdByOutcome = { merged: [], closed_unmerged: [], open: [] };
for (const p of prsCreated) createdByOutcome[prOutcome(p)].push(p);

const evidence = {
  status: 'scanned',
  source_key: 'github_activity',
  tool: 'gh',
  generated_at: new Date().toISOString(),
  week_start: week.week_start,
  week_end: week.week_end,
  iso_week: week.iso_week,
  week_label: week.week_label,
  author,
  queries_run: [
    `search/commits q=author:${author} author-date:${from}..${to}`,
    `search/issues q=author:${author} type:pr created:${from}..${to}`,
    `search/issues q=author:${author} type:pr merged:${from}..${to}`,
    `search/issues q=reviewed-by:${author} type:pr updated:${from}..${to}`,
  ],
  excluded_repos: [...excluded],
  excluded_commit_count: excludedCommitCount,
  commit_count: commits.length,
  // search API 单独的命中数，用于暴露它对私有仓库的漏索引程度
  commit_count_via_search_only: searchOnlyCount,
  repos_probed_per_repo: perRepoProbed,
  repos_unreadable: perRepoFailed,
  pr_created_count: prsCreated.length,
  pr_merged_count: prsMerged.length,
  pr_reviewed_count: prsReviewed.length,
  pr_reviewed_for_others_count: reviewedForOthers.length,
  // 我创建的 PR 按真实结局拆分；closed_unmerged 不能算交付
  pr_created_merged: createdByOutcome.merged.length,
  pr_created_closed_unmerged: createdByOutcome.closed_unmerged.length,
  pr_created_open: createdByOutcome.open.length,
  pr_created_by_outcome: {
    merged: createdByOutcome.merged.map((p) => `${p.repo}#${p.number}`),
    closed_unmerged: createdByOutcome.closed_unmerged.map((p) => `${p.repo}#${p.number}`),
    open: createdByOutcome.open.map((p) => `${p.repo}#${p.number}`),
  },
  outcome_note:
    'search/issues state is only open/closed — closed covers BOTH merged and closed-without-merge; merged_at is the only reliable signal',
  repos_touched: Object.keys(byRepo).sort(),
  commits_by_repo: byRepo,
  commits_by_day: Object.fromEntries(Object.keys(byDay).sort().map((k) => [k, byDay[k]])),
  tickets,
  coverage_note:
    'commits come from search/commits UNION per-repo commits API; search alone under-reports private repos (observed 0 hits for a private repo with 73 commits). Per-repo probing also covers main/master/production because the default branch is not always the trunk. PRs and reviews are invisible to local git entirely.',
  commits,
  prs_created: prsCreated,
  prs_merged: prsMerged,
  prs_reviewed: prsReviewed,
};

if (toStdout) {
  console.log(JSON.stringify(evidence, null, 2));
  process.exit(0);
}

const outPath = readOption('--out')
  || path.join(scratchWeekDir(config, week), 'github-evidence', 'github-activity.json');

// 与 session 采集器同一条红线：原始证据不进 vault
if (config.vaultRoot && path.resolve(outPath).startsWith(path.resolve(config.vaultRoot) + path.sep)) {
  console.error('FAIL [GITHUB-002] refusing to write github evidence inside the vault');
  process.exit(1);
}

fs.mkdirSync(path.dirname(outPath), { recursive: true });
fs.writeFileSync(outPath, `${JSON.stringify(evidence, null, 2)}\n`);

console.log(JSON.stringify({
  status: evidence.status,
  out: outPath,
  week_label: week.week_label,
  commit_count: evidence.commit_count,
  pr_created_count: evidence.pr_created_count,
  pr_created_by_outcome: evidence.pr_created_by_outcome,
  pr_merged_count: evidence.pr_merged_count,
  pr_reviewed_count: evidence.pr_reviewed_count,
  repos_touched: evidence.repos_touched,
  tickets: evidence.tickets,
}, null, 2));

#!/usr/bin/env node
// 零依赖回归测试。用法：node weekly-work-review/tests/run-tests.mjs
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { join, relative } from 'node:path';
import {
  cpSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { resolveWeek, isWeekDirName, weekLabel, mondayOf, formatDateOnly } from '../scripts/lib/week.mjs';

const results = [];

function test(name, fn) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (error) {
    results.push({ name, ok: false, error: error.message });
  }
}

test('WEEK-001 普通周收敛到同一周目录', () => {
  const monday = resolveWeek('2026-08-03');
  const sunday = resolveWeek('2026-08-09');
  assert.equal(monday.week_dir_name, '2026-08-03 至 08-09');
  assert.equal(sunday.week_dir_name, monday.week_dir_name);
  assert.equal(monday.report_file_name, '2026-08-03 至 08-09 周复盘.md');
  assert.equal(monday.iso_week, '2026-W32');
});

test('WEEK-002 归档年月取 week_start（跨月周）', () => {
  const week = resolveWeek('2026-09-02');
  assert.equal(week.week_start, '2026-08-31');
  assert.equal(week.week_end, '2026-09-06');
  assert.equal(week.archive_year, '2026');
  assert.equal(week.archive_month, '08');
  assert.equal(week.week_dir_name, '2026-08-31 至 09-06');
});

test('WEEK-003 跨年周使用完整日期', () => {
  const week = resolveWeek('2027-01-01');
  assert.equal(week.week_start, '2026-12-28');
  assert.equal(week.week_end, '2027-01-03');
  assert.equal(week.archive_year, '2026');
  assert.equal(week.archive_month, '12');
  assert.equal(week.week_dir_name, '2026-12-28 至 2027-01-03');
});

test('WEEK-004 周一到周日七天全部映射到同一周', () => {
  const names = new Set(
    ['2026-08-03', '2026-08-04', '2026-08-05', '2026-08-06', '2026-08-07', '2026-08-08', '2026-08-09'].map(
      (day) => resolveWeek(day).week_dir_name,
    ),
  );
  assert.equal(names.size, 1);
});

test('WEEK-005 ISO 周编号与跨年归属正确', () => {
  assert.equal(resolveWeek('2026-01-01').iso_week, '2026-W01');
  assert.equal(resolveWeek('2026-07-27').iso_week, '2026-W31');
  assert.equal(resolveWeek('2027-01-01').iso_week, '2026-W53');
});

test('WEEK-006 周目录名校验接受两种形态', () => {
  assert.equal(isWeekDirName('2026-08-03 至 08-09'), true);
  assert.equal(isWeekDirName('2026-12-28 至 2027-01-03'), true);
  assert.equal(isWeekDirName('week-1'), false);
  assert.equal(isWeekDirName('2026-W32'), false);
});

test('WEEK-007 非法日期必须报错', () => {
  assert.throws(() => resolveWeek('2026-02-30'));
  assert.throws(() => resolveWeek('2026/08/03'));
  assert.throws(() => resolveWeek('not-a-date'));
});

test('WEEK-008 周一计算不受时区偏移影响', () => {
  assert.equal(formatDateOnly(mondayOf('2026-08-09')), '2026-08-03');
  assert.equal(weekLabel('2026-08-03', '2026-08-09'), '2026-08-03 至 08-09');
});

// SESSION-001：原先默认只读、扫描要显式 --scan，导致"更早创建、本周有更新"的 session
// 落在旧索引外被整块漏掉（W32 实测漏掉一整块方案设计工作）。现在默认先扫描再采集。
test('SESSION-001 采集器默认先扫描，--no-scan 才跳过', () => {
  const source = readFileSync(new URL('../scripts/collect-sessions.mjs', import.meta.url), 'utf8');
  // 默认必须扫描：跳过只能由显式 --no-scan 触发
  assert.match(source, /const skipScan = args\.includes\('--no-scan'\)/);
  assert.match(source, /const wantScan = !skipScan/);
  assert.match(source, /if \(wantScan\) \{/);
  // 不得回退成"默认不扫描"
  assert.ok(
    !/const wantScan = args\.includes\('--scan'\)/.test(source),
    'scan must default to on, not require an explicit --scan',
  );
  // 是否扫描/是否成功都要交给调用方写进 manifest
  assert.match(source, /skipped: skipScan/);
  // 拒绝把 session 证据写进 vault
  assert.match(source, /SESSION-002/);
  assert.match(source, /refusing to write session evidence inside the vault/);
});

// SESSION-005：采集器改为默认扫描后，环境预检若原样调用就会跟着写 ~/.memory-manager。
// 预检在 SKILL.md 脚本表里承诺只读，必须显式 --no-scan。
test('SESSION-005 环境预检调用采集器时保持只读', () => {
  const source = readFileSync(new URL('../scripts/check-environment.mjs', import.meta.url), 'utf8');
  assert.match(source, /'collect-sessions\.mjs'\),\s*\n\s*'--week',\s*\n\s*week\.week_start,\s*\n\s*'--no-scan',/);
});

test('SESSION-002 工具缺失时降级为 tool_unavailable 而非失败', () => {
  const source = readFileSync(new URL('../scripts/collect-sessions.mjs', import.meta.url), 'utf8');
  assert.match(source, /status: 'tool_unavailable'/);
  // 降级必须以 0 退出，让调用方把状态写进 manifest
  assert.match(source, /process\.exit\(0\)/);
});

// SESSION-003：周边界必须按配置时区算。曾用 UTC，导致周一 00:00–08:00（Asia/Shanghai）
// 的会话被判到上一周，W32 实测丢 5 条（含 MoeGo OPC skill 设计）。
test('SESSION-003 周边界按配置时区而非 UTC 计算', () => {
  const source = readFileSync(new URL('../scripts/collect-sessions.mjs', import.meta.url), 'utf8');
  // 不得再出现裸 UTC 边界
  assert.ok(
    !/Date\.parse\(`\$\{week\.week_start\}T00:00:00Z`\)/.test(source),
    'week boundary must not be hardcoded to UTC',
  );
  assert.match(source, /zonedWallTimeToMs/);
  assert.match(source, /config\.timezone/);
  // 按日归属也要用时区，否则跨零点会话归错日
  assert.match(source, /date: zonedDate\(session\.updatedAt\)/);
  assert.ok(
    !/date: String\(session\.updatedAt \|\| ''\)\.slice\(0, 10\)/.test(source),
    'day attribution must not slice the UTC ISO string',
  );

  // 行为验证：Asia/Shanghai 下，周一 01:00 本地（= 上周日 17:00 UTC）必须落在本周内
  const tzOffsetMs = (instantMs, timeZone) => {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone, hour12: false,
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    }).formatToParts(new Date(instantMs));
    const get = (t) => Number(parts.find((p) => p.type === t)?.value);
    return Date.UTC(get('year'), get('month') - 1, get('day'), get('hour') % 24, get('minute'), get('second')) - instantMs;
  };
  const zonedWallTimeToMs = (wallIso, timeZone) => {
    const naive = Date.parse(`${wallIso}Z`);
    let guess = naive - tzOffsetMs(naive, timeZone);
    return naive - tzOffsetMs(guess, timeZone);
  };
  const startMs = zonedWallTimeToMs('2026-08-03T00:00:00.000', 'Asia/Shanghai');
  const mondayEarly = Date.parse('2026-08-02T17:03:36.848Z'); // 实测被丢掉的那条
  assert.ok(mondayEarly >= startMs, 'Monday 01:03 Asia/Shanghai must fall inside the week');
  // 而真正属于上一周的时刻仍要被排除
  assert.ok(Date.parse('2026-08-02T15:59:00.000Z') < startMs, 'Sunday 23:59 local must stay outside');
});

// SESSION-004：memory-manager 规则提取会 spawn session 再被自己索引收回（自我回灌）。
// W31 实测 326 条在周命中里有 200 条属此类，不剔除会让工时口径虚高 2.6 倍。
test('SESSION-004 剔除工具自产 session 且按正文判定', () => {
  const source = readFileSync(new URL('../scripts/collect-sessions.mjs', import.meta.url), 'utf8');
  // 判据必须落在正文，不能靠标题（标题缺失会退化成 "<project> · <agent>"）
  assert.match(source, /TOOL_SPAWN_PATTERNS/);
  assert.match(source, /根据 evidence 提取可复用的 agent 规则候选/);
  assert.match(source, /readFileSync\(sourcePath, 'utf8'\)/);
  // 聚合与输出都必须基于剔除后的集合
  assert.match(source, /for \(const session of humanSessions\)/);
  assert.match(source, /const items = humanSessions/);
  // 剔除情况必须可回读，不能静默丢弃
  assert.match(source, /tool_spawned_count/);
  assert.match(source, /undetermined_count/);
  assert.match(source, /exclusion_note/);
  // 无法判定的按人工计，不得静默丢弃
  assert.match(source, /counted as human/);
  // 非 JSONL 源（opencode SQLite / copilot）必须走 CLI 的 sessions show，不能直接判为无法判定
  assert.match(source, /runCli\(\['sessions', 'show', session\.id\]/);
  assert.ok(
    !/if \(!sourcePath \|\| !sourcePath\.endsWith\('\.jsonl'\)\) return null/.test(source),
    'non-JSONL sources must fall through to sessions show, not short-circuit to undetermined',
  );

  // 行为验证：正文含工具 prompt 的文件判为自产，普通正文不判
  const dir = mkdtempSync(join(tmpdir(), 'sess-'));
  const toolFile = join(dir, 'tool.jsonl');
  const humanFile = join(dir, 'human.jsonl');
  writeFileSync(toolFile, `${JSON.stringify({
    message: { role: 'user', content: '根据 evidence 提取可复用的 agent 规则候选。 置信度判断框架: high=明确要求' },
  })}\n`);
  writeFileSync(humanFile, `${JSON.stringify({
    message: { role: 'user', content: '我想做一个 MoeGo OPC skills，覆盖需求挖掘到上线反馈的闭环' },
  })}\n`);
  const patterns = [
    /根据 evidence 提取可复用的 agent 规则候选/,
    /置信度判断框架[:：]?\s*high=/,
    /evidence_refs 必须引用 locator/,
  ];
  const verdict = (p) => patterns.some((re) => re.test(readFileSync(p, 'utf8')));
  assert.equal(verdict(toolFile), true, 'tool-spawned session must be detected');
  assert.equal(verdict(humanFile), false, 'human session must not be excluded');
  rmSync(dir, { recursive: true, force: true });
});

// ─── dry-run 零写入：唯一可信的验证是执行前后全目录 hash 一致 ───────────────
function hashTree(root) {
  const entries = [];
  const walk = (dir) => {
    if (!existsSync(dir)) return;
    for (const entry of readdirSync(dir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) {
        entries.push(`D ${relative(root, full)}`);
        walk(full);
      } else if (entry.isFile()) {
        const digest = createHash('sha256').update(readFileSync(full)).digest('hex');
        entries.push(`F ${relative(root, full)} ${digest}`);
      }
    }
  };
  walk(root);
  return createHash('sha256').update(entries.join('\n')).digest('hex');
}

function makeMeetingFixture() {
  const dir = mkdtempSync(join(tmpdir(), 'wwr-dryrun-'));
  const meeting = join(dir, 'meetings', '2026-08-06_Quick-Win-830');
  mkdirSync(meeting, { recursive: true });
  writeFileSync(
    join(meeting, '会议纪要.md'),
    [
      '---',
      'type: meeting-note',
      'minute_token: obcnFixtureToken',
      'note_doc_url: https://example.feishu.cn/docx/DocFixtureToken',
      '---',
      '',
      '# 会议纪要',
      '',
      '文字记录：https://example.feishu.cn/docx/VerbatimFixtureToken',
    ].join('\n'),
  );
  writeFileSync(
    join(meeting, '会议转写.md'),
    ['---', 'type: meeting-transcript', '---', '', 'vc +notes --minute-tokens transcript artifact'].join('\n'),
  );
  writeFileSync(
    join(dir, 'evidence-manifest.json'),
    `${JSON.stringify({ schema_version: '1.2', candidate_items: [] }, null, 2)}\n`,
  );
  return dir;
}

function runScript(script, scriptArgs) {
  const result = spawnSync(
    process.execPath,
    [fileURLToPath(new URL(`../scripts/${script}`, import.meta.url)), ...scriptArgs],
    { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 },
  );
  return `${result.stdout || ''}${result.stderr || ''}`;
}

test('DRYRUN-001 export-meeting-pdfs --dry-run 不修改任何文件', () => {
  const dir = makeMeetingFixture();
  try {
    const before = hashTree(dir);
    runScript('export-meeting-pdfs.mjs', [dir, '--dry-run']);
    assert.equal(hashTree(dir), before, 'dry-run 改动了 fixture');
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('DRYRUN-002 repair-meeting-docs --dry-run 不修改任何文件', () => {
  const dir = makeMeetingFixture();
  try {
    const before = hashTree(dir);
    runScript('repair-meeting-docs.mjs', [dir, '--dry-run']);
    assert.equal(hashTree(dir), before, 'dry-run 改动了 fixture');
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('MEETING-008 空正文与权限页不得判为 valid', async () => {
  const mod = await import('../scripts/repair-meeting-docs.mjs');
  const classify = mod.classifyDocContent;
  assert.equal(classify(''), 'empty');
  assert.equal(classify('---\ntype: x\n---\n'), 'metadata_only');
  assert.equal(classify('无权限查看该文档'), 'permission_denied');
  assert.equal(classify('会议开始 8 秒'), 'suspiciously_short');
  assert.equal(classify(`# 转写\n\n${'说话人A：这是一段足够长的真实会议转写正文。'.repeat(4)}`), 'valid');
});

// ─── validator 门禁：合法 fixture 通过，各类非法 fixture 命中预期规则 ID ────
const FIXTURE_WEEK = fileURLToPath(
  new URL('fixtures/minimal-valid/2026/08/2026-08-03 至 08-09', import.meta.url),
);

function runValidator(dir) {
  const result = spawnSync(
    process.execPath,
    [fileURLToPath(new URL('../scripts/validate-package.mjs', import.meta.url)), dir, '--no-receipt'],
    { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 },
  );
  return { code: result.status, output: `${result.stdout || ''}${result.stderr || ''}` };
}

function withFixtureCopy(mutate) {
  const dir = join(mkdtempSync(join(tmpdir(), 'wwr-gate-')), '2026', '08', '2026-08-03 至 08-09');
  mkdirSync(dir, { recursive: true });
  cpSync(FIXTURE_WEEK, dir, { recursive: true });
  try {
    mutate(dir);
    return runValidator(dir);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

// manifest 改动后必须同步 readback hash，否则 RECEIPT-003 会正确报错
function rewriteManifest(dir, mutateManifest) {
  const manifestPath = join(dir, 'evidence-manifest.json');
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
  mutateManifest(manifest);
  const json = `${JSON.stringify(manifest, null, 2)}\n`;
  writeFileSync(manifestPath, json);
  const hash = createHash('sha256').update(json).digest('hex');
  const mdPath = join(dir, 'evidence-manifest.md');
  writeFileSync(
    mdPath,
    readFileSync(mdPath, 'utf8').replace(/manifest_sha256: [a-f0-9]+/, `manifest_sha256: ${hash}`),
  );
}

test('PKG-000 最小合法 fixture 通过校验', () => {
  const { code, output } = runValidator(FIXTURE_WEEK);
  assert.equal(code, 0, output);
  assert.match(output, /validation passed/);
});

test('PATH-002 旧式 week-N 目录名被拒绝', () => {
  const dir = join(mkdtempSync(join(tmpdir(), 'wwr-gate-')), '2026', '08', 'week-1');
  mkdirSync(dir, { recursive: true });
  cpSync(FIXTURE_WEEK, dir, { recursive: true });
  try {
    const { code, output } = runValidator(dir);
    assert.equal(code, 1);
    assert.match(output, /\[PATH-002\]/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('PRIVACY-002 凭证形状被拦且不回显原文', () => {
  const secret = 'sk-live-abcdefghijklmnopqrstuvwxyz123456';
  const { code, output } = withFixtureCopy((dir) => {
    const target = join(dir, '小时证据附录.md');
    writeFileSync(target, `${readFileSync(target, 'utf8')}\nAuthorization: Bearer ${secret}\n`);
  });
  assert.equal(code, 1);
  assert.match(output, /\[PRIVACY-002\]/);
  assert.match(output, /SECRET-009/);
  assert.equal(output.includes(secret), false, 'validator 回显了凭证原文');
});

test('RECEIPT-003 readback 未绑定当前 manifest hash 时失败', () => {
  const { code, output } = withFixtureCopy((dir) => {
    const manifestPath = join(dir, 'evidence-manifest.json');
    const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
    manifest.generated_at = '2026-08-09T12:00:00Z';
    writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
  });
  assert.equal(code, 1);
  assert.match(output, /\[RECEIPT-003\]/);
});

test('RECEIPT-002 readback 记录 failed 时不得交付', () => {
  const { code, output } = withFixtureCopy((dir) => {
    const mdPath = join(dir, 'evidence-manifest.md');
    writeFileSync(mdPath, readFileSync(mdPath, 'utf8').replace('status: passed', 'status: failed'));
  });
  assert.equal(code, 1);
  assert.match(output, /\[RECEIPT-002\]/);
});

test('MANIFEST-030 候选未分类为 used 或 excluded 时失败', () => {
  const { code, output } = withFixtureCopy((dir) => {
    rewriteManifest(dir, (manifest) => {
      manifest.candidate_items.push({
        id: 'cand-orphan',
        type: 'session',
        title: 'orphan candidate',
        date: '2026-08-04',
        source_key: 'sessions',
        source: 'sessions',
        source_path_or_token: '/tmp/x.jsonl',
        discovery_method: 'fixture',
        evidence_ref: 'fixture',
        used_in: [],
        confidence: 'high',
        sensitivity: 'personal',
      });
      manifest.coverage_summary.total_candidates = 1;
      manifest.coverage_summary.high_signal_candidates = 1;
    });
  });
  assert.equal(code, 1);
  assert.match(output, /\[MANIFEST-030\]/);
});

// COVERAGE-007：曾经 github_activity 标成 partial + "local git only" 就能通过校验，
// 于是 W32 漏掉 6 个仓库、9 个 PR、11 个 review 却一路 0 failure。
test('COVERAGE-007 github_activity 停留在本地 git 口径时失败', () => {
  const localOnly = withFixtureCopy((dir) => {
    rewriteManifest(dir, (manifest) => {
      manifest.sources_scanned.github_activity = {
        status: 'partial',
        tool: 'local git',
        query: 'git log --since --until',
        artifact_path: '',
        raw_count: 5,
        candidate_count: 1,
        used_count: 1,
        skipped_reason: 'local git only; GitHub PR/review API not queried',
      };
    });
  });
  assert.equal(localOnly.code, 1);
  assert.match(localOnly.output, /\[COVERAGE-007\]/);

  // 谎称 scanned 但工具仍是 local git 也要拦——本地 clone 拿不到 PR 与 review
  const fakeScanned = withFixtureCopy((dir) => {
    rewriteManifest(dir, (manifest) => {
      manifest.sources_scanned.github_activity = {
        status: 'scanned',
        tool: 'local git',
        query: 'git log',
        artifact_path: '',
        raw_count: 5,
        candidate_count: 1,
        used_count: 1,
        skipped_reason: '',
      };
    });
  });
  assert.equal(fakeScanned.code, 1);
  assert.match(fakeScanned.output, /\[COVERAGE-007\]/);

  // 用 gh 采集后应放行
  const viaGh = withFixtureCopy((dir) => {
    rewriteManifest(dir, (manifest) => {
      manifest.sources_scanned.github_activity = {
        status: 'scanned',
        tool: 'gh',
        query: 'collect-github.mjs --week 2026-08-09',
        artifact_path: '/tmp/github-activity.json',
        raw_count: 9,
        candidate_count: 1,
        used_count: 1,
        skipped_reason: '',
      };
    });
  });
  assert.equal(viaGh.code, 0, `gh-collected coverage must pass, got: ${viaGh.output}`);
});

// COVERAGE-008：jira 停在 "not collected this run" 曾让 W32 的 25 个自建 issue
// （含 19 个子任务拆解）整块缺席正文。worklog 空是合法的，但要说清是字段无人填写。
// GITHUB-003：search/issues 的 state 只有 open/closed，closed 同时含"已合并"与"关掉没合"。
// 实测 W32 的 CS-49309 与 moego-agent#21 都是 closed 未合并，却被当成已交付写进了周报。
test('GITHUB-003 PR 结局按 merged_at 判定，closed 不等于已合并', () => {
  const source = readFileSync(new URL('../scripts/collect-github.mjs', import.meta.url), 'utf8');
  // 必须取 merged_at，不能只取 state
  assert.match(source, /merged_at: \(\.pull_request\.merged_at \/\/ null\)/);
  assert.match(source, /pr_created_closed_unmerged/);
  assert.match(source, /pr_created_by_outcome/);
  assert.match(source, /outcome_note/);

  // 行为验证：三种结局分别归桶
  const prOutcome = (p) => {
    if (p.merged_at) return 'merged';
    if (p.state === 'closed') return 'closed_unmerged';
    return 'open';
  };
  assert.equal(prOutcome({ state: 'closed', merged_at: '2026-08-07T09:34:40Z' }), 'merged');
  assert.equal(prOutcome({ state: 'closed', merged_at: null }), 'closed_unmerged', 'closed without merged_at must NOT count as delivered');
  assert.equal(prOutcome({ state: 'open', merged_at: null }), 'open');
});

test('COVERAGE-008 Jira 停在“本轮未采集”时失败，字段无人填写时放行', () => {
  const notCollected = withFixtureCopy((dir) => {
    rewriteManifest(dir, (manifest) => {
      manifest.sources_scanned.jira_linear_worklog = {
        status: 'not_applicable',
        tool: 'jira skill',
        query: '',
        artifact_path: '',
        raw_count: 0,
        candidate_count: 0,
        used_count: 0,
        skipped_reason: 'not collected this run',
      };
    });
  });
  assert.equal(notCollected.code, 1);
  assert.match(notCollected.output, /\[COVERAGE-008\]/);

  // worklog 为空但写明字段无人填写 → 放行
  const unusedField = withFixtureCopy((dir) => {
    rewriteManifest(dir, (manifest) => {
      manifest.sources_scanned.jira_issues = {
        status: 'scanned',
        tool: 'jira skill',
        query: 'reporter = currentUser() AND created >= ...',
        artifact_path: '/tmp/jira-activity.json',
        raw_count: 25,
        candidate_count: 2,
        used_count: 2,
        skipped_reason: '',
      };
      manifest.sources_scanned.jira_worklog = {
        status: 'zero_result',
        tool: 'jira skill',
        query: 'worklogAuthor = currentUser() AND worklogDate >= ...',
        artifact_path: '/tmp/jira-activity.json',
        raw_count: 0,
        candidate_count: 0,
        used_count: 0,
        skipped_reason: 'JQL ran successfully; worklog field is unused, not uncollected',
      };
      // zero_result 必须同时登记进 empty_results（MANIFEST-012）
      manifest.empty_results.push({
        source_key: 'jira_worklog',
        query: 'worklogAuthor = currentUser() AND worklogDate >= ...',
      });
    });
  });
  assert.equal(unusedField.code, 0, `unused-worklog coverage must pass, got: ${unusedField.output}`);

  // worklog 空且没给理由 → 拦
  const noReason = withFixtureCopy((dir) => {
    rewriteManifest(dir, (manifest) => {
      manifest.sources_scanned.jira_worklog = {
        status: 'zero_result',
        tool: 'jira skill',
        query: 'worklogAuthor = currentUser()',
        artifact_path: '',
        raw_count: 0,
        candidate_count: 0,
        used_count: 0,
        skipped_reason: '',
      };
    });
  });
  assert.equal(noReason.code, 1);
  assert.match(noReason.output, /\[COVERAGE-008\]/);
});

// COVERAGE-009：slack_inbound 停在 "not run this cycle" 曾让 W32 的 38 条被提及与
// 407 条入站 DM 整块缺席。另外 to:@handle 是 DM 作用域，不能当"被提及"用。
test('COVERAGE-009 Slack 入站未检索时失败，误用 to: 当被提及时也失败', () => {
  const notRun = withFixtureCopy((dir) => {
    rewriteManifest(dir, (manifest) => {
      manifest.sources_scanned.slack_inbound = {
        status: 'not_applicable',
        tool: 'slack skill',
        query: '',
        artifact_path: '',
        raw_count: 0,
        candidate_count: 0,
        used_count: 0,
        skipped_reason: 'inbound mention search not run this cycle',
      };
    });
  });
  assert.equal(notRun.code, 1);
  assert.match(notRun.output, /\[COVERAGE-009\]/);

  // 只用 to:@handle → 拦（DM 作用域，不是被提及）
  const dmScoped = withFixtureCopy((dir) => {
    rewriteManifest(dir, (manifest) => {
      manifest.sources_scanned.slack_inbound = {
        status: 'scanned',
        tool: 'slack skill',
        query: 'to:@winches after:2026-08-02 before:2026-08-10',
        artifact_path: '/tmp/slack-activity.json',
        raw_count: 407,
        candidate_count: 1,
        used_count: 1,
        skipped_reason: '',
      };
    });
  });
  assert.equal(dmScoped.code, 1);
  assert.match(dmScoped.output, /\[COVERAGE-009\]/);

  // 用 <@UID> 采集 → 放行
  const proper = withFixtureCopy((dir) => {
    rewriteManifest(dir, (manifest) => {
      manifest.sources_scanned.slack_inbound = {
        status: 'scanned',
        tool: 'slack skill',
        query: '<@U06GM8PAFEX> -from:@winches after:2026-08-02 before:2026-08-10; to:@winches -from:@winches',
        artifact_path: '/tmp/slack-activity.json',
        raw_count: 38,
        candidate_count: 1,
        used_count: 1,
        skipped_reason: '',
      };
    });
  });
  assert.equal(proper.code, 0, `mention-scoped coverage must pass, got: ${proper.output}`);
});

// REPORT-015：产出类别必须是层级 tag `category/<value>`。
// 用 frontmatter 平铺属性不行——Properties 面板显示得了，但 Tags 树建不起来，
// 侧栏里就没法像目录那样展开浏览。
test('REPORT-015 category 层级 tag 缺失或与 manifest 不一致时失败', () => {
  const reportName = '2026-08-03 至 08-09 周复盘.md';

  // fixture 的 candidate/output 都是空的，所以要成对补齐并同步 coverage 计数
  const addOutput = (manifest, category) => {
    const candId = `cand-${category}`;
    manifest.candidate_items.push({
      id: candId,
      type: 'github',
      title: category,
      date: '2026-08-04',
      source_key: 'github_activity',
      source: 'github',
      source_path_or_token: 'fixture',
      discovery_method: 'fixture',
      evidence_ref: 'fixture',
      used_in: [`${reportName}#本周概览`],
      confidence: 'high',
      sensitivity: 'internal',
    });
    manifest.output_items.push({
      id: `out-${category}`,
      category,
      title: category,
      status: 'completed',
      evidence_refs: [candId],
      report_anchor: '本周概览',
      used_in: [`${reportName}#本周产出总账`],
      sprint_review_selected: false,
    });
    manifest.used_in_report.push({
      candidate_id: candId,
      report_section: '本周概览',
      anchor_text: category,
      claim_supported: 'fixture',
    });
    const s = manifest.coverage_summary;
    s.total_candidates = manifest.candidate_items.length;
    s.total_used = manifest.candidate_items.length;
    s.total_outputs = manifest.output_items.length;
    s.outputs_in_report = manifest.output_items.length;
    s.high_signal_candidates = manifest.candidate_items.length;
    s.high_signal_used = manifest.candidate_items.length;
    s.high_signal_usage_ratio = 1;
  };

  // manifest 有 engineering 产出但 tags 里没有 category/engineering → 拦
  const missingTag = withFixtureCopy((dir) => {
    rewriteManifest(dir, (manifest) => addOutput(manifest, 'engineering'));
  });
  assert.equal(missingTag.code, 1);
  assert.match(missingTag.output, /\[REPORT-015\].*category\/engineering/);

  // tags 有 category/engineering 但 manifest 没有对应产出 → 拦
  const orphanTag = withFixtureCopy((dir) => {
    const p = join(dir, reportName);
    writeFileSync(p, readFileSync(p, 'utf8').replace('  - 工作/周报', '  - 工作/周报\n  - category/engineering'));
  });
  assert.equal(orphanTag.code, 1);
  assert.match(orphanTag.output, /\[REPORT-015\]/);

  // 两边一致 → 放行
  const inSync = withFixtureCopy((dir) => {
    rewriteManifest(dir, (manifest) => addOutput(manifest, 'engineering'));
    const p = join(dir, reportName);
    writeFileSync(p, readFileSync(p, 'utf8').replace('  - 工作/周报', '  - 工作/周报\n  - category/engineering'));
  });
  assert.equal(inSync.code, 0, `matching category tag must pass, got: ${inSync.output}`);
});

test('MANIFEST-001 schema 违规（缺 iso_week）被拦', () => {
  const { code, output } = withFixtureCopy((dir) => {
    rewriteManifest(dir, (manifest) => {
      delete manifest.iso_week;
    });
  });
  assert.equal(code, 1);
  assert.match(output, /\[MANIFEST-001\].*iso_week/);
});

test('MEETING-006/008/009 空会议正文与假 full 转写被拦', () => {
  const { code, output } = withFixtureCopy((dir) => {
    const meeting = join(dir, 'meetings', '2026-08-06_Fixture');
    mkdirSync(meeting, { recursive: true });
    writeFileSync(join(meeting, '会议纪要.md'), '---\ntype: meeting-note\nminute_token: obcnFake\n---\n');
    writeFileSync(
      join(meeting, '会议转写.md'),
      '---\ntype: meeting-transcript\ntranscript_publication: full\n---\n',
    );
  });
  assert.equal(code, 1);
  assert.match(output, /\[MEETING-006\]/);
  assert.match(output, /\[MEETING-008\]/);
  assert.match(output, /\[MEETING-009\]/);
});

test('REPORT-030 Sprint Review 超过 6 条被拦', () => {
  const { code, output } = withFixtureCopy((dir) => {
    const reportPath = join(dir, '2026-08-03 至 08-09 周复盘.md');
    const extra = Array.from({ length: 7 }, (_, i) => `- 第 ${i + 1} 条摘录`).join('\n');
    writeFileSync(
      reportPath,
      readFileSync(reportPath, 'utf8').replace(
        '- 交付物：最小合法归档包 fixture；影响：validator 有可复现基线；下一步：补齐非法 fixture。',
        extra,
      ),
    );
  });
  assert.equal(code, 1);
  assert.match(output, /\[REPORT-030\]/);
});

test('STYLE-001 第一人称完成句式被拦', () => {
  const { code, output } = withFixtureCopy((dir) => {
    const reportPath = join(dir, '2026-08-03 至 08-09 周复盘.md');
    writeFileSync(reportPath, `${readFileSync(reportPath, 'utf8')}\n我完成了这个 fixture。\n`);
  });
  assert.equal(code, 1);
  assert.match(output, /\[STYLE-001\]/);
});

test('RECEIPT-004 校验后写出绑定当前包的 validation-result.json', () => {
  // 归档包被复制到别处后仍应通过：archive_dir 只比较尾部三段
  const dir = join(mkdtempSync(join(tmpdir(), 'wwr-receipt-')), '2026', '08', '2026-08-03 至 08-09');
  mkdirSync(dir, { recursive: true });
  cpSync(FIXTURE_WEEK, dir, { recursive: true });
  try {
    const result = spawnSync(
      process.execPath,
      [fileURLToPath(new URL('../scripts/validate-package.mjs', import.meta.url)), dir],
      { encoding: 'utf8' },
    );
    assert.equal(result.status, 0);
    const receipt = JSON.parse(readFileSync(join(dir, 'validation-result.json'), 'utf8'));
    assert.equal(receipt.status, 'passed');
    assert.equal(receipt.package_path, dir);
    assert.equal(receipt.report_path, '2026-08-03 至 08-09 周复盘.md');
    assert.match(receipt.manifest_sha256, /^[a-f0-9]{64}$/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

// ─── 旧周报迁移 ─────────────────────────────────────────────────────────────
function makeLegacyArchive() {
  const root = mkdtempSync(join(tmpdir(), 'wwr-legacy-'));
  const archive = join(root, '工作', '周报');
  mkdirSync(archive, { recursive: true });
  writeFileSync(
    join(archive, '2026-W31（07-27 至 08-02）.md'),
    ['---', 'title: 2026-W31 周工作', 'week: 2026-W31', 'tags:', '  - 工作/周报', '---', '', '# 2026-W31', '', '旧式平铺周报。'].join('\n'),
  );
  writeFileSync(
    join(archive, '2026-W32（08-03 至 08-09）.md'),
    ['---', 'title: 2026-W32 周工作', 'period_start: 2026-08-03', '---', '', '# 2026-W32'].join('\n'),
  );
  writeFileSync(
    join(archive, '周报索引.md'),
    ['# 周报索引', '', '- [[2026-W31（07-27 至 08-02）]]', '- [[2026-W32（08-03 至 08-09）]]'].join('\n'),
  );
  return { root, archive };
}

function runMigrate(archive, extra = []) {
  const result = spawnSync(
    process.execPath,
    [fileURLToPath(new URL('../scripts/migrate-legacy-weeklies.mjs', import.meta.url)), '--archive-dir', archive, ...extra],
    { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 },
  );
  return { code: result.status, output: `${result.stdout || ''}${result.stderr || ''}` };
}

test('MIGRATE-001 预览模式对归档目录零写入', () => {
  const { root, archive } = makeLegacyArchive();
  try {
    const before = hashTree(archive);
    const { code, output } = runMigrate(archive);
    assert.equal(code, 0, output);
    assert.equal(hashTree(archive), before, '预览模式改动了归档目录');
    const summary = JSON.parse(output);
    assert.equal(summary.mode, 'preview');
    assert.equal(summary.ready, 2);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('MIGRATE-002 年月取周一：W31 归入 2026/07 而非 2026/08', () => {
  const { root, archive } = makeLegacyArchive();
  try {
    const summary = JSON.parse(runMigrate(archive).output);
    const w31 = summary.plans.find((p) => p.source.startsWith('2026-W31'));
    const w32 = summary.plans.find((p) => p.source.startsWith('2026-W32'));
    assert.equal(w31.target_dir, '2026/07/2026-07-27 至 08-02');
    assert.equal(w32.target_dir, '2026/08/2026-08-03 至 08-09');
    assert.equal(w31.week_start, '2026-07-27');
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('MIGRATE-003 --apply 迁移到日期范围目录并更新索引链接', () => {
  const { root, archive } = makeLegacyArchive();
  try {
    const { code, output } = runMigrate(archive, ['--apply']);
    assert.equal(code, 0, output);
    const summary = JSON.parse(output);
    assert.equal(summary.migrated, 2);

    const migrated = join(archive, '2026/08/2026-08-03 至 08-09/2026-08-03 至 08-09 周复盘.md');
    assert.equal(existsSync(migrated), true, '目标主报告未生成');
    assert.equal(existsSync(join(archive, '2026-W32（08-03 至 08-09）.md')), false, '旧文件未移除');

    // 机器字段补齐，原有 frontmatter 保留
    const text = readFileSync(migrated, 'utf8');
    assert.match(text, /^type: weekly-review$/m);
    assert.match(text, /^week_start: 2026-08-03$/m);
    assert.match(text, /^iso_week: 2026-W32$/m);
    assert.match(text, /title: 2026-W32 周工作/);

    // 索引 wikilink 已指向新路径
    const index = readFileSync(join(archive, '周报索引.md'), 'utf8');
    assert.match(index, /\[\[2026\/08\/2026-08-03 至 08-09\/2026-08-03 至 08-09 周复盘\]\]/);
    assert.equal(index.includes('[[2026-W32（08-03 至 08-09）]]'), false);

    // 备份存在，可人工恢复
    assert.equal(existsSync(summary.backup_dir), true, '未建立备份');
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('MIGRATE-005 改写全 vault backlink 并保留锚点与别名', () => {
  const { root, archive } = makeLegacyArchive();
  try {
    // vault 内其他位置的引用，含 #锚点|别名 形式
    const projectDir = join(root, '项目', 'Memory Manager');
    mkdirSync(projectDir, { recursive: true });
    writeFileSync(
      join(projectDir, '为什么需要这个项目.md'),
      '- [[2026-W31（07-27 至 08-02）#Memory Manager|2026-W31：工程进展]]\n',
    );
    const meetingDir = join(root, '工作', '会议');
    mkdirSync(meetingDir, { recursive: true });
    writeFileSync(
      join(meetingDir, '会议笔记.md'),
      'related: "[[2026-W32（08-03 至 08-09）]]"\n返回：[[2026-W32（08-03 至 08-09）]]\n',
    );

    const preview = JSON.parse(runMigrate(archive).output);
    assert.equal(preview.backlink_files, 3, '未发现全部引用文件');

    const { code, output } = runMigrate(archive, ['--apply']);
    assert.equal(code, 0, output);

    // 锚点与别名必须原样保留，只改 target
    const projectText = readFileSync(join(projectDir, '为什么需要这个项目.md'), 'utf8');
    assert.match(
      projectText,
      /\[\[2026\/07\/2026-07-27 至 08-02\/2026-07-27 至 08-02 周复盘#Memory Manager\|2026-W31：工程进展\]\]/,
    );

    const meetingText = readFileSync(join(meetingDir, '会议笔记.md'), 'utf8');
    assert.equal(meetingText.includes('2026-W32（08-03 至 08-09）'), false, '旧链接残留');
    assert.equal((meetingText.match(/2026-08-03 至 08-09 周复盘/g) || []).length, 2);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('MIGRATE-004 目标已存在时拒绝 --apply', () => {
  const { root, archive } = makeLegacyArchive();
  try {
    const conflictDir = join(archive, '2026', '08', '2026-08-03 至 08-09');
    mkdirSync(conflictDir, { recursive: true });
    writeFileSync(join(conflictDir, '2026-08-03 至 08-09 周复盘.md'), '# 已存在\n');
    const before = hashTree(archive);
    const { code, output } = runMigrate(archive, ['--apply']);
    assert.equal(code, 1);
    assert.match(output, /\[MIGRATE-002\]/);
    assert.equal(hashTree(archive), before, '冲突时仍然写入了文件');
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

const failed = results.filter((item) => !item.ok);
for (const item of results) {
  console.log(`${item.ok ? 'PASS' : 'FAIL'} ${item.name}${item.ok ? '' : ` -> ${item.error}`}`);
}
console.log(`${results.length - failed.length}/${results.length} passed`);
process.exit(failed.length === 0 ? 0 : 1);

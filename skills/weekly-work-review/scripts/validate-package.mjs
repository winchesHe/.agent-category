#!/usr/bin/env node
// weekly-work-review 归档包校验。
// 结构契约：<archive>/<YYYY>/<MM>/<日期范围>/<日期范围> 周复盘.md
// 所有失败都带规则 ID，便于文档、eval 与 fixture 交叉引用。
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { isWeekDirName, reportFileNameForWeekDir } from './lib/week.mjs';
import { validateAgainstSchema } from './lib/schema.mjs';
import { scanTextForSecrets } from './lib/secrets.mjs';

const VALIDATOR_VERSION = '1.2.0';
const SKILL_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

const REQUIRED_REPORT_SECTIONS = [
  '本周概览',
  '本周一句话判断',
  '本周产出总账',
  '可直接贴到 Sprint Review 的内容',
  '主要推进',
  '每天在做什么',
  '协作与沟通',
  '个人复盘',
  '风险、遗留问题与下周建议',
  '证据口径',
];

const REQUIRED_MANIFEST_MD_SECTIONS = [
  'Coverage Matrix',
  'Queries Run',
  'Empty Results',
  'Candidate Evidence',
  'Used In Report',
  'Excluded With Reason',
  'Shared Clip Discovery',
  'Validation Readback',
];

const args = process.argv.slice(2);
if (args.includes('--help') || args.includes('-h') || args.length === 0) {
  console.log(`Usage: node validate-package.mjs <week-dir> [--no-receipt]

Validates a weekly-work-review archive package and writes validation-result.json
(a receipt bound to the current evidence-manifest.json hash).

  --no-receipt   validate only; do not write validation-result.json`);
  process.exit(args.length === 0 ? 1 : 0);
}

const weekDir = path.resolve(args.find((arg) => !arg.startsWith('--')) || '');
const writeReceipt = !args.includes('--no-receipt');

const failures = [];
const warnings = [];
const fail = (id, message) => failures.push(`[${id}] ${message}`);
const warn = (id, message) => warnings.push(`[${id}] ${message}`);

const exists = (relPath) => fs.existsSync(path.join(weekDir, relPath));
const readText = (relPath) => fs.readFileSync(path.join(weekDir, relPath), 'utf8');
const normalizedRel = (relPath) => String(relPath).split(path.sep).join('/');
const isMeetingBody = (relPath) => /^meetings\/[^/]+\/会议(纪要|转写)\.md$/.test(normalizedRel(relPath));

function listFilesRecursive(root) {
  const files = [];
  if (!fs.existsSync(root)) return files;
  const stack = [root];
  while (stack.length > 0) {
    const current = stack.pop();
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const fullPath = path.join(current, entry.name);
      if (entry.isDirectory()) stack.push(fullPath);
      else if (entry.isFile()) files.push(fullPath);
    }
  }
  return files;
}

function hasHeading(markdown, heading) {
  const escaped = heading.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(`^##\\s+${escaped}\\s*$`, 'm').test(markdown || '');
}

function getHeadingSection(markdown, heading) {
  const lines = String(markdown || '').split(/\r?\n/);
  const escaped = heading.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const headingPattern = new RegExp(`^##\\s+${escaped}\\s*$`);
  const start = lines.findIndex((line) => headingPattern.test(line));
  if (start === -1) return '';
  const body = [];
  for (let index = start + 1; index < lines.length; index += 1) {
    if (/^##\s+/.test(lines[index])) break;
    body.push(lines[index]);
  }
  return body.join('\n').trim();
}

function parseFrontmatter(markdown) {
  const match = String(markdown || '').match(/^---\n([\s\S]*?)\n---/);
  return match ? match[1] : '';
}

function parseFrontmatterFields(markdown) {
  const fields = {};
  for (const line of parseFrontmatter(markdown).split(/\r?\n/)) {
    const match = line.match(/^([A-Za-z0-9_-]+):\s*(.*)$/);
    if (match) fields[match[1]] = match[2].replace(/^"(.*)"$/, '$1');
  }
  return fields;
}

function findFieldValue(text, key) {
  const patterns = [
    new RegExp(`^${key}:\\s*(\\S+)`, 'm'),
    new RegExp(`^${key}：\\s*(\\S+)`, 'm'),
    new RegExp(`^-\\s*${key}:\\s*(\\S+)`, 'm'),
    new RegExp(`^-\\s*${key}：\\s*(\\S+)`, 'm'),
  ];
  for (const pattern of patterns) {
    const match = String(text || '').match(pattern);
    if (match) return match[1].replace(/^"|"$/g, '');
  }
  return '';
}

// ── 结构与主报告定位 ────────────────────────────────────────────────────────
let structureOk = true;
if (!fs.existsSync(weekDir) || !fs.statSync(weekDir).isDirectory()) {
  fail('PATH-001', `week dir does not exist or is not a directory: ${weekDir}`);
  structureOk = false;
}

const weekDirName = path.basename(weekDir);
if (structureOk && !isWeekDirName(weekDirName)) {
  fail('PATH-002', `week dir must be a date-range name like "2026-08-03 至 08-09", got: ${weekDirName}`);
}

if (structureOk) {
  for (const entry of fs.readdirSync(weekDir, { withFileTypes: true })) {
    if (entry.isDirectory() && /^(20\d{2}-W\d{2}__|week-\d+$)/.test(entry.name)) {
      fail('PATH-003', `legacy nested archive dir must not exist inside the week dir: ${entry.name}`);
    }
  }
}

let manifest = null;
if (structureOk && exists('evidence-manifest.json')) {
  try {
    manifest = JSON.parse(readText('evidence-manifest.json'));
  } catch (error) {
    fail('MANIFEST-000', `evidence-manifest.json is not valid JSON: ${error.message}`);
  }
}

function resolveReportRel() {
  if (!structureOk) return '';
  const fromManifest = typeof manifest?.report_path === 'string' ? manifest.report_path : '';
  if (fromManifest && exists(fromManifest)) return fromManifest;
  if (isWeekDirName(weekDirName) && exists(reportFileNameForWeekDir(weekDirName))) {
    return reportFileNameForWeekDir(weekDirName);
  }
  const found = fs
    .readdirSync(weekDir, { withFileTypes: true })
    .filter((entry) => entry.isFile() && /周复盘\.md$/.test(entry.name))
    .map((entry) => entry.name);
  if (found.length === 1) return found[0];
  if (found.length > 1) {
    fail('REPORT-002', `multiple 周复盘.md candidates in week dir: ${found.join(', ')}`);
    return found[0];
  }
  if (exists('复盘.md')) {
    fail('REPORT-003', 'legacy 复盘.md found; rename to "<日期范围> 周复盘.md"');
    return '复盘.md';
  }
  return '';
}

const reportRel = resolveReportRel();
if (structureOk && !reportRel) {
  fail('REPORT-001', 'missing main report: expected "<日期范围> 周复盘.md" in the week dir');
}
if (reportRel && reportRel !== '复盘.md' && isWeekDirName(weekDirName)) {
  const expected = reportFileNameForWeekDir(weekDirName);
  if (reportRel !== expected) {
    fail('REPORT-004', `report name must match the week dir: expected ${expected}, got ${reportRel}`);
  }
}

for (const file of ['小时证据附录.md', '迭代记录.md', 'evidence-manifest.json', 'evidence-manifest.md', 'meetings/会议索引.md']) {
  if (structureOk && !exists(file)) fail('PKG-001', `missing required file: ${file}`);
}

// ── 主报告正文 ──────────────────────────────────────────────────────────────
const reportText = reportRel && exists(reportRel) ? readText(reportRel) : '';
if (reportText) {
  const fields = parseFrontmatterFields(reportText);
  if (!parseFrontmatter(reportText)) {
    fail('REPORT-010', `${reportRel} missing YAML frontmatter`);
  } else {
    if (fields.type !== 'weekly-review') fail('REPORT-011', 'frontmatter must contain type: weekly-review');
    for (const key of ['week_start', 'week_end', 'iso_week']) {
      if (!fields[key]) fail('REPORT-012', `frontmatter missing ${key}`);
    }
    if (manifest) {
      if (fields.week_start && manifest.week_start && fields.week_start !== manifest.week_start) {
        fail('REPORT-013', `frontmatter week_start (${fields.week_start}) != manifest (${manifest.week_start})`);
      }
      if (fields.iso_week && manifest.iso_week && fields.iso_week !== manifest.iso_week) {
        fail('REPORT-013', `frontmatter iso_week (${fields.iso_week}) != manifest (${manifest.iso_week})`);
      }
    }
    const frontmatter = parseFrontmatter(reportText);
    // tags 沿用 vault 现有中文体系
    if (!/工作\/周报/.test(frontmatter)) fail('REPORT-014', 'frontmatter tags must include 工作/周报');

    // REPORT-015：产出类别用层级 tag `category/<value>` 表达，且与 manifest 一致。
    // 不用 frontmatter 属性：Properties 面板的平铺属性不进 Tags 树，侧栏里没法像目录一样展开浏览。
    // 层级 tag 才会在 Tags 面板折叠成 category > engineering 这种可点的树。
    if (manifest && Array.isArray(manifest.output_items)) {
      const tagList = new Set(
        (frontmatter.match(/^tags:\s*\n((?:\s*-\s*.+\n?)+)/m)?.[1] || '')
          .split('\n')
          .map((line) => line.replace(/^\s*-\s*/, '').trim())
          .filter(Boolean),
      );
      const actual = new Set(manifest.output_items.map((o) => o.category).filter(Boolean));
      for (const c of actual) {
        if (!tagList.has(`category/${c}`)) {
          fail('REPORT-015', `frontmatter tags missing "category/${c}" (present in output_items); nested tags are what render as a browsable tree in the Tags pane`);
        }
      }
      for (const t of tagList) {
        if (!t.startsWith('category/')) continue;
        const value = t.slice('category/'.length);
        if (!actual.has(value)) {
          fail('REPORT-015', `tag "category/${value}" has no matching output_items entry`);
        }
      }
    }
  }

  for (const section of REQUIRED_REPORT_SECTIONS) {
    if (!hasHeading(reportText, section)) fail('REPORT-020', `${reportRel} missing section: ${section}`);
  }

  if (/我做了|我完成了/.test(reportText)) {
    fail('STYLE-001', `${reportRel} contains first-person completion phrasing`);
  }
  if (/Slack范围/.test(reportText)) fail('PRIVACY-010', `${reportRel} contains raw Slack Top table marker`);
  if (/\b[UC][0-9][0-9A-Z]{7,}\b/.test(reportText)) {
    fail('PRIVACY-011', `${reportRel} contains raw Slack user/channel id`);
  }

  // Sprint Review 摘录最多 6 条
  const sprint = getHeadingSection(reportText, '可直接贴到 Sprint Review 的内容');
  const sprintItems = sprint
    .split(/\r?\n/)
    .filter((line) => /^\s*(?:[-*+]\s+|\d+\.\s+)/.test(line) && !/^\s{2,}/.test(line));
  if (sprintItems.length > 6) {
    fail('REPORT-030', `Sprint Review excerpt must have at most 6 items, got ${sprintItems.length}`);
  }
}

// ── 隐私与凭证扫描（整包） ──────────────────────────────────────────────────
const allFiles = structureOk ? listFilesRecursive(weekDir) : [];
const secretFindings = [];
for (const file of allFiles) {
  const relPath = normalizedRel(path.relative(weekDir, file));
  if (relPath === 'validation-result.json') continue;
  if (/\.(pdf|png|jpg|jpeg|gif|webp|mp4|mov|zip)$/i.test(relPath)) continue;

  let text;
  try {
    text = fs.readFileSync(file, 'utf8');
  } catch {
    continue;
  }

  // PRIVACY-002：凭证形状对会议原文同样不豁免
  secretFindings.push(...scanTextForSecrets(text, relPath));

  if (/internal-api-drive-stream\.feishu\.cn|api3-eeft-drive\.feishu\.cn/.test(text)) {
    fail('PRIVACY-020', `${relPath} contains non-persistent Feishu internal asset URL`);
  }
  if (/^PROMPT:/m.test(text) || /^TAIL:/m.test(text)) {
    fail('PRIVACY-021', `${relPath} contains raw session PROMPT/TAIL dump`);
  }
  if (/source_package:\s*Codex workspace outputs/.test(text)) {
    fail('PRIVACY-022', `${relPath} contains workspace-only source_package metadata`);
  }
  // 会议正文按飞书原文归档，姓名与客户名不脱敏；其余 markdown 不得含 raw Slack 结构
  if (relPath.endsWith('.md') && !isMeetingBody(relPath)) {
    if (/[{,]\s*"(text|user|ts|blocks)"\s*:/.test(text)) {
      fail('PRIVACY-023', `${relPath} appears to contain raw Slack JSON fields`);
    }
    if (/\b[UC][0-9][0-9A-Z]{7,}\b/.test(text)) {
      fail('PRIVACY-024', `${relPath} contains raw Slack user/channel id`);
    }
  }
}
for (const finding of secretFindings) {
  // 只报位置与规则，不回显凭证原文
  fail('PRIVACY-002', `${finding.file}:${finding.line} matches ${finding.rule_id} (${finding.label})`);
}

// ── Manifest schema 与跨字段规则 ────────────────────────────────────────────
const schemaPath = path.join(SKILL_DIR, 'references', 'evidence-manifest.schema.json');
if (manifest && fs.existsSync(schemaPath)) {
  const schema = JSON.parse(fs.readFileSync(schemaPath, 'utf8'));
  for (const error of validateAgainstSchema(manifest, schema)) {
    fail('MANIFEST-001', `evidence-manifest.json ${error}`);
  }
}

if (manifest) {
  // archive_dir 只校验尾部 <YYYY>/<MM>/<日期范围>，让归档包可以整体移动或复制
  if (manifest.archive_dir) {
    const declaredTail = normalizedRel(manifest.archive_dir).split('/').slice(-3).join('/');
    const actualTail = normalizedRel(weekDir).split('/').slice(-3).join('/');
    if (declaredTail !== actualTail) {
      fail('MANIFEST-002', `archive_dir tail does not match package path: ${declaredTail} vs ${actualTail}`);
    }
  }
  if (manifest.week_label && isWeekDirName(weekDirName) && manifest.week_label !== weekDirName) {
    fail('MANIFEST-003', `week_label (${manifest.week_label}) must equal the week dir name (${weekDirName})`);
  }
  if (manifest.report_path && reportRel && manifest.report_path !== reportRel) {
    fail('MANIFEST-004', `report_path (${manifest.report_path}) does not match the actual report (${reportRel})`);
  }

  const sources = manifest.sources_scanned || {};
  for (const [key, source] of Object.entries(sources)) {
    if (source.status === 'scanned' || source.status === 'partial') {
      if (!source.query && !source.artifact_path) {
        fail('MANIFEST-010', `sources_scanned.${key} status=${source.status} requires query or artifact_path`);
      }
    }
    if (['tool_unavailable', 'permission_denied', 'skipped_by_user'].includes(source.status) && !source.skipped_reason) {
      fail('MANIFEST-011', `sources_scanned.${key} status=${source.status} requires skipped_reason`);
    }
    if (source.status === 'zero_result') {
      const recorded = (manifest.empty_results || []).some((entry) =>
        typeof entry === 'string' ? entry.includes(key) : entry?.source_key === key || entry?.source === key,
      );
      if (!recorded) fail('MANIFEST-012', `sources_scanned.${key} status=zero_result must appear in empty_results[]`);
    }
  }

  const candidateItems = Array.isArray(manifest.candidate_items) ? manifest.candidate_items : [];
  const outputItems = Array.isArray(manifest.output_items) ? manifest.output_items : [];
  const candidateIds = new Set();
  for (const item of candidateItems) {
    if (candidateIds.has(item.id)) fail('MANIFEST-020', `duplicate candidate id: ${item.id}`);
    candidateIds.add(item.id);
  }

  for (const item of outputItems) {
    for (const ref of Array.isArray(item.evidence_refs) ? item.evidence_refs : []) {
      if (!candidateIds.has(ref)) {
        fail('MANIFEST-021', `output_items references unknown candidate: ${item.id} -> ${ref}`);
      }
    }
    if (!(item.used_in || []).some((value) => /周复盘\.md#本周产出总账|复盘\.md#本周产出总账/.test(value))) {
      fail('MANIFEST-022', `output_items.used_in must include the 本周产出总账 anchor: ${item.id}`);
    }
    if (item.report_anchor && reportText && !reportText.includes(item.report_anchor)) {
      fail('REPORT-040', `output_items report_anchor missing from report: ${item.id} -> ${item.report_anchor}`);
    }
  }

  const usedIds = new Set(
    candidateItems.filter((item) => Array.isArray(item.used_in) && item.used_in.length > 0).map((item) => item.id),
  );
  for (const item of Array.isArray(manifest.used_in_report) ? manifest.used_in_report : []) {
    if (item.candidate_id) usedIds.add(item.candidate_id);
    if (item.candidate_id && !candidateIds.has(item.candidate_id)) {
      fail('MANIFEST-023', `used_in_report references unknown candidate: ${item.candidate_id}`);
    }
  }
  for (const item of outputItems) {
    for (const ref of Array.isArray(item.evidence_refs) ? item.evidence_refs : []) usedIds.add(ref);
  }

  const excludedIds = new Set(
    (Array.isArray(manifest.excluded_with_reason) ? manifest.excluded_with_reason : [])
      .map((item) => item.candidate_id)
      .filter(Boolean),
  );
  for (const candidate of candidateItems) {
    const used = usedIds.has(candidate.id);
    const excluded = excludedIds.has(candidate.id);
    if (!used && !excluded) fail('MANIFEST-030', `candidate is neither used nor excluded: ${candidate.id}`);
    if (used && excluded) fail('MANIFEST-031', `candidate cannot be both used and excluded: ${candidate.id}`);
  }
  for (const id of excludedIds) {
    if (!candidateIds.has(id)) fail('MANIFEST-032', `excluded_with_reason references unknown candidate: ${id}`);
  }

  const summary = manifest.coverage_summary || {};
  if (summary.total_candidates !== candidateItems.length) {
    fail('COVERAGE-001', `coverage_summary.total_candidates mismatch: ${summary.total_candidates} vs ${candidateItems.length}`);
  }
  if (summary.total_used !== usedIds.size) {
    fail('COVERAGE-002', `coverage_summary.total_used mismatch: ${summary.total_used} vs ${usedIds.size}`);
  }
  if (summary.total_outputs !== outputItems.length) {
    fail('COVERAGE-003', `coverage_summary.total_outputs mismatch: ${summary.total_outputs} vs ${outputItems.length}`);
  }
  if (summary.outputs_in_report !== outputItems.length) {
    fail('COVERAGE-004', `output coverage must be complete: ${summary.outputs_in_report} vs ${outputItems.length}`);
  }
  if (typeof summary.high_signal_usage_ratio === 'number' && summary.high_signal_usage_ratio < 0.7) {
    if (!summary.low_usage_explanation) {
      fail('COVERAGE-005', `high_signal_usage_ratio below target without low_usage_explanation: ${summary.high_signal_usage_ratio}`);
    } else {
      warn('COVERAGE-005', `high_signal_usage_ratio below target: ${summary.high_signal_usage_ratio}`);
    }
  }
  if (summary.shared_clip_candidates !== summary.shared_clip_indexed) {
    fail('COVERAGE-006', `shared clip candidates/indexed mismatch: ${summary.shared_clip_candidates} vs ${summary.shared_clip_indexed}`);
  }

  // COVERAGE-007：github_activity 不得停在"只查了本地 git"。
  // 实测 W32 本地只扫到 2 个仓库，GitHub 上跨 6 个仓库另有 9 个 PR、11 个 review 完全不可见；
  // 而 partial + skipped_reason 曾让这种残缺包一路通过校验。
  const githubSource = manifest?.sources_scanned?.github_activity;
  if (githubSource && typeof githubSource === 'object') {
    const reason = String(githubSource.skipped_reason || '');
    const tool = String(githubSource.tool || '');
    const localOnly = /local git only|PR\/review API not queried|未查 PR|only local/i.test(reason);
    if (localOnly) {
      fail('COVERAGE-007', `github_activity still declares local-git-only coverage; run collect-github.mjs (gh API) so PRs and reviews are covered: "${reason.slice(0, 120)}"`);
    }
    if (githubSource.status === 'scanned' && /^local git$/i.test(tool)) {
      fail('COVERAGE-007', 'github_activity claims status=scanned with tool="local git"; local clones cannot show PRs or reviews');
    }
  }

  // COVERAGE-008：Jira 不得停在"本轮未采集"。
  // 实测 W32 有 25 个自建 issue（含 19 个子任务拆解）从未进入正文，因为 manifest 写了
  // not_applicable + "not collected this run" 就没人再碰。
  // worklog 为空是合法的——字段本身没人填——但必须写明是"字段未使用"而不是"未采集"。
  for (const [key, source] of Object.entries(manifest?.sources_scanned || {})) {
    if (!/jira|linear|worklog/i.test(key)) continue;
    if (!source || typeof source !== 'object') continue;
    const reason = String(source.skipped_reason || '');
    if (/not collected this run|本轮未采集|未采集/i.test(reason)) {
      fail('COVERAGE-008', `${key} still declares "not collected"; run collect-jira.mjs — issue-level evidence exists even when worklog is empty`);
    }
    // 空 worklog 必须区分"字段无人填写"与"没查"
    if (source.status === 'zero_result' && /worklog/i.test(key) && !reason) {
      fail('COVERAGE-008', `${key} is zero_result without a reason; state whether the worklog field is unused or the query failed`);
    }
  }

  // COVERAGE-009：slack_inbound 不得停在"本轮未执行"。
  // 出站能看到我说了什么，看不到别人找我做什么。实测 W32 有 38 条被提及、407 条入站 DM
  // 全部缺席，而 manifest 只写了 "inbound mention search not run this cycle"。
  const slackInbound = manifest?.sources_scanned?.slack_inbound;
  if (slackInbound && typeof slackInbound === 'object') {
    const reason = String(slackInbound.skipped_reason || '');
    if (/not run this cycle|未执行|本轮未检索|not searched/i.test(reason)) {
      fail('COVERAGE-009', `slack_inbound still declares the search was not run; use collect-slack.mjs — outbound alone cannot show what others asked of you: "${reason.slice(0, 100)}"`);
    }
    // to: 是 DM 作用域，拿它当"被提及"会虚高约 10 倍
    if (/\bto:@/.test(String(slackInbound.query || '')) && !/<@/.test(String(slackInbound.query || ''))) {
      fail('COVERAGE-009', 'slack_inbound query uses only to:@handle, which is DM-scoped; mentions require <@UID>');
    }
  }

  // shared clip 必须进会议索引
  const meetingIndex = exists('meetings/会议索引.md') ? readText('meetings/会议索引.md') : '';
  const indexedItems = Array.isArray(manifest.indexed_items) ? manifest.indexed_items : [];
  for (const clip of candidateItems.filter((item) => ['shared-clip', 'shared-minute'].includes(item.type))) {
    const indexed = indexedItems.find(
      (item) => item.candidate_id === clip.id && /shared-(clip|minute)/.test(item.source_type || ''),
    );
    if (!indexed) fail('CLIP-001', `shared clip candidate not indexed in manifest: ${clip.id}`);
    if (!clip.minute_token && !clip.token_unavailable_reason) {
      fail('CLIP-002', `shared clip missing minute_token or token_unavailable_reason: ${clip.id}`);
    }
    if (clip.minute_token && !meetingIndex.includes(clip.minute_token)) {
      fail('CLIP-003', `shared clip minute_token missing from meetings/会议索引.md: ${clip.minute_token}`);
    }
  }
}

// ── 会议索引与会议正文质量 ──────────────────────────────────────────────────
if (exists('meetings/会议索引.md')) {
  const meetingIndex = readText('meetings/会议索引.md');
  for (const column of ['source_type', 'discovery_method', 'minute_token/meeting_id']) {
    if (!meetingIndex.includes(column)) {
      fail('MEETING-001', `meetings/会议索引.md missing column: ${column}`);
    }
  }

  const meetingsDir = path.join(weekDir, 'meetings');
  const meetingFolders = fs
    .readdirSync(meetingsDir, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name);

  for (const folder of meetingFolders) {
    const noteRel = `meetings/${folder}/会议纪要.md`;
    const transcriptRel = `meetings/${folder}/会议转写.md`;
    if (!exists(noteRel)) fail('MEETING-002', `meeting folder missing 会议纪要.md: ${folder}`);
    if (!exists(transcriptRel)) fail('MEETING-003', `meeting folder missing 会议转写.md: ${folder}`);
    if (!meetingIndex.includes(folder)) warn('MEETING-004', `meeting folder not referenced by 会议索引.md: ${folder}`);

    if (exists(noteRel)) {
      const noteText = readText(noteRel);
      const fields = parseFrontmatterFields(noteText);
      const body = noteText.replace(/^---[\s\S]*?---/, '').trim();
      const status = fields.read_status || fields.human_check_required || '';

      // MEETING-005：空正文 / 权限页 / 占位内容不得伪装成完整纪要
      if (/no permission|permission denied|无权限|没有权限/i.test(noteText) && !status) {
        fail('MEETING-005', `${noteRel} looks like a permission error page without a read status`);
      }
      if (body.length === 0) {
        fail('MEETING-006', `${noteRel} has no body content (metadata only)`);
      } else if (body.length < 80 && !status) {
        fail('MEETING-007', `${noteRel} body is suspiciously short (${body.length} chars) without a read status`);
      }

      const minuteToken = fields.minute_token || findFieldValue(noteText, 'minute_token');
      const meetingId = fields.meeting_id || findFieldValue(noteText, 'meeting_id');
      const sourceType = fields.source_type || findFieldValue(noteText, 'source_type');
      const isLarkMeeting =
        Boolean(minuteToken || meetingId) || /lark|vc|minutes|shared-(clip|minute)|manual-link/i.test(sourceType || '');

      if (isLarkMeeting) {
        const noteDocToken =
          fields.note_doc_token ||
          findFieldValue(noteText, 'note_doc_token') ||
          (String(fields.note_doc_url || findFieldValue(noteText, 'note_doc_url') || '').match(/\/docx\/([A-Za-z0-9]+)/) || [])[1] ||
          '';
        const pdfRel = `meetings/${folder}/exports/飞书原始纪要.pdf`;
        const pdfReason = fields.pdf_unavailable_reason || findFieldValue(noteText, 'pdf_unavailable_reason');
        if (noteDocToken && !exists(pdfRel)) {
          fail('MEETING-010', `meeting has note_doc_token but missing exports/飞书原始纪要.pdf: ${folder}`);
        }
        if (!noteDocToken && !exists(pdfRel) && !pdfReason) {
          fail('MEETING-011', `meeting missing note_doc_token/note_doc_url and pdf_unavailable_reason: ${folder}`);
        }
      }
    }

    // MEETING-008：转写要么有正文，要么写明不可用原因
    if (exists(transcriptRel)) {
      const transcriptText = readText(transcriptRel);
      const transcriptFields = parseFrontmatterFields(transcriptText);
      const transcriptBody = transcriptText.replace(/^---[\s\S]*?---/, '').trim();
      const declaredUnavailable =
        /transcript_unavailable|transcript_publication:\s*unavailable/.test(transcriptText) ||
        Boolean(transcriptFields.transcript_unavailable_reason);
      if (transcriptBody.length === 0 && !declaredUnavailable) {
        fail('MEETING-008', `${transcriptRel} has no body and no transcript_unavailable reason`);
      }
      if (transcriptFields.transcript_publication === 'full' && transcriptBody.length < 80) {
        fail('MEETING-009', `${transcriptRel} claims transcript_publication: full but body is nearly empty`);
      }
    }
  }
}

// ── evidence-manifest.md 与 Validation Readback ─────────────────────────────
const manifestJsonPath = path.join(weekDir, 'evidence-manifest.json');
const manifestHash = fs.existsSync(manifestJsonPath)
  ? createHash('sha256').update(fs.readFileSync(manifestJsonPath)).digest('hex')
  : '';

if (exists('evidence-manifest.md')) {
  const manifestMd = readText('evidence-manifest.md');
  for (const section of REQUIRED_MANIFEST_MD_SECTIONS) {
    if (!hasHeading(manifestMd, section)) fail('MANIFEST-040', `evidence-manifest.md missing section: ${section}`);
  }
  const readback = getHeadingSection(manifestMd, 'Validation Readback');
  const declaresPassed = /\bvalidation (?:passed|succeeded)\b|\bstatus\s*[:：]\s*passed\b/i.test(readback);
  const declaresFailed = /\bvalidation failed\b|\bstatus\s*[:：]\s*failed\b/i.test(readback);

  if (!declaresPassed && !declaresFailed) {
    fail('RECEIPT-001', 'evidence-manifest.md Validation Readback must record a real passed/failed result');
  } else if (declaresFailed) {
    // 交付前 readback 必须是 passed，不能留着旧的 failed
    fail('RECEIPT-002', 'Validation Readback records a failed result; re-run the validator and update it');
  } else if (manifestHash) {
    // RECEIPT-003：readback 必须绑定当前 manifest hash，杜绝手写或过期 readback
    const shortHash = manifestHash.slice(0, 16);
    if (!readback.includes(shortHash)) {
      fail(
        'RECEIPT-003',
        `Validation Readback is not bound to the current manifest hash (expected manifest_sha256 prefix ${shortHash})`,
      );
    }
  }
}

// ── 输出与 receipt ──────────────────────────────────────────────────────────
for (const warning of warnings) console.warn(`WARN ${warning}`);
for (const failure of failures) console.error(`FAIL ${failure}`);

const passed = failures.length === 0;

if (writeReceipt && structureOk) {
  const receipt = {
    status: passed ? 'passed' : 'failed',
    validator_version: VALIDATOR_VERSION,
    validated_at: new Date().toISOString(),
    package_path: weekDir,
    week_label: manifest?.week_label ?? path.basename(weekDir),
    report_path: reportRel || null,
    manifest_sha256: manifestHash || null,
    failures: failures.length,
    warnings: warnings.length,
    failure_rule_ids: Array.from(new Set(failures.map((item) => (item.match(/^\[([^\]]+)\]/) || [])[1]).filter(Boolean))),
  };
  fs.writeFileSync(path.join(weekDir, 'validation-result.json'), `${JSON.stringify(receipt, null, 2)}\n`);
}

if (!passed) {
  console.error(
    `weekly-work-review package validation failed: ${failures.length} failure(s), ${warnings.length} warning(s)`,
  );
  process.exit(1);
}

console.log(
  `weekly-work-review package validation passed: ${warnings.length} warning(s)` +
    (manifestHash ? ` | manifest_sha256=${manifestHash.slice(0, 16)}` : ''),
);

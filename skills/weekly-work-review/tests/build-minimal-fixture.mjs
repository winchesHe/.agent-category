#!/usr/bin/env node
// 生成最小合法 fixture 的 manifest 与 hash 绑定 readback。
// 顺序固定：先定稿 manifest → 算 sha256 → 再写 evidence-manifest.md 的 readback。
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';

const weekDir = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  'fixtures/minimal-valid/2026/08/2026-08-03 至 08-09',
);

const SOURCE_KEYS = [
  'sessions',
  'slack_outbound',
  'slack_inbound',
  'lark_vc',
  'lark_calendar',
  'lark_minutes_owner',
  'lark_minutes_participant',
  'shared_clip_link_extraction',
  'shared_clip_keyword_search',
  'lark_drive_docs',
  'local_vault_notes',
  'personal_outputs',
  'github_activity',
  'jira_issues',
  'jira_worklog',
];

const sources = {};
for (const key of SOURCE_KEYS) {
  sources[key] = {
    status: 'not_applicable',
    tool: 'fixture',
    query: '',
    artifact_path: '',
    raw_count: 0,
    candidate_count: 0,
    used_count: 0,
    skipped_reason: 'minimal regression fixture',
  };
}

const manifest = {
  schema_version: '1.2',
  week_start: '2026-08-03',
  week_end: '2026-08-09',
  iso_week: '2026-W32',
  week_label: '2026-08-03 至 08-09',
  timezone: 'Asia/Shanghai',
  archive_dir: weekDir,
  archive_shape: 'date-range-week-dir',
  report_path: '2026-08-03 至 08-09 周复盘.md',
  generated_at: '2026-08-09T00:00:00Z',
  sources_scanned: sources,
  queries_run: [],
  empty_results: [],
  candidate_items: [],
  output_items: [],
  indexed_items: [],
  used_in_report: [],
  excluded_with_reason: [],
  coverage_summary: {
    total_candidates: 0,
    total_used: 0,
    total_outputs: 0,
    outputs_in_report: 0,
    output_coverage_ratio: 1,
    high_signal_candidates: 0,
    high_signal_used: 0,
    high_signal_usage_ratio: 0,
    shared_clip_candidates: 0,
    shared_clip_indexed: 0,
    sources_missing: [],
    low_usage_explanation: 'minimal regression fixture has no real evidence',
    session_agents: {},
  },
};

const manifestJson = `${JSON.stringify(manifest, null, 2)}\n`;
fs.writeFileSync(path.join(weekDir, 'evidence-manifest.json'), manifestJson);

const manifestHash = createHash('sha256').update(manifestJson).digest('hex');

const manifestMd = `# Evidence Manifest

## Coverage Matrix

所有来源均为 \`not_applicable\`，仅用于回归基线。

## Queries Run

无。

## Empty Results

无。

## Candidate Evidence

无。

## Used In Report

无。

## Excluded With Reason

无。

## Shared Clip Discovery

\`not_applicable\`。

## Validation Readback

status: passed
validator_version: 1.2.0
manifest_sha256: ${manifestHash}
note: 由 tests/build-minimal-fixture.mjs 生成，readback 绑定当前 manifest hash。
`;

fs.writeFileSync(path.join(weekDir, 'evidence-manifest.md'), manifestMd);

console.log(JSON.stringify({ week_dir: weekDir, manifest_sha256: manifestHash }, null, 2));

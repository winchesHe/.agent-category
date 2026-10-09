#!/usr/bin/env node
// 输出某一天所属复盘周的全部归档标识。归档路径不允许 agent 心算。
import fs from 'node:fs';
import path from 'node:path';
import { resolveWeek, weekDirRelativePath } from './lib/week.mjs';

const args = process.argv.slice(2);

if (args.includes('--help') || args.includes('-h')) {
  console.log(`Usage: node resolve-week.mjs [YYYY-MM-DD] [--vault-root <dir>] [--archive-relative-dir <dir>]

Resolves the weekly-review archive identity for a date:
  week_start / week_end (Monday..Sunday)
  iso_week (machine metadata only)
  archive_year / archive_month (both taken from week_start)
  week_label, week_dir_name, report_file_name
  week_dir / report_path when a vault root is available

Reads <skill-dir>/.env when present. Output is JSON on stdout.`);
  process.exit(0);
}

function loadEnvFile(envPath) {
  const values = {};
  if (!fs.existsSync(envPath)) return values;
  for (const rawLine of fs.readFileSync(envPath, 'utf8').split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const index = line.indexOf('=');
    if (index === -1) continue;
    values[line.slice(0, index).trim()] = line.slice(index + 1).trim();
  }
  return values;
}

const skillDir = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const envValues = loadEnvFile(path.join(skillDir, '.env'));

function readOption(flag) {
  const index = args.indexOf(flag);
  return index === -1 ? '' : args[index + 1] || '';
}

const positional = args.filter((arg) => !arg.startsWith('--') && !/^\d{4}-\d{2}-\d{2}$/.test(arg) === false);
const dateArg = positional[0] || new Date().toISOString().slice(0, 10);

const vaultRoot = readOption('--vault-root') || process.env.WEEKLY_REVIEW_VAULT_ROOT || envValues.WEEKLY_REVIEW_VAULT_ROOT || '';
const archiveRelativeDir =
  readOption('--archive-relative-dir') ||
  process.env.WEEKLY_REVIEW_ARCHIVE_RELATIVE_DIR ||
  envValues.WEEKLY_REVIEW_ARCHIVE_RELATIVE_DIR ||
  '工作/周报';

let week;
try {
  week = resolveWeek(dateArg);
} catch (error) {
  console.error(`FAIL [WEEK-001] ${error.message}`);
  process.exit(1);
}

const relativeWeekDir = weekDirRelativePath(week.week_start, archiveRelativeDir);
const output = {
  input_date: dateArg,
  ...week,
  archive_relative_dir: archiveRelativeDir,
  week_dir_relative: relativeWeekDir,
  report_relative: `${relativeWeekDir}/${week.report_file_name}`,
  vault_root: vaultRoot || null,
  week_dir: vaultRoot ? path.join(vaultRoot, relativeWeekDir) : null,
  report_path: vaultRoot ? path.join(vaultRoot, relativeWeekDir, week.report_file_name) : null,
  vault_root_exists: vaultRoot ? fs.existsSync(vaultRoot) : false,
  week_dir_exists: vaultRoot ? fs.existsSync(path.join(vaultRoot, relativeWeekDir)) : false,
};

console.log(JSON.stringify(output, null, 2));

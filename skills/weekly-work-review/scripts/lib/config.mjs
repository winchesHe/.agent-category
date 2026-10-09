// 统一读取 skill 配置。仅解析路径与行为偏好，不处理任何凭证。
import fs from 'node:fs';
import path from 'node:path';

export const SKILL_DIR = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..');

export function loadEnvFile(envPath = path.join(SKILL_DIR, '.env')) {
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

export function loadConfig(overrides = {}) {
  const env = loadEnvFile();
  const read = (key, fallback = '') =>
    overrides[key] || process.env[key] || env[key] || fallback;

  const vaultRoot = read('WEEKLY_REVIEW_VAULT_ROOT');
  const scratchRoot = read('WEEKLY_REVIEW_SCRATCH_ROOT');
  const archiveRelativeDir = read('WEEKLY_REVIEW_ARCHIVE_RELATIVE_DIR', '工作/周报');
  const meetingsRelativeDir = read('WEEKLY_REVIEW_MEETINGS_RELATIVE_DIR', '工作/会议');

  return {
    skillDir: SKILL_DIR,
    vaultRoot,
    scratchRoot,
    archiveRelativeDir,
    meetingsRelativeDir,
    timezone: read('WEEKLY_REVIEW_TIMEZONE'),
    slackSkillDir: read('WEEKLY_REVIEW_SLACK_SKILL_DIR', path.resolve(SKILL_DIR, '..', 'slack')),
    memoryManagerCli: read('WEEKLY_REVIEW_MEMORY_MANAGER_CLI'),
    sessionArchaeologyDir: read('WEEKLY_REVIEW_SESSION_ARCHAEOLOGY_DIR'),
  };
}

export function isInside(parent, child) {
  if (!parent || !child) return false;
  const normalizedParent = path.resolve(parent) + path.sep;
  const normalizedChild = path.resolve(child) + path.sep;
  return normalizedChild.startsWith(normalizedParent);
}

export function scratchWeekDir(config, week) {
  if (!config.scratchRoot) return '';
  return path.join(config.scratchRoot, week.archive_year, week.archive_month, week.week_dir_name);
}

#!/usr/bin/env node
// 把旧式平铺周报迁移到 <YYYY>/<MM>/<日期范围>/<日期范围> 周复盘.md。
//
// 默认只读预览。--apply 才写入，且写入前建立备份、失败整体回滚。
// 不删除未知手工内容，不覆盖已存在的目标文件。
import fs from 'node:fs';
import path from 'node:path';
import { loadConfig } from './lib/config.mjs';
import { resolveWeek, isWeekDirName } from './lib/week.mjs';

const args = process.argv.slice(2);

if (args.includes('--help') || args.includes('-h')) {
  console.log(`Usage: node migrate-legacy-weeklies.mjs [--apply] [--archive-dir <dir>]

Migrates legacy flat weekly notes such as
  工作/周报/2026-W32（08-03 至 08-09）.md
into the date-range package layout
  工作/周报/2026/08/2026-08-03 至 08-09/2026-08-03 至 08-09 周复盘.md

Default is a READ-ONLY preview. Nothing is written without --apply.

  --apply              perform the migration (moves files, rewrites wikilinks)
  --archive-dir <dir>  override the archive root (default: vault + archive relative dir);
                       the vault root is then derived as <archive-dir>/../..
  --vault-root <dir>   override the vault root scanned for wikilink backlinks

Wikilinks are rewritten across the whole vault, preserving #heading anchors
and |display aliases. Originals are backed up before any write.`);
  process.exit(0);
}

const apply = args.includes('--apply');
const config = loadConfig();

function readOption(flag) {
  const index = args.indexOf(flag);
  return index === -1 ? '' : args[index + 1] || '';
}

const archiveDir = path.resolve(
  readOption('--archive-dir') ||
    (config.vaultRoot ? path.join(config.vaultRoot, config.archiveRelativeDir) : ''),
);

if (!archiveDir || !fs.existsSync(archiveDir)) {
  console.error(`FAIL [MIGRATE-001] archive dir not found: ${archiveDir || '(unset)'}`);
  process.exit(1);
}

// 从文件名推断周：优先显式日期，其次 ISO 周
function inferWeek(fileName, frontmatter) {
  const explicit = frontmatter.week_start || frontmatter.period_start;
  if (explicit && /^\d{4}-\d{2}-\d{2}$/.test(explicit)) return resolveWeek(explicit);

  const range = fileName.match(/(\d{4})-(\d{2})-(\d{2})/);
  if (range) return resolveWeek(`${range[1]}-${range[2]}-${range[3]}`);

  // 2026-W32（08-03 至 08-09） → 用括号内起始日 + ISO 年
  const iso = fileName.match(/^(\d{4})-W(\d{2})/);
  const bracket = fileName.match(/[（(](\d{2})-(\d{2})/);
  if (iso && bracket) return resolveWeek(`${iso[1]}-${bracket[1]}-${bracket[2]}`);
  if (iso) {
    // 仅有 ISO 周：按该 ISO 年第 N 周的周一反推
    const jan4 = new Date(Date.UTC(Number(iso[1]), 0, 4));
    const jan4Monday = new Date(jan4.getTime() - ((jan4.getUTCDay() + 6) % 7) * 86400000);
    const monday = new Date(jan4Monday.getTime() + (Number(iso[2]) - 1) * 7 * 86400000);
    return resolveWeek(monday.toISOString().slice(0, 10));
  }
  return null;
}

function parseFrontmatterFields(markdown) {
  const match = String(markdown || '').match(/^---\n([\s\S]*?)\n---/);
  const fields = {};
  if (!match) return fields;
  for (const line of match[1].split(/\r?\n/)) {
    const field = line.match(/^([A-Za-z0-9_-]+):\s*(.*)$/);
    if (field) fields[field[1]] = field[2].replace(/^"(.*)"$/, '$1');
  }
  return fields;
}

// 补齐机器字段，保留原有 frontmatter 与正文
function ensureFrontmatter(markdown, week, label) {
  const match = markdown.match(/^---\n([\s\S]*?)\n---\n?/);
  const body = match ? markdown.slice(match[0].length) : markdown;
  const lines = match ? match[1].split(/\r?\n/) : [];
  const has = (key) => lines.some((line) => new RegExp(`^${key}:`).test(line));
  const added = [];

  if (!has('title')) added.push(`title: ${label} 周复盘`);
  if (!has('type')) added.push('type: weekly-review');
  if (!has('week_start')) added.push(`week_start: ${week.week_start}`);
  if (!has('week_end')) added.push(`week_end: ${week.week_end}`);
  if (!has('iso_week')) added.push(`iso_week: ${week.iso_week}`);

  const next = [...lines, ...added].filter((line) => line.trim().length > 0);
  return { text: `---\n${next.join('\n')}\n---\n\n${body.replace(/^\n+/, '')}`, added };
}

const legacyFiles = fs
  .readdirSync(archiveDir, { withFileTypes: true })
  .filter((entry) => entry.isFile() && entry.name.endsWith('.md'))
  .map((entry) => entry.name)
  // 索引文件不是周报
  .filter((name) => !/^周报索引\.md$/.test(name))
  .filter((name) => /^\d{4}-W\d{2}|^\d{4}-\d{2}-\d{2}/.test(name))
  .sort();

const plans = [];
for (const fileName of legacyFiles) {
  const sourcePath = path.join(archiveDir, fileName);
  const text = fs.readFileSync(sourcePath, 'utf8');
  const frontmatter = parseFrontmatterFields(text);
  const week = inferWeek(fileName, frontmatter);

  if (!week) {
    plans.push({ source: fileName, status: 'skipped', reason: 'cannot infer week from name or frontmatter' });
    continue;
  }

  const label = week.week_label;
  const targetDirRel = path.join(week.archive_year, week.archive_month, label);
  const targetRel = path.join(targetDirRel, week.report_file_name);
  const targetPath = path.join(archiveDir, targetRel);
  const { added } = ensureFrontmatter(text, week, label);

  plans.push({
    source: fileName,
    status: fs.existsSync(targetPath) ? 'conflict' : 'ready',
    reason: fs.existsSync(targetPath) ? 'target already exists' : undefined,
    week_start: week.week_start,
    week_end: week.week_end,
    iso_week: week.iso_week,
    target_dir: targetDirRel,
    target: targetRel,
    frontmatter_added: added,
    // 迁移后仍需补齐的包内文件，由正式采集流程生成
    package_files_still_missing: [
      '小时证据附录.md',
      '迭代记录.md',
      'evidence-manifest.json',
      'evidence-manifest.md',
      'meetings/会议索引.md',
    ],
  });
}

// 全 vault 扫描 wikilink 引用。只改 target，保留 #heading 锚点与 |显示别名。
function linkPattern(stem) {
  const escaped = stem.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(`\\[\\[${escaped}((?:#|\\|)[^\\]]*)?\\]\\]`, 'g');
}

function collectBacklinks(vaultRoot, stems) {
  const hits = [];
  if (!vaultRoot || !fs.existsSync(vaultRoot)) return hits;
  const stack = [vaultRoot];
  while (stack.length > 0) {
    const current = stack.pop();
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      if (entry.name.startsWith('.')) continue;
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) {
        stack.push(full);
        continue;
      }
      if (!entry.name.endsWith('.md')) continue;
      const text = fs.readFileSync(full, 'utf8');
      for (const [stem, replacement] of stems) {
        const matches = text.match(linkPattern(stem));
        if (!matches) continue;
        hits.push({
          file: path.relative(vaultRoot, full),
          absolute: full,
          stem,
          replacement,
          occurrences: matches.length,
          samples: Array.from(new Set(matches)).slice(0, 3),
        });
      }
    }
  }
  return hits;
}

function rewriteWikilinks(text, stems) {
  let next = text;
  for (const [stem, replacement] of stems) {
    next = next.replace(linkPattern(stem), (_match, suffix) => `[[${replacement}${suffix || ''}]]`);
  }
  return next;
}

const linkStems = plans
  .filter((plan) => plan.status === 'ready')
  .map((plan) => [plan.source.replace(/\.md$/, ''), plan.target.replace(/\.md$/, '')]);

// vault 根：显式 --vault-root 优先；显式 --archive-dir 时由该目录上溯两级，
// 避免误扫配置里的真实 vault；否则回落到配置。
const explicitVaultRoot = readOption('--vault-root');
const vaultRoot = explicitVaultRoot
  ? path.resolve(explicitVaultRoot)
  : readOption('--archive-dir')
    ? path.resolve(archiveDir, '..', '..')
    : config.vaultRoot || path.resolve(archiveDir, '..', '..');
const backlinks = collectBacklinks(vaultRoot, linkStems);
const indexPath = path.join(archiveDir, '周报索引.md');
const indexExists = fs.existsSync(indexPath);

const summary = {
  mode: apply ? 'apply' : 'preview',
  archive_dir: archiveDir,
  vault_root: vaultRoot,
  legacy_found: legacyFiles.length,
  ready: plans.filter((p) => p.status === 'ready').length,
  conflicts: plans.filter((p) => p.status === 'conflict').length,
  skipped: plans.filter((p) => p.status === 'skipped').length,
  index_file: indexExists ? '周报索引.md' : null,
  // 全 vault backlink，含 #锚点 与 |别名 形式；迁移时一并改写
  backlinks_to_rewrite: backlinks.map(({ absolute, ...rest }) => rest),
  backlink_files: Array.from(new Set(backlinks.map((hit) => hit.file))).length,
  backlink_occurrences: backlinks.reduce((sum, hit) => sum + hit.occurrences, 0),
  plans,
};

if (!apply) {
  summary.note = '预览模式：未写入任何文件。确认无误后加 --apply。';
  console.log(JSON.stringify(summary, null, 2));
  process.exit(0);
}

if (summary.conflicts > 0) {
  console.error('FAIL [MIGRATE-002] 存在目标冲突，先解决后再 --apply');
  console.error(JSON.stringify(summary, null, 2));
  process.exit(1);
}

// ── 写入阶段：先备份，失败整体回滚 ──────────────────────────────────────────
const backupDir = path.join(
  path.dirname(archiveDir),
  `.weekly-review-migration-backup-${new Date().toISOString().replace(/[:.]/g, '-')}`,
);
fs.mkdirSync(backupDir, { recursive: true });

const done = [];
const rewritten = [];
try {
  for (const plan of plans) {
    if (plan.status !== 'ready') continue;
    const sourcePath = path.join(archiveDir, plan.source);
    const targetPath = path.join(archiveDir, plan.target);
    const text = fs.readFileSync(sourcePath, 'utf8');
    const { text: nextText } = ensureFrontmatter(text, resolveWeek(plan.week_start), plan.week_start && path.basename(plan.target_dir));

    fs.copyFileSync(sourcePath, path.join(backupDir, plan.source));
    fs.mkdirSync(path.dirname(targetPath), { recursive: true });
    fs.writeFileSync(targetPath, nextText);
    fs.rmSync(sourcePath);
    done.push({ source: sourcePath, target: targetPath });
  }

  // 改写全 vault backlink，保留锚点与别名
  const rewrittenFiles = [];
  const backlinkTargets = Array.from(new Set(backlinks.map((hit) => hit.absolute)));
  for (const target of backlinkTargets) {
    const original = fs.readFileSync(target, 'utf8');
    const next = rewriteWikilinks(original, linkStems);
    if (next === original) continue;
    const backupName = `backlink-${path.relative(vaultRoot, target).split(path.sep).join('__')}`;
    fs.writeFileSync(path.join(backupDir, backupName), original);
    fs.writeFileSync(target, next);
    rewrittenFiles.push({ file: path.relative(vaultRoot, target), backup: backupName });
  }
  rewritten.push(...rewrittenFiles);
} catch (error) {
  // 回滚：恢复备份并移除已写入的目标
  for (const entry of done) {
    try {
      if (fs.existsSync(entry.target)) fs.rmSync(entry.target);
      const backup = path.join(backupDir, path.basename(entry.source));
      if (fs.existsSync(backup)) fs.copyFileSync(backup, entry.source);
    } catch {
      /* 保留备份目录供人工恢复 */
    }
  }
  for (const file of fs.readdirSync(backupDir)) {
    if (!file.startsWith('backlink-')) continue;
    const relative = file.slice('backlink-'.length).split('__').join(path.sep);
    try {
      fs.writeFileSync(path.join(vaultRoot, relative), fs.readFileSync(path.join(backupDir, file), 'utf8'));
    } catch {
      /* 保留备份目录供人工恢复 */
    }
  }
  console.error(`FAIL [MIGRATE-003] 迁移失败并已回滚：${error.message}`);
  console.error(`备份保留在：${backupDir}`);
  process.exit(1);
}

summary.migrated = done.length;
summary.backlinks_rewritten = rewritten;
summary.backup_dir = backupDir;
summary.next_step =
  '每个周目录仍缺 manifest 与附录，需要按正式流程补齐后才能通过 validate-package.mjs。';
console.log(JSON.stringify(summary, null, 2));

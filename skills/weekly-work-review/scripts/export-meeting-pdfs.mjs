#!/usr/bin/env node
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const args = process.argv.slice(2);

function usage(exitCode = 0) {
  console.log(`Usage: node export-meeting-pdfs.mjs <week-dir> [--overwrite] [--dry-run] [--scratch-dir <dir>]

Exports Feishu/Lark meeting note docx files to:
  <week-dir>/meetings/<meeting-folder>/exports/飞书原始纪要.pdf

For each meeting folder, the script:
  1. Reads note_doc_token / note_doc_url from 会议纪要.md when present.
  2. Falls back to lark-cli minutes +detail, then lark-cli note +detail.
  3. Exports the note docx as PDF with lark-cli drive +export.
  4. Records pdf_export_path or pdf_unavailable_reason in 会议纪要.md frontmatter.

This script exports meeting-note PDFs only. It does not export or persist transcripts.
`);
  process.exit(exitCode);
}

if (args.includes('--help') || args.includes('-h') || args.length === 0) usage(args.length === 0 ? 1 : 0);

const options = {
  overwrite: false,
  dryRun: false,
  scratchDir: '',
};

let weekDirArg = '';
for (let index = 0; index < args.length; index += 1) {
  const arg = args[index];
  if (arg === '--overwrite') {
    options.overwrite = true;
  } else if (arg === '--dry-run') {
    options.dryRun = true;
  } else if (arg === '--scratch-dir') {
    options.scratchDir = args[index + 1] || '';
    index += 1;
  } else if (!weekDirArg) {
    weekDirArg = arg;
  } else {
    console.error(`Unexpected argument: ${arg}`);
    usage(1);
  }
}

const weekDir = path.resolve(weekDirArg);
const meetingsDir = path.join(weekDir, 'meetings');
if (!fs.existsSync(meetingsDir) || !fs.statSync(meetingsDir).isDirectory()) {
  console.error(`meetings dir not found: ${meetingsDir}`);
  process.exit(1);
}

const scratchDir = path.resolve(
  options.scratchDir ||
    path.join(os.tmpdir(), 'weekly-work-review-pdf-export', path.basename(path.dirname(weekDir)), path.basename(weekDir)),
);
// DRYRUN-001: dry-run 不创建任何目录
if (!options.dryRun) fs.mkdirSync(scratchDir, { recursive: true });

const env = {
  ...process.env,
  LARKSUITE_CLI_NO_UPDATE_NOTIFIER: '1',
  LARKSUITE_CLI_NO_SKILLS_NOTIFIER: '1',
};

function readText(filePath) {
  return fs.readFileSync(filePath, 'utf8');
}

// DRYRUN-001: --dry-run 必须零写入。所有落盘统一经过这里，dry-run 时只记录意图。
const plannedWrites = [];

function writeText(filePath, text) {
  if (options.dryRun) {
    plannedWrites.push(filePath);
    return;
  }
  fs.writeFileSync(filePath, text);
}

function parseFrontmatter(markdown) {
  const match = markdown.match(/^---\n([\s\S]*?)\n---\n?/);
  if (!match) return { fields: {}, bodyStart: 0, raw: '' };
  const fields = {};
  for (const line of match[1].split(/\r?\n/)) {
    const field = line.match(/^([A-Za-z0-9_-]+):\s*(.*)$/);
    if (!field) continue;
    fields[field[1]] = field[2].replace(/^"(.*)"$/, '$1');
  }
  return { fields, bodyStart: match[0].length, raw: match[1] };
}

function upsertFrontmatterField(markdown, key, value) {
  const valueText = /[\s:#]/.test(value) ? JSON.stringify(value) : value;
  if (!markdown.startsWith('---\n')) {
    return `---\n${key}: ${valueText}\n---\n\n${markdown}`;
  }
  const end = markdown.indexOf('\n---', 4);
  if (end === -1) return markdown;
  const frontmatter = markdown.slice(4, end);
  const lines = frontmatter.split(/\r?\n/);
  let updated = false;
  const nextLines = lines.map((line) => {
    if (new RegExp(`^${key}:`).test(line)) {
      updated = true;
      return `${key}: ${valueText}`;
    }
    return line;
  });
  if (!updated) nextLines.push(`${key}: ${valueText}`);
  return `---\n${nextLines.join('\n')}\n---${markdown.slice(end + 4)}`;
}

function removeFrontmatterField(markdown, key) {
  if (!markdown.startsWith('---\n')) return markdown;
  const end = markdown.indexOf('\n---', 4);
  if (end === -1) return markdown;
  const frontmatter = markdown.slice(4, end);
  const lines = frontmatter.split(/\r?\n/).filter((line) => !new RegExp(`^${key}:`).test(line));
  return `---\n${lines.join('\n')}\n---${markdown.slice(end + 4)}`;
}

function extractTokenFromDocUrl(value) {
  const match = String(value || '').match(/\/docx\/([A-Za-z0-9]+)/);
  return match ? match[1] : '';
}

function findFieldValue(text, key) {
  const patterns = [
    new RegExp(`^${key}:\\s*(\\S+)`, 'm'),
    new RegExp(`^${key}：\\s*(\\S+)`, 'm'),
    new RegExp(`^-\\s*${key}:\\s*(\\S+)`, 'm'),
    new RegExp(`^-\\s*${key}：\\s*(\\S+)`, 'm'),
  ];
  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (match) return match[1].replace(/^"|"$/g, '');
  }
  return '';
}

function extractJson(output) {
  const text = String(output || '');
  for (let start = text.indexOf('{'); start !== -1; start = text.indexOf('{', start + 1)) {
    let depth = 0;
    let inString = false;
    let escaped = false;
    for (let index = start; index < text.length; index += 1) {
      const char = text[index];
      if (inString) {
        if (escaped) {
          escaped = false;
        } else if (char === '\\') {
          escaped = true;
        } else if (char === '"') {
          inString = false;
        }
        continue;
      }
      if (char === '"') {
        inString = true;
      } else if (char === '{') {
        depth += 1;
      } else if (char === '}') {
        depth -= 1;
        if (depth === 0) {
          const candidate = text.slice(start, index + 1);
          try {
            return JSON.parse(candidate);
          } catch {
            break;
          }
        }
      }
    }
  }
  throw new Error(`No JSON object found in command output: ${text.slice(0, 500)}`);
}

function runLark(args, { cwd }) {
  const result = spawnSync('lark-cli', args, {
    cwd,
    env,
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
  });
  const output = `${result.stdout || ''}${result.stderr || ''}`;
  if (result.status !== 0) {
    const error = new Error(output.trim() || `lark-cli exited with ${result.status}`);
    error.status = result.status;
    error.output = output;
    throw error;
  }
  return { output, json: extractJson(output) };
}

function summarizeError(error) {
  const output = String(error.output || error.message || '');
  if (/permission|no permission|forbidden|denied/i.test(output)) return 'permission_denied';
  if (/not found|not exist|invalid token/i.test(output)) return 'note_doc_unavailable';
  return output.split(/\r?\n/).find((line) => line.trim())?.slice(0, 180) || 'unknown_error';
}

function readManifest() {
  const manifestPath = path.join(weekDir, 'evidence-manifest.json');
  if (!fs.existsSync(manifestPath)) return null;
  try {
    return JSON.parse(readText(manifestPath));
  } catch {
    return null;
  }
}

function writeManifest(manifest) {
  if (!manifest) return;
  // dry-run 不得改写 manifest，连 generated_at 也不能动
  if (options.dryRun) {
    plannedWrites.push(path.join(weekDir, 'evidence-manifest.json'));
    return;
  }
  manifest.generated_at = new Date().toISOString();
  const manifestPath = path.join(weekDir, 'evidence-manifest.json');
  writeText(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
}

function matchingManifestItems(manifest, folderName, minuteToken) {
  if (!manifest || !Array.isArray(manifest.candidate_items)) return [];
  return manifest.candidate_items.filter((item) => {
    return (
      item.evidence_ref === folderName ||
      item.evidence_ref === `meetings/${folderName}` ||
      item.id?.includes(folderName) ||
      (minuteToken && (item.minute_token === minuteToken || item.source_path_or_token === minuteToken))
    );
  });
}

function updateManifestPdfFields(manifest, folderName, minuteToken, fields) {
  for (const item of matchingManifestItems(manifest, folderName, minuteToken)) {
    if (fields.note_doc_token) item.note_doc_token = fields.note_doc_token;
    if (fields.pdf_export_path) {
      item.pdf_export_path = fields.pdf_export_path;
      delete item.pdf_unavailable_reason;
    }
    if (fields.pdf_unavailable_reason) {
      item.pdf_unavailable_reason = fields.pdf_unavailable_reason;
      delete item.pdf_export_path;
    }
  }
}

function discoverNoteDocToken({ folderName, notePath, noteText, minuteToken, manifest }) {
  const frontmatter = parseFrontmatter(noteText);
  const fromFrontmatter = frontmatter.fields.note_doc_token || '';
  if (fromFrontmatter) return { token: fromFrontmatter, source: 'frontmatter' };

  const fromBody = findFieldValue(noteText, 'note_doc_token');
  if (fromBody) return { token: fromBody, source: 'body' };

  const urlValue =
    frontmatter.fields.note_doc_url ||
    findFieldValue(noteText, 'note_doc_url') ||
    Array.from(noteText.matchAll(/https:\/\/[^\s)]+\/docx\/[A-Za-z0-9]+[^\s)]*/g)).map((match) => match[0])[0] ||
    '';
  const fromUrl = extractTokenFromDocUrl(urlValue);
  if (fromUrl) return { token: fromUrl, source: 'note_doc_url' };

  const manifestItems = matchingManifestItems(manifest, folderName, minuteToken);
  for (const item of manifestItems) {
    if (item.note_doc_token) return { token: item.note_doc_token, source: 'manifest' };
    const manifestUrl = item.note_doc_url || item.source_path_or_token || '';
    const token = extractTokenFromDocUrl(manifestUrl);
    if (token) return { token, source: 'manifest_url' };
  }

  if (!minuteToken) return { token: '', source: 'missing_minute_token' };

  const minuteResult = runLark(['minutes', '+detail', '--minute-tokens', minuteToken, '--json'], { cwd: scratchDir });
  const minutes = minuteResult.json?.data?.minutes || [];
  const minute = minutes.find((item) => item.minute_token === minuteToken) || minutes[0];
  const noteId = minute?.note_id || '';
  if (!noteId) return { token: '', source: 'minutes_detail_no_note_id' };

  const noteResult = runLark(['note', '+detail', '--note-id', noteId, '--json'], { cwd: scratchDir });
  const note = noteResult.json?.data?.note || {};
  const token = note.note_doc_token || '';
  return { token, source: token ? 'minutes_detail_note_detail' : 'note_detail_no_note_doc_token', noteId };
}

function exportPdf({ folderName, token }) {
  const outputDir = path.join('meetings', folderName, 'exports');
  const result = runLark(
    [
      'drive',
      '+export',
      '--token',
      token,
      '--doc-type',
      'docx',
      '--file-extension',
      'pdf',
      '--file-name',
      '飞书原始纪要.pdf',
      '--output-dir',
      outputDir,
      '--overwrite',
      '--json',
    ],
    { cwd: weekDir },
  );
  return result.json?.data?.saved_path || path.join(weekDir, outputDir, '飞书原始纪要.pdf');
}

const manifest = readManifest();
const meetingFolders = fs
  .readdirSync(meetingsDir, { withFileTypes: true })
  .filter((entry) => entry.isDirectory())
  .map((entry) => entry.name)
  .sort();

const results = [];
let hardFailures = 0;

for (const folderName of meetingFolders) {
  const folderPath = path.join(meetingsDir, folderName);
  const notePath = path.join(folderPath, '会议纪要.md');
  const pdfRelPath = path.join('meetings', folderName, 'exports', '飞书原始纪要.pdf');
  const pdfPath = path.join(weekDir, pdfRelPath);

  if (!fs.existsSync(notePath)) {
    results.push({ folderName, status: 'skipped', reason: 'missing 会议纪要.md' });
    continue;
  }

  let noteText = readText(notePath);
  const minuteToken = findFieldValue(noteText, 'minute_token') || findFieldValue(noteText, 'minute_token/meeting_id').split(/[ /]/)[0];

  if (fs.existsSync(pdfPath) && !options.overwrite) {
    results.push({ folderName, status: 'skipped', reason: 'pdf_exists' });
    continue;
  }

  let discovery;
  try {
    discovery = discoverNoteDocToken({ folderName, notePath, noteText, minuteToken, manifest });
  } catch (error) {
    const reason = `note_doc_token lookup failed: ${summarizeError(error)}`;
    noteText = upsertFrontmatterField(noteText, 'pdf_unavailable_reason', reason);
    writeText(notePath, noteText);
    updateManifestPdfFields(manifest, folderName, minuteToken, { pdf_unavailable_reason: reason });
    results.push({ folderName, status: 'unavailable', reason });
    continue;
  }

  if (!discovery.token) {
    const reason = `note_doc_token unavailable via ${discovery.source}`;
    noteText = upsertFrontmatterField(noteText, 'pdf_unavailable_reason', reason);
    writeText(notePath, noteText);
    updateManifestPdfFields(manifest, folderName, minuteToken, { pdf_unavailable_reason: reason });
    results.push({ folderName, status: 'unavailable', reason });
    continue;
  }

  noteText = upsertFrontmatterField(noteText, 'note_doc_token', discovery.token);
  updateManifestPdfFields(manifest, folderName, minuteToken, { note_doc_token: discovery.token });

  if (options.dryRun) {
    // 只报告将要导出什么，不写文件、不建目录、不导出 PDF
    results.push({
      folderName,
      status: 'dry_run',
      note_doc_token: discovery.token,
      source: discovery.source,
      would_write: [path.join('meetings', folderName, '会议纪要.md'), pdfRelPath],
    });
    continue;
  }

  fs.mkdirSync(path.dirname(pdfPath), { recursive: true });
  try {
    const savedPath = exportPdf({ folderName, token: discovery.token });
    noteText = upsertFrontmatterField(noteText, 'pdf_export_path', 'exports/飞书原始纪要.pdf');
    noteText = removeFrontmatterField(noteText, 'pdf_unavailable_reason');
    writeText(notePath, noteText);
    updateManifestPdfFields(manifest, folderName, minuteToken, {
      note_doc_token: discovery.token,
      pdf_export_path: pdfRelPath,
    });
    results.push({ folderName, status: 'exported', note_doc_token: discovery.token, source: discovery.source, saved_path: savedPath });
  } catch (error) {
    hardFailures += 1;
    const reason = `pdf export failed: ${summarizeError(error)}`;
    noteText = upsertFrontmatterField(noteText, 'pdf_unavailable_reason', reason);
    writeText(notePath, noteText);
    updateManifestPdfFields(manifest, folderName, minuteToken, { note_doc_token: discovery.token, pdf_unavailable_reason: reason });
    results.push({ folderName, status: 'failed', note_doc_token: discovery.token, source: discovery.source, reason });
  }
}

writeManifest(manifest);

const summary = {
  ok: hardFailures === 0,
  week_dir: weekDir,
  scratch_dir: scratchDir,
  exported: results.filter((item) => item.status === 'exported').length,
  unavailable: results.filter((item) => item.status === 'unavailable').length,
  failed: results.filter((item) => item.status === 'failed').length,
  skipped: results.filter((item) => item.status === 'skipped').length,
  dry_run: options.dryRun,
  planned_writes: options.dryRun ? Array.from(new Set(plannedWrites)) : undefined,
  results,
};

console.log(JSON.stringify(summary, null, 2));
process.exit(hardFailures === 0 ? 0 : 1);

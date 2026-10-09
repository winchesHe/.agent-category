#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const args = process.argv.slice(2);

function usage(exitCode = 0) {
  console.log(`Usage: node repair-meeting-docs.mjs <week-dir>... [--dry-run] [--overwrite-notes]

Scans weekly-work-review meeting folders and repairs meeting-level archive gaps:
  - transcript still sourced from minutes/vc artifact while a 文字记录 docx exists
  - missing 会议转写.md when a 文字记录 docx exists
  - non-persistent Feishu internal image URLs in 会议纪要.md

The script fetches note/transcript docx content with lark-cli docs +fetch.
It preserves Feishu text and only rewrites temporary image URLs to durable
assets/images files or explicit unavailable placeholders.
`);
  process.exit(exitCode);
}

if (args.includes('--help') || args.includes('-h') || args.length === 0) usage(args.length === 0 ? 1 : 0);

const options = {
  dryRun: false,
  overwriteNotes: false,
};
const weekDirArgs = [];

for (let index = 0; index < args.length; index += 1) {
  const arg = args[index];
  if (arg === '--dry-run') {
    options.dryRun = true;
  } else if (arg === '--overwrite-notes') {
    options.overwriteNotes = true;
  } else {
    weekDirArgs.push(arg);
  }
}

if (weekDirArgs.length === 0) usage(1);

const env = {
  ...process.env,
  LARKSUITE_CLI_NO_UPDATE_NOTIFIER: '1',
  LARKSUITE_CLI_NO_SKILLS_NOTIFIER: '1',
};

function readText(filePath) {
  return fs.existsSync(filePath) ? fs.readFileSync(filePath, 'utf8') : '';
}

// DRYRUN-001: --dry-run 必须零写入。所有落盘统一经过这里。
const plannedWrites = [];

function writeText(filePath, text) {
  if (options.dryRun) {
    plannedWrites.push(filePath);
    return;
  }
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, text);
}

// MEETING-008: lark 返回成功但正文为空时，不能当作有效内容。
export function classifyDocContent(text) {
  const value = String(text || '');
  const trimmed = value.trim();
  if (trimmed.length === 0) return 'empty';
  if (/no permission|permission denied|无权限|没有权限|申请权限/i.test(trimmed)) return 'permission_denied';
  const body = trimmed.replace(/^---[\s\S]*?---/, '').trim();
  if (body.length === 0) return 'metadata_only';
  if (body.length < 80) return 'suspiciously_short';
  return 'valid';
}

function parseFrontmatter(markdown) {
  const match = markdown.match(/^---\n([\s\S]*?)\n---\n?/);
  if (!match) return { fields: {}, raw: '', body: markdown };
  const fields = {};
  for (const line of match[1].split(/\r?\n/)) {
    const field = line.match(/^([A-Za-z0-9_-]+):\s*(.*)$/);
    if (field) fields[field[1]] = field[2].replace(/^"(.*)"$/, '$1');
  }
  return { fields, raw: match[1], body: markdown.slice(match[0].length) };
}

function yamlValue(key, value) {
  if (key === 'tags' && value === '') return '[work/moego, meeting]';
  if (/^\[[^\n]*\]$/.test(value)) return value;
  if (value === '') return '""';
  if (/[\s:#{}[\],&*?|>'"%@`]/.test(value)) return JSON.stringify(value);
  return value;
}

function serializeFrontmatter(fields, fallbackRaw = '') {
  const existingOrder = [];
  for (const line of fallbackRaw.split(/\r?\n/)) {
    const match = line.match(/^([A-Za-z0-9_-]+):/);
    if (match && !(existingOrder.includes(match[1]))) existingOrder.push(match[1]);
  }
  const keys = [...existingOrder, ...Object.keys(fields).filter((key) => !existingOrder.includes(key))];
  return keys
    .filter((key) => fields[key] !== undefined && fields[key] !== null)
    .map((key) => `${key}: ${yamlValue(key, String(fields[key]))}`)
    .join('\n');
}

function withFrontmatter(originalMarkdown, updates, body) {
  const parsed = parseFrontmatter(originalMarkdown);
  const fields = { ...parsed.fields, ...updates };
  const frontmatter = serializeFrontmatter(fields, parsed.raw);
  return `---\n${frontmatter}\n---\n\n${body.replace(/^\n+/, '')}`;
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

function extractDocxToken(value) {
  const match = String(value || '').match(/\/docx\/([A-Za-z0-9]+)/);
  return match ? match[1] : '';
}

function docxUrlFromToken(token) {
  return token ? `https://mengshikeji.feishu.cn/docx/${token}` : '';
}

function extractDocxUrls(text) {
  return Array.from(new Set(Array.from(text.matchAll(/https:\/\/[^\s)\]]+\/docx\/[A-Za-z0-9]+[^\s)\]]*/g)).map((match) => match[0])));
}

function extractTextRecordDocLinks(markdown) {
  const lines = markdown.split(/\r?\n/);
  const links = [];
  for (let index = 0; index < lines.length; index += 1) {
    if (!/文字记录/.test(lines[index])) continue;
    const windowText = lines.slice(index, index + 10).join('\n');
    links.push(...extractDocxUrls(windowText));
  }
  return Array.from(new Set(links));
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
        if (escaped) escaped = false;
        else if (char === '\\') escaped = true;
        else if (char === '"') inString = false;
        continue;
      }
      if (char === '"') inString = true;
      else if (char === '{') depth += 1;
      else if (char === '}') {
        depth -= 1;
        if (depth === 0) {
          try {
            return JSON.parse(text.slice(start, index + 1));
          } catch {
            break;
          }
        }
      }
    }
  }
  throw new Error(`No JSON object found in command output: ${text.slice(0, 500)}`);
}

function runLark(larkArgs, { cwd }) {
  const result = spawnSync('lark-cli', larkArgs, {
    cwd,
    env,
    encoding: 'utf8',
    maxBuffer: 256 * 1024 * 1024,
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
  if (/not found|not exist|invalid token/i.test(output)) return 'not_found';
  return output.split(/\r?\n/).find((line) => line.trim())?.slice(0, 180) || 'unknown_error';
}

function fetchDocMarkdown(doc, cwd) {
  const result = runLark(['docs', '+fetch', '--doc', doc, '--doc-format', 'markdown', '--format', 'json'], { cwd });
  return result.json?.data?.document?.content || '';
}

function fetchDocXmlFull(doc, cwd) {
  const result = runLark(['docs', '+fetch', '--doc', doc, '--doc-format', 'xml', '--detail', 'full', '--format', 'json'], { cwd });
  return result.json?.data?.document?.content || '';
}

function parseXmlAttrs(tag) {
  const attrs = {};
  for (const match of tag.matchAll(/\s([A-Za-z0-9_-]+)="([^"]*)"/g)) {
    attrs[match[1]] = match[2]
      .replace(/&quot;/g, '"')
      .replace(/&#xA;/g, '\n')
      .replace(/&amp;/g, '&')
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>');
  }
  return attrs;
}

function safeFilename(name, fallback) {
  const ext = path.extname(name || '').replace(/[^A-Za-z0-9.]/g, '') || '';
  const base = path
    .basename(name || fallback, ext)
    .replace(/[^\p{L}\p{N}._-]+/gu, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80);
  return `${base || fallback}${ext}`;
}

function imageEntriesFromXml(xml) {
  const entries = [];
  let index = 0;
  for (const match of xml.matchAll(/<img\b[^>]*>/g)) {
    index += 1;
    const attrs = parseXmlAttrs(match[0]);
    const token = attrs.token || attrs.src || '';
    entries.push({
      index,
      token,
      name: attrs.name || '',
      caption: (attrs.caption || '').trim(),
    });
  }
  return entries;
}

function downloadImageAssets({ meetingDir, xml }) {
  const entries = imageEntriesFromXml(xml);
  const assets = [];
  if (entries.length === 0) return assets;
  fs.mkdirSync(path.join(meetingDir, 'assets', 'images'), { recursive: true });
  for (const entry of entries) {
    if (!entry.token) {
      assets.push({ ...entry, status: 'unavailable', reason: 'missing_image_token' });
      continue;
    }
    const filename = safeFilename(entry.name, `image-${String(entry.index).padStart(2, '0')}`);
    const output = path.join('assets', 'images', `${String(entry.index).padStart(2, '0')}-${filename}`);
    try {
      const result = runLark(['docs', '+media-download', '--token', entry.token, '--output', output, '--format', 'json'], {
        cwd: meetingDir,
      });
      const savedPath = result.json?.data?.saved_path || path.join(meetingDir, output);
      const rel = path.relative(meetingDir, savedPath).split(path.sep).join('/');
      assets.push({ ...entry, status: 'downloaded', rel, content_type: result.json?.data?.content_type || '' });
    } catch (error) {
      assets.push({ ...entry, status: 'unavailable', reason: summarizeError(error) });
    }
  }
  return assets;
}

function rewriteInternalImageUrls(markdown, assets) {
  let imageIndex = 0;
  return markdown.replace(/!\[([^\]]*)\]\((https:\/\/(?:internal-api-drive-stream|api3-eeft-drive)\.feishu\.cn[^)]*)\)/g, (_match, alt) => {
    const asset = assets[imageIndex] || null;
    imageIndex += 1;
    if (asset?.status === 'downloaded') {
      const label = alt || asset.caption || asset.name || '飞书图片';
      return `![${label}](${asset.rel})`;
    }
    const reason = asset?.reason || 'image_asset_unavailable';
    const label = alt || asset?.caption || asset?.name || `image-${imageIndex}`;
    return `[图片未归档：${label}；${reason}]`;
  });
}

function discoverNoteDoc(noteText, transcriptText) {
  const noteFm = parseFrontmatter(noteText).fields;
  const transcriptFm = parseFrontmatter(transcriptText).fields;
  const token =
    noteFm.note_doc_token ||
    findFieldValue(noteText, 'note_doc_token') ||
    transcriptFm.note_doc_token ||
    findFieldValue(transcriptText, 'note_doc_token') ||
    extractDocxToken(noteFm.note_doc_url || findFieldValue(noteText, 'note_doc_url')) ||
    '';
  const url = noteFm.note_doc_url || findFieldValue(noteText, 'note_doc_url') || docxUrlFromToken(token);
  return { token, url, doc: token || url };
}

function discoverVerbatimDoc(noteText, transcriptText) {
  const noteFm = parseFrontmatter(noteText).fields;
  const transcriptFm = parseFrontmatter(transcriptText).fields;
  const explicit =
    noteFm.verbatim_doc_url ||
    transcriptFm.verbatim_doc_url ||
    findFieldValue(noteText, 'verbatim_doc_url') ||
    findFieldValue(transcriptText, 'verbatim_doc_url') ||
    '';
  const explicitToken =
    noteFm.verbatim_doc_token ||
    transcriptFm.verbatim_doc_token ||
    findFieldValue(noteText, 'verbatim_doc_token') ||
    findFieldValue(transcriptText, 'verbatim_doc_token') ||
    extractDocxToken(explicit) ||
    '';
  if (explicitToken || explicit) return { token: explicitToken, url: explicit || docxUrlFromToken(explicitToken), source: 'explicit' };
  const links = extractTextRecordDocLinks(noteText);
  if (links.length > 0) return { token: extractDocxToken(links[0]), url: links[0], source: 'local_note_text_record' };
  return { token: '', url: '', source: 'not_found' };
}

function hasDocFetchSource(transcriptText) {
  return /docs \+fetch|verbatim_doc_(token|url)|文字记录/.test(transcriptText);
}

function hasInternalFeishuUrl(text) {
  return /internal-api-drive-stream\.feishu\.cn|api3-eeft-drive\.feishu\.cn/.test(text);
}

function shouldRepairTranscript(noteText, transcriptText) {
  if (!transcriptText) return true;
  if (/vc \+notes --minute-tokens transcript artifact/.test(transcriptText)) return true;
  const links = extractTextRecordDocLinks(noteText);
  return links.length > 0 && !hasDocFetchSource(transcriptText);
}

function transcriptFrontmatterDefaults(folderName, noteText) {
  const noteFields = parseFrontmatter(noteText).fields;
  return {
    type: 'meeting-transcript',
    status: noteFields.status || 'draft',
    domain: noteFields.domain || 'work',
    tags: noteFields.tags || '[work/moego, meeting]',
    created: noteFields.created || folderName.slice(0, 10),
    updated: new Date().toISOString().slice(0, 10),
    source_type: noteFields.source_type || noteFields.source || findFieldValue(noteText, 'source_type') || '',
    minute_token: noteFields.minute_token || noteFields.meeting_id || findFieldValue(noteText, 'minute_token') || findFieldValue(noteText, 'meeting_id') || '',
  };
}

function repairMeeting({ weekDir, folderName, dryRun, overwriteNotes }) {
  const meetingDir = path.join(weekDir, 'meetings', folderName);
  const notePath = path.join(meetingDir, '会议纪要.md');
  const transcriptPath = path.join(meetingDir, '会议转写.md');
  let noteText = readText(notePath);
  let transcriptText = readText(transcriptPath);

  const actions = [];
  const errors = [];
  let noteDoc = discoverNoteDoc(noteText, transcriptText);
  let verbatimDoc = discoverVerbatimDoc(noteText, transcriptText);
  const needsRemoteNote =
    hasInternalFeishuUrl(noteText) ||
    (shouldRepairTranscript(noteText, transcriptText) && !verbatimDoc.url && noteDoc.doc);

  if (needsRemoteNote) {
    if (!noteDoc.doc) {
      errors.push('note_doc_unavailable_for_remote_note_repair');
    } else {
      actions.push('fetch_note_doc');
      if (!dryRun) {
        try {
          const fetchedNote = fetchDocMarkdown(noteDoc.doc, weekDir);
          const fetchedXml = fetchDocXmlFull(noteDoc.doc, weekDir);
          const assets = downloadImageAssets({ meetingDir, xml: fetchedXml });
          const durableNote = rewriteInternalImageUrls(fetchedNote, assets);
          const fetchedLinks = extractTextRecordDocLinks(durableNote);
          const noteUpdates = {
            note_doc_token: noteDoc.token || extractDocxToken(noteDoc.url),
            note_doc_url: noteDoc.url || docxUrlFromToken(noteDoc.token),
            fetched_by: 'lark-cli docs +fetch',
            updated: new Date().toISOString().slice(0, 10),
          };
          if (fetchedLinks[0]) {
            noteUpdates.verbatim_doc_url = fetchedLinks[0];
            noteUpdates.verbatim_doc_token = extractDocxToken(fetchedLinks[0]);
          }
          if (assets.length > 0) {
            noteUpdates.asset_export_status = assets.every((asset) => asset.status === 'downloaded') ? 'downloaded' : 'partial';
          }
          if (overwriteNotes || hasInternalFeishuUrl(noteText) || fetchedLinks.length > 0) {
            noteText = withFrontmatter(noteText, noteUpdates, durableNote);
            writeText(notePath, noteText);
          }
          noteDoc = discoverNoteDoc(noteText, transcriptText);
          verbatimDoc = discoverVerbatimDoc(noteText, transcriptText);
          actions.push(`note_assets:${assets.filter((asset) => asset.status === 'downloaded').length}/${assets.length}`);
        } catch (error) {
          errors.push(`fetch_note_doc_failed:${summarizeError(error)}`);
        }
      }
    }
  }

  if (shouldRepairTranscript(noteText, transcriptText)) {
    if (!verbatimDoc.url && !verbatimDoc.token) {
      errors.push('verbatim_doc_unavailable');
    } else {
      actions.push('fetch_verbatim_doc');
      if (!dryRun) {
        try {
          const doc = verbatimDoc.token || verbatimDoc.url;
          const fetchedTranscript = fetchDocMarkdown(doc, weekDir);
          const quality = classifyDocContent(fetchedTranscript);
          const existingTranscript = transcriptText || `---\n${serializeFrontmatter(transcriptFrontmatterDefaults(folderName, noteText))}\n---\n`;
          const transcriptUpdates = {
            verbatim_doc_token: verbatimDoc.token || extractDocxToken(verbatimDoc.url),
            verbatim_doc_url: verbatimDoc.url || docxUrlFromToken(verbatimDoc.token),
            source_tool: 'lark-cli docs +fetch',
            source_command: 'lark-cli docs +fetch --doc <文字记录 docx> --doc-format markdown',
            updated: new Date().toISOString().slice(0, 10),
          };
          if (quality === 'valid') {
            transcriptUpdates.transcript_publication = 'full';
            transcriptText = withFrontmatter(existingTranscript, transcriptUpdates, fetchedTranscript);
          } else {
            // 空正文/权限页/占位内容不得标记为 full，必须留下 human check 缺口
            transcriptUpdates.transcript_publication = 'unavailable';
            transcriptUpdates.transcript_unavailable_reason = quality;
            transcriptUpdates.human_check_required = 'true';
            transcriptText = withFrontmatter(
              existingTranscript,
              transcriptUpdates,
              [
                `transcript_unavailable: ${quality}`,
                '',
                '已尝试来源：会议纪要底部 文字记录 docx（lark-cli docs +fetch）。',
                '需要 human check：确认权限或提供真实转写链接后重跑。',
              ].join('\n'),
            );
            errors.push(`verbatim_doc_${quality}`);
          }
          writeText(transcriptPath, transcriptText);
        } catch (error) {
          errors.push(`fetch_verbatim_doc_failed:${summarizeError(error)}`);
        }
      }
    }
  }

  const remaining = [];
  const nextNote = dryRun ? noteText : readText(notePath);
  const nextTranscript = dryRun ? transcriptText : readText(transcriptPath);
  if (hasInternalFeishuUrl(nextNote)) remaining.push('temp_feishu_asset_url_in_note');
  if (hasInternalFeishuUrl(nextTranscript)) remaining.push('temp_feishu_asset_url_in_transcript');
  if (!nextTranscript) remaining.push('missing_transcript');
  if (shouldRepairTranscript(nextNote, nextTranscript)) remaining.push('transcript_still_needs_docfetch');

  return { folderName, actions, errors, remaining };
}

function meetingFolders(weekDir) {
  const meetingsDir = path.join(weekDir, 'meetings');
  if (!fs.existsSync(meetingsDir)) return [];
  return fs
    .readdirSync(meetingsDir, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort();
}

const results = [];
for (const weekArg of weekDirArgs) {
  const weekDir = path.resolve(weekArg);
  for (const folderName of meetingFolders(weekDir)) {
    const notePath = path.join(weekDir, 'meetings', folderName, '会议纪要.md');
    const transcriptPath = path.join(weekDir, 'meetings', folderName, '会议转写.md');
    const noteText = readText(notePath);
    const transcriptText = readText(transcriptPath);
    const issue =
      hasInternalFeishuUrl(noteText) ||
      hasInternalFeishuUrl(transcriptText) ||
      shouldRepairTranscript(noteText, transcriptText);
    if (!issue) continue;
    results.push({
      week_dir: weekDir,
      ...repairMeeting({
        weekDir,
        folderName,
        dryRun: options.dryRun,
        overwriteNotes: options.overwriteNotes,
      }),
    });
  }
}

const summary = {
  ok: results.every((result) => result.errors.length === 0 && result.remaining.length === 0),
  dry_run: options.dryRun,
  checked_week_dirs: weekDirArgs.map((weekArg) => path.resolve(weekArg)),
  repaired_or_flagged: results.length,
  planned_writes: options.dryRun ? Array.from(new Set(plannedWrites)) : undefined,
  results,
};

console.log(JSON.stringify(summary, null, 2));
process.exit(summary.ok ? 0 : 1);

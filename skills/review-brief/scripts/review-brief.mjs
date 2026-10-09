#!/usr/bin/env node

import { createHash, randomUUID } from "node:crypto";
import {
  closeSync,
  constants,
  fstatSync,
  lstatSync,
  openSync,
  readSync,
  realpathSync,
  renameSync,
  statSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { basename, dirname, extname, isAbsolute, join, relative, resolve } from "node:path";
import { inflateSync } from "node:zlib";
import {
  collectVisibleBriefFields,
  findForbiddenVisibleContent,
} from "./review-brief-policy.mjs";

const START_PREFIX = "<!-- review-brief:start";
const END_MARKER = "<!-- review-brief:end -->";
const OPERATIONAL_KEYS = new Set([
  "channel_url",
  "content_hash",
  "file_id",
  "file_hash",
  "generated_at",
  "github_file_hash",
  "github_target_identity",
  "github_url",
  "local_path",
  "permalink",
  "png_hash",
  "png_path",
  "render_hash",
  "slack_file_id",
  "svg_path",
  "thread_ts",
  "upload_url",
  "visual_review",
]);

function usage() {
  process.stderr.write(
    [
      "用法：",
      "  node scripts/review-brief.mjs <finalize|check|hash> <review-brief.json>",
      "  node scripts/review-brief.mjs render-github <review-brief.json> --output <body.md> [--existing-body <body.md>] [--adopt append|replace] [--github-bindings <bindings.json>] [--require-image] [--require-diagram]",
      "  node scripts/review-brief.mjs render-slack <review-brief.json> --output <message.md> [--target-url <https-url>]",
    ].join("\n") + "\n",
  );
}

function fail(message, code = 1) {
  process.stderr.write(`${message}\n`);
  process.exit(code);
}

const JSON_MAX_FILE_BYTES = 4 * 1024 * 1024;
const MAX_TEXT_LENGTH = 20_000;
const MAX_LIST_ITEMS = 200;
const MAX_MAIN_CHANGES = 100;
const MAX_CHANGE_POINTS = 20;
const MAX_ATTACHMENTS = 200;
const MAX_DOCUMENT_DEPTH = 32;
const MAX_DOCUMENT_NODES = 20_000;
const SLACK_MAX_MESSAGE_CHARS = 4_000;
const SLACK_MAX_FILES = 20;
const ARTIFACT_MAX_TOTAL_FILE_BYTES = 100 * 1024 * 1024;
const SLACK_MAX_TOTAL_FILE_BYTES = ARTIFACT_MAX_TOTAL_FILE_BYTES;
const GITHUB_BINDINGS_MAX_FILE_BYTES = 1024 * 1024;
const artifactSnapshots = new Map();
const artifactPathAliases = new Map();

function loadDocument(path) {
  try {
    const stat = lstatSync(path);
    if (!stat.isFile()) fail("ReviewBrief JSON 必须是普通文件", 2);
    if (stat.size > JSON_MAX_FILE_BYTES) fail("ReviewBrief JSON 不得超过 4 MiB", 2);
    const bytes = readBoundedOrdinaryFile(path, JSON_MAX_FILE_BYTES, stat);
    if (!bytes) fail("ReviewBrief JSON 在读取期间发生变化或不可安全读取", 2);
    return {
      document: JSON.parse(bytes.toString("utf8")),
      source: { identity: stat, sha256: sha256(bytes) },
    };
  } catch (error) {
    fail(`无法读取 ReviewBrief JSON：${error.message}`, 2);
  }
}

function assertTraversalBounds(value) {
  const stack = [{ value, depth: 0 }];
  let nodes = 0;
  while (stack.length) {
    const current = stack.pop();
    nodes += 1;
    if (nodes > MAX_DOCUMENT_NODES) fail(`ReviewBrief JSON 最多包含 ${MAX_DOCUMENT_NODES} 个节点`, 2);
    if (current.depth > MAX_DOCUMENT_DEPTH) fail(`ReviewBrief JSON 嵌套不得超过 ${MAX_DOCUMENT_DEPTH} 层`, 2);
    if (Array.isArray(current.value)) {
      for (const item of current.value) stack.push({ value: item, depth: current.depth + 1 });
    } else if (isObject(current.value)) {
      for (const item of Object.values(current.value)) {
        stack.push({ value: item, depth: current.depth + 1 });
      }
    }
  }
}

function assertArtifactCollectionBounds(document) {
  if (Array.isArray(document.artifacts?.attachments) && document.artifacts.attachments.length > MAX_ATTACHMENTS) {
    fail(`artifacts.attachments 最多包含 ${MAX_ATTACHMENTS} 项`, 2);
  }
  let semanticAttachments = 0;
  for (const change of Array.isArray(document.review_brief?.main_changes)
    ? document.review_brief.main_changes
    : []) {
    if (Array.isArray(change?.attachments)) semanticAttachments += change.attachments.length;
    if (semanticAttachments > MAX_ATTACHMENTS) {
      fail(`main_changes.attachments 合计最多包含 ${MAX_ATTACHMENTS} 项`, 2);
    }
  }
}

function getBrief(document) {
  const brief = document?.review_brief;
  if (!brief || typeof brief !== "object" || Array.isArray(brief)) {
    fail("缺少 review_brief 对象", 2);
  }
  return brief;
}

function normalizeString(value) {
  return value.replace(/\r\n?/g, "\n").trim();
}

function normalizeForHash(value) {
  if (Array.isArray(value)) return value.map(normalizeForHash);
  if (value && typeof value === "object") {
    const result = {};
    for (const key of Object.keys(value).sort()) {
      // 本地路径、渠道标识和校验状态只描述交付过程，不改变 Brief 语义。
      if (OPERATIONAL_KEYS.has(key)) continue;
      result[key] = normalizeForHash(value[key]);
    }
    return result;
  }
  return typeof value === "string" ? normalizeString(value) : value;
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function computeHash(brief) {
  return sha256(Buffer.from(JSON.stringify(normalizeForHash(brief)), "utf8"));
}

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isNonEmptyString(value) {
  return typeof value === "string" && Boolean(value.trim());
}

function isBoundedString(value) {
  return typeof value === "string" && value.length <= MAX_TEXT_LENGTH;
}

function isOrdinaryFile(path) {
  try {
    return lstatSync(path).isFile();
  } catch {
    return false;
  }
}

const CRC32_TABLE = Array.from({ length: 256 }, (_, index) => {
  let value = index;
  for (let bit = 0; bit < 8; bit += 1) {
    value = (value & 1) ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
  }
  return value >>> 0;
});
const PNG_ALLOWED_DEPTHS = new Map([
  [0, new Set([1, 2, 4, 8, 16])],
  [2, new Set([8, 16])],
  [3, new Set([1, 2, 4, 8])],
  [4, new Set([8, 16])],
  [6, new Set([8, 16])],
]);
const PNG_CHANNELS = new Map([[0, 1], [2, 3], [3, 1], [4, 2], [6, 4]]);
const PNG_MAX_FILE_BYTES = 25 * 1024 * 1024;
const PNG_MAX_PIXELS = 40_000_000;
const PNG_MAX_INFLATED_BYTES = 64 * 1024 * 1024;
const PNG_MAX_ROW_BYTES = 8 * 1024 * 1024;
const PNG_MAX_IDAT_CHUNKS = 4_096;
const PNG_MAX_CHUNKS = 8_192;
const PNG_MAX_SCANLINES = 100_000;

function crc32(buffer) {
  let value = 0xffffffff;
  for (const byte of buffer) value = CRC32_TABLE[(value ^ byte) & 0xff] ^ (value >>> 8);
  return (value ^ 0xffffffff) >>> 0;
}

function pngScanlineLayouts(width, height, bitsPerPixel, interlace) {
  const passes = interlace === 0
    ? [[0, 0, 1, 1]]
    : [
        [0, 0, 8, 8], [4, 0, 8, 8], [0, 4, 4, 8], [2, 0, 4, 4],
        [0, 2, 2, 4], [1, 0, 2, 2], [0, 1, 1, 2],
      ];
  return passes.flatMap(([xStart, yStart, xStep, yStep]) => {
    const columns = width <= xStart ? 0 : Math.ceil((width - xStart) / xStep);
    const rows = height <= yStart ? 0 : Math.ceil((height - yStart) / yStep);
    return columns && rows ? [{ columns, rows, rowBytes: Math.ceil((columns * bitsPerPixel) / 8) }] : [];
  });
}

function paethPredictor(left, above, upperLeft) {
  const estimate = left + above - upperLeft;
  const leftDistance = Math.abs(estimate - left);
  const aboveDistance = Math.abs(estimate - above);
  const upperLeftDistance = Math.abs(estimate - upperLeft);
  if (leftDistance <= aboveDistance && leftDistance <= upperLeftDistance) return left;
  return aboveDistance <= upperLeftDistance ? above : upperLeft;
}

function hasValidPngStructure(buffer) {
  // Slack 会把返回路径交给外部上传方，因此要限制体积，并校验 chunk、CRC、解压上限和每行 filter。
  const signature = Buffer.from("89504e470d0a1a0a", "hex");
  if (
    buffer.length < 45
    || buffer.length > PNG_MAX_FILE_BYTES
    || !buffer.subarray(0, 8).equals(signature)
  ) return false;
  let offset = 8;
  let chunkIndex = 0;
  let sawIend = false;
  let sawPlte = false;
  let idatEnded = false;
  let width;
  let height;
  let bitDepth;
  let colorType;
  let interlace;
  let paletteEntries = 0;
  const idatChunks = [];
  while (offset + 12 <= buffer.length) {
    if (chunkIndex >= PNG_MAX_CHUNKS) return false;
    const length = buffer.readUInt32BE(offset);
    const typeStart = offset + 4;
    const dataStart = offset + 8;
    const crcOffset = dataStart + length;
    const nextOffset = crcOffset + 4;
    if (nextOffset > buffer.length) return false;
    const type = buffer.subarray(typeStart, dataStart).toString("ascii");
    const data = buffer.subarray(dataStart, crcOffset);
    if (!/^[A-Za-z]{4}$/.test(type)) return false;
    if (type === "IDAT" && idatChunks.length >= PNG_MAX_IDAT_CHUNKS) return false;
    if (buffer.readUInt32BE(crcOffset) !== crc32(buffer.subarray(typeStart, crcOffset))) return false;
    if (chunkIndex === 0) {
      if (type !== "IHDR" || length !== 13 || data.readUInt32BE(0) === 0 || data.readUInt32BE(4) === 0) {
        return false;
      }
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      bitDepth = data[8];
      colorType = data[9];
      interlace = data[12];
      if (
        width * height > PNG_MAX_PIXELS
        || !PNG_ALLOWED_DEPTHS.get(colorType)?.has(bitDepth)
        || data[10] !== 0
        || data[11] !== 0
        || ![0, 1].includes(interlace)
      ) return false;
    } else if (type === "IHDR") {
      return false;
    }
    if (type === "PLTE") {
      if (sawPlte || idatChunks.length || length === 0 || length > 768 || length % 3 !== 0) return false;
      if ([0, 4].includes(colorType)) return false;
      if (colorType === 3 && length / 3 > 2 ** bitDepth) return false;
      paletteEntries = length / 3;
      sawPlte = true;
    }
    if (type === "IDAT") {
      if (idatEnded) return false;
      idatChunks.push(data);
    } else if (idatChunks.length && type !== "IEND") {
      idatEnded = true;
    }
    if (type[0] === type[0].toUpperCase() && !["IHDR", "PLTE", "IDAT", "IEND"].includes(type)) {
      return false;
    }
    if (type === "IEND") {
      if (
        length !== 0
        || idatChunks.length === 0
        || nextOffset !== buffer.length
        || (colorType === 3 && !sawPlte)
      ) return false;
      const bitsPerPixel = PNG_CHANNELS.get(colorType) * bitDepth;
      const layouts = pngScanlineLayouts(width, height, bitsPerPixel, interlace);
      const expectedLength = layouts.reduce(
        (total, layout) => total + layout.rows * (layout.rowBytes + 1),
        0,
      );
      if (
        expectedLength === 0
        || expectedLength > PNG_MAX_INFLATED_BYTES
        || layouts.some((layout) => layout.rowBytes > PNG_MAX_ROW_BYTES)
        || layouts.reduce((total, layout) => total + layout.rows, 0) > PNG_MAX_SCANLINES
      ) return false;
      try {
        const pixels = inflateSync(Buffer.concat(idatChunks), { maxOutputLength: expectedLength });
        if (pixels.length !== expectedLength) return false;
        let rowOffset = 0;
        for (const layout of layouts) {
          let previous = Buffer.alloc(layout.rowBytes);
          let decoded = Buffer.alloc(layout.rowBytes);
          const bytesPerPixel = Math.max(1, Math.ceil(bitsPerPixel / 8));
          for (let row = 0; row < layout.rows; row += 1) {
            const filter = pixels[rowOffset];
            if (filter > 4) return false;
            const filtered = pixels.subarray(rowOffset + 1, rowOffset + layout.rowBytes + 1);
            for (let index = 0; index < layout.rowBytes; index += 1) {
              const left = index >= bytesPerPixel ? decoded[index - bytesPerPixel] : 0;
              const above = previous[index] ?? 0;
              const upperLeft = index >= bytesPerPixel ? previous[index - bytesPerPixel] : 0;
              let predictor = 0;
              if (filter === 1) predictor = left;
              if (filter === 2) predictor = above;
              if (filter === 3) predictor = Math.floor((left + above) / 2);
              if (filter === 4) predictor = paethPredictor(left, above, upperLeft);
              decoded[index] = (filtered[index] + predictor) & 0xff;
            }
            if (colorType === 3) {
              const mask = (1 << bitDepth) - 1;
              for (let column = 0; column < layout.columns; column += 1) {
                const bitOffset = column * bitDepth;
                const shift = 8 - bitDepth - (bitOffset % 8);
                const paletteIndex = (decoded[Math.floor(bitOffset / 8)] >> shift) & mask;
                if (paletteIndex >= paletteEntries) return false;
              }
            }
            [previous, decoded] = [decoded, previous];
            rowOffset += layout.rowBytes + 1;
          }
        }
        if (rowOffset !== pixels.length) return false;
      } catch {
        return false;
      }
      sawIend = true;
      break;
    }
    offset = nextOffset;
    chunkIndex += 1;
  }
  return sawIend;
}

function isPngFile(path) {
  if (typeof path !== "string" || extname(path).toLowerCase() !== ".png") return false;
  const snapshot = artifactSnapshot(path);
  if (!snapshot) return false;
  if (snapshot.pngValid === undefined) snapshot.pngValid = hasValidPngStructure(snapshot.bytes);
  return snapshot.pngValid;
}

function readBoundedOrdinaryFile(path, maxBytes, expectedIdentity = null) {
  if (typeof path !== "string") return null;
  let descriptor;
  try {
    descriptor = openSync(
      path,
      constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK,
    );
    const stat = fstatSync(descriptor);
    if (!stat.isFile() || stat.nlink !== 1 || stat.size > maxBytes) return null;
    if (
      expectedIdentity
      && (
        stat.dev !== expectedIdentity.dev
        || stat.ino !== expectedIdentity.ino
        || stat.nlink !== expectedIdentity.nlink
        || stat.size !== expectedIdentity.size
        || stat.ctimeMs !== expectedIdentity.ctimeMs
        || stat.mtimeMs !== expectedIdentity.mtimeMs
      )
    ) return null;
    const buffer = Buffer.alloc(stat.size + 1);
    let offset = 0;
    while (offset < buffer.length) {
      const bytesRead = readSync(descriptor, buffer, offset, buffer.length - offset, null);
      if (bytesRead === 0) break;
      offset += bytesRead;
    }
    // inode、链接数或时间戳变化都说明读到的不是稳定单快照。
    const finalStat = fstatSync(descriptor);
    if (
      offset !== stat.size
      || finalStat.dev !== stat.dev
      || finalStat.ino !== stat.ino
      || finalStat.nlink !== stat.nlink
      || finalStat.size !== stat.size
      || finalStat.ctimeMs !== stat.ctimeMs
      || finalStat.mtimeMs !== stat.mtimeMs
    ) return null;
    return buffer.subarray(0, offset);
  } catch {
    return null;
  } finally {
    try {
      if (descriptor !== undefined) closeSync(descriptor);
    } catch {
      // 返回值已由同一 fd 的 size 与内容门禁决定；关闭失败统一视为本次读取失败风险之外的清理异常。
    }
  }
}

function artifactSnapshot(path) {
  if (typeof path !== "string") return null;
  try {
    const lexical = resolve(path);
    return artifactSnapshots.get(artifactPathAliases.get(lexical) ?? lexical) ?? null;
  } catch {
    return null;
  }
}

function isInsideRoot(path, root) {
  try {
    const child = realpathSync(path);
    const parent = realpathSync(root);
    const relation = relative(parent, child);
    return relation !== "" && !relation.startsWith("..") && !isAbsolute(relation);
  } catch {
    return false;
  }
}

function pngInflatedBudgetFromSnapshot(header) {
  try {
    const signature = Buffer.from("89504e470d0a1a0a", "hex");
    if (
      header.length < 29
      || !header.subarray(0, 8).equals(signature)
      || header.readUInt32BE(8) !== 13
      || header.subarray(12, 16).toString("ascii") !== "IHDR"
    ) return 0;
    const width = header.readUInt32BE(16);
    const height = header.readUInt32BE(20);
    const bitDepth = header[24];
    const colorType = header[25];
    const interlace = header[28];
    if (
      width === 0
      || height === 0
      || width * height > PNG_MAX_PIXELS
      || !PNG_ALLOWED_DEPTHS.get(colorType)?.has(bitDepth)
      || ![0, 1].includes(interlace)
    ) return 0;
    const bitsPerPixel = PNG_CHANNELS.get(colorType) * bitDepth;
    return pngScanlineLayouts(width, height, bitsPerPixel, interlace).reduce(
      (total, layout) => total + layout.rows * (layout.rowBytes + 1),
      0,
    );
  } catch {
    return 0;
  }
}

function preflightLocalArtifacts(document, documentPath, requireInsideDocumentRoot = false) {
  const attachments = Array.isArray(document.artifacts?.attachments)
    ? document.artifacts.attachments.filter(isObject)
    : [];
  const rawPaths = [
    ...attachments.map((artifact) => artifact.local_path),
    document.artifacts?.diagram?.svg_path,
    document.artifacts?.diagram?.png_path,
  ].filter((value) => value !== undefined && value !== null);
  const paths = new Map();
  artifactPathAliases.clear();
  for (const rawPath of rawPaths) {
    if (typeof rawPath !== "string" || !isAbsolute(rawPath)) {
      fail(JSON.stringify({ ok: false, errors: ["本地产物路径必须是绝对路径字符串"] }, null, 2), 2);
    }
    const lexicalPath = resolve(rawPath);
    let canonicalPath;
    try {
      canonicalPath = realpathSync(lexicalPath);
    } catch {
      fail(JSON.stringify({ ok: false, errors: [`本地产物不存在或不可读取：${lexicalPath}`] }, null, 2), 2);
    }
    artifactPathAliases.set(lexicalPath, canonicalPath);
    if (!paths.has(canonicalPath)) paths.set(canonicalPath, lexicalPath);
  }
  let declaredBytes = 0;
  let inflatedBytes = 0;
  const assetRoot = dirname(resolve(documentPath));
  const descriptors = [];
  artifactSnapshots.clear();
  for (const [canonicalPath, localPath] of paths) {
    if (requireInsideDocumentRoot && !isInsideRoot(localPath, assetRoot)) {
      fail(`Slack 本地产物必须位于 ReviewBrief 产物目录内：${localPath}`, 3);
    }
    let stat;
    try {
      stat = lstatSync(localPath);
    } catch {
      fail(JSON.stringify({ ok: false, errors: [`本地产物不存在或不可读取：${localPath}`] }, null, 2), 2);
    }
    if (!stat.isFile() || stat.nlink !== 1 || stat.size > PNG_MAX_FILE_BYTES) {
      fail(JSON.stringify({ ok: false, errors: [`本地产物必须是大小不超过 25 MiB 的单链接普通文件：${localPath}`] }, null, 2), 2);
    }
    declaredBytes += stat.size;
    if (declaredBytes > ARTIFACT_MAX_TOTAL_FILE_BYTES) {
      fail("全部本地产物总计不得超过 100 MiB", requireInsideDocumentRoot ? 3 : 2);
    }
    descriptors.push({ canonicalPath, localPath, stat });
  }
  for (const { canonicalPath, localPath, stat } of descriptors) {
    const bytes = readBoundedOrdinaryFile(canonicalPath, PNG_MAX_FILE_BYTES, stat);
    if (bytes === null) {
      fail(`本地产物在读取期间发生变化或不可安全读取：${localPath}`, requireInsideDocumentRoot ? 3 : 2);
    }
    const snapshot = { bytes, sha256: sha256(bytes), pngValid: undefined };
    artifactSnapshots.set(canonicalPath, snapshot);
    if (extname(localPath).toLowerCase() === ".png") {
      inflatedBytes += pngInflatedBudgetFromSnapshot(bytes);
      if (inflatedBytes > PNG_MAX_INFLATED_BYTES) {
        fail("全部 PNG 的累计解压预算不得超过 64 MiB", requireInsideDocumentRoot ? 3 : 2);
      }
    }
  }
}

function pathsReferToSameFile(first, second) {
  if (resolve(first) === resolve(second)) return true;
  try {
    if (realpathSync(first) === realpathSync(second)) return true;
    const firstStat = statSync(first);
    const secondStat = statSync(second);
    return firstStat.dev === secondStat.dev && firstStat.ino === secondStat.ino;
  } catch {
    return false;
  }
}

function assertSafeOutputPath(document, documentPath, outputPath, extraProtectedPaths = []) {
  const protectedPaths = [
    documentPath,
    ...(document.artifacts?.attachments ?? []).map((attachment) => attachment.local_path),
    document.artifacts?.diagram?.svg_path,
    document.artifacts?.diagram?.png_path,
    ...extraProtectedPaths,
  ].filter(Boolean);
  const conflict = protectedPaths.find((path) => pathsReferToSameFile(path, outputPath));
  if (conflict) fail(`--output 不能覆盖 ReviewBrief 输入或本地产物：${conflict}`, 2);
}

function validateStringArray(value, field, errors) {
  if (!Array.isArray(value)) {
    errors.push(`${field} 必须是数组`);
    return;
  }
  if (value.length > MAX_LIST_ITEMS) errors.push(`${field} 最多包含 ${MAX_LIST_ITEMS} 项`);
  if (value.some((item) => typeof item !== "string" || !item.trim())) {
    errors.push(`${field} 的每一项都必须是非空字符串`);
  }
  if (value.some((item) => typeof item === "string" && !isBoundedString(item))) {
    errors.push(`${field} 的每一项不得超过 ${MAX_TEXT_LENGTH} 个字符`);
  }
}

function containsMarkerToken(value) {
  if (typeof value === "string") {
    return /review-brief:(?:start|end)/i.test(value);
  }
  if (Array.isArray(value)) return value.some(containsMarkerToken);
  if (isObject(value)) return Object.values(value).some(containsMarkerToken);
  return false;
}

function isAllowedGitHubUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:"
      && url.hostname === "github.com"
      && !url.username
      && !url.password
      && !url.port
      && !url.search
      && !url.hash
      && /^\/user-attachments\/assets\/[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(url.pathname);
  } catch {
    return false;
  }
}

function hasVerifiedGitHubBinding(artifact, hashField, targetIdentity) {
  const localHash = artifact?.[hashField];
  const localPath = hashField === "png_hash" ? artifact?.png_path : artifact?.local_path;
  const snapshot = artifactSnapshot(localPath);
  return isAllowedGitHubUrl(artifact?.github_url)
    && /^[a-f0-9]{64}$/.test(localHash ?? "")
    && /^[a-f0-9]{64}$/.test(artifact?.github_file_hash ?? "")
    && artifact.github_file_hash === localHash
    && snapshot?.sha256 === localHash
    && artifact.github_target_identity === targetIdentity;
}

function validateAttachment(attachment, field, errors) {
  if (!isObject(attachment)) {
    errors.push(`${field} 必须是对象`);
    return;
  }
  if (!isNonEmptyString(attachment.alt_text)) errors.push(`${field}.alt_text 必须是非空字符串`);
  if (typeof attachment.alt_text === "string" && !isBoundedString(attachment.alt_text)) {
    errors.push(`${field}.alt_text 不得超过 ${MAX_TEXT_LENGTH} 个字符`);
  }
  if (attachment.local_path === undefined && attachment.github_url === undefined) {
    errors.push(`${field} 必须包含 local_path 或 github_url`);
  }
  if (attachment.local_path !== undefined) {
    if (
      typeof attachment.local_path !== "string"
      || !isBoundedString(attachment.local_path)
      || !isAbsolute(attachment.local_path)
      || !isOrdinaryFile(attachment.local_path)
    ) {
      errors.push(`${field}.local_path 必须是存在的普通文件绝对路径`);
    }
  }
  if (typeof attachment.github_url === "string" && !isBoundedString(attachment.github_url)) {
    errors.push(`${field}.github_url 不得超过 ${MAX_TEXT_LENGTH} 个字符`);
  }
  if (attachment.github_url !== undefined && !isAllowedGitHubUrl(attachment.github_url)) {
    errors.push(`${field}.github_url 必须是已验证的 GitHub HTTPS 附件 URL`);
  }
}

function attachmentLocator(attachment) {
  return attachment.local_path ?? attachment.github_url;
}

function hasVerifiedFileHash(artifact, hashField, pathField) {
  const expected = artifact?.[hashField];
  if (!/^[a-f0-9]{64}$/.test(expected ?? "")) return false;
  const localPath = artifact?.[pathField];
  const snapshot = artifactSnapshot(localPath);
  return snapshot?.sha256 === expected;
}

function verifiedPublishableImage(artifact, hashField, pathField) {
  if (artifact?.visual_review !== "passed") return false;
  const localPath = artifact[pathField];
  const expected = artifact?.[hashField];
  if (
    typeof localPath !== "string"
    || extname(localPath).toLowerCase() !== ".png"
    || !/^[a-f0-9]{64}$/.test(expected ?? "")
  ) return null;
  const snapshot = artifactSnapshot(localPath);
  if (
    snapshot === null
    || !isPngFile(localPath)
    || snapshot.sha256 !== expected
  ) return null;
  return { sha256: expected, size: snapshot.bytes.length };
}

function validateAttachmentConsistency(brief, artifacts, errors) {
  const semanticAttachments = brief.main_changes.flatMap((change) => change.attachments);
  const artifactsByLocator = new Map();
  const semanticsByLocator = new Map();
  for (const artifact of artifacts) {
    const locator = attachmentLocator(artifact);
    const entries = artifactsByLocator.get(locator) ?? [];
    entries.push(artifact);
    artifactsByLocator.set(locator, entries);
  }
  for (const attachment of semanticAttachments) {
    const locator = attachmentLocator(attachment);
    const entries = semanticsByLocator.get(locator) ?? [];
    entries.push(attachment);
    semanticsByLocator.set(locator, entries);
  }
  for (const [index, attachment] of semanticAttachments.entries()) {
    const locator = attachmentLocator(attachment);
    const matches = artifactsByLocator.get(locator) ?? [];
    if (matches.length !== 1) {
      errors.push(`main_changes 的附件 ${index} 必须在 artifacts.attachments 中恰好匹配一项`);
      continue;
    }
    const artifact = matches[0];
    if (artifact.alt_text !== attachment.alt_text) {
      errors.push(`main_changes 的附件 ${index} 与 artifacts.attachments 的 alt_text 不一致`);
    }
    if (
      attachment.github_url !== undefined
      && artifact.github_url !== attachment.github_url
    ) {
      errors.push(`main_changes 的附件 ${index} 与 artifacts.attachments 的 github_url 冲突`);
    }
  }
  for (const [index, artifact] of artifacts.entries()) {
    const locator = attachmentLocator(artifact);
    const matches = semanticsByLocator.get(locator) ?? [];
    if (matches.length !== 1) {
      errors.push(`artifacts.attachments[${index}] 必须与 main_changes 中恰好一项附件对应`);
    }
    if (
      artifact.visual_review !== undefined
      && !["passed", "failed", "skipped"].includes(artifact.visual_review)
    ) {
      errors.push(`artifacts.attachments[${index}].visual_review 状态无效`);
    }
    if (
      artifact.visual_review === "passed"
      && !hasVerifiedFileHash(artifact, "file_hash", "local_path")
    ) {
      errors.push(`artifacts.attachments[${index}].file_hash 与本地文件不匹配`);
    }
    if (
      artifact.visual_review === "passed"
      && typeof artifact.local_path === "string"
      && extname(artifact.local_path).toLowerCase() === ".png"
      && !isPngFile(artifact.local_path)
    ) {
      errors.push(`artifacts.attachments[${index}].local_path 必须是有效的 PNG 文件`);
    }
    if (
      artifact.github_url !== undefined
      && !hasVerifiedGitHubBinding(artifact, "file_hash", brief.target.identity)
    ) {
      errors.push(`artifacts.attachments[${index}] 的 GitHub URL 必须绑定当前目标与本地 file_hash`);
    }
  }
}

function validateVisibleContent(brief, errors) {
  // target.identity 是不可改写的目标标识，分支名中的 P2 等 token 不属于 Reviewer 结论。
  for (const label of findForbiddenVisibleContent(collectVisibleBriefFields(brief))) {
    errors.push(`Reviewer 可见内容不得包含${label}`);
  }
}

function validate(document) {
  const brief = getBrief(document);
  const errors = [];
  const stringArrays = ["reading_route", "review_focus", "risk_release", "related"];

  if (brief.schema_version !== 1) errors.push("schema_version 必须为 1");
  if (!isObject(brief.target)) errors.push("target 必须是对象");
  if (!isNonEmptyString(brief.target?.identity)) errors.push("target.identity 必须是非空字符串");
  if (typeof brief.target?.identity === "string" && !isBoundedString(brief.target.identity)) {
    errors.push(`target.identity 不得超过 ${MAX_TEXT_LENGTH} 个字符`);
  }
  if (!["pr", "branch", "range", "worktree"].includes(brief.target?.kind)) {
    errors.push("target.kind 必须是 pr、branch、range 或 worktree");
  }
  for (const field of ["base", "head"]) {
    if (!Object.hasOwn(brief.target ?? {}, field)) {
      errors.push(`target.${field} 必须存在`);
    } else if (brief.target[field] !== null && !isNonEmptyString(brief.target[field])) {
      errors.push(`target.${field} 必须是非空字符串或 null`);
    } else if (typeof brief.target[field] === "string" && !isBoundedString(brief.target[field])) {
      errors.push(`target.${field} 不得超过 ${MAX_TEXT_LENGTH} 个字符`);
    }
  }
  if (!["lite", "full"].includes(brief.mode)) errors.push("mode 必须是 lite 或 full");
  if (!isNonEmptyString(brief.overview)) errors.push("overview 必须是非空字符串");
  if (typeof brief.overview === "string" && !isBoundedString(brief.overview)) {
    errors.push(`overview 不得超过 ${MAX_TEXT_LENGTH} 个字符`);
  }
  for (const field of stringArrays) validateStringArray(brief[field], field, errors);

  if (!Array.isArray(brief.main_changes)) {
    errors.push("main_changes 必须是数组");
  } else {
    if (brief.main_changes.length === 0) errors.push("main_changes 至少包含一项");
    if (brief.main_changes.length > MAX_MAIN_CHANGES) {
      errors.push(`main_changes 最多包含 ${MAX_MAIN_CHANGES} 项`);
    }
    let semanticAttachmentCount = 0;
    brief.main_changes.forEach((change, index) => {
      const field = `main_changes[${index}]`;
      if (!isObject(change)) {
        errors.push(`${field} 必须是对象`);
        return;
      }
      if (!isNonEmptyString(change.title)) errors.push(`${field}.title 必须是非空字符串`);
      if (typeof change.title === "string" && !isBoundedString(change.title)) {
        errors.push(`${field}.title 不得超过 ${MAX_TEXT_LENGTH} 个字符`);
      }
      const hasDescription = isNonEmptyString(change.description);
      if (change.description !== undefined && !hasDescription) {
        errors.push(`${field}.description 存在时必须是非空字符串`);
      }
      if (hasDescription && !isBoundedString(change.description)) {
        errors.push(`${field}.description 不得超过 ${MAX_TEXT_LENGTH} 个字符`);
      }
      const points = change.points ?? [];
      if (!Array.isArray(points)) {
        errors.push(`${field}.points 必须是数组`);
      } else {
        if (points.length > MAX_CHANGE_POINTS) {
          errors.push(`${field}.points 最多包含 ${MAX_CHANGE_POINTS} 项`);
        }
        points.forEach((point, pointIndex) => {
          const pointField = `${field}.points[${pointIndex}]`;
          if (!isObject(point)) {
            errors.push(`${pointField} 必须是对象`);
            return;
          }
          if (!isNonEmptyString(point.title)) errors.push(`${pointField}.title 必须是非空字符串`);
          if (!isNonEmptyString(point.description)) {
            errors.push(`${pointField}.description 必须是非空字符串`);
          }
          if (typeof point.title === "string" && !isBoundedString(point.title)) {
            errors.push(`${pointField}.title 不得超过 ${MAX_TEXT_LENGTH} 个字符`);
          }
          if (typeof point.description === "string" && !isBoundedString(point.description)) {
            errors.push(`${pointField}.description 不得超过 ${MAX_TEXT_LENGTH} 个字符`);
          }
        });
      }
      if (!hasDescription && (!Array.isArray(points) || points.length === 0)) {
        errors.push(`${field} 必须包含 description 或至少一个 point`);
      }
      if (brief.mode === "lite" && Array.isArray(points) && points.length > 0) {
        errors.push("Lite 的 main_changes 不使用 points");
      }
      validateStringArray(change.code_refs, `${field}.code_refs`, errors);
      if (!Array.isArray(change.attachments)) {
        errors.push(`${field}.attachments 必须是数组`);
      } else {
        semanticAttachmentCount += change.attachments.length;
        change.attachments.forEach((attachment, attachmentIndex) => {
          validateAttachment(attachment, `${field}.attachments[${attachmentIndex}]`, errors);
        });
      }
    });
    if (semanticAttachmentCount > MAX_ATTACHMENTS) {
      errors.push(`main_changes.attachments 合计最多包含 ${MAX_ATTACHMENTS} 项`);
    }
  }

  if (!isObject(document.artifacts)) {
    errors.push("artifacts 必须是对象");
  } else if (!Array.isArray(document.artifacts.attachments)) {
    errors.push("artifacts.attachments 必须是数组");
  } else {
    if (document.artifacts.attachments.length > MAX_ATTACHMENTS) {
      errors.push(`artifacts.attachments 最多包含 ${MAX_ATTACHMENTS} 项`);
    }
    document.artifacts.attachments.forEach((attachment, index) => {
      validateAttachment(attachment, `artifacts.attachments[${index}]`, errors);
    });
    if (
      Array.isArray(brief.main_changes)
      && brief.main_changes.every((change) => (
        isObject(change)
        && Array.isArray(change.attachments)
        && change.attachments.every(isObject)
      ))
      && document.artifacts.attachments.every(isObject)
    ) {
      validateAttachmentConsistency(brief, document.artifacts.attachments, errors);
    }
  }

  if (brief.mode === "lite" && brief.reading_route?.length !== 0) {
    errors.push("Lite 的 reading_route 必须为空");
  }
  if (
    brief.mode === "full" &&
    (!Array.isArray(brief.reading_route) || brief.reading_route.length < 3 || brief.reading_route.length > 7)
  ) {
    errors.push("Full 的 reading_route 必须包含 3–7 步");
  }

  if (brief.diagram === null) {
    if (document.artifacts?.diagram !== null) errors.push("diagram 为空时 artifacts.diagram 必须为 null");
  } else if (!isObject(brief.diagram)) {
    errors.push("diagram 必须为 null 或对象");
  } else {
    if (!["sequence", "state", "data-flow", "architecture"].includes(brief.diagram.type)) {
      errors.push("diagram.type 不受支持");
    }
    if (!isNonEmptyString(brief.diagram.alt_text)) errors.push("diagram.alt_text 必须是非空字符串");
    if (typeof brief.diagram.alt_text === "string" && !isBoundedString(brief.diagram.alt_text)) {
      errors.push(`diagram.alt_text 不得超过 ${MAX_TEXT_LENGTH} 个字符`);
    }
    const sourceHashValid = /^[a-f0-9]{64}$/.test(brief.diagram.source_hash ?? "");
    if (!sourceHashValid) {
      errors.push("diagram.source_hash 必须是 64 位小写 SHA-256");
    }
    const artifact = document.artifacts?.diagram;
    if (!isObject(artifact)) {
      errors.push("存在 diagram 时 artifacts.diagram 必须是对象");
    } else {
      for (const field of ["svg_path", "png_path"]) {
        if (
          typeof artifact[field] !== "string"
          || !isAbsolute(artifact[field])
          || !isOrdinaryFile(artifact[field])
        ) {
          errors.push(`artifacts.diagram.${field} 必须是存在的普通文件绝对路径`);
        }
      }
      if (sourceHashValid && isOrdinaryFile(artifact.svg_path)) {
        if (lstatSync(artifact.svg_path).size > PNG_MAX_FILE_BYTES) {
          errors.push("artifacts.diagram.svg_path 不得超过 25 MiB");
        } else {
          try {
            const svg = artifactSnapshot(artifact.svg_path);
            if (!svg || svg.sha256 !== brief.diagram.source_hash) {
              errors.push("diagram.source_hash 与 artifacts.diagram.svg_path 的实际内容不匹配");
            }
          } catch {
            errors.push("artifacts.diagram.svg_path 必须是可读取的普通文件");
          }
        }
      }
      if (isOrdinaryFile(artifact.png_path) && !isPngFile(artifact.png_path)) {
        errors.push("artifacts.diagram.png_path 必须是有效的 PNG 文件");
      }
      if (
        artifact.visual_review === "passed"
        && !hasVerifiedFileHash(artifact, "png_hash", "png_path")
      ) {
        errors.push("artifacts.diagram.png_hash 与 PNG 文件不匹配");
      }
      if (!["passed", "failed", "skipped"].includes(artifact.visual_review)) {
        errors.push("artifacts.diagram.visual_review 状态无效");
      } else if (artifact.visual_review !== "passed") {
        errors.push("存在 diagram 时 artifacts.diagram.visual_review 必须为 passed");
      }
      if (artifact.github_url !== undefined && !isAllowedGitHubUrl(artifact.github_url)) {
        errors.push("artifacts.diagram.github_url 必须是已验证的 GitHub HTTPS 附件 URL");
      }
      if (
        artifact.github_url !== undefined
        && !hasVerifiedGitHubBinding(artifact, "png_hash", brief.target.identity)
      ) {
        errors.push("artifacts.diagram 的 GitHub URL 必须绑定当前目标与本地 png_hash");
      }
    }
  }

  if (containsMarkerToken(brief)) errors.push("Brief 语义字段不得包含 review-brief marker");
  validateVisibleContent(brief, errors);
  if (!/^[a-f0-9]{64}$/.test(brief.content_hash ?? "")) {
    errors.push("content_hash 必须是 64 位小写 SHA-256");
  } else {
    const expected = computeHash(brief);
    if (brief.content_hash !== expected) errors.push(`content_hash 不匹配，应为 ${expected}`);
  }

  return { brief, errors };
}

function writeTextAtomically(path, content, expectedSource = null) {
  const temporary = join(dirname(path), `.${basename(path)}.${process.pid}.${randomUUID()}.tmp`);
  let descriptor;
  try {
    descriptor = openSync(temporary, "wx", 0o600);
    writeFileSync(descriptor, content, "utf8");
    closeSync(descriptor);
    descriptor = undefined;
    if (expectedSource) {
      const current = readBoundedOrdinaryFile(
        path,
        JSON_MAX_FILE_BYTES,
        expectedSource.identity,
      );
      if (!current || sha256(current) !== expectedSource.sha256) {
        throw new Error("ReviewBrief JSON 在 finalize 写入前已被其他进程修改");
      }
    }
    renameSync(temporary, path);
  } catch (error) {
    if (descriptor !== undefined) closeSync(descriptor);
    try {
      unlinkSync(temporary);
    } catch {
      // 临时文件可能尚未创建或已经完成 rename，无需掩盖原错误。
    }
    throw error;
  }
}

function writeDocumentAtomically(path, document, expectedSource) {
  writeTextAtomically(path, `${JSON.stringify(document, null, 2)}\n`, expectedSource);
}

function parseOptions(args) {
  const options = {};
  for (let index = 0; index < args.length; index += 1) {
    const option = args[index];
    if (option === "--require-diagram") {
      options.requireDiagram = true;
      continue;
    }
    if (option === "--require-image") {
      options.requireImage = true;
      continue;
    }
    if (!["--output", "--existing-body", "--adopt", "--target-url", "--github-bindings"].includes(option)) {
      fail(`未知参数：${option}`, 2);
    }
    const value = args[index + 1];
    if (!value || value.startsWith("--")) fail(`${option} 缺少值`, 2);
    index += 1;
    if (option === "--output") options.output = value;
    if (option === "--existing-body") options.existingBody = value;
    if (option === "--adopt") options.adopt = value;
    if (option === "--target-url") options.targetUrl = value;
    if (option === "--github-bindings") options.githubBindings = value;
  }
  if (options.adopt && !["append", "replace"].includes(options.adopt)) {
    fail("--adopt 只能是 append 或 replace", 2);
  }
  return options;
}

function validateCommandOptions(command, options) {
  if (command === "render-github") {
    if (options.targetUrl) fail("render-github 不支持 --target-url", 2);
    if (options.adopt && !options.existingBody) {
      fail("--adopt 只能与 --existing-body 一起使用", 2);
    }
    return;
  }
  if (
    options.existingBody
    || options.adopt
    || options.requireDiagram
    || options.requireImage
    || options.githubBindings
  ) {
    fail("render-slack 不支持 GitHub Body 参数", 2);
  }
}

function validatedHttpsUrl(value, label, allowedGitHubHost = false) {
  if (!value) return null;
  let url;
  try {
    url = new URL(value);
  } catch {
    fail(`${label} 必须是有效 URL`, 3);
  }
  if (url.protocol !== "https:") fail(`${label} 必须使用 HTTPS`, 3);
  if (
    allowedGitHubHost &&
    url.hostname !== "github.com" &&
    !url.hostname.endsWith(".githubusercontent.com")
  ) {
    fail(`${label} 必须是已验证的 GitHub 附件 URL`, 3);
  }
  return url.toString();
}

function validatedSlackTargetUrl(target, value) {
  const normalized = validatedHttpsUrl(value, "--target-url");
  if (!normalized) return null;
  const url = new URL(normalized);
  if (url.username || url.password || url.port || url.search || url.hash) {
    fail("--target-url 不得包含 credentials、非默认端口、query 或 fragment", 3);
  }
  if (target.kind !== "pr") return normalized;
  const pathMatch = url.pathname.match(/^\/([^/]+)\/([^/]+)\/pull\/(\d+)\/?$/);
  let identityMatch = target.identity.match(/^([^/\s]+)\/([^#\s]+)#(\d+)$/);
  if (!identityMatch) {
    try {
      const identityUrl = new URL(target.identity);
      if (identityUrl.hostname === "github.com") {
        identityMatch = identityUrl.pathname.match(/^\/([^/]+)\/([^/]+)\/pull\/(\d+)\/?$/);
      }
    } catch {
      // 继续由下方统一错误说明不支持的 PR 目标身份格式。
    }
  }
  if (url.hostname !== "github.com" || !pathMatch || !identityMatch) {
    fail("PR 的 --target-url 必须与 owner/repo#number 或 GitHub PR URL 格式的 target.identity 对应", 3);
  }
  const [, urlOwner, urlRepo, urlNumber] = pathMatch;
  const [, identityOwner, identityRepo, identityNumber] = identityMatch;
  if (
    urlOwner.toLowerCase() !== identityOwner.toLowerCase()
    || urlRepo.toLowerCase() !== identityRepo.toLowerCase()
    || urlNumber !== identityNumber
  ) {
    fail("--target-url 与 ReviewBrief 的 PR 目标身份不一致", 3);
  }
  return normalized;
}

function escapeGitHubCharacters(value) {
  const entities = new Map([
    ["&", "&amp;"], ["<", "&lt;"], [">", "&gt;"], ["@", "&#64;"], ["#", "&#35;"],
    ["!", "&#33;"], ["[", "&#91;"], ["]", "&#93;"], ["(", "&#40;"], [")", "&#41;"],
    ["\\", "&#92;"], ["`", "&#96;"], ["*", "&#42;"], ["_", "&#95;"], ["~", "&#126;"],
    ["|", "&#124;"], ["-", "&#45;"], ["+", "&#43;"], ["=", "&#61;"], [".", "&#46;"],
  ]);
  return [...value].map((character) => entities.get(character) ?? character).join("");
}

function escapeGitHubText(value) {
  const plainText = normalizeString(value).replace(/\s*\n+\s*/g, " ");
  return escapeGitHubCharacters(plainText);
}

function githubInlineCode(value) {
  const code = value.replace(/\r\n?/g, "\n").replace(/\s*\n+\s*/g, " ");
  const longestRun = Math.max(0, ...(code.match(/`+/g) ?? []).map((run) => run.length));
  const fence = "`".repeat(longestRun + 1);
  const needsPadding = code.startsWith("`") || code.endsWith("`")
    || code.startsWith(" ") || code.endsWith(" ");
  return needsPadding ? `${fence} ${code} ${fence}` : `${fence}${code}${fence}`;
}

function renderGitHubInlineText(value) {
  const plainText = normalizeString(value).replace(/\s*\n+\s*/g, " ");
  const pattern = /`([^`\n]+)`/g;
  let cursor = 0;
  let rendered = "";
  for (const match of plainText.matchAll(pattern)) {
    rendered += escapeGitHubCharacters(plainText.slice(cursor, match.index));
    rendered += githubInlineCode(match[1]);
    cursor = match.index + match[0].length;
  }
  rendered += escapeGitHubCharacters(plainText.slice(cursor));
  return rendered;
}

function renderGitHubParagraphs(value) {
  return normalizeString(value)
    .split(/\n\s*\n+/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean)
    .map(renderGitHubInlineText)
    .join("\n\n");
}

function escapeAltText(value) {
  return escapeGitHubText(value).replaceAll("\n", " ");
}

function markdownImageDestination(value) {
  const safe = value.replace(/[\s\\()<>\[\]!]/gu, (character) => (
    [...Buffer.from(character)].map((byte) => `%${byte.toString(16).toUpperCase().padStart(2, "0")}`).join("")
  ));
  return `<${safe}>`;
}

function formatRoute(value) {
  const [reference, ...rest] = normalizeString(value).split(" — ");
  if (rest.length === 0) return normalizeString(value);
  const plainReference = reference.startsWith("`") && reference.endsWith("`")
    ? reference.slice(1, -1)
    : reference;
  return `${plainReference} — ${rest.join(" — ")}`;
}

function formatGitHubRoute(value) {
  const [reference, ...rest] = normalizeString(value).split(" — ");
  if (rest.length === 0) return renderGitHubInlineText(value);
  const plainReference = reference.startsWith("`") && reference.endsWith("`")
    ? reference.slice(1, -1)
    : reference;
  return `${githubInlineCode(plainReference)} — ${renderGitHubInlineText(rest.join(" — "))}`;
}

function escapeSlackText(value) {
  return normalizeString(value)
    .replace(/\s*\n+\s*/g, " ")
    .replace(/`([^`\n]+)`/g, "$1")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("*", "＊")
    .replaceAll("_", "＿")
    .replaceAll("~", "～")
    .replaceAll("`", "｀");
}

function clippedSlackText(value, maxChars) {
  const escaped = escapeSlackText(value);
  return escaped.length <= maxChars ? escaped : `${escaped.slice(0, maxChars - 1)}…`;
}

function renderStringSection(title, values, formatter = renderGitHubInlineText) {
  if (!values.length) return "";
  return `## ${title}\n\n${values.map((value) => `- ${formatter(value)}`).join("\n")}`;
}

function artifactAttachmentMap(document) {
  return new Map(
    (document.artifacts.attachments ?? [])
      .map((attachment) => [attachmentLocator(attachment), attachment]),
  );
}

function loadGitHubBindings(path, targetIdentity) {
  if (!path) return new Map();
  let manifest;
  try {
    const stat = lstatSync(path);
    if (!stat.isFile()) fail("GitHub 附件绑定清单必须是普通文件", 3);
    if (stat.nlink !== 1) fail("GitHub 附件绑定清单不得是硬链接", 3);
    if (stat.size > GITHUB_BINDINGS_MAX_FILE_BYTES) {
      fail("GitHub 附件绑定清单不得超过 1 MiB", 3);
    }
    const bytes = readBoundedOrdinaryFile(path, GITHUB_BINDINGS_MAX_FILE_BYTES, stat);
    if (!bytes) fail("GitHub 附件绑定清单在读取期间发生变化或不可安全读取", 3);
    manifest = JSON.parse(bytes.toString("utf8"));
  } catch (error) {
    fail(`无法读取 GitHub 附件绑定清单：${error.message}`, 3);
  }
  if (!isObject(manifest) || manifest.schema_version !== 1) {
    fail("GitHub 附件绑定清单 schema_version 必须为 1", 3);
  }
  if (manifest.target_identity !== targetIdentity) {
    fail("GitHub 附件绑定清单与 ReviewBrief 目标不一致", 3);
  }
  if (!Array.isArray(manifest.assets) || manifest.assets.length > MAX_ATTACHMENTS + 1) {
    fail(`GitHub 附件绑定清单 assets 必须是最多 ${MAX_ATTACHMENTS + 1} 项的数组`, 3);
  }
  const bindings = new Map();
  for (const [index, asset] of manifest.assets.entries()) {
    if (
      !isObject(asset)
      || !isAllowedGitHubUrl(asset.url)
      || !/^[a-f0-9]{64}$/.test(asset.sha256 ?? "")
    ) {
      fail(`GitHub 附件绑定清单 assets[${index}] 必须包含合法的 url 与 sha256`, 3);
    }
    if (bindings.has(asset.url)) fail(`GitHub 附件绑定清单包含重复 URL：${asset.url}`, 3);
    bindings.set(asset.url, asset.sha256);
  }
  return bindings;
}

function resolveGitHubBindingsPath(path, documentPath) {
  if (!path) return null;
  const lexicalPath = resolve(path);
  let canonicalPath;
  try {
    if (lstatSync(lexicalPath).isSymbolicLink()) {
      fail("GitHub 附件绑定清单不得是 symlink", 3);
    }
    canonicalPath = realpathSync(lexicalPath);
  } catch (error) {
    fail(`无法解析 GitHub 附件绑定清单：${error.message}`, 3);
  }
  if (
    pathsReferToSameFile(canonicalPath, documentPath)
    || isInsideRoot(canonicalPath, dirname(resolve(documentPath)))
  ) {
    fail("GitHub 附件绑定清单必须位于候选 ReviewBrief 产物目录之外", 3);
  }
  return canonicalPath;
}

function hasTrustedGitHubBinding(artifact, hashField, bindings) {
  return bindings.get(artifact?.github_url) === artifact?.[hashField];
}

function githubImage(attachment, artifactMap, label, targetIdentity, bindings) {
  const artifact = artifactMap.get(attachmentLocator(attachment));
  if (!verifiedPublishableImage(artifact, "file_hash", "local_path")) return null;
  if (!hasVerifiedGitHubBinding(artifact, "file_hash", targetIdentity)) return null;
  if (!hasTrustedGitHubBinding(artifact, "file_hash", bindings)) return null;
  const url = validatedHttpsUrl(artifact?.github_url, `${label}.github_url`, true);
  if (!url) return null;
  return `![${escapeAltText(attachment.alt_text)}](${markdownImageDestination(url)})`;
}

function renderGitHubInner(document, requireDiagram, requireImage, bindings) {
  const brief = document.review_brief;
  const artifactMap = artifactAttachmentMap(document);
  let attachmentImageCount = 0;
  if (requireDiagram && brief.diagram === null) {
    fail("当前 Brief 被要求必须包含图，但语义模型没有 diagram", 3);
  }
  const changeBlocks = brief.main_changes.map((change, index) => {
    const images = change.attachments
      .map((attachment, attachmentIndex) => githubImage(
        attachment,
        artifactMap,
        `main_changes[${index}].attachments[${attachmentIndex}]`,
        brief.target.identity,
        bindings,
      ))
      .filter(Boolean);
    attachmentImageCount += images.length;
    if (brief.mode === "lite") {
      return [
        `- **${renderGitHubInlineText(change.title)}**：${renderGitHubInlineText(change.description)}`,
        ...(images.length ? ["", ...images] : []),
      ].join("\n");
    }
    const block = [`### ${renderGitHubInlineText(change.title)}`];
    if (isNonEmptyString(change.description)) {
      block.push("", renderGitHubParagraphs(change.description));
    }
    if (change.points?.length) {
      block.push("", ...change.points.map((point) => (
        `- **${renderGitHubInlineText(point.title)}**：${renderGitHubInlineText(point.description)}`
      )));
    }
    if (images.length) block.push("", ...images);
    return block.join("\n");
  });

  let diagramMarkdown = null;
  if (brief.diagram !== null) {
    const artifact = document.artifacts.diagram;
    if (
      verifiedPublishableImage(artifact, "png_hash", "png_path")
      && hasVerifiedGitHubBinding(artifact, "png_hash", brief.target.identity)
      && hasTrustedGitHubBinding(artifact, "png_hash", bindings)
    ) {
      const url = validatedHttpsUrl(artifact.github_url, "artifacts.diagram.github_url", true);
      if (url) diagramMarkdown = `![${escapeAltText(brief.diagram.alt_text)}](${markdownImageDestination(url)})`;
    }
    if (requireDiagram && !diagramMarkdown) {
      fail("当前 Brief 需要图，但缺少通过视觉检查且可用于 GitHub 的附件 URL", 3);
    }
  }
  if (requireImage && attachmentImageCount === 0 && !diagramMarkdown) {
    fail("当前 Brief 被要求必须包含图片，但没有通过门禁且可用于 GitHub 的附件 URL", 3);
  }

  const sections = [
    `## 概要\n\n${renderGitHubParagraphs(brief.overview)}`,
    `## 主要变化\n\n${changeBlocks.join("\n\n")}`,
  ];
  if (diagramMarkdown) sections.push(`## 变更导览图\n\n${diagramMarkdown}`);
  sections.push(...[
    renderStringSection("推荐阅读路线", brief.reading_route, formatGitHubRoute),
    renderStringSection("Review 重点", brief.review_focus),
    renderStringSection("风险与发布", brief.risk_release),
    renderStringSection("关联资料", brief.related),
  ].filter(Boolean));
  return { inner: sections.join("\n\n"), diagramIncluded: Boolean(diagramMarkdown) };
}

function buildGitHubBlock(document, requireDiagram, requireImage, bindings) {
  const { inner, diagramIncluded } = renderGitHubInner(document, requireDiagram, requireImage, bindings);
  const renderHash = sha256(Buffer.from(inner, "utf8"));
  const marker = `${START_PREFIX} schema=1 content=${document.review_brief.content_hash} render=${renderHash} -->`;
  return {
    block: `${marker}\n${inner}\n${END_MARKER}`,
    diagramIncluded,
    renderHash,
  };
}

function mergeGitHubBody(block, existingBodyPath, adopt) {
  if (!existingBodyPath) return { action: "create", body: `${block}\n` };
  let existing;
  try {
    const stat = lstatSync(existingBodyPath);
    if (!stat.isFile()) fail("现有 PR Body 必须是普通文件", 3);
    if (stat.size > JSON_MAX_FILE_BYTES) fail("现有 PR Body 不得超过 4 MiB", 3);
    const bytes = readBoundedOrdinaryFile(existingBodyPath, JSON_MAX_FILE_BYTES, stat);
    if (!bytes) fail("现有 PR Body 在读取期间发生变化或不可安全读取", 3);
    existing = bytes.toString("utf8");
  } catch (error) {
    fail(`无法读取现有 PR Body：${error.message}`, 3);
  }

  const starts = [...existing.matchAll(/<!-- review-brief:start schema=1 content=[a-f0-9]{64} render=[a-f0-9]{64} -->/g)];
  const ends = [...existing.matchAll(/<!-- review-brief:end -->/g)];
  const hasReservedToken = existing.includes("review-brief:start") || existing.includes("review-brief:end");
  if (starts.length === 0 && ends.length === 0) {
    if (hasReservedToken) fail("现有 PR Body 的 review-brief marker 格式无效或残缺", 3);
    if (!existing.trim()) return { action: "create", body: `${block}\n` };
    if (!adopt) fail("现有 PR Body 没有 marker；必须显式指定 --adopt append|replace", 3);
    if (adopt === "append") {
      // 作者正文必须保持逐字不变；只补足自动区域前所需的分隔换行。
      const separator = existing.endsWith("\n\n") ? "" : existing.endsWith("\n") ? "\n" : "\n\n";
      return { action: "append", body: `${existing}${separator}${block}\n` };
    }
    return { action: "replace-existing", body: `${block}\n` };
  }
  const exactTokenCount = starts.length + ends.length;
  const reservedTokenCount = (existing.match(/review-brief:(?:start|end)/g) ?? []).length;
  if (
    starts.length !== 1
    || ends.length !== 1
    || starts[0].index > ends[0].index
    || exactTokenCount !== reservedTokenCount
  ) {
    fail("现有 PR Body 的 review-brief marker 残缺、重复或顺序错误", 3);
  }

  // 只替换受控区域，marker 之外的人工正文逐字保留。
  const startIndex = starts[0].index;
  const endIndex = ends[0].index + ends[0][0].length;
  const body = `${existing.slice(0, startIndex)}${block}${existing.slice(endIndex)}`;
  return { action: body === existing ? "noop" : "replace", body };
}

function renderGitHub(document, options, documentPath) {
  if (!options.output) fail("render-github 必须提供 --output", 2);
  if (options.targetUrl) fail("render-github 不支持 --target-url", 2);
  if (options.adopt && !options.existingBody) {
    fail("--adopt 只能与 --existing-body 一起使用", 2);
  }
  const bindingsPath = resolveGitHubBindingsPath(options.githubBindings, documentPath);
  assertSafeOutputPath(document, documentPath, options.output, [bindingsPath]);
  const bindings = loadGitHubBindings(bindingsPath, document.review_brief.target.identity);
  const { block, diagramIncluded, renderHash } = buildGitHubBlock(
    document,
    options.requireDiagram,
    options.requireImage,
    bindings,
  );
  const merged = mergeGitHubBody(block, options.existingBody, options.adopt);
  writeTextAtomically(options.output, merged.body);
  process.stdout.write(`${JSON.stringify({
    ok: true,
    channel: "github",
    action: merged.action,
    content_hash: document.review_brief.content_hash,
    render_hash: renderHash,
    output: options.output,
    diagram_included: diagramIncluded,
  })}\n`);
}

function collectSlackCandidateDescriptors(document, selectedChanges, assetRoot) {
  const candidates = new Map();
  const artifactMap = new Map(
    (Array.isArray(document.artifacts?.attachments) ? document.artifacts.attachments : [])
      .filter(isObject)
      .map((attachment) => [attachmentLocator(attachment), attachment]),
  );
  const addCandidate = (artifact, hashField, pathField) => {
    const path = artifact?.[pathField];
    const expected = artifact?.[hashField];
    if (
      artifact?.visual_review !== "passed"
      || typeof path !== "string"
      || extname(path).toLowerCase() !== ".png"
      || !/^[a-f0-9]{64}$/.test(expected ?? "")
    ) return;
    if (!isInsideRoot(path, assetRoot)) {
      fail(`Slack 待上传 PNG 必须位于 ReviewBrief 产物目录内：${path}`, 3);
    }
    const normalizedPath = artifactPathAliases.get(resolve(path));
    if (!normalizedPath) fail("Slack 待上传文件缺少规范路径身份", 3);
    const existing = candidates.get(normalizedPath);
    if (existing && existing.expected !== expected) {
      fail(`Slack 同一文件存在冲突的审核 hash：${normalizedPath}`, 3);
    }
    if (!existing) {
      candidates.set(normalizedPath, {
        artifact,
        hashField,
        pathField,
        expected,
        outputPath: resolve(path),
      });
    }
  };
  for (const change of selectedChanges) {
    for (const attachment of Array.isArray(change.attachments) ? change.attachments : []) {
      if (!isObject(attachment)) continue;
      const artifact = artifactMap.get(attachmentLocator(attachment));
      addCandidate(artifact, "file_hash", "local_path");
    }
  }
  if (document.review_brief?.diagram !== null && isObject(document.artifacts?.diagram)) {
    const diagram = document.artifacts.diagram;
    addCandidate(diagram, "png_hash", "png_path");
  }
  if (candidates.size > SLACK_MAX_FILES) {
    fail(`Slack 校验上传每次最多包含 ${SLACK_MAX_FILES} 个文件`, 3);
  }
  let declaredBytes = 0;
  for (const candidate of candidates.values()) {
    const snapshot = artifactSnapshot(candidate.artifact?.[candidate.pathField]);
    if (!snapshot) fail("Slack 待上传文件缺少预检快照", 3);
    declaredBytes += snapshot.bytes.length;
  }
  if (declaredBytes > SLACK_MAX_TOTAL_FILE_BYTES) {
    fail("Slack 校验上传文件总计不得超过 100 MiB", 3);
  }
  return candidates;
}

function collectSlackFiles(candidates) {
  const files = [];
  let verifiedBytes = 0;
  for (const candidate of candidates.values()) {
    const verified = verifiedPublishableImage(
      candidate.artifact,
      candidate.hashField,
      candidate.pathField,
    );
    if (!verified) continue;
    verifiedBytes += verified.size;
    if (verifiedBytes > SLACK_MAX_TOTAL_FILE_BYTES) {
      fail("Slack 校验上传文件总计不得超过 100 MiB", 3);
    }
    files.push({ path: candidate.outputPath, sha256: verified.sha256 });
  }
  return files;
}

function preflightSlackArtifacts(document, documentPath) {
  const assetRoot = dirname(resolve(documentPath));
  // 先做所有命令共享的文件与解压预算，再进入会读取完整文件的 schema 校验。
  preflightLocalArtifacts(document, documentPath, true);
  const selectedChanges = Array.isArray(document.review_brief?.main_changes)
    ? document.review_brief.main_changes.slice(0, 3).filter(isObject)
    : [];
  return collectSlackCandidateDescriptors(document, selectedChanges, assetRoot);
}

function renderSlack(document, options, documentPath, slackCandidates) {
  if (!options.output) fail("render-slack 必须提供 --output", 2);
  assertSafeOutputPath(document, documentPath, options.output);
  if (
    options.existingBody
    || options.adopt
    || options.requireDiagram
    || options.requireImage
    || options.githubBindings
  ) {
    fail("render-slack 不支持 GitHub Body 参数", 2);
  }
  const brief = document.review_brief;
  validatedSlackTargetUrl(brief.target, options.targetUrl);
  const selectedChanges = brief.main_changes.slice(0, 3);
  const lines = ["*Review Brief*"];
  lines.push("", clippedSlackText(brief.overview, 1_000), "", "*主要变化*");
  for (const change of selectedChanges) {
    const details = [
      ...(isNonEmptyString(change.description) ? [change.description] : []),
      ...(change.points ?? []).map((point) => `${point.title}：${point.description}`),
    ].join("；");
    lines.push(`- *${clippedSlackText(change.title, 100)}*：${clippedSlackText(details, 350)}`);
  }
  if (brief.diagram !== null) {
    lines.push("", `*变更导览图*：${clippedSlackText(brief.diagram.alt_text, 200)}`);
  }
  const guidance = [...brief.reading_route, ...brief.review_focus].slice(0, 3);
  if (guidance.length) {
    lines.push("", "*Review 导览*");
    guidance.forEach((item) => lines.push(`- ${clippedSlackText(formatRoute(item), 200)}`));
  }
  // context 只接受文本对象；按完整行分块，避免切断链接或格式标记。
  const blocks = [];
  let contextText = "";
  for (const line of lines) {
    if (line.length > 3_000) fail("Slack context 单行不得超过 3000 字符", 3);
    const next = contextText ? `${contextText}\n${line}` : line;
    if (next.length > 3_000) {
      blocks.push({ type: "context", elements: [{ type: "mrkdwn", text: contextText, verbatim: true }] });
      contextText = line;
    } else {
      contextText = next;
    }
  }
  if (contextText) blocks.push({ type: "context", elements: [{ type: "mrkdwn", text: contextText, verbatim: true }] });
  const markdown = `${lines.join("\n")}\n`;
  if (markdown.length > SLACK_MAX_MESSAGE_CHARS) {
    fail(`Slack 精简消息不得超过 ${SLACK_MAX_MESSAGE_CHARS} 个字符`, 3);
  }
  const files = collectSlackFiles(slackCandidates);
  // Slack 的渲染身份同时覆盖消息正文和待上传文件内容，避免只改图片却误判为 no-op。
  const fileHashes = files.map((file) => ({
    name: basename(file.path),
    hash: file.sha256,
  }));
  const renderHash = sha256(Buffer.from(JSON.stringify({ markdown, blocks, fileHashes }), "utf8"));
  writeTextAtomically(options.output, markdown);
  process.stdout.write(`${JSON.stringify({
    ok: true,
    channel: "slack",
    blocks,
    content_hash: brief.content_hash,
    render_hash: renderHash,
    output: options.output,
    files,
  })}\n`);
}

const [command, path, ...optionArgs] = process.argv.slice(2);
if (command === "--help" || command === "-h") {
  usage();
  process.exit(0);
}
const commands = ["finalize", "check", "hash", "render-github", "render-slack"];
if (!command || !path || !commands.includes(command)) {
  usage();
  process.exit(2);
}

let options = null;
if (["finalize", "check", "hash"].includes(command)) {
  if (optionArgs.length) fail(`${command} 不接受额外参数`, 2);
} else {
  options = parseOptions(optionArgs);
  if (!options.output) fail(`${command} 必须提供 --output`, 2);
  validateCommandOptions(command, options);
}

const { document, source: documentSource } = loadDocument(path);
assertTraversalBounds(document);
assertArtifactCollectionBounds(document);
const brief = getBrief(document);
if (command === "render-github" && options.githubBindings) {
  options.githubBindings = resolveGitHubBindingsPath(options.githubBindings, path);
}
if (!["hash", "render-slack"].includes(command)) {
  preflightLocalArtifacts(document, path);
}
if (command === "finalize") {
  brief.content_hash = computeHash(brief);
  const { errors } = validate(document);
  if (errors.length) fail(JSON.stringify({ ok: false, errors }, null, 2), 2);
  try {
    writeDocumentAtomically(path, document, documentSource);
  } catch (error) {
    fail(`无法安全写入 ReviewBrief JSON：${error.message}`, 2);
  }
  process.stdout.write(`${JSON.stringify({ ok: true, content_hash: brief.content_hash })}\n`);
} else if (command === "check") {
  const { errors } = validate(document);
  if (errors.length) fail(JSON.stringify({ ok: false, errors }, null, 2), 2);
  process.stdout.write(`${JSON.stringify({ ok: true, content_hash: brief.content_hash })}\n`);
} else if (command === "hash") {
  process.stdout.write(`${computeHash(brief)}\n`);
} else {
  const slackCandidates = command === "render-slack"
    ? preflightSlackArtifacts(document, path)
    : null;
  const { errors } = validate(document);
  if (errors.length) fail(JSON.stringify({ ok: false, errors }, null, 2), 2);
  if (command === "render-github") renderGitHub(document, options, path);
  if (command === "render-slack") renderSlack(document, options, path, slackCandidates);
}

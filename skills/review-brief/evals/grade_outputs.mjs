#!/usr/bin/env node

import { createHash, randomUUID } from "node:crypto";
import {
  closeSync,
  constants,
  existsSync,
  fstatSync,
  lstatSync,
  mkdtempSync,
  openSync,
  opendirSync,
  readFileSync,
  readSync,
  realpathSync,
  renameSync,
  rmSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { extname, isAbsolute, relative, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import {
  collectVisibleBriefFields,
  collectVisibleBriefStrings,
  findForbiddenVisibleContent,
} from "../scripts/review-brief-policy.mjs";

const [evalIdRaw, outputsRaw, skillRootRaw, traceRaw] = process.argv.slice(2);
const evalId = Number(evalIdRaw);
const outputs = resolve(outputsRaw ?? "");
const skillRoot = resolve(skillRootRaw ?? new URL("..", import.meta.url).pathname);
const evalConfig = JSON.parse(readFileSync(resolve(skillRoot, "evals/evals.json"), "utf8"));
const evalCase = evalConfig.evals.find((item) => item.id === evalId);
if (!evalCase || !outputsRaw) {
  process.stderr.write("用法：node evals/grade_outputs.mjs <eval-id> <outputs-dir> [skill-root] [trusted-trace.json]\n");
  process.exit(2);
}
let outputsRoot;
try {
  if (lstatSync(outputs).isSymbolicLink()) throw new Error("输出目录本身不得是 symlink");
  outputsRoot = realpathSync(outputs);
  if (!lstatSync(outputsRoot).isDirectory()) throw new Error("不是目录");
} catch (error) {
  process.stderr.write(`输出目录不可用：${outputs}（${error.message}）\n`);
  process.exit(2);
}

const expectations = [];
const MAX_CANDIDATE_BYTES = 4 * 1024 * 1024;
const MAX_ARTIFACT_BYTES = 25 * 1024 * 1024;
const MAX_OUTPUT_FILES = 1_000;
const MAX_OUTPUT_ENTRIES = 2_000;
const MAX_TOTAL_OUTPUT_BYTES = 100 * 1024 * 1024;
const MAX_ARTIFACT_REFERENCES = 202;
let outputResourceExceeded = false;
let safeOutputBytes = 0;
let outputScanError = null;
const add = (index, passed, evidence) => {
  expectations.push({ text: evalCase.expectations[index], passed, evidence });
};
const file = (name) => resolve(outputsRoot, name);
const isInsideOutputs = (path) => {
  if (typeof path !== "string" || !path || !isAbsolute(path)) return false;
  try {
    if (!lstatSync(path).isFile()) return false;
    const rel = relative(outputsRoot, realpathSync(path));
    return rel !== "" && !rel.startsWith("..") && !isAbsolute(rel);
  } catch {
    return false;
  }
};
// 清单保留扫描时的词法身份；realpath 只用于边界判断，不能把额外 symlink 隐藏成允许文件。
const outputRelative = (path) => relative(outputsRoot, path);
const unsafeCandidateFiles = new Set();
const candidateSnapshots = new Map();
const artifactSnapshots = new Map();
const artifactCanonicalPaths = new Map();
const outputSnapshots = new Map();
const candidateSnapshot = (name) => {
  if (candidateSnapshots.has(name)) return candidateSnapshots.get(name);
  const bytes = outputSnapshots.get(file(name)) ?? null;
  if (!bytes && existsSync(file(name))) unsafeCandidateFiles.add(name);
  if (bytes && bytes.length > MAX_CANDIDATE_BYTES) {
    unsafeCandidateFiles.add(name);
    candidateSnapshots.set(name, null);
    return null;
  }
  candidateSnapshots.set(name, bytes);
  return bytes;
};
const readBoundedFile = (path, maxBytes, expectedIdentity = null) => {
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
      // 读取结果已由 size/hash 门禁约束；关闭失败不应让 grader 丢失评分文件。
    }
  }
};
const safeOutputArtifactBytes = (path) => {
  if (typeof path !== "string" || !isAbsolute(path)) return null;
  const lexical = resolve(path);
  if (artifactSnapshots.has(lexical)) return artifactSnapshots.get(lexical);
  let bytes = null;
  try {
    const lexicalStat = lstatSync(lexical);
    if (!lexicalStat.isFile() || lexicalStat.nlink !== 1) return null;
    const normalized = realpathSync(lexical);
    const snapshot = outputSnapshots.get(normalized);
    if (snapshot && snapshot.length <= MAX_ARTIFACT_BYTES && isInsideOutputs(normalized)) {
      bytes = snapshot;
      artifactCanonicalPaths.set(lexical, normalized);
    }
  } catch {
    bytes = null;
  }
  if (bytes) artifactSnapshots.set(lexical, bytes);
  return bytes;
};
const loadTrustedTrace = () => {
  if (!traceRaw) return { trace: null, error: "缺少评测 harness 提供的可信调用轨迹" };
  if (!isAbsolute(traceRaw) || isInsideOutputs(traceRaw)) {
    return { trace: null, error: "可信调用轨迹必须是候选输出目录之外的绝对路径" };
  }
  const path = resolve(traceRaw);
  const bytes = readBoundedFile(path, 1024 * 1024);
  if (!bytes) return { trace: null, error: "可信调用轨迹不可安全读取或超过 1 MiB" };
  try {
    const trace = JSON.parse(bytes.toString("utf8"));
    const expectedRunId = process.env.REVIEW_BRIEF_EVAL_RUN_ID;
    if (
      !trace
      || typeof trace !== "object"
      || Array.isArray(trace)
      || trace.schema_version !== 2
      || trace.eval_id !== evalId
      || typeof trace.run_id !== "string"
      || !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(trace.run_id)
      || typeof trace.output_manifest_sha256 !== "string"
      || !/^[a-f0-9]{64}$/.test(trace.output_manifest_sha256)
      || !trace.capture
      || trace.capture.tool_names !== true
      || trace.capture.tool_arguments !== true
      || trace.capture.skill_activations !== true
      || trace.capture.child_agents !== true
      || trace.capture.review_activity !== true
      || !Array.isArray(trace.tool_calls)
      || !Array.isArray(trace.skill_activations)
      || !Array.isArray(trace.child_agents)
      || !Array.isArray(trace.review_activity)
      || trace.tool_calls.some((item) => (
        !item
        || typeof item.name !== "string"
        || typeof item.arguments_text !== "string"
      ))
      || trace.skill_activations.some((item) => typeof item !== "string")
      || trace.review_activity.some((item) => (
        !item
        || typeof item.kind !== "string"
        || typeof item.identifier !== "string"
      ))
      || (trace.total_steps !== undefined
        && (!Number.isSafeInteger(trace.total_steps) || trace.total_steps < 0))
    ) {
      return { trace: null, error: "可信调用轨迹结构无效" };
    }
    if (
      typeof expectedRunId !== "string"
      || !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(expectedRunId)
      || trace.run_id !== expectedRunId
    ) {
      return { trace: null, error: "可信调用轨迹 run_id 未绑定到本次 grader 调用" };
    }
    if (trace.output_manifest_sha256 !== outputManifestSha256) {
      return { trace: null, error: "可信调用轨迹与当前候选输出 manifest 不匹配" };
    }
    return { trace, error: null };
  } catch (error) {
    return { trace: null, error: `可信调用轨迹 JSON 无法解析：${error.message}` };
  }
};
const text = (name) => {
  const bytes = candidateSnapshot(name);
  return bytes ? bytes.toString("utf8") : "";
};
const jsonErrors = new Map();
const json = (name) => {
  try {
    const bytes = candidateSnapshot(name);
    if (!bytes) return null;
    return JSON.parse(bytes.toString("utf8"));
  } catch (error) {
    jsonErrors.set(name, error.message);
    return null;
  }
};
const scanOutputFiles = () => {
  const files = [];
  const directories = [outputsRoot];
  let entriesSeen = 0;
  while (directories.length && !outputResourceExceeded) {
    const directory = directories.pop();
    let handle;
    try {
      handle = opendirSync(directory);
      let entry;
      while ((entry = handle.readSync()) !== null) {
        entriesSeen += 1;
        if (entriesSeen > MAX_OUTPUT_ENTRIES) {
          outputResourceExceeded = true;
          break;
        }
        const path = resolve(directory, entry.name);
        if (entry.isDirectory()) {
          directories.push(path);
          continue;
        }
        if (entry.isSymbolicLink()) {
          outputScanError = `候选输出包含不允许的 symlink：${path}`;
          outputResourceExceeded = true;
          break;
        }
        if (!entry.isFile()) {
          outputScanError = `候选输出包含不允许的特殊节点：${path}`;
          outputResourceExceeded = true;
          break;
        }
        files.push(path);
        if (files.length > MAX_OUTPUT_FILES) {
          outputResourceExceeded = true;
          break;
        }
        if (entry.isFile()) {
          const scanned = lstatSync(path);
          if (!isInsideOutputs(path) || scanned.nlink !== 1) {
            outputScanError = `候选输出文件不是安全的单链接普通文件：${path}`;
            outputResourceExceeded = true;
            break;
          }
          if (scanned.size > MAX_ARTIFACT_BYTES) {
            safeOutputBytes += scanned.size;
            outputScanError = `候选输出文件超过单文件资源上限：${path}`;
            outputResourceExceeded = true;
            break;
          }
          const remaining = MAX_TOTAL_OUTPUT_BYTES - safeOutputBytes;
          if (scanned.size > remaining) {
            outputResourceExceeded = true;
            break;
          }
          const snapshot = readBoundedFile(path, Math.min(MAX_ARTIFACT_BYTES, remaining), scanned);
          if (!snapshot) {
            outputScanError = `候选输出文件在扫描后发生变化或不可安全读取：${path}`;
            outputResourceExceeded = true;
            break;
          }
          outputSnapshots.set(path, snapshot);
          safeOutputBytes += snapshot.length;
        }
      }
    } catch (error) {
      outputScanError = `${directory}: ${error.message}`;
      outputResourceExceeded = true;
    } finally {
      try {
        if (handle) handle.closeSync();
      } catch (error) {
        outputScanError ??= `${directory}: ${error.message}`;
        outputResourceExceeded = true;
      }
    }
  }
  return files;
};
const allFiles = scanOutputFiles();
const outputManifest = [...outputSnapshots]
  .map(([path, bytes]) => ({
    path: outputRelative(path),
    size: bytes.length,
    sha256: createHash("sha256").update(bytes).digest("hex"),
  }))
  .sort((left, right) => left.path.localeCompare(right.path));
const outputManifestSha256 = createHash("sha256")
  .update(JSON.stringify(outputManifest))
  .digest("hex");
const trustedTrace = loadTrustedTrace();
const forbidden = (markdown) => findForbiddenVisibleContent([markdown]);
const checkBundle = (path, trustedSource = false) => {
  if (outputResourceExceeded && !trustedSource) {
    return { ok: false, evidence: "候选输出超过资源上限，已跳过 bundle 子进程" };
  }
  if (!existsSync(path)) return { ok: false, evidence: `${path} 不存在` };
  if (!trustedSource && !isInsideOutputs(path)) {
    return { ok: false, evidence: `${path} 不是输出目录内的普通文件` };
  }
  let checkPath = path;
  let snapshotDirectory = null;
  if (!trustedSource) {
    let candidate;
    const bytes = candidateSnapshot("review-brief.json");
    try {
      if (!bytes) return { ok: false, evidence: "候选 JSON 超过 4 MiB、发生变化或不可安全读取" };
      candidate = JSON.parse(bytes.toString("utf8"));
    } catch (error) {
      return { ok: false, evidence: `候选 JSON 无法解析：${error.message}` };
    }
    if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) {
      return { ok: false, evidence: "候选 JSON 根节点必须是对象" };
    }
    const artifactPaths = [
      ...(Array.isArray(candidate.artifacts?.attachments)
        ? candidate.artifacts.attachments.map((item) => item?.local_path)
        : []),
      candidate.artifacts?.diagram?.svg_path,
      candidate.artifacts?.diagram?.png_path,
    ].filter(Boolean);
    if (artifactPaths.length > MAX_ARTIFACT_REFERENCES) {
      return {
        ok: false,
        evidence: `artifact 引用数量超过 ${MAX_ARTIFACT_REFERENCES} 项`,
      };
    }
    const expectedScreenshot = resolve(skillRoot, "evals/fixtures/assets/booking-card-after.png");
    const artifactBytes = new Map();
    const artifactAliases = new Map();
    const allArtifactsSafe = artifactPaths.every((artifactPath) => {
      let bytes = safeOutputArtifactBytes(artifactPath);
      if (!bytes && evalId === 3) {
        try {
          const lexical = resolve(artifactPath);
          const lexicalStat = lstatSync(lexical);
          if (
            lexicalStat.isFile()
            && lexicalStat.nlink === 1
            && lexicalStat.size <= MAX_ARTIFACT_BYTES
            && realpathSync(lexical) === realpathSync(expectedScreenshot)
          ) {
            bytes = readBoundedFile(lexical, MAX_ARTIFACT_BYTES, lexicalStat);
            if (bytes) {
              artifactSnapshots.set(lexical, bytes);
              artifactCanonicalPaths.set(lexical, realpathSync(lexical));
            }
          }
        } catch {
          bytes = null;
        }
      }
      if (!bytes) return false;
      const identity = artifactCanonicalPaths.get(resolve(artifactPath));
      if (!identity) return false;
      artifactAliases.set(artifactPath, identity);
      if (!artifactBytes.has(identity)) artifactBytes.set(identity, bytes);
      return true;
    });
    if (!allArtifactsSafe) {
      return { ok: false, evidence: "候选 JSON 引用了未授权的输出目录外 artifact" };
    }
    const temporaryBytes = [...artifactBytes.values()].reduce(
      (total, snapshot) => total + snapshot.length,
      0,
    );
    if (temporaryBytes > MAX_TOTAL_OUTPUT_BYTES) {
      return { ok: false, evidence: "artifact 唯一临时快照超过 100 MiB" };
    }
    try {
      snapshotDirectory = mkdtempSync(resolve(tmpdir(), "review-brief-grader-check-"));
      const pathMap = new Map();
      let index = 0;
      for (const [artifactIdentity, snapshot] of artifactBytes) {
        const extension = /^\.[a-z0-9]{1,8}$/i.test(extname(artifactIdentity))
          ? extname(artifactIdentity).toLowerCase()
          : ".bin";
        const snapshotPath = resolve(snapshotDirectory, `artifact-${index}${extension}`);
        writeFileSync(snapshotPath, snapshot, { flag: "wx", mode: 0o600 });
        pathMap.set(artifactIdentity, snapshotPath);
        index += 1;
      }
      const rewriteAttachment = (attachment) => {
        const identity = attachment && typeof attachment === "object"
          ? artifactAliases.get(attachment.local_path)
          : null;
        if (identity && pathMap.has(identity)) {
          attachment.local_path = pathMap.get(identity);
        }
      };
      for (const attachment of Array.isArray(candidate.artifacts?.attachments)
        ? candidate.artifacts.attachments
        : []) rewriteAttachment(attachment);
      for (const change of Array.isArray(candidate.review_brief?.main_changes)
        ? candidate.review_brief.main_changes
        : []) {
        for (const attachment of Array.isArray(change?.attachments) ? change.attachments : []) {
          rewriteAttachment(attachment);
        }
      }
      if (candidate.artifacts?.diagram && typeof candidate.artifacts.diagram === "object") {
        for (const field of ["svg_path", "png_path"]) {
          const identity = artifactAliases.get(candidate.artifacts.diagram[field]);
          if (identity && pathMap.has(identity)) {
            candidate.artifacts.diagram[field] = pathMap.get(identity);
          }
        }
      }
      checkPath = resolve(snapshotDirectory, "review-brief.json");
      writeFileSync(checkPath, `${JSON.stringify(candidate)}\n`, { flag: "wx", mode: 0o600 });
    } catch (error) {
      if (snapshotDirectory) {
        try {
          rmSync(snapshotDirectory, { recursive: true, force: true });
        } catch {
          // 失败证据保留原始异常；临时目录只包含 grader 自有快照。
        }
      }
      return { ok: false, evidence: `无法建立 grader 自有候选快照：${error.message}` };
    }
  }
  const result = spawnSync(
    "node",
    [resolve(skillRoot, "scripts/review-brief.mjs"), "check", checkPath],
    { encoding: "utf8", timeout: 15_000, maxBuffer: 2 * 1024 * 1024 },
  );
  if (snapshotDirectory) {
    try {
      rmSync(snapshotDirectory, { recursive: true, force: true });
    } catch {
      // 快照目录由 mkdtemp 创建且不含候选路径；清理失败不改变本次评分证据。
    }
  }
  return {
    ok: result.status === 0,
    evidence: (result.stdout || result.stderr || result.error?.message || "bundle 子进程失败").trim(),
  };
};
const semanticText = (brief) => JSON.stringify(collectVisibleBriefStrings(brief));

if (evalId === 1) {
  const markdown = text("review-brief.md");
  const document = json("review-brief.json");
  const check = checkBundle(file("review-brief.json"));
  const brief = document?.review_brief;
  const shape = check.ok && brief?.mode === "lite" && Array.isArray(brief?.reading_route)
    && brief.reading_route.length === 0;
  add(0, shape, `${check.evidence}; parse_error=${jsonErrors.get("review-brief.json") ?? "none"}; mode=${brief?.mode}; reading_route=${brief?.reading_route?.length}`);
  const semantics = brief ? semanticText(brief) : "";
  const facts = /null/.test(semantics) && /(undefined|缺失|未提供|不修改)/.test(semantics)
    && /(空白|清空)/.test(semantics) && /(非空|首尾空白|trim)/i.test(semantics);
  add(1, facts, facts ? "JSON 同时保留缺失、空白清除和非空规范化三种语义" : "JSON 未完整表达三态语义");
  const banned = forbidden(markdown);
  add(2, Boolean(markdown) && banned.length === 0, banned.length ? `命中禁止模式：${banned.join(", ")}` : "Markdown 存在且未展示内部状态或审查结论");
} else if (evalId === 2) {
  const markdown = text("review-brief.md");
  const document = json("review-brief.json");
  const check = checkBundle(file("review-brief.json"));
  const brief = document?.review_brief;
  const routeCount = brief?.reading_route?.length ?? 0;
  add(0, check.ok && brief?.mode === "full" && routeCount >= 3 && routeCount <= 7, `${check.evidence}; mode=${brief?.mode}; reading_route=${routeCount}`);
  const semantics = brief ? semanticText(brief) : "";
  const symbols = ["createBooking", "dispatchReminder", "sendReminder", "ReminderStatus", "applyReminderResult"];
  const missing = symbols.filter((symbol) => !semantics.includes(symbol));
  add(1, missing.length === 0, missing.length ? `缺少 symbol：${missing.join(", ")}` : "关键入口、服务、worker、状态与 webhook symbol 均存在");
  const artifact = document?.artifacts?.diagram;
  const svgPath = artifact?.svg_path;
  const pngPath = artifact?.png_path;
  let sourceHash = "";
  const svgBytes = safeOutputArtifactBytes(svgPath);
  const pngBytes = safeOutputArtifactBytes(pngPath);
  const svgSafe = svgBytes !== null;
  const pngSafe = pngBytes !== null;
  if (svgBytes) sourceHash = createHash("sha256").update(svgBytes).digest("hex");
  const pngSignature = pngBytes ? pngBytes.subarray(0, 8).toString("hex") : "";
  const pngHash = pngBytes ? createHash("sha256").update(pngBytes).digest("hex") : "";
  const artifactOk = svgSafe && pngSafe
    && brief?.diagram?.source_hash === sourceHash && artifact?.visual_review === "passed"
    && artifact?.png_hash === pngHash
    && pngSignature === "89504e470d0a1a0a";
  add(2, artifactOk, `svg/png_in_outputs=${svgSafe && pngSafe}; source_hash_match=${brief?.diagram?.source_hash === sourceHash}; png_hash_match=${artifact?.png_hash === pngHash}; visual_review=${artifact?.visual_review}; png_signature=${pngSignature}`);
  const banned = forbidden(markdown);
  const imagePointsToCurrent = pngPath && markdown.includes(pngPath) && isInsideOutputs(pngPath);
  add(3, Boolean(imagePointsToCurrent) && banned.length === 0, `current_png=${Boolean(imagePointsToCurrent)}; forbidden=${banned.length ? banned.join(", ") : "none"}`);
} else if (evalId === 3) {
  const markdown = text("review-brief.md");
  const document = json("review-brief.json");
  const check = checkBundle(file("review-brief.json"));
  const brief = document?.review_brief;
  add(0, check.ok && brief?.mode === "lite" && brief?.diagram === null && brief?.reading_route?.length === 0, `${check.evidence}; mode=${brief?.mode}; diagram=${brief?.diagram}; reading_route=${brief?.reading_route?.length}`);
  const imageMatch = markdown.match(/!\[[^\]]+\]\(<?(\/[^\n>)]+)>?\)/);
  const imagePath = imageMatch?.[1];
  const expectedScreenshot = resolve(skillRoot, "evals/fixtures/assets/booking-card-after.png");
  const expectedHash = createHash("sha256").update(readFileSync(expectedScreenshot)).digest("hex");
  const artifacts = Array.isArray(document?.artifacts?.attachments)
    ? document.artifacts.attachments
    : [];
  const artifact = artifacts.find((item) => item?.local_path === imagePath);
  let actualHash = "";
  let allowedImagePath = false;
  try {
    const isExpectedFixture = imagePath && realpathSync(imagePath) === realpathSync(expectedScreenshot);
    const bytes = isExpectedFixture
      ? readBoundedFile(imagePath, MAX_ARTIFACT_BYTES)
      : safeOutputArtifactBytes(imagePath);
    if (bytes) {
      actualHash = createHash("sha256").update(bytes).digest("hex");
      allowedImagePath = true;
    }
  } catch {
    // 下方统一把不可读、symlink 或目录外未知路径判为失败证据。
  }
  const avoidsMechanical = !markdown.includes("src/generated/api-types.ts") && !markdown.includes("BookingCard.snap");
  const screenshotOk = Boolean(
    artifact
    && artifact.visual_review === "passed"
    && artifact.file_hash === actualHash
    && actualHash === expectedHash
    && allowedImagePath
    && avoidsMechanical
  );
  add(1, screenshotOk, `image=${imagePath ?? "missing"}; artifact_match=${Boolean(artifact)}; hash_match=${actualHash === expectedHash}; allowed_path=${allowedImagePath}; avoids_mechanical=${avoidsMechanical}`);
  const semantics = brief ? semanticText(brief) : "";
  const facts = ["状态", "负责", "cancelled", "aria-label"].every((term) => `${semantics}${markdown}`.includes(term));
  const banned = forbidden(markdown);
  add(2, facts && banned.length === 0, `facts=${facts}; forbidden=${banned.length ? banned.join(", ") : "none"}`);
} else if (evalId === 4 || evalId === 5) {
  const answer = text("answer.md");
  const owner = evalId === 4 ? "review-swarm" : "fireworks-tech-graph";
  const context = evalId === 4 ? /(finding|verdict|P0|Approve|Request changes)/i : /(没有|缺少).*(PR|branch|diff|变更)/i;
  add(0, answer.includes(owner) && context.test(answer), `owner=${answer.includes(owner)}; context=${context.test(answer)}`);
  const generated = allFiles.some((path) => /review-brief\.(?:json|md)$/.test(path) || /\.(?:svg|png)$/.test(path));
  const guessed = evalId === 5 && /(API Gateway|订单服务|数据库|消息队列).*(→|调用|连接)/.test(answer);
  const fakeFinding = evalId === 4 && /P[0-3]\s*[：:].*(?:存在|发现|问题)/.test(answer);
  add(1, !generated && !guessed && !fakeFinding, `generated=${generated}; guessed=${guessed}; fake_finding=${fakeFinding}`);
} else if (evalId === 6) {
  const github = text("github-preview.md");
  const slack = text("slack-preview.md");
  const sourcePath = resolve(skillRoot, "evals/fixtures/channel-source-bundle.json");
  const source = JSON.parse(readFileSync(sourcePath, "utf8")).review_brief;
  const check = checkBundle(sourcePath, true);
  const marker = github.match(/review-brief:start schema=1 content=([a-f0-9]{64}) render=[a-f0-9]{64}/i)?.[1];
  add(0, check.ok && marker === source.content_hash, `${check.evidence}; marker=${marker}`);
  const overviewSame = github.includes(source.overview) && slack.includes(source.overview);
  const githubTitles = source.main_changes.every((change) => github.includes(change.title));
  const slackTitles = source.main_changes.filter((change) => slack.includes(change.title));
  add(1, overviewSame && githubTitles && slackTitles.length >= 1, `overview_same=${overviewSame}; github_titles=${githubTitles}; slack_source_titles=${slackTitles.length}`);
  const routeFocusItems = [...source.reading_route, ...source.review_focus].filter((item) => slack.includes(item)).length;
  add(2, slackTitles.length >= 1 && slackTitles.length <= 3 && routeFocusItems <= 3, `slack_changes=${slackTitles.length}; exact_route_focus_items=${routeFocusItems}`);
  const banned = [...forbidden(github), ...forbidden(slack)];
  add(3, banned.length === 0, banned.length ? `命中禁止模式：${banned.join(", ")}` : "两个预览均未展示内部状态或审查结论");
  const allowed = new Set(["github-preview.md", "slack-preview.md", "answer.md"]);
  const unexpected = allFiles.map(outputRelative).filter((path) => !allowed.has(path));
  const remoteWriteClaim = /(uploaded|file_id|thread_ts|已发送|已更新 PR|已上传)/i.test(`${github}\n${slack}\n${text("answer.md")}`);
  add(4, unexpected.length === 0 && !remoteWriteClaim, `unexpected_files=${unexpected.join(",") || "none"}; remote_write_claim=${remoteWriteClaim}`);
} else if (evalId === 7) {
  const markdown = text("review-brief.md");
  const document = json("review-brief.json");
  const check = checkBundle(file("review-brief.json"));
  add(0, check.ok && markdown.includes("## 概要") && markdown.includes("## 主要变化"), `${check.evidence}; required_sections=${markdown.includes("## 概要") && markdown.includes("## 主要变化")}`);
  const visible = `${markdown}\n${document?.review_brief ? semanticText(document.review_brief) : ""}\n${text("answer.md")}`;
  const describesChange = /(平均|averageItemAmount|calculateAverage)/i.test(visible)
    && /(buildOrderSummary|订单摘要|调用)/i.test(visible);
  const reviewConclusion = forbidden(`${markdown}\n${text("answer.md")}`).includes("代码审查 finding 或 verdict")
    || findForbiddenVisibleContent(collectVisibleBriefFields(document?.review_brief))
      .includes("代码审查 finding 或 verdict");
  add(1, describesChange && !reviewConclusion, `describes_change=${describesChange}; review_conclusion=${reviewConclusion}`);
  const visibleReviewSwarm = /review-swarm|spawn_agent|reviewer 已启动|已执行代码审查/i.test(visible);
  const unexpected = allFiles
    .map(outputRelative)
    .filter((path) => !["review-brief.md", "review-brief.json", "answer.md"].includes(path));
  const traceReviewCalls = trustedTrace.trace?.tool_calls.filter((item) => (
    /spawn_agent|review[-_](?:swarm|agent)|reviewer/i.test(
      `${item.name}\n${item.arguments_text}`,
    )
  )) ?? [];
  const traceReviewSkills = trustedTrace.trace?.skill_activations.filter((item) => (
    /review[-_](?:swarm|agent)|reviewer/i.test(item)
  )) ?? [];
  const reportedReviewActivity = trustedTrace.trace?.review_activity ?? [];
  const childAgents = trustedTrace.trace?.child_agents ?? [];
  const traceClean = Boolean(trustedTrace.trace)
    && traceReviewCalls.length === 0
    && traceReviewSkills.length === 0
    && reportedReviewActivity.length === 0
    && childAgents.length === 0;
  add(
    2,
    !visibleReviewSwarm && unexpected.length === 0 && traceClean,
    `${trustedTrace.error ?? `trace_review_calls=${traceReviewCalls.length}; trace_review_skills=${traceReviewSkills.length}; reported_review_activity=${reportedReviewActivity.length}; child_agents=${childAgents.length}`}; visible_review_swarm=${visibleReviewSwarm}; unexpected_files=${unexpected.join(",") || "none"}`,
  );
}

if (outputResourceExceeded) {
  expectations.push({
    text: "候选输出文件数量与总字节必须位于评测资源上限内",
    passed: false,
    evidence: outputScanError
      ? `目录扫描失败：${outputScanError}`
      : `files=${allFiles.length}/${MAX_OUTPUT_FILES}; bytes=${safeOutputBytes}/${MAX_TOTAL_OUTPUT_BYTES}`,
  });
}

const passed = expectations.filter((item) => item.passed).length;
const grading = {
  expectations,
  summary: {
    passed,
    failed: expectations.length - passed,
    total: expectations.length,
    pass_rate: expectations.length ? passed / expectations.length : 0,
  },
  execution_metrics: {
    total_tool_calls: trustedTrace.trace?.tool_calls.length ?? null,
    total_steps: trustedTrace.trace?.total_steps ?? null,
    files_created: allFiles.map(outputRelative),
    errors_encountered: 0,
    output_chars: safeOutputBytes,
  },
  timing: { total_duration_seconds: 0, measurement: "not exposed by collaboration runtime" },
  run_metadata: {
    grader: "deterministic review-brief evaluator",
    output_manifest_sha256: outputManifestSha256,
    unsafe_candidate_files: [...unsafeCandidateFiles],
  },
};

const gradingPath = resolve(outputsRoot, "../grading.json");
const gradingTemporary = resolve(outputsRoot, `../.grading-${process.pid}-${randomUUID()}.tmp`);
try {
  let descriptor;
  try {
    descriptor = openSync(gradingTemporary, "wx", 0o600);
    writeFileSync(descriptor, `${JSON.stringify(grading, null, 2)}\n`, "utf8");
    closeSync(descriptor);
    descriptor = undefined;
    renameSync(gradingTemporary, gradingPath);
  } finally {
    if (descriptor !== undefined) closeSync(descriptor);
  }
} catch (error) {
  try {
    unlinkSync(gradingTemporary);
  } catch {
    // 临时文件可能尚未创建或已经完成 rename。
  }
  process.stderr.write(`无法安全写入评分结果：${error.message}\n`);
  process.exit(2);
}
process.stdout.write(`${JSON.stringify(grading.summary)}\n`);
process.exit(grading.summary.failed ? 1 : 0);

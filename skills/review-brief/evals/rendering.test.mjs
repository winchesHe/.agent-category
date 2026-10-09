import assert from "node:assert/strict";
import { createHash, randomUUID } from "node:crypto";
import { chmodSync, linkSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, symlinkSync, truncateSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, test } from "node:test";
import { spawnSync } from "node:child_process";
import { deflateSync } from "node:zlib";
import { findForbiddenVisibleContent } from "../scripts/review-brief-policy.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const skillRoot = resolve(here, "..");
const script = resolve(skillRoot, "scripts/review-brief.mjs");
const grader = resolve(skillRoot, "evals/grade_outputs.mjs");
const sourceFixture = resolve(skillRoot, "evals/fixtures/channel-source-bundle.json");
const githubAssetUrl = "https://github.com/user-attachments/assets/00000000-0000-4000-8000-000000000001";

function pngBytes(variant = 0) {
  if (variant === 1) return readFileSync(resolve(skillRoot, "evals/fixtures/assets/booking-card-after.png"));
  return Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
    "base64",
  );
}

function fileHash(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function outputManifestSha256(directory) {
  const pending = [directory];
  const files = [];
  while (pending.length) {
    const current = pending.pop();
    for (const entry of readdirSync(current, { withFileTypes: true })) {
      const path = resolve(current, entry.name);
      if (entry.isDirectory()) pending.push(path);
      else if (entry.isFile()) {
        const bytes = readFileSync(path);
        files.push({
          path: path.slice(resolve(directory).length + 1),
          size: bytes.length,
          sha256: createHash("sha256").update(bytes).digest("hex"),
        });
      }
    }
  }
  files.sort((left, right) => left.path.localeCompare(right.path));
  return createHash("sha256").update(JSON.stringify(files)).digest("hex");
}

function trustedTraceDocument(outputs, overrides = {}) {
  return {
    schema_version: 2,
    eval_id: 7,
    run_id: randomUUID(),
    output_manifest_sha256: outputManifestSha256(outputs),
    capture: {
      tool_names: true,
      tool_arguments: true,
      skill_activations: true,
      child_agents: true,
      review_activity: true,
    },
    tool_calls: [],
    skill_activations: [],
    child_agents: [],
    review_activity: [],
    total_steps: 1,
    ...overrides,
  };
}

function reviewedAttachment(attachment) {
  return {
    ...attachment,
    visual_review: "passed",
    file_hash: fileHash(attachment.local_path),
  };
}

function githubBoundArtifact(document, artifact, url = githubAssetUrl) {
  return {
    ...artifact,
    github_url: url,
    github_file_hash: artifact.file_hash ?? artifact.png_hash,
    github_target_identity: document.review_brief.target.identity,
  };
}

function writeGitHubBindings(_directory, document, name = "github-bindings.json") {
  const artifacts = [
    ...(document.artifacts.attachments ?? []),
    ...(document.artifacts.diagram ? [document.artifacts.diagram] : []),
  ];
  const ownerDirectory = mkdtempSync(resolve(tmpdir(), "review-brief-owner-bindings-"));
  const path = resolve(ownerDirectory, name);
  writeFileSync(path, `${JSON.stringify({
    schema_version: 1,
    target_identity: document.review_brief.target.identity,
    assets: artifacts
      .filter((artifact) => artifact.github_url)
      .map((artifact) => ({
        url: artifact.github_url,
        sha256: artifact.file_hash ?? artifact.png_hash,
      })),
  }, null, 2)}\n`);
  return path;
}

function crc32(buffer) {
  let value = 0xffffffff;
  for (const byte of buffer) {
    value ^= byte;
    for (let bit = 0; bit < 8; bit += 1) {
      value = (value & 1) ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
    }
  }
  return (value ^ 0xffffffff) >>> 0;
}

function pngChunk(type, data) {
  const typeBytes = Buffer.from(type, "ascii");
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const checksum = Buffer.alloc(4);
  checksum.writeUInt32BE(crc32(Buffer.concat([typeBytes, data])));
  return Buffer.concat([length, typeBytes, data, checksum]);
}

function rgbaPng(rawScanline, width = 1, height = 1) {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = 8;
  header[9] = 6;
  return Buffer.concat([
    Buffer.from("89504e470d0a1a0a", "hex"),
    pngChunk("IHDR", header),
    pngChunk("IDAT", deflateSync(rawScanline)),
    pngChunk("IEND", Buffer.alloc(0)),
  ]);
}

function indexedPng(bitDepth, paletteEntries, pixelIndex = 0) {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(1, 0);
  header.writeUInt32BE(1, 4);
  header[8] = bitDepth;
  header[9] = 3;
  return Buffer.concat([
    Buffer.from("89504e470d0a1a0a", "hex"),
    pngChunk("IHDR", header),
    pngChunk("PLTE", Buffer.alloc(paletteEntries * 3)),
    pngChunk("IDAT", deflateSync(Buffer.from([0, pixelIndex << (8 - bitDepth)]))),
    pngChunk("IEND", Buffer.alloc(0)),
  ]);
}

function run(args, expectedStatus = 0) {
  const result = spawnSync("node", [script, ...args], { encoding: "utf8" });
  assert.equal(result.status, expectedStatus, result.stderr || result.stdout);
  return result;
}

function copyFixture(directory, name = "review-brief.json") {
  const path = resolve(directory, name);
  writeFileSync(path, readFileSync(sourceFixture));
  return path;
}

function parseResult(result) {
  return JSON.parse(result.stdout);
}

describe("GitHub 渠道渲染", () => {
  test("畸形字段返回结构化校验错误而不是异常堆栈", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-invalid-"));
    const input = copyFixture(directory);
    const document = JSON.parse(readFileSync(input, "utf8"));
    document.review_brief.main_changes[0].title = 42;
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    const result = run(["finalize", input], 2);
    assert.match(result.stderr, /main_changes\[0\]\.title 必须是非空字符串/);
    assert.ok(!result.stderr.includes("TypeError"));
  });

  test("畸形 artifact 容器与深层 JSON 都在遍历前失败", () => {
    for (const attachments of [{}, [null]]) {
      const directory = mkdtempSync(resolve(tmpdir(), "review-brief-invalid-artifacts-"));
      const input = copyFixture(directory);
      const document = JSON.parse(readFileSync(input, "utf8"));
      document.artifacts.attachments = attachments;
      writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
      for (const command of ["finalize", "render-slack"]) {
        const args = command === "render-slack"
          ? [command, input, "--output", resolve(directory, "slack.md")]
          : [command, input];
        const result = run(args, 2);
        assert.ok(!result.stderr.includes("TypeError"));
        assert.match(result.stderr, /artifacts\.attachments/);
      }
    }

    const shapeDirectory = mkdtempSync(resolve(tmpdir(), "review-brief-invalid-visible-shape-"));
    const shapeInput = copyFixture(shapeDirectory);
    const shapeDocument = JSON.parse(readFileSync(shapeInput, "utf8"));
    shapeDocument.review_brief.main_changes = {};
    shapeDocument.review_brief.reading_route = {};
    writeFileSync(shapeInput, `${JSON.stringify(shapeDocument)}\n`);
    const shapeResult = run(["finalize", shapeInput], 2);
    assert.ok(!shapeResult.stderr.includes("TypeError"));
    assert.match(shapeResult.stderr, /main_changes 必须是数组/);

    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-deep-json-"));
    const input = copyFixture(directory);
    const document = JSON.parse(readFileSync(input, "utf8"));
    let nested = {};
    document.unknown = nested;
    for (let depth = 0; depth < 40; depth += 1) {
      nested.next = {};
      nested = nested.next;
    }
    writeFileSync(input, `${JSON.stringify(document)}\n`);
    assert.match(run(["hash", input], 2).stderr, /嵌套不得超过 32 层/);
  });

  test("禁止内容在 finalize 和双渠道渲染前被拦截", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-visible-boundary-"));
    const input = copyFixture(directory);
    const document = JSON.parse(readFileSync(input, "utf8"));
    document.review_brief.overview = "Out of scope：旧流程。验证结果：测试通过。Verdict：Approve。";
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    const hash = run(["hash", input]).stdout.trim();
    document.review_brief.content_hash = hash;
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);

    assert.match(run(["finalize", input], 2).stderr, /Reviewer 可见内容不得包含/);
    assert.match(run(["render-github", input, "--output", resolve(directory, "github.md")], 2).stderr, /Reviewer 可见内容不得包含/);
    assert.match(run(["render-slack", input, "--output", resolve(directory, "slack.md")], 2).stderr, /Reviewer 可见内容不得包含/);

    for (const forbidden of [
      "本次不包含登录页重构。",
      "登录页重构未纳入本次改动。",
      "该改动不覆盖旧登录页。",
      "Not in scope: legacy login.",
      "单元测试均成功。",
      "CI 状态正常。",
      "CI 尚未执行。",
      "改动已完成，但 CI 还没跑。",
      "Tests passed.",
      "Tests failed.",
      "CI 正在运行。",
      "CI 尚在执行中。",
      "CI 正在排队中。",
      "CI 还在跑。",
      "单测全过了。",
      "Tests are pending.",
      "旧登录页留待后续处理。",
      "这次不改旧页面。",
      "旧页面保持原样。",
      "这里存在一个除零缺陷。",
      "单测没过。",
      "旧页面没有变化。",
      "该实现存在正确性问题，建议修复后再审。",
      "需要修正后才能合并。",
      "calculateAverage 在空数组时会除零，必须修复。",
      "这里会触发死循环。",
      "该逻辑会导致数据丢失。",
      "其余页面保持不变。",
      "其他流程不受影响。",
      "除登录页外不做调整。",
      "单测没跑。",
      "CI 红了。",
      "流水线挂了。",
      "预计 Review 需要 30 分钟。",
      "Review 大约半小时。",
      "复杂度评分为 8/10。",
      "LGTM，可以合并。",
      "审查建议通过。",
      "calculateAverage 对空数组返回 NaN，需要处理。",
      "当前改动尚未验证。",
      "验证尚未完成。",
      "技术图已生成。",
      "PNG 已通过视觉检查。",
      "当前改动待验证。",
      "当前改动没有经过验证。",
      "技术图生成完成。",
      "已生成技术图。",
      "视觉检查通过。",
      "建议修复 calculateAverage 对空数组返回 NaN 的问题后再审。",
      "修复当前实现会导致数据丢失的问题后再审。",
      "P1：空数组返回 NaN。",
      "修复登录 bug 后再审。",
      "关联已有 P2 缺陷工单，建议合并。",
      "修复登录 bug。当前实现会导致数据丢失，这是一个新的问题。",
      "修复登录 bug。空数组返回 NaN。",
      "新增的缓存会导致数据丢失。",
      "新增测试失败重试能力，CI 已通过。",
      "调整测试失败重试次数；单测全部通过。",
      "新增测试失败重试机制，流水线仍在运行。",
      "关联已有 P2 缺陷工单，当前实现会导致数据丢失。",
      "新增测试失败重试能力且 CI 已通过。",
      "调整测试失败重试机制并且流水线仍在运行。",
      "新增测试失败重试能力并通过了 CI。",
      "调整测试失败重试机制同时流水线仍在运行。",
      "兼容旧版。支付接口不受影响。",
      "解析器返回数据丢失并映射为参数错误。",
      "修复登录 bug 并发现新的权限漏洞。",
      "修复登录 bug。当前实现存在权限漏洞。",
      "修复登录 bug：当前实现存在权限漏洞。",
      "修复登录 bug - 当前实现存在权限漏洞。",
      "CI 已通过并将日志发送到 Slack。",
      "单测全部通过后将结果同步到数据仓库。",
      "CI 已通过质量门禁后发布产物。",
      "单测全部通过质量门禁后将结果同步到数据仓库。",
    ]) {
      document.review_brief.overview = forbidden;
      writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
      assert.match(run(["finalize", input], 2).stderr, /Reviewer 可见内容不得包含/);
    }

    for (const allowed of [
      "CI 执行器改为按矩阵拆分任务，缩短单次任务的等待队列。",
      "表单验证失败时保留用户输入。",
      "配置数组现在可以合并。",
      "本次变更在手机号为空时不包含 phone 字段，让服务端保留原值。",
      "多个配置变更可以合并成一次请求。",
      "CI 任务失败时自动归档日志。",
      "页面在保存失败时保持原样。",
      "修复登录 bug。",
      "新增依赖漏洞扫描能力。",
      "补齐缺陷工单同步入口。",
      "同步 P2 缺陷工单。",
      "修复已发现的登录缺陷。",
      "关联已存在的 P2 缺陷工单。",
      "修复 calculateAverage 在空数组时会导致 NaN 的问题。",
      "修复在批量更新多个租户并保留每个租户原有覆盖顺序时，当前实现会导致数据丢失的问题。",
      "新增单测失败重试机制。",
      "调整测试失败重试次数。",
      "CI 失败重试改为指数退避。",
      "新增测试失败重试能力。",
      "新增测试失败重试上限。",
      "新增 CI 失败重跑能力。",
      "失败测试自动重试能力。",
      "解析失败时返回 null。",
      "更新解析器，失败时返回 undefined。",
      "接口返回 null 时需要处理为未设置状态。",
      "解析器返回 undefined 时进入错误处理分支。",
      "参数为 null 时返回参数错误。",
      "参数为 null 时返回 PERMISSION_DENIED 错误码。",
      "解析失败时返回 INVALID_ARGUMENT 错误码。",
      "CI 凭据通过环境变量注入。",
      "CI 日志通过 Slack webhook 发送。",
      "测试结果通过事件总线同步到数据仓库。",
      "调整测试失败重试机制同时失败测试保留诊断日志。",
      "CI 通过后发布产物。",
      "测试结果已通过后端接口发送到数据仓库。",
      "CI 日志均通过后台任务发送到归档服务。",
      "单测全部通过后台任务发送结果。",
    ]) {
      document.review_brief.overview = allowed;
      writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
      run(["finalize", input]);
    }

    document.review_brief.overview = "整理平均金额与订单摘要的调用关系。";
    for (const allowedFocus of [
      "确认当前实现是否会导致数据丢失。",
      "核对当前逻辑是否可能触发重复通知。",
      "请 Reviewer 确认当前实现是否会导致异常。",
      "确认本次修复后的兼容行为是否符合预期。",
      "核对配置合并是否保留现有覆盖顺序。",
    ]) {
      document.review_brief.review_focus = [allowedFocus];
      writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
      run(["finalize", input]);
    }
    for (const forbiddenFocus of [
      "确认当前实现是否会导致数据丢失，修复后可以合并。",
      "核对当前逻辑是否可能触发重复通知；修复后合并。",
      "确认当前实现是否会导致数据丢失，修好再审。",
      "P1 - 空数组返回 NaN。",
      "【P0】空数组返回 NaN。",
      "空数组返回 NaN。",
      "修复后再审。",
      "修复历史登录 bug。",
      "关联历史登录 bug 工单。",
      "确认当前实现是否会导致数据丢失；空数组返回 NaN。",
      "确认当前实现是否会导致数据丢失；这里存在一个缺陷。",
      "确认重试是否符合预期，当前实现存在缺陷。",
      "核对保存是否成功：当前逻辑会导致数据丢失。",
      "确认重试是否符合预期—空数组返回 NaN。",
      "确认重试是否符合预期，当前实现可以导致数据丢失。",
      "确认重试是否符合预期-空数组返回 NaN。",
    ]) {
      document.review_brief.review_focus = [forbiddenFocus];
      writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
      assert.match(run(["finalize", input], 2).stderr, /Reviewer 可见内容不得包含/);
    }
    document.review_brief.review_focus = [];
    document.review_brief.risk_release = [
      "灰度期间旧页面保持不变，新页面按租户逐步放量。",
      "回滚后旧页面保持原样，已写入新表的数据继续保留。",
    ];
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    run(["finalize", input]);
    document.review_brief.risk_release = ["旧登录页留待后续处理。"];
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    assert.match(run(["finalize", input], 2).stderr, /非目标说明/);
    for (const scopeCaveat of [
      "其他流程不受影响。",
      "旧页面保持原样。",
      "灰度期间新页面按租户逐步放量，其他流程不受影响。",
      "回滚后登录页切回旧版；其他流程不受影响。",
      "回滚后切回旧版；其他接口不受影响。",
      "灰度期间逐步放量，其他业务保持不变。",
      "兼容旧版，其他调用方不做调整。",
      "回滚后切回旧版；支付接口不受影响。",
      "兼容旧版且支付接口不受影响。",
      "回滚后切回旧版并且支付接口不受影响。",
      "兼容旧版并保持其他调用方不变。",
    ]) {
      document.review_brief.risk_release = [scopeCaveat];
      writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
      assert.match(run(["finalize", input], 2).stderr, /非目标说明/);
    }
    document.review_brief.risk_release = [];
    document.review_brief.target.kind = "branch";
    document.review_brief.target.identity = "fix/P2-brief";
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    run(["finalize", input]);

    assert.deepEqual(
      findForbiddenVisibleContent(["Tests passed. Verdict: LGTM. Finding: blocker. CI 正在运行。"]),
      ["验证结果", "代码审查 finding 或 verdict"],
    );
    assert.deepEqual(findForbiddenVisibleContent([
      "### 修复登录 bug\n\n修复登录 bug。\n\n## 风险与发布\n\n- 灰度期间旧页面保持不变，新页面按租户逐步放量。",
      "- *修复登录 bug*：修复登录 bug。",
      "- *修复登录 bug*：创建入口现在保留既有调用顺序。",
      "- *更新解析契约*：接口返回 null 时需要处理为未设置状态。",
    ]), []);
    assert.deepEqual(
      findForbiddenVisibleContent(["- *修复登录 bug*：更新逻辑可能触发死循环。"]),
      ["代码审查 finding 或 verdict"],
    );
  });

  test("输入体积和集合数量都有明确上限", () => {
    const oversizedDirectory = mkdtempSync(resolve(tmpdir(), "review-brief-oversized-json-"));
    const oversized = resolve(oversizedDirectory, "review-brief.json");
    writeFileSync(oversized, Buffer.alloc(4 * 1024 * 1024 + 1, 0x20));
    assert.match(run(["check", oversized], 2).stderr, /不得超过 4 MiB/);

    const validInput = copyFixture(oversizedDirectory, "valid.json");
    assert.match(run([
      "render-github", validInput, "--existing-body", oversized,
      "--adopt", "replace", "--output", resolve(oversizedDirectory, "body.md"),
    ], 3).stderr, /现有 PR Body 不得超过 4 MiB/);

    const collectionDirectory = mkdtempSync(resolve(tmpdir(), "review-brief-oversized-list-"));
    const input = copyFixture(collectionDirectory);
    const document = JSON.parse(readFileSync(input, "utf8"));
    document.review_brief.main_changes = Array.from(
      { length: 101 },
      (_, index) => ({
        title: `变化 ${index}`,
        description: "用于验证集合数量门禁。",
        code_refs: [],
        attachments: [],
      }),
    );
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    assert.match(run(["finalize", input], 2).stderr, /main_changes 最多包含 100 项/);
  });

  test("参数与 artifact 数量在文件快照读取前失败", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-cheap-preflight-"));
    const input = copyFixture(directory);
    const document = JSON.parse(readFileSync(input, "utf8"));
    document.artifacts.attachments = Array.from({ length: 201 }, (_, index) => ({
      alt_text: `不存在的附件 ${index}`,
      local_path: resolve(directory, `missing-${index}.png`),
    }));
    writeFileSync(input, `${JSON.stringify(document)}\n`);

    assert.match(run(["check", input, "unexpected"], 2).stderr, /check 不接受额外参数/);
    assert.match(run(["render-github", input], 2).stderr, /必须提供 --output/);
    assert.match(run([
      "render-github", input, "--target-url", "https://example.com", "--output", resolve(directory, "github.md"),
    ], 2).stderr, /render-github 不支持 --target-url/);
    assert.match(run([
      "render-slack", input, "--adopt", "append", "--output", resolve(directory, "slack.md"),
    ], 2).stderr, /render-slack 不支持 GitHub Body 参数/);
    const bounded = run(["check", input], 2);
    assert.match(bounded.stderr, /artifacts\.attachments 最多包含 200 项/);
    assert.ok(!bounded.stderr.includes("本地产物不存在"));
  });

  test("从统一 JSON 生成双 hash marker 和完整 Brief", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-github-"));
    const input = copyFixture(directory);
    const output = resolve(directory, "github.md");
    const result = parseResult(run(["render-github", input, "--output", output]));
    const markdown = readFileSync(output, "utf8");

    assert.equal(result.action, "create");
    assert.match(result.content_hash, /^[a-f0-9]{64}$/);
    assert.match(result.render_hash, /^[a-f0-9]{64}$/);
    assert.ok(markdown.includes(`content=${result.content_hash} render=${result.render_hash}`));
    assert.ok(markdown.includes("## 概要"));
    assert.ok(markdown.includes("## 推荐阅读路线"));
    assert.ok(markdown.includes("## 风险与发布"));
    assert.ok(!markdown.includes("visual_review"));
  });

  test("Full 使用主线和子要点渲染，并保留短段落与行内代码", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-grouped-changes-"));
    const input = copyFixture(directory);
    const document = JSON.parse(readFileSync(input, "utf8"));
    document.review_brief.overview = "技术方案可以从最小输入直接开始。\n\n后续代码审查可以追溯方案依据。";
    document.review_brief.main_changes = [
      {
        title: "1. 技术方案编写",
        points: [
          {
            title: "直接进入，执行中补齐证据",
            description: "点名后立即执行，仅在真实跨栈时加载 `moe-stack`。",
          },
          {
            title: "稳定落盘",
            description: "使用稳定身份写入并在结果未知时先 reconcile。",
          },
        ],
        code_refs: ["moe-opc/SKILL.md"],
        attachments: [],
      },
      {
        title: "2. Review Readiness 交接",
        points: [
          {
            title: "版本化 Handoff",
            description: "生成与正文同版本的 `review_handoff/v1`。",
          },
          {
            title: "独立消费",
            description: "后续审查重新读取实际 diff 和仓库规则。",
          },
        ],
        code_refs: ["moe-opc/references/review-readiness.md"],
        attachments: [],
      },
    ];
    document.review_brief.reading_route = [
      "moe-opc/SKILL.md — 确认全局入口。",
      "moe-opc/references/stages/technical-design.md — 理解执行主线。",
      "moe-opc/references/review-readiness.md — 核对交接边界。",
    ];
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    run(["finalize", input]);

    const output = resolve(directory, "github.md");
    run(["render-github", input, "--output", output]);
    const markdown = readFileSync(output, "utf8");
    assert.ok(markdown.includes("技术方案可以从最小输入直接开始。\n\n后续代码审查可以追溯方案依据。"));
    assert.ok(markdown.includes("### 1&#46; 技术方案编写"));
    assert.ok(markdown.includes("- **直接进入，执行中补齐证据**："));
    assert.ok(markdown.includes("`moe-stack`"));
    assert.ok(markdown.includes("`review_handoff/v1`"));
    assert.ok(markdown.includes("`moe-opc/SKILL.md` —"));
    assert.ok(!markdown.includes("&#96;moe"));

    const slackOutput = resolve(directory, "slack.md");
    run(["render-slack", input, "--output", slackOutput]);
    const slack = readFileSync(slackOutput, "utf8");
    assert.ok(slack.includes("直接进入，执行中补齐证据"));
    assert.ok(slack.includes("版本化 Handoff"));
    assert.ok(!slack.includes("｀review_handoff/v1｀"));
  });

  test("Lite 的主要变化使用简短列表，不提升为三级标题", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-lite-list-"));
    const input = copyFixture(directory);
    const document = JSON.parse(readFileSync(input, "utf8"));
    document.review_brief.mode = "lite";
    document.review_brief.reading_route = [];
    document.review_brief.main_changes = [{
      title: "清空备注语义",
      description: "空字符串会规范化为 `null`。",
      code_refs: ["src/preferences.ts:savePreference"],
      attachments: [],
    }];
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    run(["finalize", input]);

    const output = resolve(directory, "github.md");
    run(["render-github", input, "--output", output]);
    const markdown = readFileSync(output, "utf8");
    assert.ok(markdown.includes("- **清空备注语义**：空字符串会规范化为 `null`"));
    assert.ok(!markdown.includes("### 清空备注语义"));
  });

  test("子要点沿用可见内容门禁，Lite 不接受分组 points", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-point-validation-"));
    const input = copyFixture(directory);
    const document = JSON.parse(readFileSync(input, "utf8"));
    document.review_brief.main_changes[0] = {
      title: "分组变化",
      points: [{ title: "结果", description: "Tests passed." }],
      code_refs: [],
      attachments: [],
    };
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    assert.match(run(["finalize", input], 2).stderr, /Reviewer 可见内容不得包含验证结果/);

    document.review_brief.main_changes[0].points[0].description = "描述当前行为。";
    document.review_brief.mode = "lite";
    document.review_brief.reading_route = [];
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    assert.match(run(["finalize", input], 2).stderr, /Lite 的 main_changes 不使用 points/);

    delete document.review_brief.main_changes[0].points;
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    assert.match(run(["finalize", input], 2).stderr, /必须包含 description 或至少一个 point/);

    document.review_brief.mode = "full";
    document.review_brief.main_changes[0].points = Array.from({ length: 21 }, (_, index) => ({
      title: `要点 ${index + 1}`,
      description: "描述当前行为。",
    }));
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    assert.match(run(["finalize", input], 2).stderr, /points 最多包含 20 项/);
  });

  test("相同 marker block 为 no-op，内容被改写时会修复", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-noop-"));
    const input = copyFixture(directory);
    const first = resolve(directory, "first.md");
    run(["render-github", input, "--output", first]);

    const second = resolve(directory, "second.md");
    const noop = parseResult(run([
      "render-github", input, "--existing-body", first, "--output", second,
    ]));
    assert.equal(noop.action, "noop");
    assert.equal(readFileSync(second, "utf8"), readFileSync(first, "utf8"));

    const tampered = resolve(directory, "tampered.md");
    writeFileSync(tampered, readFileSync(first, "utf8").replace("## 概要", "## 被改写"));
    const repaired = resolve(directory, "repaired.md");
    const repair = parseResult(run([
      "render-github", input, "--existing-body", tampered, "--output", repaired,
    ]));
    assert.equal(repair.action, "replace");
    assert.ok(readFileSync(repaired, "utf8").includes("## 概要"));
  });

  test("更新只替换 marker 区域并保留人工正文", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-preserve-"));
    const input = copyFixture(directory);
    const generated = resolve(directory, "generated.md");
    run(["render-github", input, "--output", generated]);
    const existing = resolve(directory, "existing.md");
    writeFileSync(existing, `作者前言\n\n${readFileSync(generated, "utf8").trim()}\n\n作者补充\n`);

    const document = JSON.parse(readFileSync(input, "utf8"));
    document.review_brief.overview = "更新后的概要只用于验证 marker 替换。";
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    run(["finalize", input]);

    const output = resolve(directory, "updated.md");
    const result = parseResult(run([
      "render-github", input, "--existing-body", existing, "--output", output,
    ]));
    const markdown = readFileSync(output, "utf8");
    assert.equal(result.action, "replace");
    assert.ok(markdown.startsWith("作者前言\n\n"));
    assert.ok(markdown.endsWith("\n\n作者补充\n"));
    assert.ok(markdown.includes("更新后的概要"));
  });

  test("已有无 marker 正文必须显式选择 adopt 策略", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-adopt-"));
    const input = copyFixture(directory);
    const existing = resolve(directory, "existing.md");
    const authorBody = "作者已有正文  \n\n\n";
    writeFileSync(existing, authorBody);

    const blocked = run([
      "render-github", input, "--existing-body", existing,
      "--output", resolve(directory, "blocked.md"),
    ], 3);
    assert.match(blocked.stderr, /--adopt append\|replace/);

    const appended = resolve(directory, "appended.md");
    const appendResult = parseResult(run([
      "render-github", input, "--existing-body", existing,
      "--adopt", "append", "--output", appended,
    ]));
    assert.equal(appendResult.action, "append");
    assert.ok(readFileSync(appended, "utf8").startsWith(authorBody));

    const replaced = resolve(directory, "replaced.md");
    const replaceResult = parseResult(run([
      "render-github", input, "--existing-body", existing,
      "--adopt", "replace", "--output", replaced,
    ]));
    assert.equal(replaceResult.action, "replace-existing");
    assert.ok(!readFileSync(replaced, "utf8").includes("作者已有正文"));
  });

  test("残缺或重复 marker 会失败", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-marker-"));
    const input = copyFixture(directory);
    const malformed = resolve(directory, "malformed.md");
    writeFileSync(malformed, "<!-- review-brief:start schema=1 content=x render=y -->\n");
    run([
      "render-github", input, "--existing-body", malformed,
      "--output", resolve(directory, "out.md"),
    ], 3);

    for (const [name, body] of [
      ["unclosed", "作者正文\n<!-- review-brief:start schema=1 content="],
      ["wrong-schema", `<!-- review-brief:start schema=2 content=${"a".repeat(64)} render=${"b".repeat(64)} -->\n人工正文\n<!-- review-brief:end -->`],
    ]) {
      const path = resolve(directory, `${name}.md`);
      writeFileSync(path, body);
      for (const adopt of ["append", "replace"]) {
        const result = run([
          "render-github", input, "--existing-body", path, "--adopt", adopt,
          "--output", resolve(directory, `${name}-${adopt}.md`),
        ], 3);
        assert.match(result.stderr, /marker/);
      }
    }

    const generated = resolve(directory, "generated.md");
    run(["render-github", input, "--output", generated]);
    const duplicate = resolve(directory, "duplicate.md");
    const block = readFileSync(generated, "utf8");
    writeFileSync(duplicate, `${block}\n${block}`);
    run([
      "render-github", input, "--existing-body", duplicate,
      "--output", resolve(directory, "duplicate-out.md"),
    ], 3);

    const reserved = JSON.parse(readFileSync(input, "utf8"));
    reserved.review_brief.overview = "说明 review-brief:start marker 协议。";
    writeFileSync(input, `${JSON.stringify(reserved, null, 2)}\n`);
    const rejected = run(["finalize", input], 2);
    assert.match(rejected.stderr, /marker/);
  });

  test("图片 URL 改变 render_hash，但不改变 content_hash", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-diagram-"));
    const input = copyFixture(directory);
    const svg = resolve(directory, "flow.svg");
    const png = resolve(directory, "flow.png");
    writeFileSync(svg, "<svg xmlns=\"http://www.w3.org/2000/svg\"></svg>\n");
    writeFileSync(png, pngBytes());
    const document = JSON.parse(readFileSync(input, "utf8"));
    document.review_brief.diagram = {
      type: "sequence",
      alt_text: "预约保存与异步通知流程",
      source_hash: createHash("sha256").update(readFileSync(svg)).digest("hex"),
    };
    document.artifacts.diagram = {
      svg_path: svg,
      png_path: png,
      png_hash: fileHash(png),
      visual_review: "passed",
    };
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    const finalized = parseResult(run(["finalize", input]));

    const textOnly = resolve(directory, "text-only.md");
    const textResult = parseResult(run(["render-github", input, "--output", textOnly]));
    assert.ok(!readFileSync(textOnly, "utf8").includes("!["));
    run([
      "render-github", input, "--require-diagram", "--output", resolve(directory, "required.md"),
    ], 3);

    const withUrl = JSON.parse(readFileSync(input, "utf8"));
    withUrl.artifacts.diagram = githubBoundArtifact(withUrl, withUrl.artifacts.diagram);
    writeFileSync(input, `${JSON.stringify(withUrl, null, 2)}\n`);
    const bindings = writeGitHubBindings(directory, withUrl);
    const withImage = resolve(directory, "with-image.md");
    const imageResult = parseResult(run([
      "render-github", input, "--require-diagram", "--github-bindings", bindings, "--output", withImage,
    ]));
    assert.equal(imageResult.content_hash, finalized.content_hash);
    assert.notEqual(imageResult.render_hash, textResult.render_hash);
    assert.ok(readFileSync(withImage, "utf8").includes("https://github.com/user-attachments/assets/"));
  });

  test("技术图 source_hash 必须与当前 SVG 内容一致", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-diagram-hash-"));
    const input = copyFixture(directory);
    const svg = resolve(directory, "flow.svg");
    const png = resolve(directory, "flow.png");
    writeFileSync(svg, "<svg xmlns=\"http://www.w3.org/2000/svg\"></svg>\n");
    writeFileSync(png, pngBytes());
    const document = JSON.parse(readFileSync(input, "utf8"));
    document.review_brief.diagram = {
      type: "sequence",
      alt_text: "预约保存与异步通知流程",
      source_hash: createHash("sha256").update(readFileSync(svg)).digest("hex"),
    };
    document.artifacts.diagram = {
      svg_path: svg,
      png_path: png,
      png_hash: fileHash(png),
      visual_review: "passed",
    };
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    run(["finalize", input]);

    writeFileSync(svg, "<svg xmlns=\"http://www.w3.org/2000/svg\"><text>changed</text></svg>\n");
    const checked = run(["check", input], 2);
    assert.match(checked.stderr, /source_hash 与 artifacts\.diagram\.svg_path 的实际内容不匹配/);
  });

  test("target 必须显式包含合法的 base 和 head", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-target-revisions-"));
    const input = copyFixture(directory);
    const document = JSON.parse(readFileSync(input, "utf8"));
    delete document.review_brief.target.base;
    document.review_brief.target.head = [];
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);

    const finalized = run(["finalize", input], 2);
    assert.match(finalized.stderr, /target\.base 必须存在/);
    assert.match(finalized.stderr, /target\.head 必须是非空字符串或 null/);
  });

  test("非空技术图必须已经通过视觉门禁", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-diagram-review-"));
    const input = copyFixture(directory);
    const svg = resolve(directory, "flow.svg");
    const png = resolve(directory, "flow.png");
    writeFileSync(svg, "<svg xmlns=\"http://www.w3.org/2000/svg\"></svg>\n");
    writeFileSync(png, pngBytes());
    const document = JSON.parse(readFileSync(input, "utf8"));
    document.review_brief.diagram = {
      type: "sequence",
      alt_text: "预约保存与异步通知流程",
      source_hash: createHash("sha256").update(readFileSync(svg)).digest("hex"),
    };
    document.artifacts.diagram = {
      svg_path: svg,
      png_path: png,
      visual_review: "failed",
    };
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);

    const finalized = run(["finalize", input], 2);
    assert.match(finalized.stderr, /visual_review 必须为 passed/);
  });

  test("渠道输出不能覆盖唯一的 ReviewBrief JSON", () => {
    for (const command of ["render-github", "render-slack"]) {
      const directory = mkdtempSync(resolve(tmpdir(), `review-brief-overwrite-${command}-`));
      const input = copyFixture(directory);
      const original = readFileSync(input, "utf8");
      const rendered = run([command, input, "--output", input], 2);
      assert.match(rendered.stderr, /不能覆盖 ReviewBrief 输入或本地产物/);
      assert.equal(readFileSync(input, "utf8"), original);
    }

    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-overwrite-artifact-"));
    const input = copyFixture(directory);
    const screenshot = resolve(directory, "booking.png");
    writeFileSync(screenshot, pngBytes());
    const document = JSON.parse(readFileSync(input, "utf8"));
    const attachment = { alt_text: "预约卡片截图", local_path: screenshot };
    document.review_brief.main_changes[0].attachments = [attachment];
    document.artifacts.attachments = [reviewedAttachment(attachment)];
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    run(["finalize", input]);
    const originalPng = readFileSync(screenshot);
    const rendered = run(["render-slack", input, "--output", screenshot], 2);
    assert.match(rendered.stderr, /不能覆盖 ReviewBrief 输入或本地产物/);
    assert.deepEqual(readFileSync(screenshot), originalPng);
  });

  test("普通附件可满足任意图片门禁，但不能冒充技术图", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-required-image-"));
    const input = copyFixture(directory);
    const screenshot = resolve(directory, "booking.png");
    writeFileSync(screenshot, pngBytes());
    const document = JSON.parse(readFileSync(input, "utf8"));
    const attachment = { alt_text: "预约卡片截图", local_path: screenshot };
    document.review_brief.main_changes[0].attachments = [attachment];
    document.artifacts.attachments = [githubBoundArtifact(document, reviewedAttachment(attachment))];
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    run(["finalize", input]);
    const bindings = writeGitHubBindings(directory, document);

    const requiredImage = resolve(directory, "required-image.md");
    run(["render-github", input, "--require-image", "--github-bindings", bindings, "--output", requiredImage]);
    assert.ok(readFileSync(requiredImage, "utf8").includes("![预约卡片截图]"));
    run([
      "render-github", input, "--require-diagram", "--output", resolve(directory, "required-diagram.md"),
    ], 3);
  });

  test("视觉 passed 必须携带回看时 hash，remote-only 假 hash 不能发布", () => {
    const localDirectory = mkdtempSync(resolve(tmpdir(), "review-brief-visual-hash-"));
    const localInput = copyFixture(localDirectory);
    const screenshot = resolve(localDirectory, "booking.png");
    writeFileSync(screenshot, pngBytes());
    const localDocument = JSON.parse(readFileSync(localInput, "utf8"));
    const attachment = { alt_text: "预约卡片截图", local_path: screenshot };
    localDocument.review_brief.main_changes[0].attachments = [attachment];
    localDocument.artifacts.attachments = [{ ...attachment, visual_review: "passed" }];
    writeFileSync(localInput, `${JSON.stringify(localDocument, null, 2)}\n`);
    assert.match(run(["finalize", localInput], 2).stderr, /file_hash 与本地文件不匹配/);
    localDocument.artifacts.attachments = [reviewedAttachment(attachment)];
    writeFileSync(localInput, `${JSON.stringify(localDocument, null, 2)}\n`);
    run(["finalize", localInput]);

    const remoteDirectory = mkdtempSync(resolve(tmpdir(), "review-brief-remote-only-"));
    const remoteInput = copyFixture(remoteDirectory);
    const remoteDocument = JSON.parse(readFileSync(remoteInput, "utf8"));
    const remoteAttachment = {
      alt_text: "没有本地证据的远端图片",
      github_url: githubAssetUrl,
    };
    remoteDocument.review_brief.main_changes[0].attachments = [remoteAttachment];
    remoteDocument.artifacts.attachments = [{
      ...remoteAttachment,
      visual_review: "passed",
      file_hash: "0".repeat(64),
    }];
    writeFileSync(remoteInput, `${JSON.stringify(remoteDocument, null, 2)}\n`);
    const finalized = run(["finalize", remoteInput], 2);
    assert.match(finalized.stderr, /file_hash 与本地文件不匹配/);

    remoteDocument.artifacts.attachments = [{
      ...remoteAttachment,
      visual_review: "skipped",
      github_target_identity: remoteDocument.review_brief.target.identity,
    }];
    writeFileSync(remoteInput, `${JSON.stringify(remoteDocument, null, 2)}\n`);
    assert.match(run(["finalize", remoteInput], 2).stderr, /绑定当前目标与本地 file_hash/);

    remoteDocument.artifacts.attachments = [{
      ...remoteAttachment,
      visual_review: "skipped",
      file_hash: "0".repeat(64),
      github_file_hash: "0".repeat(64),
      github_target_identity: remoteDocument.review_brief.target.identity,
    }];
    writeFileSync(remoteInput, `${JSON.stringify(remoteDocument, null, 2)}\n`);
    assert.match(run(["finalize", remoteInput], 2).stderr, /绑定当前目标与本地 file_hash/);

    localDocument.review_brief.main_changes[0].attachments = [{
      ...attachment,
      github_url: githubAssetUrl,
    }];
    localDocument.artifacts.attachments = [{
      ...attachment,
      github_url: githubAssetUrl,
      visual_review: "skipped",
      file_hash: "0".repeat(64),
      github_file_hash: "0".repeat(64),
      github_target_identity: localDocument.review_brief.target.identity,
    }];
    writeFileSync(localInput, `${JSON.stringify(localDocument, null, 2)}\n`);
    const localFakeHash = run(["finalize", localInput], 2);
    assert.match(localFakeHash.stderr, /绑定当前目标与本地 file_hash/);
  });

  test("GitHub 文本和替代文本不能逃逸受控 Markdown 结构", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-markdown-url-"));
    const input = copyFixture(directory);
    const screenshot = resolve(directory, "safe.png");
    writeFileSync(screenshot, pngBytes());
    const document = JSON.parse(readFileSync(input, "utf8"));
    document.review_brief.overview = "正常概要\n\n伪造结论\n========\n\n![外部追踪](https://evil.example/tracker.png)\n\n@attacker";
    const attachment = {
      alt_text: "x\\](https://evil.example/from-alt.png) ignored",
      local_path: screenshot,
    };
    document.review_brief.main_changes[0].attachments = [attachment];
    document.artifacts.attachments = [githubBoundArtifact(document, reviewedAttachment(attachment))];
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    run(["finalize", input]);
    const bindings = writeGitHubBindings(directory, document);

    const output = resolve(directory, "github.md");
    run(["render-github", input, "--require-image", "--github-bindings", bindings, "--output", output]);
    const markdown = readFileSync(output, "utf8");
    assert.equal((markdown.match(/!\[/g) ?? []).length, 1);
    assert.ok(!markdown.includes("](https://evil.example"));
    assert.ok(!markdown.includes("@attacker"));
    assert.ok(markdown.includes("&#64;attacker"));
    assert.ok(!markdown.includes("\n========"));
    assert.equal((markdown.match(/^## /gm) ?? []).length, 6);

    for (const blockToken of ["---", "- 列表", "+ 列表", "1. 列表"]) {
      const escapedDocument = JSON.parse(readFileSync(input, "utf8"));
      escapedDocument.review_brief.overview = blockToken;
      writeFileSync(input, `${JSON.stringify(escapedDocument, null, 2)}\n`);
      run(["finalize", input]);
      const escapedOutput = resolve(directory, `escaped-${blockToken.charCodeAt(0)}.md`);
      run(["render-github", input, "--output", escapedOutput]);
      const escapedMarkdown = readFileSync(escapedOutput, "utf8");
      assert.ok(!escapedMarkdown.includes(`\n${blockToken}\n`));
    }
  });

  test("GitHub 图片 URL 必须是目标与本地 hash 绑定的匿名附件", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-github-binding-"));
    const input = copyFixture(directory);
    const screenshot = resolve(directory, "safe.png");
    writeFileSync(screenshot, pngBytes());
    const document = JSON.parse(readFileSync(input, "utf8"));
    const attachment = { alt_text: "预约卡片截图", local_path: screenshot };
    document.review_brief.main_changes[0].attachments = [attachment];
    const artifact = reviewedAttachment(attachment);
    document.artifacts.attachments = [{
      ...artifact,
      github_url: "https://raw.githubusercontent.com/attacker/repo/main/other.png",
      github_file_hash: artifact.file_hash,
      github_target_identity: document.review_brief.target.identity,
    }];
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    assert.match(run(["finalize", input], 2).stderr, /GitHub HTTPS 附件 URL/);

    document.artifacts.attachments = [{
      ...githubBoundArtifact(document, artifact),
      github_target_identity: "other/repo#999",
    }];
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    assert.match(run(["finalize", input], 2).stderr, /绑定当前目标与本地 file_hash/);

    document.artifacts.attachments = [githubBoundArtifact(document, artifact)];
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    run(["finalize", input]);
    const bindings = writeGitHubBindings(directory, document);
    run([
      "render-github", input, "--require-image", "--github-bindings", bindings,
      "--output", resolve(directory, "github.md"),
    ]);
    const bindingsBefore = readFileSync(bindings);
    const overwrittenBindings = run([
      "render-github", input, "--require-image", "--github-bindings", bindings,
      "--output", bindings,
    ], 2);
    assert.match(overwrittenBindings.stderr, /--output 不能覆盖/);
    assert.deepEqual(readFileSync(bindings), bindingsBefore);

    const bindingsAlias = resolve(directory, "bindings-output-link.json");
    symlinkSync(bindings, bindingsAlias);
    const overwrittenAlias = run([
      "render-github", input, "--require-image", "--github-bindings", bindings,
      "--output", bindingsAlias,
    ], 2);
    assert.match(overwrittenAlias.stderr, /--output 不能覆盖/);
    assert.deepEqual(readFileSync(bindings), bindingsBefore);

    const otherUrl = "https://github.com/user-attachments/assets/00000000-0000-4000-8000-000000000002";
    document.artifacts.attachments = [githubBoundArtifact(document, artifact, otherUrl)];
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    run(["finalize", input]);
    const mismatched = run([
      "render-github", input, "--require-image", "--github-bindings", bindings,
      "--output", resolve(directory, "mismatched.md"),
    ], 3);
    assert.match(mismatched.stderr, /没有通过门禁且可用于 GitHub 的附件 URL/);

    document.artifacts.attachments = [githubBoundArtifact(document, artifact)];
    document.schema_version = 1;
    document.target_identity = document.review_brief.target.identity;
    document.assets = [{ url: githubAssetUrl, sha256: artifact.file_hash }];
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    run(["finalize", input]);
    const selfBound = run([
      "render-github", input, "--require-image", "--github-bindings", input,
      "--output", resolve(directory, "self-bound.md"),
    ], 3);
    assert.match(selfBound.stderr, /必须位于候选 ReviewBrief 产物目录之外/);

    const externalDirectory = mkdtempSync(resolve(tmpdir(), "review-brief-hardlink-bindings-"));
    const hardlink = resolve(externalDirectory, "github-bindings.json");
    linkSync(bindings, hardlink);
    const hardlinkBound = run([
      "render-github", input, "--require-image", "--github-bindings", hardlink,
      "--output", resolve(directory, "hardlink-bound.md"),
    ], 3);
    assert.match(hardlinkBound.stderr, /产物目录之外|不得是硬链接/);

    const symlink = resolve(externalDirectory, "github-bindings-link.json");
    symlinkSync(bindings, symlink);
    const symlinkBound = run([
      "render-github", input, "--require-image", "--github-bindings", symlink,
      "--output", resolve(directory, "symlink-bound.md"),
    ], 3);
    assert.match(symlinkBound.stderr, /不得是 symlink/);
  });
});

describe("Slack 渠道渲染", () => {
  test("生成同源精简消息和待上传文件列表", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-slack-"));
    const input = copyFixture(directory);
    const output = resolve(directory, "slack.md");
    const result = parseResult(run([
      "render-slack", input,
      "--target-url", "https://github.com/MoeGolibrary/example/pull/128",
      "--output", output,
    ]));
    const markdown = readFileSync(output, "utf8");
    assert.equal(result.channel, "slack");
    for (const block of result.blocks) {
      assert.equal(block.type, "context");
      assert.equal(block.elements.length, 1);
      assert.equal(block.elements[0].type, "mrkdwn");
      assert.equal(block.elements[0].verbatim, true);
      assert.ok(block.elements[0].text.length <= 3_000);
    }
    assert.equal(result.blocks.map((block) => block.elements[0].text).join("\n"), markdown.trimEnd());
    assert.equal(result.render_hash, createHash("sha256")
      .update(JSON.stringify({ markdown, blocks: result.blocks, fileHashes: [] })).digest("hex"));

    assert.deepEqual(result.files, []);
    assert.ok(markdown.includes("预约确认流程现在会先保存预约"));
    assert.ok(!markdown.includes("MoeGolibrary/example#128"));
    assert.ok(!markdown.includes("https://github.com/MoeGolibrary/example/pull/128"));
    assert.equal((markdown.match(/^- \*/gm) ?? []).length, 3);
    assert.ok(!markdown.includes("permalink"));
    assert.ok(!markdown.includes("visual_review"));
  });

  test("长 Brief 按完整行分为 context，保留正文且不重复目标行", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-slack-context-"));
    const input = copyFixture(directory);
    const document = JSON.parse(readFileSync(input, "utf8"));
    document.review_brief.overview = "预约信息".repeat(250);
    for (const change of document.review_brief.main_changes.slice(0, 3)) {
      change.title = "字段含义".repeat(25);
      change.description = "预约数据".repeat(90);
    }
    document.review_brief.reading_route = ["阅读入口".repeat(50), "阅读领域".repeat(50), "阅读消费方".repeat(40)];
    document.review_brief.review_focus = [];
    writeFileSync(input, JSON.stringify(document));
    run(["finalize", input]);
    const output = resolve(directory, "slack.md");
    const result = parseResult(run(["render-slack", input, "--target-url",
      "https://github.com/MoeGolibrary/example/pull/128", "--output", output]));
    assert.ok(result.blocks.length > 1);
    const texts = result.blocks.map((block) => {
      assert.equal(block.type, "context");
      assert.ok(block.elements[0].text.length <= 3_000);
      return block.elements[0].text;
    });
    assert.equal(texts.join("\n"), readFileSync(output, "utf8").trimEnd());
    assert.ok(!texts.join("\n").includes("https://github.com/MoeGolibrary/example/pull/128"));
  });

  test("无链接时也省略目标行并转义 Slack 特殊文本", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-slack-escape-"));
    const input = copyFixture(directory);
    const document = JSON.parse(readFileSync(input, "utf8"));
    document.review_brief.target.identity = "PR <#C123>|&";
    document.review_brief.overview = "请勿触发 <!channel>、<!here> 或 <@U123> & 原样标记。";
    document.review_brief.main_changes[0].title = "标题 <script> & *伪造*";
    document.review_brief.main_changes[0].description = "描述包含 <@U456>。\n\n*格式*\n- 伪造段落";
    document.review_brief.review_focus = ["确认 <tag> & 内容只作为文字。"];
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    run(["finalize", input]);

    const output = resolve(directory, "slack.md");
    const result = parseResult(run(["render-slack", input, "--output", output]));
    const native = JSON.stringify(result.blocks);
    assert.ok(native.includes("&lt;!channel&gt;"));
    assert.ok(!native.includes("<!channel>"));
    assert.ok(!/"type":"(user|usergroup|broadcast|channel)"/.test(native));
    assert.ok(native.includes("标题 &lt;script&gt; &amp; ＊伪造＊"));
    const markdown = readFileSync(output, "utf8");
    assert.ok(!markdown.includes("*目标*"));
    assert.ok(!markdown.includes("C123"));
    assert.ok(markdown.includes("&lt;!channel&gt;"));
    assert.ok(markdown.includes("&lt;@U123&gt;"));
    assert.ok(!markdown.includes("<!channel>"));
    assert.ok(!markdown.includes("<@U456>"));
    assert.ok(!markdown.includes("*格式*"));
    assert.ok(!markdown.includes("\n- 伪造段落"));
    assert.ok(markdown.includes("＊格式＊"));
  });

  test("Slack 仍校验 PR 链接身份，但不展示分支目标行", () => {
    const mismatchDirectory = mkdtempSync(resolve(tmpdir(), "review-brief-slack-target-mismatch-"));
    const mismatchInput = copyFixture(mismatchDirectory);
    const mismatch = run([
      "render-slack", mismatchInput,
      "--target-url", "https://github.com/other/repository/pull/999",
      "--output", resolve(mismatchDirectory, "slack.md"),
    ], 3);
    assert.match(mismatch.stderr, /与 ReviewBrief 的 PR 目标身份不一致/);

    const branchDirectory = mkdtempSync(resolve(tmpdir(), "review-brief-slack-label-"));
    const branchInput = copyFixture(branchDirectory);
    const document = JSON.parse(readFileSync(branchInput, "utf8"));
    document.review_brief.target.kind = "branch";
    document.review_brief.target.identity = "release|spoof";
    writeFileSync(branchInput, `${JSON.stringify(document, null, 2)}\n`);
    run(["finalize", branchInput]);
    const output = resolve(branchDirectory, "slack.md");
    run([
      "render-slack", branchInput,
      "--target-url", "https://github.com/MoeGolibrary/example/tree/release",
      "--output", output,
    ]);
    const markdown = readFileSync(output, "utf8");
    assert.ok(!markdown.includes("release"));
    assert.ok(!markdown.includes("&#124;"));
  });

  test("Slack 目标 URL 不接受凭据、query、fragment 或非默认端口", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-slack-url-secret-"));
    const input = copyFixture(directory);
    for (const url of [
      "https://user:secret@github.com/MoeGolibrary/example/pull/128",
      "https://github.com:444/MoeGolibrary/example/pull/128",
      "https://github.com/MoeGolibrary/example/pull/128?token=abc",
      "https://github.com/MoeGolibrary/example/pull/128#secret",
    ]) {
      const result = run([
        "render-slack", input, "--target-url", url,
        "--output", resolve(directory, "slack.md"),
      ], 3);
      assert.match(result.stderr, /不得包含 credentials/);
      assert.ok(!result.stderr.includes("secret@"));
      assert.ok(!result.stderr.includes("token=abc"));
    }
  });

  test("Slack 对长字段做确定性精简并保持在 4000 字符内", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-slack-length-"));
    const input = copyFixture(directory);
    const document = JSON.parse(readFileSync(input, "utf8"));
    document.review_brief.overview = "概".repeat(20_000);
    for (const change of document.review_brief.main_changes) {
      change.title = "标题".repeat(5_000);
      change.description = "描述".repeat(10_000);
    }
    document.review_brief.reading_route = document.review_brief.reading_route.map(() => "路线".repeat(10_000));
    const svg = resolve(directory, "flow.svg");
    const png = resolve(directory, "flow.png");
    writeFileSync(svg, "<svg xmlns=\"http://www.w3.org/2000/svg\"></svg>\n");
    writeFileSync(png, pngBytes());
    document.review_brief.diagram = {
      type: "sequence",
      alt_text: "导览".repeat(10_000),
      source_hash: fileHash(svg),
    };
    document.artifacts.diagram = {
      svg_path: svg,
      png_path: png,
      png_hash: fileHash(png),
      visual_review: "passed",
    };
    writeFileSync(input, `${JSON.stringify(document)}\n`);
    run(["finalize", input]);
    const output = resolve(directory, "slack.md");
    run(["render-slack", input, "--output", output]);
    const markdown = readFileSync(output, "utf8");
    assert.ok(markdown.length <= 4_000);
    assert.ok(markdown.includes("…"));
  });

  test("Slack 返回技术图时同时在正文解释该图", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-slack-diagram-"));
    const input = copyFixture(directory);
    const svg = resolve(directory, "flow.svg");
    const png = resolve(directory, "flow.png");
    writeFileSync(svg, "<svg xmlns=\"http://www.w3.org/2000/svg\"></svg>\n");
    writeFileSync(png, pngBytes());
    const document = JSON.parse(readFileSync(input, "utf8"));
    document.review_brief.diagram = {
      type: "sequence",
      alt_text: "预约保存与异步通知流程",
      source_hash: fileHash(svg),
    };
    document.artifacts.diagram = {
      svg_path: svg,
      png_path: png,
      png_hash: fileHash(png),
      visual_review: "passed",
    };
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    run(["finalize", input]);
    const output = resolve(directory, "slack.md");
    const result = parseResult(run(["render-slack", input, "--output", output]));
    assert.ok(readFileSync(output, "utf8").includes("*变更导览图*：预约保存与异步通知流程"));
    assert.deepEqual(result.files, [{ path: png, sha256: fileHash(png) }]);
  });

  test("普通附件必须与 artifact 一一对应且通过视觉门禁才可发布", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-attachment-contract-"));
    const input = copyFixture(directory);
    const screenshot = resolve(directory, "booking.png");
    writeFileSync(screenshot, pngBytes());
    const document = JSON.parse(readFileSync(input, "utf8"));
    const attachment = { alt_text: "预约卡片截图", local_path: screenshot };
    document.review_brief.main_changes[0].attachments = [attachment];
    document.artifacts.attachments = [{ ...attachment }];
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    run(["finalize", input]);

    const slack = parseResult(run([
      "render-slack", input, "--output", resolve(directory, "slack.md"),
    ]));
    assert.deepEqual(slack.files, []);

    const conflict = JSON.parse(readFileSync(input, "utf8"));
    conflict.review_brief.main_changes[0].attachments[0].github_url =
      "https://github.com/user-attachments/assets/00000000-0000-4000-8000-000000000001";
    conflict.artifacts.attachments[0].github_url =
      "https://github.com/user-attachments/assets/00000000-0000-4000-8000-000000000002";
    conflict.artifacts.attachments[0].visual_review = "passed";
    writeFileSync(input, `${JSON.stringify(conflict, null, 2)}\n`);
    const finalized = run(["finalize", input], 2);
    assert.match(finalized.stderr, /github_url 冲突/);
  });

  test("返回去重后的本地 PNG，并让文件变化进入 render_hash", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-slack-files-"));
    const input = copyFixture(directory);
    const screenshot = resolve(directory, "booking.png");
    writeFileSync(screenshot, pngBytes());
    const document = JSON.parse(readFileSync(input, "utf8"));
    const attachment = {
      alt_text: "预约卡片更新后截图",
      local_path: screenshot,
    };
    document.review_brief.main_changes[0].attachments = [attachment];
    document.artifacts.attachments = [reviewedAttachment(attachment)];
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    run(["finalize", input]);

    const first = parseResult(run([
      "render-slack", input, "--output", resolve(directory, "first.md"),
    ]));
    assert.deepEqual(first.files, [{ path: screenshot, sha256: fileHash(screenshot) }]);

    writeFileSync(screenshot, pngBytes(1));
    const stale = run([
      "render-slack", input, "--output", resolve(directory, "stale.md"),
    ], 2);
    assert.match(stale.stderr, /file_hash 与本地文件不匹配/);

    const reviewed = JSON.parse(readFileSync(input, "utf8"));
    reviewed.artifacts.attachments[0].file_hash = fileHash(screenshot);
    writeFileSync(input, `${JSON.stringify(reviewed, null, 2)}\n`);
    run(["finalize", input]);
    const second = parseResult(run([
      "render-slack", input, "--output", resolve(directory, "second.md"),
    ]));
    assert.deepEqual(second.files, [{ path: screenshot, sha256: fileHash(screenshot) }]);
    assert.notEqual(second.render_hash, first.render_hash);
    assert.equal(second.content_hash, first.content_hash);
  });

  test("Slack 按规范路径去重同一份本地 PNG", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-slack-canonical-path-"));
    const input = copyFixture(directory);
    const nested = resolve(directory, "nested");
    mkdirSync(nested);
    const screenshot = resolve(directory, "booking.png");
    const alias = `${nested}/../booking.png`;
    const linkedDirectory = resolve(directory, "linked-directory");
    symlinkSync(directory, linkedDirectory);
    writeFileSync(screenshot, pngBytes());
    const document = JSON.parse(readFileSync(input, "utf8"));
    const attachments = [
      { alt_text: "预约卡片截图", local_path: screenshot },
      { alt_text: "同一预约卡片截图", local_path: alias },
      { alt_text: "父目录别名下的预约卡片截图", local_path: `${linkedDirectory}/booking.png` },
    ];
    document.review_brief.main_changes[0].attachments = attachments;
    document.artifacts.attachments = attachments.map(reviewedAttachment);
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    run(["finalize", input]);

    const result = parseResult(run([
      "render-slack", input, "--output", resolve(directory, "slack.md"),
    ]));
    assert.deepEqual(result.files, [{ path: screenshot, sha256: fileHash(screenshot) }]);
  });

  test("所有校验在解压前拒绝超宽 PNG 行", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-slack-wide-row-"));
    const input = copyFixture(directory);
    const screenshot = resolve(directory, "wide.png");
    const width = 2_097_153;
    writeFileSync(screenshot, rgbaPng(Buffer.alloc(width * 4 + 1), width, 1));
    const document = JSON.parse(readFileSync(input, "utf8"));
    const attachment = { alt_text: "超宽截图", local_path: screenshot };
    document.review_brief.main_changes[0].attachments = [attachment];
    document.artifacts.attachments = [reviewedAttachment(attachment)];
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    const finalized = run(["finalize", input], 2);
    assert.match(finalized.stderr, /必须是有效的 PNG 文件/);
  });

  test("所有校验在解压前拒绝过多 scanline 与 PNG chunk", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-slack-png-operations-"));
    const input = copyFixture(directory);
    const scanlines = resolve(directory, "scanlines.png");
    writeFileSync(scanlines, rgbaPng(Buffer.alloc(0), 1, 100_001));

    const chunks = resolve(directory, "chunks.png");
    const header = Buffer.alloc(13);
    header.writeUInt32BE(1, 0);
    header.writeUInt32BE(1, 4);
    header[8] = 8;
    header[9] = 6;
    writeFileSync(chunks, Buffer.concat([
      Buffer.from("89504e470d0a1a0a", "hex"),
      pngChunk("IHDR", header),
      ...Array.from({ length: 8_193 }, () => pngChunk("tEXt", Buffer.alloc(0))),
      pngChunk("IDAT", deflateSync(Buffer.from([0, 0, 0, 0, 0]))),
      pngChunk("IEND", Buffer.alloc(0)),
    ]));

    for (const path of [scanlines, chunks]) {
      const document = JSON.parse(readFileSync(sourceFixture, "utf8"));
      const attachment = { alt_text: "资源放大图片", local_path: path };
      document.review_brief.main_changes[0].attachments = [attachment];
      document.artifacts.attachments = [reviewedAttachment(attachment)];
      writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
      const finalized = run(["finalize", input], 2);
      assert.match(finalized.stderr, /必须是有效的 PNG 文件/);
    }
  });

  test("默认跳过非 PNG 本地附件", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-slack-non-png-"));
    const input = copyFixture(directory);
    const svg = resolve(directory, "booking.svg");
    const truncatedPng = resolve(directory, "truncated.png");
    const invalidScanlinePng = resolve(directory, "invalid-scanline.png");
    const oversizedPalettePng = resolve(directory, "oversized-palette.png");
    const invalidPaletteIndexPng = resolve(directory, "invalid-palette-index.png");
    writeFileSync(svg, "<svg xmlns=\"http://www.w3.org/2000/svg\"></svg>\n");
    writeFileSync(truncatedPng, Buffer.from("89504e470d0a1a0a", "hex"));
    writeFileSync(invalidScanlinePng, rgbaPng(Buffer.from("hello")));
    writeFileSync(oversizedPalettePng, indexedPng(1, 3));
    writeFileSync(invalidPaletteIndexPng, indexedPng(1, 1, 1));
    const document = JSON.parse(readFileSync(input, "utf8"));
    const attachments = [
      { alt_text: "预约卡片源文件", local_path: svg },
      { alt_text: "截断的 PNG", local_path: truncatedPng },
      { alt_text: "scanline 无效的 PNG", local_path: invalidScanlinePng },
      { alt_text: "调色板越界的 PNG", local_path: oversizedPalettePng },
      { alt_text: "像素索引越界的 PNG", local_path: invalidPaletteIndexPng },
    ];
    document.review_brief.main_changes[0].attachments = attachments;
    document.artifacts.attachments = attachments.map((attachment, index) => (
      index === 0 ? reviewedAttachment(attachment) : { ...attachment, visual_review: "skipped" }
    ));
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    run(["finalize", input]);

    const result = parseResult(run([
      "render-slack", input, "--output", resolve(directory, "slack.md"),
    ]));
    assert.deepEqual(result.files, []);
  });

  test("Slack 只返回精简正文前三项变化对应的附件", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-slack-selected-"));
    const input = copyFixture(directory);
    const document = JSON.parse(readFileSync(input, "utf8"));
    const attachments = [];
    for (let index = 0; index < 4; index += 1) {
      const screenshot = resolve(directory, `change-${index + 1}.png`);
      writeFileSync(screenshot, pngBytes());
      const attachment = { alt_text: `变化 ${index + 1} 截图`, local_path: screenshot };
      attachments.push(attachment);
      if (index < document.review_brief.main_changes.length) {
        document.review_brief.main_changes[index].attachments = [attachment];
      } else {
        document.review_brief.main_changes.push({
          title: "第四项变化",
          description: "该变化不会进入 Slack 的三项精简正文。",
          code_refs: ["src/fourth.ts:fourth"],
          attachments: [attachment],
        });
      }
    }
    document.artifacts.attachments = attachments.map(reviewedAttachment);
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    run(["finalize", input]);

    const result = parseResult(run([
      "render-slack", input, "--output", resolve(directory, "slack.md"),
    ]));
    assert.deepEqual(
      result.files,
      attachments.slice(0, 3).map((item) => ({
        path: item.local_path,
        sha256: fileHash(item.local_path),
      })),
    );
    assert.ok(!readFileSync(resolve(directory, "slack.md"), "utf8").includes("第四项变化"));
  });

  test("Slack 渲染与校验上传共享 20 文件批次上限", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-slack-file-count-"));
    const input = copyFixture(directory);
    const document = JSON.parse(readFileSync(input, "utf8"));
    const attachments = Array.from({ length: 21 }, (_, index) => {
      const path = resolve(directory, `image-${index}.png`);
      writeFileSync(path, pngBytes());
      return { alt_text: `截图 ${index}`, local_path: path };
    });
    document.review_brief.main_changes[0].attachments = attachments;
    document.artifacts.attachments = attachments.map(reviewedAttachment);
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    run(["finalize", input]);

    const result = run([
      "render-slack", input, "--output", resolve(directory, "slack.md"),
    ], 3);
    assert.match(result.stderr, /最多包含 20 个文件/);
  });

  test("Slack 在技术图深度解析前拒绝 21 个候选文件", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-slack-diagram-count-"));
    const input = copyFixture(directory);
    const document = JSON.parse(readFileSync(input, "utf8"));
    const attachments = Array.from({ length: 20 }, (_, index) => {
      const path = resolve(directory, `image-${index}.png`);
      writeFileSync(path, pngBytes());
      return { alt_text: `截图 ${index}`, local_path: path };
    });
    document.review_brief.main_changes[0].attachments = attachments;
    document.artifacts.attachments = attachments.map(reviewedAttachment);
    const svg = resolve(directory, "flow.svg");
    const invalidPng = resolve(directory, "invalid.png");
    writeFileSync(svg, "<svg xmlns=\"http://www.w3.org/2000/svg\"></svg>\n");
    writeFileSync(invalidPng, Buffer.from("not-a-png"));
    document.review_brief.diagram = {
      type: "sequence",
      alt_text: "批次门禁顺序图",
      source_hash: fileHash(svg),
    };
    document.artifacts.diagram = {
      svg_path: svg,
      png_path: invalidPng,
      png_hash: fileHash(invalidPng),
      visual_review: "passed",
    };
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);

    const result = run([
      "render-slack", input, "--output", resolve(directory, "slack.md"),
    ], 3);
    assert.match(result.stderr, /最多包含 20 个文件/);
    assert.ok(!result.stderr.includes("有效 PNG"));
  });

  test("所有校验与渲染在 hash 前拒绝超过 100 MiB 的本地产物", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-slack-global-budget-"));
    const input = copyFixture(directory);
    const document = JSON.parse(readFileSync(input, "utf8"));
    const artifacts = [];
    for (let index = 0; index < 5; index += 1) {
      const path = resolve(directory, `large-${index}.png`);
      writeFileSync(path, "");
      truncateSync(path, 25 * 1024 * 1024);
      const attachment = { alt_text: `后续变化 ${index + 1} 截图`, local_path: path };
      document.review_brief.main_changes.push({
        title: `后续变化 ${index + 1}`,
        description: "该变化位于 Slack 精简正文的前三项之后。",
        code_refs: [`src/later-${index}.ts:change`],
        attachments: [attachment],
      });
      artifacts.push({
        ...attachment,
        visual_review: "passed",
        file_hash: "a".repeat(64),
      });
    }
    document.artifacts.attachments = artifacts;
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);

    for (const [args, exitCode] of [
      [["finalize", input], 2],
      [["check", input], 2],
      [["render-github", input, "--output", resolve(directory, "github.md")], 2],
      [["render-slack", input, "--output", resolve(directory, "slack.md")], 3],
    ]) {
      const result = run(args, exitCode);
      assert.match(result.stderr, /全部本地产物总计不得超过 100 MiB/);
    }
  });

  test("所有校验在 PNG 解析前限制累计解压预算", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-inflated-budget-"));
    const input = copyFixture(directory);
    const document = JSON.parse(readFileSync(input, "utf8"));
    const artifacts = [];
    for (let index = 0; index < 2; index += 1) {
      const path = resolve(directory, `expanded-${index}.png`);
      const header = Buffer.alloc(29);
      Buffer.from("89504e470d0a1a0a", "hex").copy(header, 0);
      header.writeUInt32BE(13, 8);
      header.write("IHDR", 12, "ascii");
      header.writeUInt32BE(5_000, 16);
      header.writeUInt32BE(5_000, 20);
      header[24] = 8;
      header[25] = 6;
      header[28] = 0;
      writeFileSync(path, header);
      const attachment = { alt_text: `高解压预算 ${index + 1}`, local_path: path };
      document.review_brief.main_changes[index].attachments = [attachment];
      artifacts.push({ ...attachment, visual_review: "passed", file_hash: "a".repeat(64) });
    }
    document.artifacts.attachments = artifacts;
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);

    const result = run(["check", input], 2);
    assert.match(result.stderr, /累计解压预算不得超过 64 MiB/);
  });

  test("Slack 对畸形本地产物路径返回结构化错误", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-slack-path-type-"));
    const input = copyFixture(directory);
    const document = JSON.parse(readFileSync(input, "utf8"));
    document.artifacts.attachments = [{ local_path: {}, alt_text: "错误路径" }];
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    const result = run([
      "render-slack", input, "--output", resolve(directory, "slack.md"),
    ], 2);
    assert.match(result.stderr, /本地产物路径必须是绝对路径字符串/);
    assert.ok(!result.stderr.includes("    at "));
  });

  test("Slack 拒绝产物目录之外的待上传 PNG", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-slack-root-"));
    const externalDirectory = mkdtempSync(resolve(tmpdir(), "review-brief-external-"));
    const input = copyFixture(directory);
    const screenshot = resolve(externalDirectory, "outside.png");
    writeFileSync(screenshot, pngBytes());
    const document = JSON.parse(readFileSync(input, "utf8"));
    const attachment = { alt_text: "目录外截图", local_path: screenshot };
    document.review_brief.main_changes[0].attachments = [attachment];
    document.artifacts.attachments = [reviewedAttachment(attachment)];
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    run(["finalize", input]);

    const rendered = run([
      "render-slack", input, "--output", resolve(directory, "slack.md"),
    ], 3);
    assert.match(rendered.stderr, /必须位于 ReviewBrief 产物目录内/);
  });

  test("相同文件名和内容在不同目录得到相同 render_hash", () => {
    const hashes = [];
    for (const prefix of ["review-brief-slack-path-a-", "review-brief-slack-path-b-"]) {
      const directory = mkdtempSync(resolve(tmpdir(), prefix));
      const input = copyFixture(directory);
      const screenshot = resolve(directory, "booking.png");
      writeFileSync(screenshot, pngBytes());
      const document = JSON.parse(readFileSync(input, "utf8"));
      const attachment = { alt_text: "预约卡片截图", local_path: screenshot };
      document.review_brief.main_changes[0].attachments = [attachment];
      document.artifacts.attachments = [reviewedAttachment(attachment)];
      writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
      run(["finalize", input]);
      hashes.push(parseResult(run([
        "render-slack", input, "--output", resolve(directory, "slack.md"),
      ])).render_hash);
    }
    assert.equal(hashes[0], hashes[1]);
  });
});

describe("确定性评测器", () => {
  test("畸形 JSON 和缺失模型都生成失败评分而不崩溃", () => {
    for (const [name, content] of [
      ["malformed", "{"],
      ["missing-shape", "{}"],
      ["null-root", "null"],
      ["array-root", "[]"],
    ]) {
      const directory = mkdtempSync(resolve(tmpdir(), `review-brief-grader-${name}-`));
      const outputs = resolve(directory, "outputs");
      mkdirSync(outputs);
      writeFileSync(resolve(outputs, "review-brief.json"), content);
      writeFileSync(resolve(outputs, "review-brief.md"), "## 概要\n\n候选输出。\n");
      const result = spawnSync("node", [grader, "1", outputs, skillRoot], { encoding: "utf8" });
      assert.equal(result.status, 1, result.stderr || result.stdout);
      const grading = JSON.parse(readFileSync(resolve(directory, "grading.json"), "utf8"));
      assert.ok(grading.summary.failed > 0);
      assert.equal(grading.summary.total, 3);
    }
  });

  test("不存在的输出目录返回明确参数错误而不抛堆栈", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-grader-missing-"));
    const missing = resolve(directory, "not-created");
    const result = spawnSync("node", [grader, "1", missing, skillRoot], { encoding: "utf8" });
    assert.equal(result.status, 2);
    assert.match(result.stderr, /输出目录不可用/);
    assert.ok(!result.stderr.includes("    at "));
  });

  test("grader 拒绝输出根本身为 symlink", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-grader-root-symlink-"));
    const realParent = resolve(directory, "real-parent");
    const realOutputs = resolve(realParent, "outputs");
    mkdirSync(realParent);
    mkdirSync(realOutputs);
    writeFileSync(resolve(realOutputs, "answer.md"), "这是 finding/verdict 场景，应交给 review-swarm。\n");
    const linkedParent = resolve(directory, "linked-parent");
    mkdirSync(linkedParent);
    const linkedOutputs = resolve(linkedParent, "outputs");
    symlinkSync(realOutputs, linkedOutputs);

    const result = spawnSync("node", [grader, "4", linkedOutputs, skillRoot], { encoding: "utf8" });
    assert.equal(result.status, 2);
    assert.match(result.stderr, /本身不得是 symlink/);
    assert.ok(!result.stderr.includes("    at "));
  });

  test("评测器用文件元数据统计并拒绝总字节超限", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-grader-resource-limit-"));
    const outputs = resolve(directory, "outputs");
    mkdirSync(outputs);
    const oversized = resolve(outputs, "unrelated.bin");
    writeFileSync(oversized, "x");
    truncateSync(oversized, 101 * 1024 * 1024);
    const result = spawnSync("node", [grader, "1", outputs, skillRoot], { encoding: "utf8" });
    assert.equal(result.status, 1, result.stderr || result.stdout);
    const grading = JSON.parse(readFileSync(resolve(directory, "grading.json"), "utf8"));
    assert.ok(grading.expectations.some((item) => /资源上限/.test(item.text) && !item.passed));
    assert.equal(grading.execution_metrics.output_chars, 101 * 1024 * 1024);
  });

  test("评测器在父进程解析前拒绝超过 4 MiB 的候选 JSON", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-grader-candidate-limit-"));
    const outputs = resolve(directory, "outputs");
    mkdirSync(outputs);
    writeFileSync(
      resolve(outputs, "review-brief.json"),
      JSON.stringify({ padding: "x".repeat(4 * 1024 * 1024) }),
    );
    writeFileSync(resolve(outputs, "review-brief.md"), "## 概要\n\n候选输出。\n");
    const result = spawnSync("node", [grader, "1", outputs, skillRoot], { encoding: "utf8" });
    assert.equal(result.status, 1, result.stderr || result.stdout);
    const grading = JSON.parse(readFileSync(resolve(directory, "grading.json"), "utf8"));
    assert.ok(grading.summary.failed > 0);
    assert.ok(grading.expectations.some((item) => /超过 4 MiB/.test(item.evidence)));
  });

  test("评测器流式扫描并拒绝超宽输出目录", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-grader-entry-limit-"));
    const outputs = resolve(directory, "outputs");
    mkdirSync(outputs);
    for (let index = 0; index <= 1_000; index += 1) {
      writeFileSync(resolve(outputs, `entry-${index}.txt`), "x");
    }
    const result = spawnSync("node", [grader, "1", outputs, skillRoot], { encoding: "utf8" });
    assert.equal(result.status, 1, result.stderr || result.stdout);
    const grading = JSON.parse(readFileSync(resolve(directory, "grading.json"), "utf8"));
    assert.ok(grading.expectations.some((item) => /资源上限/.test(item.text) && !item.passed));
    assert.ok(grading.execution_metrics.files_created.length <= 1_001);
  });

  test("评测器拒绝畸形 artifact 路径类型并仍生成评分", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-grader-path-type-"));
    const outputs = resolve(directory, "outputs");
    mkdirSync(outputs);
    const input = copyFixture(outputs);
    const document = JSON.parse(readFileSync(input, "utf8"));
    document.artifacts.attachments = [{ local_path: 123 }];
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    writeFileSync(resolve(outputs, "review-brief.md"), "## 概要\n\n候选输出。\n");

    const result = spawnSync("node", [grader, "1", outputs, skillRoot], { encoding: "utf8" });
    assert.equal(result.status, 1, result.stderr || result.stdout);
    const grading = JSON.parse(readFileSync(resolve(directory, "grading.json"), "utf8"));
    assert.ok(grading.summary.failed > 0);
  });

  test("评测器按真实身份只物化一份 artifact 别名快照", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-grader-artifact-alias-budget-"));
    const outputs = resolve(directory, "outputs");
    mkdirSync(outputs);
    const input = copyFixture(outputs);
    const artifact = resolve(outputs, "shared.bin");
    writeFileSync(artifact, Buffer.alloc(2 * 1024 * 1024));
    const hash = fileHash(artifact);
    const document = JSON.parse(readFileSync(input, "utf8"));
    const attachments = Array.from({ length: 51 }, (_, index) => {
      const aliasDirectory = resolve(outputs, `alias-${index}`);
      mkdirSync(aliasDirectory);
      return {
        alt_text: `共享产物别名 ${index}`,
        local_path: `${aliasDirectory}/../shared.bin`,
      };
    });
    document.review_brief.main_changes[0].attachments = attachments;
    document.artifacts.attachments = attachments.map((attachment) => ({
      ...attachment,
      visual_review: "passed",
      file_hash: hash,
    }));
    writeFileSync(input, `${JSON.stringify(document)}\n`);

    const result = spawnSync("node", [grader, "1", outputs, skillRoot], { encoding: "utf8" });
    assert.equal(result.status, 1, result.stderr || result.stdout);
    const grading = JSON.parse(readFileSync(resolve(directory, "grading.json"), "utf8"));
    assert.doesNotMatch(grading.expectations[0].evidence, /临时快照超过 100 MiB/);
  });

  test("评测器在写临时文件前限制 artifact 引用数量", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-grader-artifact-count-"));
    const outputs = resolve(directory, "outputs");
    mkdirSync(outputs);
    const input = copyFixture(outputs);
    const artifact = resolve(outputs, "shared.bin");
    writeFileSync(artifact, "x");
    const document = JSON.parse(readFileSync(input, "utf8"));
    document.artifacts.attachments = Array.from({ length: 203 }, (_, index) => ({
      alt_text: `共享产物引用 ${index}`,
      local_path: artifact,
    }));
    writeFileSync(input, `${JSON.stringify(document)}\n`);

    const result = spawnSync("node", [grader, "1", outputs, skillRoot], { encoding: "utf8" });
    assert.equal(result.status, 1, result.stderr || result.stdout);
    const grading = JSON.parse(readFileSync(resolve(directory, "grading.json"), "utf8"));
    assert.match(grading.expectations[0].evidence, /artifact 引用数量超过 202 项/);
  });

  test("eval 3 遇到畸形 artifact 容器仍生成失败评分", () => {
    for (const attachments of [[null], {}, "invalid"]) {
      const directory = mkdtempSync(resolve(tmpdir(), "review-brief-grader-invalid-artifact-"));
      const outputs = resolve(directory, "outputs");
      mkdirSync(outputs);
      const input = copyFixture(outputs);
      const document = JSON.parse(readFileSync(input, "utf8"));
      document.artifacts.attachments = attachments;
      writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
      writeFileSync(resolve(outputs, "review-brief.md"), "## 概要\n\n![截图](/missing.png)\n");
      const result = spawnSync("node", [grader, "3", outputs, skillRoot], { encoding: "utf8" });
      assert.equal(result.status, 1, result.stderr || result.stdout);
      const grading = JSON.parse(readFileSync(resolve(directory, "grading.json"), "utf8"));
      assert.ok(grading.summary.failed > 0);
      assert.ok(!result.stderr.includes("    at "));
    }
  });

  test("eval 7 必须由可信轨迹证明没有启动 reviewer", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-grader-trace-"));
    const outputs = resolve(directory, "outputs");
    mkdirSync(outputs);
    copyFixture(outputs);
    writeFileSync(
      resolve(outputs, "review-brief.md"),
      "## 概要\n\naverageItemAmount 由 calculateAverage 计算。\n\n## 主要变化\n\nbuildOrderSummary 调用订单摘要能力。\n",
    );
    writeFileSync(resolve(outputs, "answer.md"), "已生成本地导览。\n");

    const missingTrace = spawnSync("node", [grader, "7", outputs, skillRoot], { encoding: "utf8" });
    assert.equal(missingTrace.status, 1, missingTrace.stderr || missingTrace.stdout);
    let grading = JSON.parse(readFileSync(resolve(directory, "grading.json"), "utf8"));
    assert.equal(grading.expectations[2].passed, false);
    assert.match(grading.expectations[2].evidence, /缺少评测 harness/);
    assert.equal(grading.execution_metrics.total_tool_calls, null);

    const fifoTrace = resolve(directory, "trusted-trace.fifo");
    const mkfifo = spawnSync("mkfifo", [fifoTrace], { encoding: "utf8" });
    assert.equal(mkfifo.status, 0, mkfifo.stderr || mkfifo.stdout);
    const fifoResult = spawnSync(
      "node",
      [grader, "7", outputs, skillRoot, fifoTrace],
      { encoding: "utf8", timeout: 2_000 },
    );
    assert.notEqual(fifoResult.error?.code, "ETIMEDOUT");
    assert.equal(fifoResult.status, 1, fifoResult.stderr || fifoResult.stdout);

    const trace = resolve(directory, "trusted-trace.json");
    const traceDocument = trustedTraceDocument(outputs);
    const trustedRunEnv = { ...process.env, REVIEW_BRIEF_EVAL_RUN_ID: traceDocument.run_id };
    writeFileSync(trace, `${JSON.stringify(traceDocument)}\n`);
    const verified = spawnSync(
      "node",
      [grader, "7", outputs, skillRoot, trace],
      { encoding: "utf8", env: trustedRunEnv },
    );
    assert.equal(verified.status, 0, verified.stderr || verified.stdout);
    grading = JSON.parse(readFileSync(resolve(directory, "grading.json"), "utf8"));
    assert.equal(grading.expectations[2].passed, true);
    assert.equal(grading.execution_metrics.total_tool_calls, 0);

    const wrongRun = spawnSync(
      "node",
      [grader, "7", outputs, skillRoot, trace],
      {
        encoding: "utf8",
        env: { ...process.env, REVIEW_BRIEF_EVAL_RUN_ID: randomUUID() },
      },
    );
    assert.equal(wrongRun.status, 1, wrongRun.stderr || wrongRun.stdout);
    grading = JSON.parse(readFileSync(resolve(directory, "grading.json"), "utf8"));
    assert.equal(grading.expectations[2].passed, false);
    assert.match(grading.expectations[2].evidence, /run_id 未绑定/);

    writeFileSync(resolve(outputs, "answer.md"), "来自另一轮的候选输出。\n");
    const reusedTrace = spawnSync(
      "node",
      [grader, "7", outputs, skillRoot, trace],
      { encoding: "utf8", env: trustedRunEnv },
    );
    assert.equal(reusedTrace.status, 1, reusedTrace.stderr || reusedTrace.stdout);
    grading = JSON.parse(readFileSync(resolve(directory, "grading.json"), "utf8"));
    assert.equal(grading.expectations[2].passed, false);
    assert.match(grading.expectations[2].evidence, /与当前候选输出 manifest 不匹配/);
    writeFileSync(resolve(outputs, "answer.md"), "已生成本地导览。\n");

    for (const finding of [
      "calculateAverage 对空数组返回 NaN，需要处理。",
      "建议修复 calculateAverage 对空数组返回 NaN 的问题后再审。",
      "修复当前实现会导致数据丢失的问题后再审。",
      "P1：空数组返回 NaN。",
      "确认当前实现是否会导致数据丢失，修复后可以合并。",
      "核对当前逻辑是否可能触发重复通知；修复后合并。",
      "确认当前实现是否会导致数据丢失，修好再审。",
      "P1 - 空数组返回 NaN。",
      "【P0】空数组返回 NaN。",
      "空数组返回 NaN。",
      "修复后再审。",
      "修复历史登录 bug。",
      "关联历史登录 bug 工单。",
    ]) {
      const hiddenFinding = JSON.parse(readFileSync(sourceFixture, "utf8"));
      hiddenFinding.review_brief.review_focus = [finding];
      writeFileSync(resolve(outputs, "review-brief.json"), `${JSON.stringify(hiddenFinding)}\n`);
      const hiddenField = spawnSync(
        "node",
        [grader, "7", outputs, skillRoot, trace],
        { encoding: "utf8", env: trustedRunEnv },
      );
      assert.equal(hiddenField.status, 1, hiddenField.stderr || hiddenField.stdout);
      grading = JSON.parse(readFileSync(resolve(directory, "grading.json"), "utf8"));
      assert.equal(grading.expectations[1].passed, false);
    }
    copyFixture(outputs);

    const reviewTrace = JSON.parse(readFileSync(trace, "utf8"));
    reviewTrace.tool_calls = [{
      name: "exec_command",
      arguments_text: "review-swarm --target current",
    }];
    writeFileSync(trace, `${JSON.stringify(reviewTrace)}\n`);
    const directReview = spawnSync(
      "node",
      [grader, "7", outputs, skillRoot, trace],
      { encoding: "utf8", env: trustedRunEnv },
    );
    assert.equal(directReview.status, 1, directReview.stderr || directReview.stdout);
    grading = JSON.parse(readFileSync(resolve(directory, "grading.json"), "utf8"));
    assert.match(grading.expectations[2].evidence, /trace_review_calls=1/);

    reviewTrace.review_activity = [{ kind: "tool_argument", identifier: "exec_command" }];
    writeFileSync(trace, `${JSON.stringify(reviewTrace)}\n`);
    const hiddenReview = spawnSync(
      "node",
      [grader, "7", outputs, skillRoot, trace],
      { encoding: "utf8", env: trustedRunEnv },
    );
    assert.equal(hiddenReview.status, 1, hiddenReview.stderr || hiddenReview.stdout);
    grading = JSON.parse(readFileSync(resolve(directory, "grading.json"), "utf8"));
    assert.equal(grading.expectations[2].passed, false);
    assert.match(grading.expectations[2].evidence, /reported_review_activity=1/);

    reviewTrace.tool_calls = [];
    reviewTrace.review_activity = [];
    reviewTrace.skill_activations = ["review-swarm"];
    writeFileSync(trace, `${JSON.stringify(reviewTrace)}\n`);
    const activatedSkill = spawnSync(
      "node",
      [grader, "7", outputs, skillRoot, trace],
      { encoding: "utf8", env: trustedRunEnv },
    );
    assert.equal(activatedSkill.status, 1, activatedSkill.stderr || activatedSkill.stdout);

    reviewTrace.skill_activations = [];
    writeFileSync(trace, `${JSON.stringify(reviewTrace)}\n`);
    symlinkSync(resolve(outputs, "answer.md"), resolve(outputs, "unexpected.json"));
    const extraSymlink = spawnSync(
      "node",
      [grader, "7", outputs, skillRoot, trace],
      { encoding: "utf8", env: trustedRunEnv },
    );
    assert.equal(extraSymlink.status, 1, extraSymlink.stderr || extraSymlink.stdout);
    grading = JSON.parse(readFileSync(resolve(directory, "grading.json"), "utf8"));
    const resourceFailure = grading.expectations.find((item) => /资源上限/.test(item.text) && !item.passed);
    assert.ok(resourceFailure);
    assert.match(resourceFailure.evidence, /symlink.*unexpected\.json/);
  });

  test("eval 7 拒绝只藏在 Markdown 中的 finding", () => {
    for (const finding of [
      "P1 - 空数组返回 NaN。",
      "【P0】空数组返回 NaN。",
      "空数组返回 NaN。",
      "登录 bug。",
      "修复后再审。",
      "新增缓存，当前实现存在数据丢失问题。",
      "调整空数组逻辑，空数组返回 NaN。",
      "- **登录逻辑**：修复登录 bug - 当前实现会导致数据丢失。",
    ]) {
      const directory = mkdtempSync(resolve(tmpdir(), "review-brief-grader-markdown-finding-"));
      const outputs = resolve(directory, "outputs");
      mkdirSync(outputs);
      copyFixture(outputs);
      writeFileSync(
        resolve(outputs, "review-brief.md"),
        `## 概要\n\naverageItemAmount 由 calculateAverage 计算。\n\n## 主要变化\n\nbuildOrderSummary 调用订单摘要能力。\n\n${finding}\n`,
      );
      writeFileSync(resolve(outputs, "answer.md"), "已生成本地导览。\n");
      const trace = resolve(directory, "trusted-trace.json");
      const traceDocument = trustedTraceDocument(outputs);
      writeFileSync(trace, `${JSON.stringify(traceDocument)}\n`);
      const result = spawnSync(
        "node",
        [grader, "7", outputs, skillRoot, trace],
        {
          encoding: "utf8",
          env: { ...process.env, REVIEW_BRIEF_EVAL_RUN_ID: traceDocument.run_id },
        },
      );
      assert.equal(result.status, 1, result.stderr || result.stdout);
      const grading = JSON.parse(readFileSync(resolve(directory, "grading.json"), "utf8"));
      assert.equal(grading.expectations[1].passed, false);
    }
  });

  test("评测器把不可读目录转换为确定性失败评分", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-grader-unreadable-"));
    const outputs = resolve(directory, "outputs");
    const unreadable = resolve(outputs, "unreadable");
    mkdirSync(outputs);
    mkdirSync(unreadable);
    chmodSync(unreadable, 0o000);
    try {
      const result = spawnSync("node", [grader, "1", outputs, skillRoot], { encoding: "utf8" });
      assert.equal(result.status, 1, result.stderr || result.stdout);
      const grading = JSON.parse(readFileSync(resolve(directory, "grading.json"), "utf8"));
      assert.ok(grading.expectations.some((item) => /资源上限/.test(item.text) && !item.passed));
      assert.ok(!result.stderr.includes("    at "));
    } finally {
      chmodSync(unreadable, 0o700);
    }
  });

  test("评分结果原子替换 symlink 而不覆盖其目标", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-grading-output-"));
    const outputs = resolve(directory, "outputs");
    mkdirSync(outputs);
    copyFixture(outputs);
    writeFileSync(resolve(outputs, "review-brief.md"), "## 概要\n\n候选输出。\n");
    const victim = resolve(directory, "victim.txt");
    writeFileSync(victim, "不得覆盖\n");
    const gradingPath = resolve(directory, "grading.json");
    symlinkSync(victim, gradingPath);

    spawnSync("node", [grader, "1", outputs, skillRoot], { encoding: "utf8" });
    assert.equal(readFileSync(victim, "utf8"), "不得覆盖\n");
    assert.equal(lstatSync(gradingPath).isFile(), true);
    assert.doesNotThrow(() => JSON.parse(readFileSync(gradingPath, "utf8")));
  });

  test("输出目录中的 FIFO 等特殊节点必须让评分失败", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-grader-special-node-"));
    const outputs = resolve(directory, "outputs");
    mkdirSync(outputs);
    copyFixture(outputs);
    writeFileSync(
      resolve(outputs, "review-brief.md"),
      "## 概要\n\naverageItemAmount 由 calculateAverage 计算。\n\n## 主要变化\n\nbuildOrderSummary 调用订单摘要能力。\n",
    );
    writeFileSync(resolve(outputs, "answer.md"), "已生成本地导览。\n");
    const fifo = spawnSync("mkfifo", [resolve(outputs, "hidden.pipe")], { encoding: "utf8" });
    assert.equal(fifo.status, 0, fifo.stderr);
    const trace = resolve(directory, "trusted-trace.json");
    writeFileSync(trace, `${JSON.stringify(trustedTraceDocument(outputs, { total_steps: undefined }))}\n`);

    const result = spawnSync("node", [grader, "7", outputs, skillRoot, trace], { encoding: "utf8" });
    assert.equal(result.status, 1, result.stderr || result.stdout);
    const grading = JSON.parse(readFileSync(resolve(directory, "grading.json"), "utf8"));
    assert.ok(grading.expectations.some((item) => /资源上限/.test(item.text) && !item.passed));
    assert.match(grading.expectations.at(-1).evidence, /特殊节点/);
  });

  test("真实路径位于输出目录外的 symlink 产物不能通过评分", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-grader-symlink-"));
    const outputs = resolve(directory, "outputs");
    const external = resolve(directory, "external");
    mkdirSync(outputs);
    mkdirSync(external);
    const svg = resolve(external, "flow.svg");
    const png = resolve(external, "flow.png");
    writeFileSync(svg, "<svg xmlns=\"http://www.w3.org/2000/svg\"></svg>\n");
    writeFileSync(png, pngBytes());
    symlinkSync(external, resolve(outputs, "assets"));

    const input = copyFixture(outputs);
    const document = JSON.parse(readFileSync(input, "utf8"));
    document.review_brief.diagram = {
      type: "sequence",
      alt_text: "测试 symlink 产物范围",
      source_hash: createHash("sha256").update(readFileSync(svg)).digest("hex"),
    };
    document.artifacts.diagram = {
      svg_path: resolve(outputs, "assets/flow.svg"),
      png_path: resolve(outputs, "assets/flow.png"),
      png_hash: fileHash(png),
      visual_review: "passed",
    };
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    run(["finalize", input]);
    writeFileSync(resolve(outputs, "review-brief.md"), "## 概要\n\n候选 Full Brief。\n");

    const result = spawnSync("node", [grader, "2", outputs, skillRoot], { encoding: "utf8" });
    assert.equal(result.status, 1, result.stderr || result.stdout);
    const grading = JSON.parse(readFileSync(resolve(directory, "grading.json"), "utf8"));
    assert.equal(grading.expectations[2].passed, false);
    assert.match(grading.expectations[2].evidence, /svg\/png_in_outputs=false/);
  });

  test("最终路径为 symlink 的候选 artifact 不能通过评分", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-grader-final-symlink-"));
    const outputs = resolve(directory, "outputs");
    mkdirSync(outputs);
    const input = copyFixture(outputs);
    const target = resolve(outputs, "target.png");
    const link = resolve(outputs, "link.png");
    writeFileSync(target, pngBytes());
    symlinkSync(target, link);
    const document = JSON.parse(readFileSync(input, "utf8"));
    const attachment = { alt_text: "最终 symlink 图片", local_path: link };
    document.review_brief.main_changes[0].attachments = [attachment];
    document.artifacts.attachments = [{
      ...attachment,
      visual_review: "passed",
      file_hash: fileHash(target),
    }];
    writeFileSync(input, `${JSON.stringify(document)}\n`);
    writeFileSync(resolve(outputs, "review-brief.md"), "## 概要\n\n候选输出。\n");

    const result = spawnSync("node", [grader, "1", outputs, skillRoot], { encoding: "utf8" });
    assert.equal(result.status, 1, result.stderr || result.stdout);
    const grading = JSON.parse(readFileSync(resolve(directory, "grading.json"), "utf8"));
    assert.match(grading.expectations[0].evidence, /symlink|资源上限/);
  });

  test("无害文件名的 symlink 也会让 grader 全局失败", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-grader-hidden-symlink-"));
    const outputs = resolve(directory, "outputs");
    mkdirSync(outputs);
    const external = resolve(directory, "review-brief.json");
    writeFileSync(external, "{}\n");
    writeFileSync(resolve(outputs, "answer.md"), "这是 finding/verdict 场景，应交给 review-swarm。\n");
    symlinkSync(external, resolve(outputs, "notes.txt"));

    const result = spawnSync("node", [grader, "4", outputs, skillRoot], { encoding: "utf8" });
    assert.equal(result.status, 1, result.stderr || result.stdout);
    const grading = JSON.parse(readFileSync(resolve(directory, "grading.json"), "utf8"));
    assert.ok(grading.expectations.some((item) => /资源上限/.test(item.text) && !item.passed));
    assert.match(grading.expectations.at(-1).evidence, /symlink/);
  });

  test("候选 Markdown symlink 不能借用目录外内容获得通过", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-grader-output-symlink-"));
    const outputs = resolve(directory, "outputs");
    const external = resolve(directory, "external");
    mkdirSync(outputs);
    mkdirSync(external);
    run(["render-github", sourceFixture, "--output", resolve(external, "github-preview.md")]);
    run([
      "render-slack", sourceFixture,
      "--target-url", "https://github.com/MoeGolibrary/example/pull/128",
      "--output", resolve(external, "slack-preview.md"),
    ]);
    writeFileSync(resolve(external, "answer.md"), "已生成两个本地预览。\n");
    for (const name of ["github-preview.md", "slack-preview.md", "answer.md"]) {
      symlinkSync(resolve(external, name), resolve(outputs, name));
    }

    const result = spawnSync("node", [grader, "6", outputs, skillRoot], { encoding: "utf8" });
    assert.equal(result.status, 1, result.stderr || result.stdout);
    const grading = JSON.parse(readFileSync(resolve(directory, "grading.json"), "utf8"));
    assert.ok(grading.summary.failed > 0);
    assert.deepEqual(
      grading.run_metadata.unsafe_candidate_files.sort(),
      ["answer.md", "github-preview.md", "slack-preview.md"],
    );
  });

  test("eval 3 不能用任意绝对路径伪造截图", () => {
    const directory = mkdtempSync(resolve(tmpdir(), "review-brief-grader-fake-screenshot-"));
    const outputs = resolve(directory, "outputs");
    mkdirSync(outputs);
    const input = copyFixture(outputs);
    const document = JSON.parse(readFileSync(input, "utf8"));
    document.review_brief.mode = "lite";
    document.review_brief.reading_route = [];
    document.review_brief.diagram = null;
    document.review_brief.main_changes = [{
      title: "预约状态卡片",
      description: "展示状态、负责员工、cancelled 样式与 aria-label。",
      code_refs: ["src/BookingCard.tsx:BookingCard"],
      attachments: [{ alt_text: "所谓截图", local_path: "/etc/hosts" }],
    }];
    document.artifacts.attachments = [{ alt_text: "所谓截图", local_path: "/etc/hosts" }];
    document.artifacts.diagram = null;
    writeFileSync(input, `${JSON.stringify(document, null, 2)}\n`);
    run(["finalize", input]);
    writeFileSync(
      resolve(outputs, "review-brief.md"),
      "## 概要\n\n预约卡片展示状态、负责员工、cancelled 样式与 aria-label。\n\n![所谓截图](/etc/hosts)\n",
    );

    const result = spawnSync("node", [grader, "3", outputs, skillRoot], { encoding: "utf8" });
    assert.equal(result.status, 1, result.stderr || result.stdout);
    const grading = JSON.parse(readFileSync(resolve(directory, "grading.json"), "utf8"));
    assert.equal(grading.expectations[1].passed, false);
    assert.match(grading.expectations[1].evidence, /allowed_path=false/);
  });
});

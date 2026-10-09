import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { execFileSync } from "node:child_process";
import { fixtureArgsMatch } from "./fixture_match.mjs";

const input = JSON.parse(await readStdin());
const packageRoot = process.env.PI_CODING_AGENT_PACKAGE || await findPackageRoot();
const agent = await import(pathToFileURL(path.join(packageRoot, "dist/index.js")).href);
const typebox = await import(pathToFileURL(path.join(packageRoot, "node_modules/typebox/build/index.mjs")).href);
const piAi = await import(pathToFileURL(path.join(packageRoot, "node_modules/@earendil-works/pi-ai/dist/compat.js")).href);
const modelRuntime = await agent.ModelRuntime.create({ allowModelNetwork: false });
if (input.action === "list_models") {
  process.stdout.write(JSON.stringify({ models: modelRuntime.getAvailableSnapshot()
    .filter((model) => /^gpt-[A-Za-z0-9][A-Za-z0-9._-]*$/.test(model.id))
    .map((model) => ({ provider: model.provider, model: model.id, source: "Pi ModelRuntime 已配置认证目录", thinking_levels: piAi.getSupportedThinkingLevels(model) })) }));
  process.exit(0);
}
if (!input.model || !input.provider) throw new Error("configuration: 必须显式选择 GPT model/provider");
const selectedModel = modelRuntime.getModel(input.provider, input.model);
if (!selectedModel || !/^gpt-[A-Za-z0-9][A-Za-z0-9._-]*$/.test(selectedModel.id)) {
  throw new Error("configuration: 所选 GPT 不在 Pi 配置目录中");
}
if (!piAi.getSupportedThinkingLevels(selectedModel).includes(input.limits?.reasoning || "medium")) {
  throw new Error("configuration: 所选模型配置不支持请求的 reasoning；先发现可用等级，不允许自动改档");
}
const settingsManager = agent.SettingsManager.inMemory({ retry: { enabled: false }, providerRetry: { maxRetries: 0 } });

const calls = [];
const skillEvents = [];
const skillLoadCalls = [];
let totalTurns = 0;
const triggerOnly = input.trigger_only === true;
const fixtures = await loadFixtures(input.fixtures || [], input.cwd);
const fixtureCall = async (tool, args) => {
  for (const fixture of fixtures) {
    if (fixture.tool !== tool) continue;
    if (!fixtureArgsMatch(fixture, args)) continue;
    return fixture.result ?? fixture.response ?? null;
  }
  throw new Error(`fixture miss: tool=${tool}`);
};

const extensionFactories = fixtures.length ? [
  (pi) => {
    const tools = [...new Set(fixtures.map((fixture) => fixture.tool))];
    for (const tool of tools) {
      pi.registerTool({
        name: tool,
        label: tool,
        description: `Replay tool ${tool}`,
        parameters: typebox.Type.Record(typebox.Type.String(), typebox.Type.Any()),
        execute: async (_id, args) => {
          const result = await fixtureCall(tool, args || {});
          return { content: [{ type: "text", text: JSON.stringify(result) }], details: { replay: true } };
        },
      });
    }
  },
] : [];

const loader = new agent.DefaultResourceLoader({
  cwd: input.cwd,
  agentDir: process.env.PI_CODING_AGENT_DIR || path.join(input.cwd, ".pi-agent"),
  additionalSkillPaths: input.skill_path && input.configuration === "with_skill" ? [input.skill_path] : [],
  noExtensions: !fixtures.length,
  noSkills: true,
  noContextFiles: true,
  noPromptTemplates: true,
  noThemes: true,
  settingsManager,
  extensionFactories,
});
await loader.reload();

const tools = fixtures.length
  ? [...new Set(["read", ...fixtures.map((fixture) => fixture.tool)])]
  : (triggerOnly ? ["read"] : input.tools || []);
const { session } = await agent.createAgentSession({
  cwd: input.cwd,
  resourceLoader: loader,
  sessionManager: agent.SessionManager.inMemory(input.cwd),
  tools,
  model: selectedModel,
  modelRuntime,
  settingsManager,
  thinkingLevel: input.limits?.reasoning || "medium",
});
await session.bindExtensions({});
let finalText = "";
let skillTriggered = false;
session.subscribe((event) => {
  if (event.type === "turn_end") totalTurns += 1;
  if (event.type === "tool_execution_start") {
    const call = {
      tool: event.toolName,
      args: event.args || {},
      call_id: event.toolCallId,
    };
    const skillFile = input.skill_path ? path.resolve(input.skill_path, "SKILL.md") : null;
    const isSkillRead = input.configuration === "with_skill" && skillFile && call.tool === "read"
      && path.resolve(input.cwd, call.args.path || "") === skillFile;
    if (isSkillRead) {
      skillLoadCalls.push(call);
      skillTriggered = true;
      skillEvents.push({ type: "skill_loaded", path: skillFile });
      if (triggerOnly) void session.abort().catch(() => {});
    } else {
      calls.push(call);
    }
  }
  if (event.type === "message_update" && event.assistantMessageEvent?.type === "text_delta") {
    finalText += event.assistantMessageEvent.delta || "";
  }
  if (event.type === "skill_loaded" || event.type === "resources_discover") {
    skillEvents.push(safeJson(event));
  }
});

try {
  try {
    let prompt = input.prompt;
    if (!triggerOnly && input.skill_path && input.configuration === "with_skill") {
      prompt += "\n\n本次任务遵循以下 Skill：\n" + await fs.readFile(path.join(input.skill_path, "SKILL.md"), "utf8");
    }
    for (const file of input.input_files || []) {
      prompt += "\n\n输入文件 " + path.basename(file) + ":\n" + await fs.readFile(file, "utf8");
    }
    await session.prompt(prompt);
  } catch (error) {
    if (!(triggerOnly && skillTriggered)) throw error;
  }
  const messages = session.state.messages || [];
  const modelErrors = messages.filter((message) => message.role === "assistant" &&
    (message.stopReason === "error" || message.stopReason === "invalid_prompt" || (message.stopReason === "aborted" && !(triggerOnly && skillTriggered))));
  const errors = modelErrors.map((message) => ({ type: "model_error", message: message.errorMessage || message.stopReason }));
  for (const message of messages) {
    if (message.role === "toolResult" && message.isError && JSON.stringify(message.content).includes("fixture miss")) {
      errors.push({ type: "fixture_error", message: "fixture miss" });
    }
  }
  if (!finalText) finalText = extractText(messages);
  if (!finalText.trim() && !(triggerOnly && skillTriggered) && !errors.length) errors.push({ type: "empty_output", message: "模型没有最终输出" });
  const skillFile = input.skill_path ? path.resolve(input.skill_path, "SKILL.md") : null;
  skillTriggered = skillTriggered || (input.configuration === "with_skill" && skillFile
    ? skillLoadCalls.some((call) => call.tool === "read" && path.resolve(input.cwd, call.args?.path || "") === skillFile)
    : false);
  process.stdout.write(JSON.stringify({
    final_answer: finalText.trim(),
    tool_calls: calls,
    skill_events: skillEvents,
    metrics: { total_tool_calls: calls.length, total_steps: session.state.messages?.length || 0, total_turns: totalTurns, errors_encountered: 0, output_chars: finalText.length, transcript_chars: JSON.stringify(session.state.messages || []).length },
    timing: messages.some((message) => message.usage) ? {
      total_tokens: messages.filter((message) => message.role === "assistant")
        .reduce((total, message) => total + (message.usage?.totalTokens || 0), 0),
      output_tokens: messages.filter((message) => message.role === "assistant")
        .reduce((total, message) => total + (message.usage?.output || 0), 0),
    } : {},
    actual_model: session.model?.id,
    actual_provider: session.model?.provider,
    actual_reasoning: session.thinkingLevel,
    runtime_version: JSON.parse(await fs.readFile(path.join(packageRoot, "package.json"), "utf8")).version,
    runtime_path: packageRoot,
    status: errors.length ? "failed" : "completed",
    errors,
    messages: safeJson(messages),
    trigger_semantics: triggerOnly ? "pi-native" : (input.configuration === "with_skill" ? "explicit" : "not_applicable"),
    skill_triggered: triggerOnly ? skillTriggered : null,
  }));
} finally {
  session.dispose();
}

async function readStdin() {
  let data = "";
  for await (const chunk of process.stdin) data += chunk;
  return data;
}

async function findPackageRoot() {
  const localRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../node_modules/@earendil-works/pi-coding-agent");
  const candidates = [
    localRoot,
    process.env.npm_config_prefix ? path.join(process.env.npm_config_prefix, "lib/node_modules/@earendil-works/pi-coding-agent") : null,
    "/usr/local/lib/node_modules/@earendil-works/pi-coding-agent",
    "/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent",
  ].filter(Boolean);
  try {
    const globalRoot = execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim();
    candidates.push(path.join(globalRoot, "@earendil-works/pi-coding-agent"));
  } catch {}
  for (const candidate of candidates) {
    try { await fs.access(path.join(candidate, "dist/index.js")); return candidate; } catch {}
  }
  throw new Error("找不到 @earendil-works/pi-coding-agent，请设置 PI_CODING_AGENT_PACKAGE");
}

async function loadFixtures(paths, cwd) {
  const result = [];
  for (const raw of paths) {
    const filename = path.isAbsolute(raw) ? raw : path.join(cwd, raw);
    const parsed = JSON.parse(await fs.readFile(filename, "utf8"));
    result.push(...(Array.isArray(parsed) ? parsed : [parsed]));
  }
  return result;
}


function extractText(messages) {
  return messages.flatMap((message) => message.role === "assistant" ? (message.content || []) : []).filter((item) => item.type === "text").map((item) => item.text || "").join("");
}

function safeJson(value) {
  return JSON.parse(JSON.stringify(value, (_key, item) => typeof item === "bigint" ? Number(item) : item));
}

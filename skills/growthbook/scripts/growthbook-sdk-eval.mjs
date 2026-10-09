#!/usr/bin/env node
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);

function fail(message) {
  process.stderr.write(`[growthbook-sdk-eval] ${message}\n`);
  process.exit(1);
}

function requiredEnv(name) {
  const value = process.env[name];
  if (!value) fail(`环境变量 ${name} 未设置`);
  return value;
}

function readStdinJson() {
  let text = "";
  process.stdin.setEncoding("utf8");
  return new Promise((resolve) => {
    process.stdin.on("data", (chunk) => {
      text += chunk;
    });
    process.stdin.on("end", () => {
      if (!text.trim()) fail("stdin 必须提供 JSON 请求体");
      try {
        resolve(JSON.parse(text));
      } catch {
        fail("stdin 必须是合法 JSON");
      }
    });
  });
}

function assertObject(value, name) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    fail(`${name} 必须是 JSON object`);
  }
  return value;
}

function maskAttributeValue(key, value) {
  const lowered = key.toLowerCase();
  if (
    lowered.includes("email") ||
    lowered.includes("token") ||
    lowered.includes("secret") ||
    lowered.includes("password") ||
    lowered.includes("auth")
  ) {
    return "***";
  }
  if (Array.isArray(value)) return value.map((item) => maskAttributeValue(key, item));
  if (value && typeof value === "object") return maskAttributes(value);
  return value;
}

function maskAttributes(attributes) {
  return Object.fromEntries(
    Object.entries(attributes).map(([key, value]) => [key, maskAttributeValue(key, value)]),
  );
}

function normalizeAttributes(attributes) {
  const normalized = { ...attributes };
  const warnings = [];
  if ("platform" in normalized && !("platfrom" in normalized)) {
    normalized.platfrom = normalized.platform;
    warnings.push("已将 platform -> platfrom 用于兼容 MoeGo GrowthBook 历史字段");
  }
  return { normalized, warnings };
}

function similarFeatureKeys(featureId, keys) {
  const lowered = featureId.toLowerCase();
  return keys
    .filter((key) => {
      const candidate = String(key).toLowerCase();
      return lowered.includes(candidate) || candidate.includes(lowered);
    })
    .slice(0, 5);
}

function serializeResult(result) {
  if (!result || typeof result !== "object") {
    return {
      value: result,
      on: Boolean(result),
      source: null,
      ruleId: null,
    };
  }
  return {
    value: result.value,
    on: Boolean(result.on),
    source: result.source ?? null,
    ruleId: result.ruleId ?? null,
  };
}

async function main() {
  const request = assertObject(await readStdinJson(), "stdin");
  const featureId = request.featureId;
  if (typeof featureId !== "string" || !featureId) fail("featureId 必须是非空字符串");
  const inputAttributes = assertObject(request.attributes ?? {}, "attributes");
  const timeoutMs = Number.isInteger(request.timeoutMs) && request.timeoutMs > 0
    ? request.timeoutMs
    : 10000;
  const { normalized: attributes, warnings } = normalizeAttributes(inputAttributes);

  let GrowthBook;
  try {
    ({ GrowthBook } = require("@growthbook/growthbook"));
  } catch {
    fail(
      "缺少 @growthbook/growthbook。请进入本 skill 目录执行 pnpm install --prod --frozen-lockfile 后重试。",
    );
  }
  if (typeof GrowthBook !== "function") {
    fail("@growthbook/growthbook 未导出 GrowthBook");
  }

  const gb = new GrowthBook({
    apiHost: requiredEnv("GROWTHBOOK_SDK_API_HOST"),
    clientKey: requiredEnv("GROWTHBOOK_SDK_CLIENT_KEY"),
  });
  try {
    const initResult = await gb.init({ timeout: timeoutMs });
    if (initResult && initResult.success === false) {
      const reason = initResult.error?.message || initResult.source || "unknown";
      fail(`GrowthBook SDK 初始化失败：${reason}`);
    }
    if (request.url && typeof gb.setURL === "function") {
      gb.setURL(String(request.url));
    }
    const features = gb.getFeatures();
    const featureKeys = Object.keys(features);
    const outputAttributes = {
      inputKeys: Object.keys(inputAttributes),
      used: maskAttributes(attributes),
    };
    if (!Object.prototype.hasOwnProperty.call(features, featureId)) {
      process.stdout.write(
        JSON.stringify(
          {
            featureId,
            found: false,
            attributes: outputAttributes,
            warnings,
            similar: similarFeatureKeys(featureId, featureKeys),
            sdk: {
              featureCount: featureKeys.length,
              init: {
                success: initResult?.success ?? null,
                source: initResult?.source ?? null,
              },
            },
          },
          null,
          2,
        ),
      );
      process.stdout.write("\n");
      return;
    }

    gb.setAttributes(attributes);
    const result = gb.evalFeature(featureId);
    gb.setAttributes({});
    const defaultResult = gb.evalFeature(featureId);
    const payload = {
      featureId,
      found: true,
      attributes: outputAttributes,
      result: serializeResult(result),
      defaultWithoutAttributes: serializeResult(defaultResult),
      warnings,
      sdk: {
        featureCount: featureKeys.length,
        init: {
          success: initResult?.success ?? null,
          source: initResult?.source ?? null,
        },
      },
    };
    if (request.raw) {
      payload.raw = { feature: features[featureId] };
    }
    process.stdout.write(JSON.stringify(payload, null, 2));
    process.stdout.write("\n");
  } finally {
    if (typeof gb.destroy === "function") gb.destroy();
  }
}

main().catch((error) => {
  fail(error?.message ?? String(error));
});

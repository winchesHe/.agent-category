import { parseArgs } from "node:util";
import { projectRoot } from "./sites-env.mjs";
import { installSharedDependencies } from "./shared-deps.mjs";

if (![
  "SHARP_IGNORE_GLOBAL_LIBVIPS",
  "SHARP_FORCE_GLOBAL_LIBVIPS",
  "npm_config_build_from_source",
  "NPM_CONFIG_BUILD_FROM_SOURCE",
].some((key) => key in process.env)) {
  process.env.SHARP_IGNORE_GLOBAL_LIBVIPS = "1";
}

const { values } = parseArgs({ options: { refresh: { type: "boolean", default: false } } });
const { modules, backup } = installSharedDependencies(projectRoot, { refresh: values.refresh });
console.error(`已连接共享依赖：${modules}`);
if (backup) console.error(`旧依赖保留于 ${backup}；预览和构建核对成功后可清理。`);

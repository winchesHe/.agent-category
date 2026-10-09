import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import YAML from "yaml";

const skillRoot = path.resolve(import.meta.dirname, "..");

async function readRegistry() {
  const source = await readFile(path.join(skillRoot, "references/connections.yaml"), "utf8");
  return { source, registry: YAML.parse(source) };
}

function captureOfflineArgs(command, executable) {
  const shellScript = `${executable}() { printf '%s\\0' "$@"; }\n${command}`;
  const result = spawnSync("bash", ["-c", shellScript], {
    encoding: "buffer",
    env: {
      ...process.env,
      T2_DATABASE_USER: "test-user",
      T2_MYSQL_OPTION_FILE: "/tmp/t2-mysql.cnf",
    },
  });

  assert.equal(result.status, 0, result.stderr.toString("utf8"));
  return result.stdout.toString("utf8").split("\0").filter(Boolean);
}

test("moe-t2-database connection registry is valid YAML with the retained connections", async () => {
  const { registry } = await readRegistry();

  assert.deepEqual(Object.keys(registry.postgres), ["pg_main", "membership_v2"]);
  assert.deepEqual(Object.keys(registry.postgres.pg_main.databases), [
    "membership_old",
    "subscription",
    "billing",
    "account",
  ]);
  assert.deepEqual(Object.keys(registry.mysql), ["grooming", "message", "business"]);
  assert.equal(registry.postgres.pg_main.databases.subscription.inferred, true);
  assert.equal(registry.postgres.pg_main.databases.billing.inferred, true);
});

test("moe-t2-database documents direct non-interactive client commands", async () => {
  const skill = await readFile(path.join(skillRoot, "SKILL.md"), "utf8");

  assert.match(skill, /^psql -h <host> -p <port> -U "\$T2_DATABASE_USER" -d <database>$/mu);
  assert.match(
    skill,
    /^mysql --defaults-extra-file="\$T2_MYSQL_OPTION_FILE" -h <host> -P <port> -u "\$T2_DATABASE_USER" <database>$/mu,
  );
  assert.match(skill, /不得回退到交互式 `-p`。/u);
  assert.match(skill, /必须按当前 shell 安全引用。不能机械替换单引号模板。/u);
});

test("moe-t2-database requires scoped confirmation for mutations", async () => {
  const skill = await readFile(path.join(skillRoot, "SKILL.md"), "utf8");

  assert.match(skill, /W1[\s\S]*单条 `INSERT`、`UPDATE` 或 `DELETE`/u);
  assert.match(skill, /W2[\s\S]*DDL、权限语句、多语句或跨 database 操作/u);
  assert.match(skill, /初始请求不构成执行确认/u);
  assert.match(skill, /每个操作必须单独确认/u);
  assert.match(skill, /SQL、目标或影响范围变化后，原确认失效/u);
  assert.match(skill, /使用只读查询回读可观察结果/u);
});

test("moe-t2-database SQL string literals remain intact in direct client argv", async () => {
  const skill = await readFile(path.join(skillRoot, "SKILL.md"), "utf8");
  const postgresCommand = skill.split("\n").find((line) => line.startsWith("psql ") && line.includes("owner@example.com"));
  const mysqlCommand = skill.split("\n").find((line) => line.startsWith("mysql ") && line.includes("Paws & Play"));

  assert.ok(postgresCommand);
  assert.ok(mysqlCommand);

  const postgresArgs = captureOfflineArgs(postgresCommand, "psql");
  const mysqlArgs = captureOfflineArgs(mysqlCommand, "mysql");

  assert.equal(
    postgresArgs[postgresArgs.indexOf("-c") + 1],
    "select id, email from public.account where email = 'owner@example.com';",
  );
  assert.equal(
    mysqlArgs[mysqlArgs.indexOf("-e") + 1],
    "select id, business_name from moe_business where business_name = 'Paws & Play';",
  );
  assert.equal(mysqlArgs[0], "--defaults-extra-file=/tmp/t2-mysql.cnf");
  assert.equal(mysqlArgs.includes("-p"), false);
  assert.equal(mysqlArgs.some((argument) => argument.startsWith("--password")), false);
});

test("moe-t2-database distributed files contain no credential values or credential-bearing DSNs", async () => {
  const skill = await readFile(path.join(skillRoot, "SKILL.md"), "utf8");
  const { source, registry } = await readRegistry();
  const metadata = await readFile(path.join(skillRoot, "skill-metadata.json"), "utf8");
  const agentMetadata = await readFile(path.join(skillRoot, "agents/openai.yaml"), "utf8");
  const distributedText = [skill, source, metadata, agentMetadata].join("\n");

  assert.equal(registry.credentials.user_env, "T2_DATABASE_USER");
  assert.equal(registry.credentials.postgres_password_env, "PGPASSWORD");
  assert.equal(registry.credentials.mysql_option_file_env, "T2_MYSQL_OPTION_FILE");
  assert.doesNotMatch(distributedText, /(?:postgres(?:ql)?|mysql):\/\/[^\s@]+@/iu);
  assert.doesNotMatch(distributedText, /\bpassword\s*:\s*(?!client\b|host\b|PGPASSWORD\b|T2_DATABASE_PASSWORD\b)\S+/iu);
  assert.doesNotMatch(distributedText, /(?:^|\s)-p[^\s<$"'`]+|PGPASSWORD=[^\s<$"'`]+/mu);
});

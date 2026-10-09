import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { chmod, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

const skillRoot = path.resolve(import.meta.dirname, "..");
const wrapperPath = path.join(skillRoot, "scripts/t2kubectl");
const skillPath = path.join(skillRoot, "SKILL.md");
const clusterReferencePath = path.join(skillRoot, "references/cluster.yaml");

async function createFixture({ dedicatedKubeconfig = false } = {}) {
  const root = await mkdtemp(path.join(os.tmpdir(), "moe-t2-k8s-"));
  const home = path.join(root, "home");
  const bin = path.join(root, "bin");
  const kubeDir = path.join(home, ".kube");

  await mkdir(bin, { recursive: true });
  await mkdir(kubeDir, { recursive: true });
  await writeFile(path.join(kubeDir, "config"), "fallback\n");
  if (dedicatedKubeconfig) {
    await writeFile(
      path.join(kubeDir, "headlamp-moego-development-ns-testing.kubeconfig"),
      "dedicated\n"
    );
  }

  const fakeKubectl = path.join(bin, "kubectl");
  await writeFile(
    fakeKubectl,
    [
      "#!/usr/bin/env bash",
      "set -euo pipefail",
      "printf 'KUBECONFIG=%s\\n' \"${KUBECONFIG:-}\"",
      "printf 'ARGS='",
      "printf '<%s>' \"$@\"",
      "printf '\\n'",
      "",
    ].join("\n")
  );
  await chmod(fakeKubectl, 0o755);

  return {
    root,
    home,
    bin,
    cleanup: () => rm(root, { recursive: true, force: true }),
  };
}

function wrapperEnv(fixture, overrides = {}) {
  const env = { ...process.env };
  for (const key of [
    "KUBECONFIG",
    "T2_KUBECONFIG",
    "T2_K8S_CONTEXT",
    "T2_K8S_NAMESPACE",
    "T2_K8S_ALLOW_WRITE",
    "T2_K8S_ALLOW_ALL_NAMESPACES",
  ]) {
    delete env[key];
  }

  return {
    ...env,
    HOME: fixture.home,
    PATH: `${fixture.bin}:${env.PATH}`,
    ...overrides,
  };
}

function runWrapper(fixture, args, overrides = {}) {
  return spawnSync("bash", [wrapperPath, ...args], {
    cwd: skillRoot,
    encoding: "utf8",
    env: wrapperEnv(fixture, overrides),
  });
}

async function withFixture(options, callback) {
  const fixture = await createFixture(options);
  try {
    await callback(fixture);
  } finally {
    await fixture.cleanup();
  }
}

test("t2kubectl has valid Bash syntax", () => {
  const result = spawnSync("bash", ["-n", wrapperPath], {
    cwd: skillRoot,
    encoding: "utf8",
  });
  assert.equal(result.status, 0, result.stderr);
});

test("t2kubectl pins the T2 context and namespace", async () => {
  await withFixture({ dedicatedKubeconfig: true }, async (fixture) => {
    const result = runWrapper(fixture, ["get", "pods"]);
    assert.equal(result.status, 0, result.stderr);
    assert.match(
      result.stdout,
      /KUBECONFIG=.*headlamp-moego-development-ns-testing\.kubeconfig/
    );
    assert.match(
      result.stdout,
      /ARGS=<--context><moego-development-ns-testing><--namespace><ns-testing><get><pods>/
    );
  });
});

test("t2kubectl preserves kubeconfig selection and fallback semantics", async (t) => {
  await t.test("uses the default kubeconfig fallback", async () => {
    await withFixture({}, async (fixture) => {
      const result = runWrapper(fixture, ["get", "pods"]);
      assert.equal(result.status, 0, result.stderr);
      assert.match(result.stdout, new RegExp(`KUBECONFIG=${fixture.home}/\\.kube/config`));
    });
  });

  await t.test("uses T2_KUBECONFIG when the file exists", async () => {
    await withFixture({}, async (fixture) => {
      const configured = path.join(fixture.root, "configured-kubeconfig");
      await writeFile(configured, "configured\n");
      const result = runWrapper(fixture, ["get", "pods"], {
        T2_KUBECONFIG: configured,
      });
      assert.equal(result.status, 0, result.stderr);
      assert.match(result.stdout, new RegExp(`KUBECONFIG=${configured}`));
    });
  });

  await t.test("preserves an existing KUBECONFIG", async () => {
    await withFixture({}, async (fixture) => {
      const configured = path.join(fixture.root, "existing-kubeconfig");
      const result = runWrapper(fixture, ["get", "pods"], {
        KUBECONFIG: configured,
      });
      assert.equal(result.status, 0, result.stderr);
      assert.match(result.stdout, new RegExp(`KUBECONFIG=${configured}`));
    });
  });
});

test("t2kubectl rejects caller supplied scope and auth flags", async () => {
  await withFixture({}, async (fixture) => {
    for (const args of [
      ["get", "pods", "--context", "other"],
      ["get", "pods", "--kubeconfig=/tmp/other"],
      ["get", "pods", "-n", "other"],
      ["get", "pods", "--namespace=other"],
    ]) {
      const result = runWrapper(fixture, args);
      assert.equal(result.status, 65, args.join(" "));
      assert.match(result.stderr, /refuses scope\/auth flags/);
    }
  });
});

test("t2kubectl preserves all-namespaces switch behavior", async () => {
  await withFixture({}, async (fixture) => {
    const blocked = runWrapper(fixture, ["get", "pods", "-A"]);
    assert.equal(blocked.status, 65);
    assert.match(blocked.stderr, /T2_K8S_ALLOW_ALL_NAMESPACES=1/);

    const allowed = runWrapper(fixture, ["get", "pods", "-A"], {
      T2_K8S_ALLOW_ALL_NAMESPACES: "1",
    });
    assert.equal(allowed.status, 0, allowed.stderr);
    assert.match(allowed.stdout, /<get><pods><-A>/);
  });
});

test("t2kubectl gates recognized write commands", async () => {
  await withFixture({}, async (fixture) => {
    for (const verb of [
      "annotate",
      "apply",
      "autoscale",
      "cordon",
      "create",
      "delete",
      "drain",
      "edit",
      "expose",
      "label",
      "patch",
      "replace",
      "run",
      "scale",
      "set",
      "taint",
      "uncordon",
    ]) {
      const result = runWrapper(fixture, [verb, "pod/example"]);
      assert.equal(result.status, 66, verb);
      assert.match(result.stderr, /blocked a mutating command/);
    }

    for (const subverb of ["restart", "undo", "pause", "resume"]) {
      const result = runWrapper(fixture, ["rollout", subverb, "deploy/example"]);
      assert.equal(result.status, 66, subverb);
    }

    const allowedWrite = runWrapper(fixture, ["delete", "pod/example"], {
      T2_K8S_ALLOW_WRITE: "1",
    });
    assert.equal(allowedWrite.status, 0, allowedWrite.stderr);
  });
});

test("t2kubectl preserves exec, debug, cp, and unknown verb passthrough", async () => {
  await withFixture({}, async (fixture) => {
    for (const verb of ["exec", "debug", "cp", "future-command"]) {
      const result = runWrapper(fixture, [verb, "pod/example"]);
      assert.equal(result.status, 0, `${verb}: ${result.stderr}`);
      assert.match(result.stdout, new RegExp(`<${verb}><pod/example>`));
    }
  });
});

test("t2kubectl gates mutating config subcommands", async () => {
  await withFixture({}, async (fixture) => {
    for (const subverb of [
      "current-context",
      "get-clusters",
      "get-contexts",
      "get-users",
      "view",
    ]) {
      const result = runWrapper(fixture, ["config", subverb]);
      assert.equal(result.status, 0, `${subverb}: ${result.stderr}`);
      assert.match(result.stdout, new RegExp(`<config><${subverb}>`));
    }

    for (const subverb of [
      "delete-cluster",
      "delete-context",
      "delete-user",
      "rename-context",
      "set",
      "set-cluster",
      "set-context",
      "set-credentials",
      "unset",
      "use-context",
    ]) {
      const result = runWrapper(fixture, ["config", subverb]);
      assert.equal(result.status, 66, subverb);
      assert.match(result.stderr, /blocked a mutating command/);
    }

    const allowedWrite = runWrapper(fixture, ["config", "use-context", "other"], {
      T2_K8S_ALLOW_WRITE: "1",
    });
    assert.equal(allowedWrite.status, 0, allowedWrite.stderr);
  });
});

test("t2kubectl preserves namespace and cluster-scoped write restrictions", async () => {
  await withFixture({}, async (fixture) => {
    for (const resource of [
      "namespace/example",
      "node/example",
      "clusterrole/example",
      "clusterrolebinding/example",
      "crd/example",
      "persistentvolume/example",
      "storageclass/example",
    ]) {
      const result = runWrapper(fixture, ["delete", resource], {
        T2_K8S_ALLOW_WRITE: "1",
      });
      assert.equal(result.status, 67, resource);
      assert.match(result.stderr, /refuses mutating namespace or cluster-scoped resources/);
    }
  });
});

test("T2 Kubernetes documentation records wrapper limitations", async () => {
  const [skill, clusterReference] = await Promise.all([
    readFile(skillPath, "utf8"),
    readFile(clusterReferencePath, "utf8"),
  ]);

  assert.match(skill, /T2_K8S_CONTEXT.*T2_K8S_NAMESPACE.*覆盖/s);
  assert.match(skill, /wrapper 不是环境隔离保证/);
  assert.match(skill, /kubectl 全局参数.*首个 token 不是 verb.*绕过写分类/);
  assert.match(skill, /auth reconcile.*certificate approve.*certificate deny.*未进入写分类/);
  assert.match(skill, /manifest-based.*只检查参数文本.*无法判断 manifest 内的 namespace 或 cluster-scoped resource/s);
  assert.match(clusterReference, /context_override_env: T2_K8S_CONTEXT/);
  assert.match(clusterReference, /namespace_override_env: T2_K8S_NAMESPACE/);
  assert.match(clusterReference, /not an environment isolation guarantee/);
  assert.match(clusterReference, /global flags before the command.*bypass write classification/);
  assert.match(clusterReference, /auth reconcile.*certificate approve or deny.*not classified as writes/);
  assert.match(clusterReference, /Manifest-based apply, create, and replace.*only argument text.*inside manifests/);
});

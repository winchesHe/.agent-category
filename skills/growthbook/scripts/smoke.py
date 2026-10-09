#!/usr/bin/env python3
"""Connectivity smoke for the growthbook skill.

覆盖 growthbook.py 全部 11 个子命令，自动从前序响应里挑取 ID，无需人工准备。
写接口（create-feature-flag / create-force-rule）默认跳过，设置
SMOKE_WRITE=1 才会创建一个 `smoke_<ts>` 临时 flag 并追加 force 规则。

用法：
    export GROWTHBOOK_API_TOKEN="..."
    export GROWTHBOOK_SDK_API_HOST="https://cdn.growthbook.io"  # SDK Connections API host；自托管时可能与 GROWTHBOOK_API_BASE_URL 相同
    export GROWTHBOOK_SDK_CLIENT_KEY="sdk-..."
    # 可选：export GROWTHBOOK_API_BASE_URL="https://api.growthbook.io"
    # 可选：export GROWTHBOOK_SDK_TIMEOUT_MS=10000
    # 可选：export SMOKE_EVAL_ATTRIBUTES_JSON='{}'
    # 可选：export SMOKE_WRITE=1          # 启用写接口
    # 可选：export SMOKE_PROJECT="<name>" # 指定项目名/ID；默认取列表第一个
    python3 scripts/smoke.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
GB = [sys.executable, str(SCRIPT_DIR / "growthbook.py")]

# 让 smoke.py 自身的检查（如 GROWTHBOOK_API_TOKEN 是否存在）也能从 .env 获取
sys.path.insert(0, str(SCRIPT_DIR))
from growthbook import _load_dotenv  # noqa: E402

_load_dotenv()

PASS = "\033[32mPASS\033[0m"
SKIP = "\033[33mSKIP\033[0m"
FAIL = "\033[31mFAIL\033[0m"

FAILURES: list[tuple[str, str]] = []
SECRET_ENV_KEYS = (
    "GROWTHBOOK_API_TOKEN",
    "GB_TOKEN",
    "GROWTHBOOK_SDK_CLIENT_KEY",
    "GROWTHBOOK_SDK_API_HOST",
)


def _smoke_retries() -> int:
    raw = os.environ.get("SMOKE_RETRIES")
    if raw is None:
        return 1
    try:
        retries = int(raw)
    except ValueError:
        return 0
    return max(retries, 0)


def _redact_secrets(text: str) -> str:
    redacted = text
    values = [
        (key, value)
        for key in SECRET_ENV_KEYS
        if (value := os.environ.get(key))
    ]
    for key, value in sorted(values, key=lambda item: len(item[1]), reverse=True):
        redacted = redacted.replace(value, f"<redacted:{key}>")
    return redacted


def run(label: str, args: list[str], *, capture: bool = True) -> dict | list | str | None:
    """调用 growthbook.py。成功返回解析后的 JSON；失败记录但不中断后续步骤。"""
    print(f"[smoke] >>> {label}  ({_redact_secrets(' '.join(args))})")
    retries = _smoke_retries()
    max_attempts = retries + 1
    for attempt in range(1, max_attempts + 1):
        try:
            proc = subprocess.run(
                GB + args,
                check=True,
                capture_output=True,
                text=True,
            )
            break
        except subprocess.CalledProcessError as e:
            err = (e.stderr or "").strip()
            preview = _redact_secrets(err.splitlines()[0] if err else "(no stderr)")
            if attempt < max_attempts:
                print(f"[smoke] retry {label} ({attempt}/{retries})")
                continue
            print(f"[smoke] {FAIL} {label} :: {preview}")
            FAILURES.append((label, preview))
            return None
    out = proc.stdout.strip()
    if not capture:
        for line in out.splitlines()[:3]:
            print(_redact_secrets(line))
        print(f"[smoke] {PASS} {label}\n")
        return None
    try:
        data = json.loads(out) if out else None
    except json.JSONDecodeError:
        data = out
    safe_out = _redact_secrets(out)
    preview = (safe_out[:200] + "…") if len(safe_out) > 200 else safe_out
    print(preview)
    print(f"[smoke] {PASS} {label}\n")
    return data


def pick_items(resp: object, keys: list[str]) -> list:
    if isinstance(resp, list):
        return resp
    if isinstance(resp, dict):
        for k in keys:
            v = resp.get(k)
            if isinstance(v, list):
                return v
    return []


def main() -> None:
    if not (os.environ.get("GROWTHBOOK_API_TOKEN") or os.environ.get("GB_TOKEN")):
        sys.stderr.write("[smoke] GROWTHBOOK_API_TOKEN / GB_TOKEN 未设置\n")
        sys.exit(1)
    if not os.environ.get("GROWTHBOOK_SDK_API_HOST") or not os.environ.get(
        "GROWTHBOOK_SDK_CLIENT_KEY"
    ):
        sys.stderr.write(
            "[smoke] GROWTHBOOK_SDK_API_HOST 和 GROWTHBOOK_SDK_CLIENT_KEY 必须设置\n"
        )
        sys.exit(1)

    print(
        "[smoke] origin = "
        f"{os.environ.get('GROWTHBOOK_API_BASE_URL') or os.environ.get('GB_APP_ORIGIN') or 'https://api.growthbook.io'}"
    )
    print(
        f"[smoke] SMOKE_WRITE = {os.environ.get('SMOKE_WRITE', '0')}  "
        f"(1 时启用 create-feature-flag / create-force-rule)\n"
    )
    print("[smoke] eval-feature = enabled  (uses GrowthBook Node SDK)\n")

    # 1. get-environments
    envs_resp = run("get-environments", ["get-environments"])
    envs = pick_items(envs_resp, ["environments", "items", "data"])
    first_env_id = envs[0].get("id") if envs and isinstance(envs[0], dict) else None

    # 2. get-projects
    projects_resp = run("get-projects", ["get-projects"])
    projects = pick_items(projects_resp, ["projects", "items", "data"])
    if not projects:
        print("[smoke] 没有项目，后续依赖项目的用例将跳过\n")

    target_project_hint = os.environ.get("SMOKE_PROJECT") or (
        projects[0].get("name") or projects[0].get("id") if projects else None
    )

    # 3. resolve-project-id
    resolved_project_id = None
    if target_project_hint:
        resolved = run(
            "resolve-project-id",
            ["resolve-project-id", "--project", target_project_hint],
        )
        if isinstance(resolved, dict):
            resolved_project_id = resolved.get("id")
    else:
        print(f"[smoke] {SKIP} resolve-project-id（无项目可用）\n")

    # 4. get-attributes
    run("get-attributes", ["get-attributes"])

    # 5. get-feature-flags（全局列表）
    feats_resp = run("get-feature-flags", ["get-feature-flags", "--limit", "5"])
    features = pick_items(feats_resp, ["features", "items", "data"])

    # 6. get-feature-flags --project
    if target_project_hint:
        run(
            "get-feature-flags --project",
            ["get-feature-flags", "--project", target_project_hint, "--limit", "5"],
        )

    # 7. get-feature-flags --q（走分页过滤路径）
    run(
        "get-feature-flags --q",
        ["get-feature-flags", "--q", "a", "--limit", "3"],
    )

    # 8. list-feature-keys
    run("list-feature-keys", ["list-feature-keys"])
    if resolved_project_id:
        run(
            "list-feature-keys --project-id",
            ["list-feature-keys", "--project-id", resolved_project_id],
        )

    # 9. get-feature-flags --feature-flag-id
    first_feature_id = None
    if features and isinstance(features[0], dict):
        first_feature_id = features[0].get("id")
    if first_feature_id:
        run(
            "get-feature-flags --feature-flag-id",
            ["get-feature-flags", "--feature-flag-id", first_feature_id],
        )
    else:
        print(f"[smoke] {SKIP} get-feature-flags --feature-flag-id（无 feature）\n")

    eval_feature_id = os.environ.get("SMOKE_EVAL_FEATURE") or first_feature_id
    if eval_feature_id:
        run(
            "eval-feature",
            [
                "eval-feature",
                "--feature-id",
                eval_feature_id,
                "--attributes-json",
                os.environ.get("SMOKE_EVAL_ATTRIBUTES_JSON", "{}"),
            ],
        )
    else:
        print(f"[smoke] {SKIP} eval-feature（无 feature）\n")

    # get-experiments
    exps_resp = run("get-experiments", ["get-experiments"])
    experiments = pick_items(exps_resp, ["experiments", "items", "data"])
    first_exp_id = (
        experiments[0].get("id") if experiments and isinstance(experiments[0], dict) else None
    )
    if first_exp_id:
        run(
            "get-experiments --experiment-id",
            ["get-experiments", "--experiment-id", first_exp_id],
        )
        run(
            "get-experiments --experiment-id --mode full",
            ["get-experiments", "--experiment-id", first_exp_id, "--mode", "full"],
        )
    else:
        print(f"[smoke] {SKIP} get-experiments --experiment-id（无实验）\n")

    # 12. get-metrics
    metrics_resp = run("get-metrics", ["get-metrics"])
    metrics_list: list = []
    fact_list: list = []
    if isinstance(metrics_resp, dict):
        metrics_list = pick_items(metrics_resp.get("metrics"), ["metrics", "items", "data"])
        fact_list = pick_items(
            metrics_resp.get("factMetrics"), ["factMetrics", "metrics", "items", "data"]
        )
    first_metric_id = (
        metrics_list[0].get("id") if metrics_list and isinstance(metrics_list[0], dict) else None
    )
    first_fact_id = (
        fact_list[0].get("id") if fact_list and isinstance(fact_list[0], dict) else None
    )
    if first_metric_id:
        run(
            "get-metrics --metric-id",
            ["get-metrics", "--metric-id", first_metric_id],
        )
    else:
        print(f"[smoke] {SKIP} get-metrics --metric-id（无普通指标）\n")
    if first_fact_id:
        run(
            "get-metrics --metric-id fact__",
            ["get-metrics", "--metric-id", f"fact__{first_fact_id}"],
        )
    else:
        print(f"[smoke] {SKIP} get-metrics --metric-id fact__（无 fact 指标）\n")

    # —— 写接口：默认跳过 ——
    if os.environ.get("SMOKE_WRITE") != "1":
        print(f"[smoke] {SKIP} create-feature-flag（设置 SMOKE_WRITE=1 启用）")
        print(f"[smoke] {SKIP} create-force-rule（设置 SMOKE_WRITE=1 启用）\n")
    else:
        if not resolved_project_id:
            print(f"[smoke] {SKIP} 写接口需要一个项目，未解析到 projectId\n")
        elif not first_env_id:
            print(f"[smoke] {SKIP} 写接口需要一个环境，未取到 environment id\n")
        else:
            ts = int(time.time())
            new_flag_id = f"smoke_{ts}"
            body = {
                "id": new_flag_id,
                "valueType": "boolean",
                "defaultValue": "false",
                "project": resolved_project_id,
                "description": "growthbook skill smoke test (safe to delete)",
                "tags": ["smoke"],
                "environments": {
                    first_env_id: {"enabled": True, "rules": []},
                },
            }
            run(
                "create-feature-flag",
                [
                    "create-feature-flag",
                    "--body-json",
                    json.dumps(body),
                    "--execute",
                ],
            )
            run(
                "create-force-rule",
                [
                    "create-force-rule",
                    "--feature-id",
                    new_flag_id,
                    "--env",
                    first_env_id,
                    "--value",
                    "true",
                    "--description",
                    "smoke force rule",
                    "--execute",
                ],
            )
            print(f"[smoke] 已创建临时 flag: {new_flag_id}（手动清理）\n")

    print("[smoke] all checks completed")
    if FAILURES:
        print(f"\n[smoke] {len(FAILURES)} step(s) FAILED:")
        for name, msg in FAILURES:
            print(f"  - {name}: {_redact_secrets(msg)}")
        sys.exit(1)


if __name__ == "__main__":
    main()

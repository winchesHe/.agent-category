"""``doctor``：聚合展示 token 身份、workspace、cache 与目标可见性。"""

from __future__ import annotations

import argparse
from typing import Any

from .actor import activate, discover_contexts, ensure_same_workspace
from .channels import resolve_channel
from .config import Config
from .output import emit


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "doctor",
        help="diagnose Bot/User identity and optional channel visibility (read-only)",
    )
    parser.add_argument("--channel", default=None, help="optional channel id or #name")
    parser.add_argument("--output", default=None)
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    cfg = Config()
    results: list[dict[str, Any]] = []
    contexts = []
    had_error = False
    for actor_name in ("bot", "user"):
        try:
            found = discover_contexts(cfg, (actor_name,))
            ctx = found.get(actor_name)
            if ctx is None:
                results.append({"actor": actor_name, "configured": False})
                continue
            contexts.append(ctx)
            activate(ctx)
            item: dict[str, Any] = {
                "actor": actor_name,
                "configured": True,
                "identity": ctx.public(),
                "cache_dir": str(ctx.cache_dir),
                "files_dir": str(ctx.files_dir),
            }
            if args.channel:
                try:
                    channel = resolve_channel(ctx.read_client(), args.channel, cfg=cfg)
                    channel_id = channel.get("id")
                    info = ctx.read_client().call("conversations.info", channel=channel_id)
                    actual = info.get("channel") or channel
                    item["channel"] = {
                        "id": actual.get("id"),
                        "name": actual.get("name"),
                        "is_member": actual.get("is_member"),
                        "is_archived": actual.get("is_archived"),
                        "visible": True,
                    }
                except Exception as exc:  # 聚合诊断，不能首错即停
                    had_error = True
                    item["channel"] = {"visible": False, "error": str(exc)}
            results.append(item)
        except Exception as exc:  # 聚合诊断，不能首错即停
            had_error = True
            results.append({"actor": actor_name, "configured": True, "error": str(exc)})

    try:
        ensure_same_workspace(contexts)
    except Exception as exc:
        had_error = True
        workspace = {"same_workspace": False, "error": str(exc)}
    else:
        workspace = {
            "same_workspace": True if len(contexts) > 1 else None,
            "team_ids": sorted({ctx.identity.team_id for ctx in contexts}),
        }

    emit(
        {
            "actor": {"requested": "doctor", "selected": None},
            "status": "ok" if not had_error else "issues_found",
            "defaults": {"read": cfg.read_actor, "write": cfg.write_actor},
            "workspace": workspace,
            "identities": results,
            "limitations": [
                "doctor 只能验证身份与只读可见性，不能证明 chat/files/reactions 写 scope",
            ],
        },
        output=args.output,
    )
    return 4 if had_error else 0


__all__ = ["register", "run"]

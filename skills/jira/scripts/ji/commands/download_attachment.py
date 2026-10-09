"""Download a Jira image attachment."""
from __future__ import annotations

import argparse
from pathlib import Path

from ji.client import JiraClient
from ji.config import Config
from ji.formatter import output


def register(subparsers) -> None:
    parser = subparsers.add_parser(
        "download-attachment",
        help="Download a single Jira image attachment with MIME and magic-byte checks",
    )
    parser.add_argument("attachment_url", help="Jira attachment content URL")
    parser.add_argument("--output-dir", help="Target directory")
    parser.add_argument("--max-bytes", type=int, help="Maximum allowed bytes")
    parser.add_argument("--format", choices=("json", "human", "summary"), default="json")
    parser.set_defaults(_handler=run)


def run(args: argparse.Namespace, config: Config) -> int:
    client = JiraClient(config)
    result = client.download_attachment(
        args.attachment_url,
        output_dir=Path(args.output_dir).expanduser() if args.output_dir else None,
        max_bytes=args.max_bytes,
    )
    result = {"schema_version": 1, "command": "download-attachment", **result}
    output(result, fmt=args.format)
    return 0 if result.get("ok") else 4

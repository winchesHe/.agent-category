"""Strict Jira Description input handling for ADF-first API creation."""
from __future__ import annotations

import json
import math
import re
import urllib.parse
from dataclasses import dataclass
from typing import Any

from ji.errors import ValidationError

MARKDOWN_PROFILE = "jira-md-v1"

_ESCAPABLE = frozenset(r"\`*_{ }[]()#+-.!|>~".replace(" ", ""))
_BLOCK_MARKS = {
    "atx_heading": "heading",
    "blockquote": "blockquote",
    "bullet_list": "bulletList",
    "ordered_list": "orderedList",
    "pipe_table": "table",
    "fenced_code": "codeBlock",
    "hard_break": "hardBreak",
}
_INLINE_MARKS = {
    "strong": "strong",
    "em": "em",
    "strike": "strike",
    "inline_code": "code",
    "inline_link": "link",
}
_BLOCKED_QUERY_KEYS = {
    "token",
    "access_token",
    "api_key",
    "apikey",
    "authorization",
    "jwt",
    "signature",
    "sig",
    "x-amz-signature",
    "x-goog-signature",
    "x-oss-signature",
}
_ALLOWED_SCHEMES = {"https", "http", "mailto"}

_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.*)$")
_TOO_DEEP_HEADING_RE = re.compile(r"^#{7,}[ \t]+")
_BLOCKQUOTE_RE = re.compile(r"^>[ \t]?(.*)$")
_BULLET_RE = re.compile(r"^([*+-])[ \t]+(.+)$")
_EMPTY_BULLET_RE = re.compile(r"^[*+-][ \t]+$")
_ORDERED_RE = re.compile(r"^(\d+)[.)][ \t]+(.+)$")
_EMPTY_ORDERED_RE = re.compile(r"^\d+[.)][ \t]+$")
_FENCE_RE = re.compile(r"^(`{3,})([^`]*)$")
_SETEXT_RE = re.compile(r"^[ \t]{0,3}(?:=+|-+)[ \t]*$")
_THEMATIC_RE = re.compile(r"^[ \t]{0,3}(?:(?:\*[ \t]*){3,}|(?:_[ \t]*){3,}|(?:-[ \t]*){3,})$")
_REFERENCE_DEF_RE = re.compile(r"^[ \t]{0,3}\[[^\]]+\]:")
_FOOTNOTE_DEF_RE = re.compile(r"^[ \t]{0,3}\[\^[^\]]+\]:")
_JIRA_WIKI_RE = re.compile(r"^(?:h[1-6]\.|\{(?:panel|code|quote)(?::[^}]*)?\})", re.IGNORECASE)
_RAW_HTML_RE = re.compile(r"^(?:</?[A-Za-z][^>]*>|<!--|<![A-Za-z])")
_AUTOLINK_RE = re.compile(r"^<(?:https?://|mailto:)[^>]+>", re.IGNORECASE)
_EMOJI_RE = re.compile(r"^:[a-z][a-z0-9_+-]{1,}:", re.IGNORECASE)
_MDX_EXPR_RE = re.compile(r"^\{[A-Za-z_$][^{}]*\}")


@dataclass(frozen=True)
class MarkdownParseResult:
    adf: dict[str, Any]
    constructs: tuple[dict[str, Any], ...]


def _fail(
    code: str,
    reason: str,
    *,
    line: int | None = None,
    token: str | None = None,
) -> None:
    details: dict[str, Any] = {"reason": reason}
    if line is not None:
        details["line"] = line
    if token is not None:
        details["token"] = token
    raise ValidationError(
        "Jira Description input validation failed",
        details,
        error_code=code,
    )


def _append_text(
    nodes: list[dict[str, Any]],
    text: str,
    marks: list[dict[str, Any]] | None = None,
) -> None:
    if not text:
        return
    node: dict[str, Any] = {"type": "text", "text": text}
    if marks:
        node["marks"] = marks
    if (
        nodes
        and nodes[-1].get("type") == "text"
        and nodes[-1].get("marks", []) == node.get("marks", [])
    ):
        nodes[-1]["text"] += text
    else:
        nodes.append(node)


def _apply_mark(
    nodes: list[dict[str, Any]],
    mark: dict[str, Any],
    *,
    line: int,
) -> list[dict[str, Any]]:
    marked: list[dict[str, Any]] = []
    for source in nodes:
        if source.get("type") != "text":
            _fail("markdown_unsupported", "inline_mark_contains_non_text", line=line)
        existing = list(source.get("marks", []))
        existing_types = {item.get("type") for item in existing if isinstance(item, dict)}
        mark_type = mark.get("type")
        if (mark_type == "code" and existing) or ("code" in existing_types and mark_type != "code"):
            _fail("markdown_unsupported", "code_mark_cannot_be_combined", line=line)
        node = dict(source)
        node["marks"] = [*existing, mark]
        marked.append(node)
    return marked


def _delimiter_can_open(text: str, index: int, delimiter: str) -> bool:
    after = index + len(delimiter)
    if after >= len(text) or text[after].isspace():
        return False
    if delimiter.startswith("_"):
        before_char = text[index - 1] if index else ""
        after_char = text[after]
        if before_char.isalnum() and after_char.isalnum():
            return False
    return True


def _delimiter_can_close(text: str, index: int, delimiter: str) -> bool:
    if index <= 0 or text[index - 1].isspace():
        return False
    after = index + len(delimiter)
    if delimiter.startswith("_"):
        before_char = text[index - 1]
        after_char = text[after] if after < len(text) else ""
        if before_char.isalnum() and after_char.isalnum():
            return False
    return True


class _InlineParser:
    def __init__(
        self,
        text: str,
        *,
        line: int,
        constructs: list[dict[str, Any]],
        allow_links: bool = True,
    ) -> None:
        self.text = text
        self.line = line
        self.constructs = constructs
        self.allow_links = allow_links

    def parse(self) -> list[dict[str, Any]]:
        nodes, index, closed = self._parse_until(0, None)
        if not closed or index != len(self.text):
            _fail("markdown_unsupported", "invalid_inline_delimiter", line=self.line)
        return nodes

    def _parse_until(
        self,
        index: int,
        closing: str | None,
    ) -> tuple[list[dict[str, Any]], int, bool]:
        nodes: list[dict[str, Any]] = []
        text_buffer: list[str] = []

        def flush() -> None:
            if text_buffer:
                _append_text(nodes, "".join(text_buffer))
                text_buffer.clear()

        while index < len(self.text):
            if (
                closing
                and self.text.startswith(closing, index)
                and _delimiter_can_close(self.text, index, closing)
            ):
                flush()
                return nodes, index + len(closing), True

            char = self.text[index]
            remaining = self.text[index:]
            if char == "\\":
                if index + 1 < len(self.text) and self.text[index + 1] in _ESCAPABLE:
                    text_buffer.append(self.text[index + 1])
                    self.constructs.append({"kind": "backslash_escape", "line": self.line})
                    index += 2
                    continue
                text_buffer.append(char)
                index += 1
                continue

            if remaining.startswith("!["):
                _fail("markdown_unsupported", "image", line=self.line, token="image")
            if remaining.startswith("[^"):
                _fail("markdown_unsupported", "footnote", line=self.line, token="footnote")
            if re.match(r"^\[[^\]]+\][ \t]*\[[^\]]*\]", remaining):
                _fail("markdown_unsupported", "reference_link", line=self.line, token="reference_link")
            if _AUTOLINK_RE.match(remaining):
                _fail("markdown_unsupported", "autolink", line=self.line, token="autolink")
            if _RAW_HTML_RE.match(remaining):
                _fail("markdown_unsupported", "raw_html", line=self.line, token="raw_html")
            if _EMOJI_RE.match(remaining):
                _fail("markdown_unsupported", "emoji_shortcode", line=self.line, token="emoji_shortcode")
            if _MDX_EXPR_RE.match(remaining):
                _fail("markdown_unsupported", "mdx", line=self.line, token="mdx")

            if char == "`":
                flush()
                run = 1
                while index + run < len(self.text) and self.text[index + run] == "`":
                    run += 1
                delimiter = "`" * run
                end = self.text.find(delimiter, index + run)
                if end < 0:
                    _fail("markdown_unsupported", "unclosed_inline_code", line=self.line)
                code = self.text[index + run:end]
                if len(code) >= 2 and code.startswith(" ") and code.endswith(" ") and code.strip():
                    code = code[1:-1]
                _append_text(nodes, code, [{"type": "code"}])
                self.constructs.append({"kind": "inline_code", "line": self.line})
                index = end + run
                continue

            if char == "[":
                link = self._try_link(index)
                if link is not None:
                    flush()
                    link_nodes, index = link
                    nodes.extend(link_nodes)
                    continue

            delimiter: str | None = None
            mark_type: str | None = None
            kind: str | None = None
            for candidate, candidate_mark, candidate_kind in (
                ("**", "strong", "strong"),
                ("__", "strong", "strong"),
                ("~~", "strike", "strike"),
                ("*", "em", "em"),
                ("_", "em", "em"),
            ):
                if self.text.startswith(candidate, index):
                    delimiter = candidate
                    mark_type = candidate_mark
                    kind = candidate_kind
                    break
            if delimiter:
                if _delimiter_can_open(self.text, index, delimiter):
                    flush()
                    inner, new_index, closed = self._parse_until(index + len(delimiter), delimiter)
                    if not closed or not inner:
                        _fail(
                            "markdown_unsupported",
                            "unclosed_or_empty_inline_delimiter",
                            line=self.line,
                            token=kind,
                        )
                    nodes.extend(_apply_mark(inner, {"type": mark_type}, line=self.line))
                    self.constructs.append({"kind": kind, "line": self.line})
                    index = new_index
                    continue
                if _delimiter_can_close(self.text, index, delimiter):
                    _fail(
                        "markdown_unsupported",
                        "unmatched_inline_closer",
                        line=self.line,
                        token=kind,
                    )

            text_buffer.append(char)
            index += 1

        flush()
        return nodes, index, closing is None

    def _try_link(self, index: int) -> tuple[list[dict[str, Any]], int] | None:
        escaped = False
        close = None
        cursor = index + 1
        while cursor < len(self.text):
            char = self.text[cursor]
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "[":
                break
            elif char == "]":
                close = cursor
                break
            cursor += 1
        if close is None:
            return None
        if close + 1 < len(self.text) and self.text[close + 1] == "[":
            _fail("markdown_unsupported", "reference_link", line=self.line, token="reference_link")
        if close + 1 >= len(self.text) or self.text[close + 1] != "(":
            return None
        if not self.allow_links:
            _fail("markdown_unsupported", "nested_link", line=self.line, token="inline_link")

        end = close + 2
        escaped = False
        while end < len(self.text):
            char = self.text[end]
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "(":
                _fail("markdown_unsupported", "nested_link_destination", line=self.line)
            elif char == ")":
                break
            end += 1
        if end >= len(self.text):
            _fail("markdown_unsupported", "unclosed_link", line=self.line, token="inline_link")

        label = self.text[index + 1:close]
        href = self.text[close + 2:end]
        if not label:
            _fail("markdown_unsupported", "empty_link_label", line=self.line)
        if any(char.isspace() for char in href):
            _fail("markdown_unsupported", "link_title_or_whitespace", line=self.line)
        validate_safe_url(href, line=self.line)
        label_nodes = _InlineParser(
            label,
            line=self.line,
            constructs=self.constructs,
            allow_links=False,
        ).parse()
        link_mark = {"type": "link", "attrs": {"href": href}}
        self.constructs.append({"kind": "inline_link", "line": self.line})
        return _apply_mark(label_nodes, link_mark, line=self.line), end + 1


def _parse_inline(
    text: str,
    *,
    line: int,
    constructs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return _InlineParser(text, line=line, constructs=constructs).parse()


def _has_unescaped_trailing_pipe(value: str) -> bool:
    if not value.endswith("|"):
        return False
    slashes = 0
    cursor = len(value) - 2
    while cursor >= 0 and value[cursor] == "\\":
        slashes += 1
        cursor -= 1
    return slashes % 2 == 0


def _split_table_row(line: str) -> list[str] | None:
    value = line.strip()
    if "|" not in value:
        return None
    leading = value.startswith("|")
    trailing = _has_unescaped_trailing_pipe(value)
    cells: list[str] = []
    buffer: list[str] = []
    saw_separator = False
    index = 0
    while index < len(value):
        char = value[index]
        if char == "\\" and index + 1 < len(value):
            buffer.extend((char, value[index + 1]))
            index += 2
            continue
        if char == "|":
            cells.append("".join(buffer).strip())
            buffer.clear()
            saw_separator = True
        else:
            buffer.append(char)
        index += 1
    cells.append("".join(buffer).strip())
    if not saw_separator:
        return None
    if leading:
        cells = cells[1:]
    if trailing:
        cells = cells[:-1]
    return cells


def _separator_info(line: str) -> tuple[bool, bool, int]:
    cells = _split_table_row(line)
    if not cells:
        return False, False, 0
    patterns = [re.fullmatch(r":?-{3,}:?", cell) for cell in cells]
    if not all(patterns):
        return False, False, len(cells)
    aligned = any(cell.startswith(":") or cell.endswith(":") for cell in cells)
    return True, aligned, len(cells)


def _unsupported_block(line: str) -> tuple[str, str] | None:
    if _TOO_DEEP_HEADING_RE.match(line):
        return "atx_heading_level", "atx_heading"
    if _THEMATIC_RE.match(line):
        return "thematic_break", "thematic_break"
    if _REFERENCE_DEF_RE.match(line):
        return "reference_link", "reference_link"
    if _FOOTNOTE_DEF_RE.match(line):
        return "footnote", "footnote"
    if _JIRA_WIKI_RE.match(line):
        return "jira_wiki_markup", "jira_wiki_markup"
    if re.match(r"^~{3,}(?:[ \t]+.*)?$", line):
        return "unsupported_fence", "fenced_code"
    if re.match(r"^[ \t]*:[ \t]+\S", line):
        return "definition_list", "definition_list"
    if re.match(r"^[ \t]{2,}(?:[*+-]|\d+[.)])[ \t]+", line):
        return "nested_list", "nested_list"
    stripped = line.lstrip(" \t")
    if line.startswith(("    ", "\t")) and stripped:
        if re.match(r"^(?:[*+-]|\d+[.)])[ \t]+", stripped):
            return "nested_list", "nested_list"
        return "indented_code", "indented_code"
    if line.startswith(">>") or re.match(r"^>[ \t]*>", line):
        return "nested_blockquote", "nested_blockquote"
    if _EMPTY_BULLET_RE.match(line) or _EMPTY_ORDERED_RE.match(line):
        return "empty_list_item", "list"
    return None


def _is_block_start(lines: list[str], index: int) -> bool:
    line = lines[index]
    if _unsupported_block(line):
        return True
    if _HEADING_RE.match(line) or _BLOCKQUOTE_RE.match(line):
        return True
    if _BULLET_RE.match(line) or _ORDERED_RE.match(line) or _FENCE_RE.match(line):
        return True
    if index + 1 < len(lines):
        is_separator, _, _ = _separator_info(lines[index + 1])
        if is_separator and _split_table_row(line) is not None:
            return True
    return False


def _paragraph_with_breaks(
    source_lines: list[tuple[str, int]],
    *,
    constructs: list[dict[str, Any]],
) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    for index, (line, line_number) in enumerate(source_lines):
        if index:
            content.append({"type": "hardBreak"})
            constructs.append({"kind": "hard_break", "line": line_number})
        content.extend(_parse_inline(line, line=line_number, constructs=constructs))
    return {"type": "paragraph", "content": content}


def markdown_to_adf_v1(markdown: str) -> MarkdownParseResult:
    if not isinstance(markdown, str):
        _fail("markdown_unsupported", "markdown_must_be_string")
    if any(char == "\x00" or (ord(char) < 32 and char not in "\n\r\t") for char in markdown):
        _fail("markdown_unsupported", "control_character")

    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    content: list[dict[str, Any]] = []
    constructs: list[dict[str, Any]] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        line_number = index + 1
        if not line.strip():
            index += 1
            continue
        unsupported = _unsupported_block(line)
        if unsupported:
            reason, token = unsupported
            _fail("markdown_unsupported", reason, line=line_number, token=token)

        fence = _FENCE_RE.match(line)
        if fence:
            language = fence.group(2).strip()
            if language and (any(char.isspace() for char in language) or not re.fullmatch(r"[A-Za-z0-9_+.-]+", language)):
                _fail("markdown_unsupported", "invalid_code_language", line=line_number)
            delimiter = fence.group(1)
            code_lines: list[str] = []
            cursor = index + 1
            while cursor < len(lines) and not re.fullmatch(rf"`{{{len(delimiter)},}}[ \t]*", lines[cursor]):
                code_lines.append(lines[cursor])
                cursor += 1
            if cursor >= len(lines):
                _fail("markdown_unsupported", "unclosed_fenced_code", line=line_number, token="fenced_code")
            node: dict[str, Any] = {
                "type": "codeBlock",
                "content": ([{"type": "text", "text": "\n".join(code_lines)}] if code_lines else []),
            }
            if language:
                node["attrs"] = {"language": language}
            content.append(node)
            constructs.append({"kind": "fenced_code", "line": line_number})
            index = cursor + 1
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            body = heading.group(2)
            content.append(
                {
                    "type": "heading",
                    "attrs": {"level": len(heading.group(1))},
                    "content": _parse_inline(body, line=line_number, constructs=constructs),
                }
            )
            constructs.append({"kind": "atx_heading", "line": line_number})
            index += 1
            continue

        quote = _BLOCKQUOTE_RE.match(line)
        if quote:
            quote_lines: list[tuple[str, int]] = []
            cursor = index
            while cursor < len(lines):
                match = _BLOCKQUOTE_RE.match(lines[cursor])
                if not match:
                    break
                inner = match.group(1)
                inner_unsupported = _unsupported_block(inner)
                inner_separator, _, _ = _separator_info(inner)
                if (
                    _BLOCKQUOTE_RE.match(inner)
                    or _HEADING_RE.match(inner)
                    or _BULLET_RE.match(inner)
                    or _ORDERED_RE.match(inner)
                    or _FENCE_RE.match(inner)
                    or inner_unsupported
                    or inner_separator
                ):
                    _fail(
                        "markdown_unsupported",
                        "blockquote_complex_block",
                        line=cursor + 1,
                        token="blockquote",
                    )
                quote_lines.append((inner, cursor + 1))
                cursor += 1
            content.append(
                {
                    "type": "blockquote",
                    "content": [_paragraph_with_breaks(quote_lines, constructs=constructs)],
                }
            )
            constructs.append({"kind": "blockquote", "line": line_number})
            index = cursor
            continue

        bullet = _BULLET_RE.match(line)
        if bullet:
            items: list[dict[str, Any]] = []
            cursor = index
            while cursor < len(lines):
                match = _BULLET_RE.match(lines[cursor])
                if not match:
                    break
                body = match.group(2)
                if re.match(r"^\[[ xX]\](?:[ \t]+|$)", body):
                    _fail("markdown_unsupported", "task_list", line=cursor + 1, token="task_list")
                items.append(
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": _parse_inline(body, line=cursor + 1, constructs=constructs),
                            }
                        ],
                    }
                )
                cursor += 1
            content.append({"type": "bulletList", "content": items})
            constructs.append({"kind": "bullet_list", "line": line_number})
            index = cursor
            continue

        ordered = _ORDERED_RE.match(line)
        if ordered:
            order = int(ordered.group(1))
            if order < 1:
                _fail("markdown_unsupported", "ordered_list_start", line=line_number)
            items = []
            cursor = index
            while cursor < len(lines):
                match = _ORDERED_RE.match(lines[cursor])
                if not match:
                    break
                body = match.group(2)
                if re.match(r"^\[[ xX]\](?:[ \t]+|$)", body):
                    _fail("markdown_unsupported", "task_list", line=cursor + 1, token="task_list")
                items.append(
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": _parse_inline(body, line=cursor + 1, constructs=constructs),
                            }
                        ],
                    }
                )
                cursor += 1
            content.append({"type": "orderedList", "attrs": {"order": order}, "content": items})
            constructs.append({"kind": "ordered_list", "line": line_number})
            index = cursor
            continue

        if index + 1 < len(lines):
            is_separator, aligned, separator_columns = _separator_info(lines[index + 1])
            header_cells = _split_table_row(line)
            next_cells = _split_table_row(lines[index + 1])
            malformed_separator = bool(
                next_cells
                and all(re.fullmatch(r":?-+:?", cell) for cell in next_cells)
            )
            if header_cells is not None and malformed_separator and not is_separator:
                _fail("markdown_unsupported", "malformed_table", line=index + 2, token="pipe_table")
            if is_separator and header_cells is not None:
                if aligned:
                    _fail("markdown_unsupported", "aligned_table", line=index + 2, token="pipe_table")
                if len(header_cells) != separator_columns:
                    _fail("markdown_unsupported", "malformed_table", line=index + 2, token="pipe_table")
                header = {
                    "type": "tableRow",
                    "content": [
                        {
                            "type": "tableHeader",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": _parse_inline(cell, line=line_number, constructs=constructs),
                                }
                            ],
                        }
                        for cell in header_cells
                    ],
                }
                rows = [header]
                cursor = index + 2
                while cursor < len(lines) and lines[cursor].strip():
                    row_cells = _split_table_row(lines[cursor])
                    if row_cells is None:
                        break
                    row_is_separator, _, _ = _separator_info(lines[cursor])
                    if row_is_separator or len(row_cells) != len(header_cells):
                        _fail("markdown_unsupported", "malformed_table", line=cursor + 1, token="pipe_table")
                    rows.append(
                        {
                            "type": "tableRow",
                            "content": [
                                {
                                    "type": "tableCell",
                                    "content": [
                                        {
                                            "type": "paragraph",
                                            "content": _parse_inline(cell, line=cursor + 1, constructs=constructs),
                                        }
                                    ],
                                }
                                for cell in row_cells
                            ],
                        }
                    )
                    cursor += 1
                content.append(
                    {
                        "type": "table",
                        "attrs": {"isNumberColumnEnabled": False, "layout": "default"},
                        "content": rows,
                    }
                )
                constructs.append({"kind": "pipe_table", "line": line_number})
                index = cursor
                continue

        is_separator, _, _ = _separator_info(line)
        if is_separator:
            _fail("markdown_unsupported", "malformed_table", line=line_number, token="pipe_table")

        paragraph_lines: list[tuple[str, int]] = []
        cursor = index
        while cursor < len(lines) and lines[cursor].strip():
            if cursor > index and _is_block_start(lines, cursor):
                break
            if cursor > index and _SETEXT_RE.match(lines[cursor]):
                _fail("markdown_unsupported", "setext_heading", line=cursor + 1, token="setext_heading")
            unsupported = _unsupported_block(lines[cursor])
            if unsupported:
                reason, token = unsupported
                _fail("markdown_unsupported", reason, line=cursor + 1, token=token)
            paragraph_lines.append((lines[cursor], cursor + 1))
            cursor += 1
        content.append(_paragraph_with_breaks(paragraph_lines, constructs=constructs))
        index = cursor

    adf = {"type": "doc", "version": 1, "content": content}
    validate_adf_document(adf)
    result = MarkdownParseResult(adf=adf, constructs=tuple(constructs))
    ensure_no_markdown_residual(result, adf)
    return result


def _walk_adf(node: Any):
    if isinstance(node, dict):
        yield node
        for child in node.get("content", []):
            yield from _walk_adf(child)
    elif isinstance(node, list):
        for child in node:
            yield from _walk_adf(child)


def ensure_no_markdown_residual(
    parsed: MarkdownParseResult,
    candidate_adf: dict[str, Any],
) -> None:
    if candidate_adf != parsed.adf:
        _fail("markdown_residual", "conversion_output_mismatch")
    nodes = list(_walk_adf(candidate_adf))
    node_counts: dict[str, int] = {}
    mark_counts: dict[str, int] = {}
    for node in nodes:
        node_type = node.get("type")
        if isinstance(node_type, str):
            node_counts[node_type] = node_counts.get(node_type, 0) + 1
        for mark in node.get("marks", []):
            if isinstance(mark, dict) and isinstance(mark.get("type"), str):
                mark_type = mark["type"]
                mark_counts[mark_type] = mark_counts.get(mark_type, 0) + 1

    expected_nodes: dict[str, int] = {}
    expected_marks: dict[str, int] = {}
    for construct in parsed.constructs:
        kind = construct["kind"]
        if kind in _BLOCK_MARKS:
            node_type = _BLOCK_MARKS[kind]
            expected_nodes[node_type] = expected_nodes.get(node_type, 0) + 1
        if kind in _INLINE_MARKS:
            mark_type = _INLINE_MARKS[kind]
            expected_marks[mark_type] = expected_marks.get(mark_type, 0) + 1
    for node_type, count in expected_nodes.items():
        if node_counts.get(node_type, 0) < count:
            _fail("markdown_residual", "missing_structural_node", token=node_type)
    for mark_type, count in expected_marks.items():
        if mark_counts.get(mark_type, 0) < count:
            _fail("markdown_residual", "missing_inline_mark", token=mark_type)


def validate_safe_url(url: str, *, line: int | None = None) -> None:
    if not isinstance(url, str) or not url:
        _fail("unsafe_link", "empty_url", line=line)
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in url):
        _fail("unsafe_link", "url_contains_whitespace_or_control", line=line)
    decoded = urllib.parse.unquote(url)
    if any(ord(char) < 32 or ord(char) == 127 for char in decoded):
        _fail("unsafe_link", "url_contains_encoded_control", line=line)
    try:
        parsed = urllib.parse.urlsplit(url)
        scheme = parsed.scheme.casefold()
        _ = parsed.port
    except ValueError:
        _fail("unsafe_link", "url_parse_failed", line=line)
    if scheme not in _ALLOWED_SCHEMES:
        _fail("unsafe_link", "scheme_not_allowed", line=line, token=scheme or "missing")
    if scheme in {"http", "https"}:
        if not parsed.hostname:
            _fail("unsafe_link", "http_url_has_no_host", line=line, token=scheme)
        if "\\" in parsed.netloc:
            _fail("unsafe_link", "http_url_has_backslash", line=line, token=scheme)
        if parsed.username is not None or parsed.password is not None:
            _fail("unsafe_link", "url_contains_userinfo", line=line, token=scheme)
    if scheme == "mailto" and not parsed.path:
        _fail("unsafe_link", "mailto_has_no_recipient", line=line, token=scheme)
    for key, _ in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        if key.casefold() in _BLOCKED_QUERY_KEYS:
            _fail("unsafe_link", "sensitive_query_key", line=line, token=key.casefold())


def _validate_json_value(value: Any, *, depth: int, active: set[int]) -> None:
    if depth > 64:
        _fail("adf_invalid", "document_too_deep")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail("adf_invalid", "non_finite_number")
        return
    if isinstance(value, list):
        identity = id(value)
        if identity in active:
            _fail("adf_invalid", "cyclic_document")
        active.add(identity)
        for item in value:
            _validate_json_value(item, depth=depth + 1, active=active)
        active.remove(identity)
        return
    if isinstance(value, dict):
        identity = id(value)
        if identity in active:
            _fail("adf_invalid", "cyclic_document")
        active.add(identity)
        for key, item in value.items():
            if not isinstance(key, str):
                _fail("adf_invalid", "non_string_object_key")
            _validate_json_value(item, depth=depth + 1, active=active)
        active.remove(identity)
        return
    _fail("adf_invalid", "non_json_value")


def _validate_url_attrs(attrs: dict[str, Any], *, token: str) -> None:
    for key in ("href", "url"):
        if key not in attrs:
            continue
        url = attrs[key]
        if not isinstance(url, str):
            _fail("adf_invalid", f"{key}_must_be_string", token=token)
        validate_safe_url(url)


def validate_adf_document(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        _fail("adf_invalid", "document_must_be_object")
    if (
        document.get("type") != "doc"
        or type(document.get("version")) is not int
        or document.get("version") != 1
    ):
        _fail("adf_invalid", "invalid_doc_root")
    if not isinstance(document.get("content"), list):
        _fail("adf_invalid", "doc_content_must_be_list")
    _validate_json_value(document, depth=0, active=set())

    for node in _walk_adf(document):
        node_type = node.get("type")
        if not isinstance(node_type, str) or not node_type:
            _fail("adf_invalid", "node_type_must_be_string")
        if "attrs" in node:
            if not isinstance(node["attrs"], dict):
                _fail("adf_invalid", "node_attrs_must_be_object", token=node_type)
            _validate_url_attrs(node["attrs"], token=node_type)
        if "content" in node:
            if not isinstance(node["content"], list):
                _fail("adf_invalid", "node_content_must_be_list", token=node_type)
            if any(not isinstance(child, dict) for child in node["content"]):
                _fail("adf_invalid", "node_content_item_must_be_object", token=node_type)
        if "marks" in node:
            if not isinstance(node["marks"], list):
                _fail("adf_invalid", "node_marks_must_be_list", token=node_type)
            for mark in node["marks"]:
                if (
                    not isinstance(mark, dict)
                    or not isinstance(mark.get("type"), str)
                    or not mark["type"]
                ):
                    _fail("adf_invalid", "invalid_mark", token=node_type)
                if "attrs" in mark:
                    if not isinstance(mark["attrs"], dict):
                        _fail("adf_invalid", "mark_attrs_must_be_object", token=mark.get("type"))
                    _validate_url_attrs(mark["attrs"], token=mark["type"])
                if mark.get("type") == "link" and "href" not in (mark.get("attrs") or {}):
                    _fail("adf_invalid", "link_href_must_be_string", token="link")
        if node_type == "text" and not isinstance(node.get("text"), str):
            _fail("adf_invalid", "text_node_requires_text")
        if node_type in {"inlineCard", "blockCard"} and "url" not in (node.get("attrs") or {}):
            _fail("adf_invalid", "card_url_must_be_string", token=node_type)

    return document


def parse_adf_json(raw: str) -> dict[str, Any]:
    def reject_constant(_value: str) -> None:
        raise ValueError("non-finite")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate-key")
            value[key] = item
        return value

    try:
        document = json.loads(
            raw,
            parse_constant=reject_constant,
            object_pairs_hook=unique_object,
        )
    except (json.JSONDecodeError, ValueError):
        _fail("adf_invalid", "invalid_json")
    return validate_adf_document(document)


def adf_semantic_projection(value: Any) -> Any:
    if isinstance(value, list):
        return [adf_semantic_projection(item) for item in value]
    if not isinstance(value, dict):
        return value
    projected: dict[str, Any] = {}
    for key, item in value.items():
        if key == "attrs" and isinstance(item, dict):
            attrs = {
                attr_key: adf_semantic_projection(attr_value)
                for attr_key, attr_value in item.items()
                if attr_key != "localId"
            }
            if attrs:
                projected[key] = attrs
            continue
        if key == "marks" and isinstance(item, list):
            marks = [adf_semantic_projection(mark) for mark in item]
            projected[key] = sorted(
                marks,
                key=lambda mark: json.dumps(mark, ensure_ascii=False, sort_keys=True),
            )
            continue
        projected[key] = adf_semantic_projection(item)
    return projected


def adf_semantically_equal(expected: Any, actual: Any) -> bool:
    return adf_semantic_projection(expected) == adf_semantic_projection(actual)

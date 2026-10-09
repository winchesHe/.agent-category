"""Small fail-closed lexer for one SELECT-family readonly statement."""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..errors import SkillError


_DOLLAR_QUOTE = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")
_WORD_START = re.compile(r"[A-Za-z_]")
_WORD_BODY = re.compile(r"[A-Za-z0-9_$]")
_BLOCKED_KEYWORDS = frozenset(
    {
        "ALTER",
        "ANALYZE",
        "BEGIN",
        "CALL",
        "CLUSTER",
        "COMMENT",
        "COMMIT",
        "COPY",
        "CREATE",
        "DEALLOCATE",
        "DECLARE",
        "DELETE",
        "DO",
        "DROP",
        "EXECUTE",
        "GRANT",
        "INSERT",
        "INTO",
        "LOCK",
        "MERGE",
        "PREPARE",
        "REFRESH",
        "REINDEX",
        "RESET",
        "REVOKE",
        "ROLLBACK",
        "SET",
        "TRUNCATE",
        "UNLOAD",
        "UPDATE",
        "VACUUM",
    }
)
_BLOCKED_FUNCTIONS = frozenset(
    {
        "PG_CANCEL_BACKEND",
        "PG_TERMINATE_BACKEND",
    }
)


@dataclass(frozen=True)
class SqlToken:
    kind: str
    value: str
    start: int
    end: int


def _syntax_error() -> SkillError:
    return SkillError(
        category="query",
        code="syntax_error",
        retry_class="after_change",
    )


def _safety_error(code: str) -> SkillError:
    return SkillError(category="safety", code=code, retry_class="never")


def _quoted_end(
    sql: str,
    start: int,
    quote: str,
    *,
    backslash_escapes: bool = False,
) -> int:
    index = start + 1
    while index < len(sql):
        if backslash_escapes and sql[index] == "\\":
            index += 2
            continue
        if sql[index] != quote:
            index += 1
            continue
        if index + 1 < len(sql) and sql[index + 1] == quote:
            index += 2
            continue
        return index + 1
    raise _syntax_error()


def _block_comment_end(sql: str, start: int) -> int:
    depth = 1
    index = start + 2
    while index < len(sql):
        if sql.startswith("/*", index):
            depth += 1
            index += 2
        elif sql.startswith("*/", index):
            depth -= 1
            index += 2
            if depth == 0:
                return index
        else:
            index += 1
    raise _syntax_error()


def _line_comment_end(sql: str, start: int) -> int:
    index = start + 2
    while index < len(sql):
        if sql[index] == "\n":
            return index + 1
        if sql[index] == "\r":
            if index + 1 < len(sql) and sql[index + 1] == "\n":
                return index + 2
            return index + 1
        index += 1
    return len(sql)


def scan_sql(sql: str) -> tuple[SqlToken, ...]:
    """Return SQL spans, including opaque comments and quoted data."""

    tokens: list[SqlToken] = []
    index = 0
    while index < len(sql):
        char = sql[index]
        if char.isspace():
            index += 1
            continue
        if sql.startswith("--", index):
            end = _line_comment_end(sql, index)
            tokens.append(SqlToken("COMMENT", "", index, end))
            index = end
            continue
        if sql.startswith("/*", index):
            end = _block_comment_end(sql, index)
            tokens.append(SqlToken("COMMENT", "", index, end))
            index = end
            continue
        if char in {"'", '"'}:
            is_escape_string = (
                char == "'"
                and bool(tokens)
                and tokens[-1].kind == "WORD"
                and tokens[-1].value == "E"
                and tokens[-1].end == index
            )
            end = _quoted_end(
                sql,
                index,
                char,
                backslash_escapes=is_escape_string,
            )
            if char == '"':
                identifier = sql[index + 1 : end - 1].replace('""', '"').upper()
                tokens.append(SqlToken("QUOTED_IDENTIFIER", identifier, index, end))
            else:
                tokens.append(SqlToken("QUOTED", "", index, end))
            index = end
            continue
        if char == "$":
            match = _DOLLAR_QUOTE.match(sql, index)
            if match:
                delimiter = match.group(0)
                close = sql.find(delimiter, match.end())
                if close < 0:
                    raise _syntax_error()
                end = close + len(delimiter)
                tokens.append(SqlToken("QUOTED", "", index, end))
                index = end
                continue
        if char == ";":
            tokens.append(SqlToken("SEMICOLON", char, index, index + 1))
            index += 1
            continue
        if _WORD_START.fullmatch(char):
            end = index + 1
            while end < len(sql) and _WORD_BODY.fullmatch(sql[end]):
                end += 1
            tokens.append(SqlToken("WORD", sql[index:end].upper(), index, end))
            index = end
            continue
        tokens.append(SqlToken("SYMBOL", char, index, index + 1))
        index += 1
    return tuple(tokens)


def tokenize_sql(sql: str) -> tuple[SqlToken, ...]:
    """Return significant tokens while treating comments and quoted data as opaque."""

    return tuple(token for token in scan_sql(sql) if token.kind != "COMMENT")


def _top_level_words(tokens: list[SqlToken]) -> list[str]:
    words: list[str] = []
    depth = 0
    for token in tokens:
        if token.kind == "SYMBOL" and token.value == "(":
            depth += 1
            continue
        if token.kind == "SYMBOL" and token.value == ")":
            depth -= 1
            if depth < 0:
                raise _syntax_error()
            continue
        if depth == 0 and token.kind == "WORD":
            words.append(token.value)
    if depth != 0:
        raise _syntax_error()
    return words


def _has_blocked_function_call(tokens: list[SqlToken]) -> bool:
    return any(
        token.kind in {"WORD", "QUOTED_IDENTIFIER"}
        and token.value in _BLOCKED_FUNCTIONS
        and index + 1 < len(tokens)
        and tokens[index + 1].kind == "SYMBOL"
        and tokens[index + 1].value == "("
        for index, token in enumerate(tokens)
    )


def validate_read_only_sql(sql: str) -> str:
    """Validate one SELECT/WITH statement and remove one trailing semicolon."""

    if not isinstance(sql, str):
        raise _safety_error("write_blocked")
    validated = sql
    tokens = list(tokenize_sql(validated))
    semicolons = [token for token in tokens if token.kind == "SEMICOLON"]
    if len(semicolons) > 1:
        raise _safety_error("multiple_statements")
    if semicolons:
        semicolon = semicolons[0]
        if tokens[-1] != semicolon:
            raise _safety_error("multiple_statements")
        tokens.pop()
        validated = validated[: semicolon.start] + validated[semicolon.end :]
    if not tokens or tokens[0].kind != "WORD":
        raise _safety_error("write_blocked")

    words = [token.value for token in tokens if token.kind == "WORD"]
    top_level_words = _top_level_words(tokens)
    if any(word in _BLOCKED_KEYWORDS for word in words):
        raise _safety_error("write_blocked")
    if _has_blocked_function_call(tokens):
        raise _safety_error("write_blocked")
    if words[0] not in {"SELECT", "WITH"}:
        raise _safety_error("write_blocked")
    if words[0] == "WITH" and "SELECT" not in top_level_words[1:]:
        raise _safety_error("write_blocked")
    return validated

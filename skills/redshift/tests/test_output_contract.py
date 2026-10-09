from __future__ import annotations

import csv
import json
import io
import math
import os
from datetime import date, datetime, time, timezone
from decimal import Decimal

import pytest

from scripts.rs.errors import Interrupted, SkillError
from scripts.rs.cli import main
from scripts.rs.models import CommandResult, InvocationState
from scripts.rs.output import (
    encode_value,
    publish_records,
    validate_output_name,
    validate_output_target,
)


def test_value_encoder_is_recursive_and_explicit() -> None:
    value = {
        "decimal": Decimal("1024.50"),
        "date": date(2026, 7, 15),
        "time": time(12, 30, 1),
        "naive": datetime(2026, 7, 15, 12, 30),
        "aware": datetime(2026, 7, 15, 12, 30, tzinfo=timezone.utc),
        "bytes": b"\x00\xaf",
        "bytearray": bytearray(b"\x01\xfe"),
        "memoryview": memoryview(b"\x02\xfd"),
        "floats": [float("nan"), float("inf"), float("-inf"), 1.25],
    }
    encoded = encode_value(value)
    assert encoded == {
        "decimal": "1024.50",
        "date": "2026-07-15",
        "time": "12:30:01",
        "naive": "2026-07-15T12:30:00",
        "aware": "2026-07-15T12:30:00+00:00",
        "bytes": "00af",
        "bytearray": "01fe",
        "memoryview": "02fd",
        "floats": ["NaN", "Infinity", "-Infinity", 1.25],
    }
    assert math.isfinite(encoded["floats"][3])
    json.dumps(encoded, allow_nan=False)


@pytest.mark.parametrize("value", [{1: "bad"}, object(), [object()]])
def test_value_encoder_rejects_unsupported_nested_values(value: object) -> None:
    with pytest.raises(SkillError) as caught:
        encode_value(value)
    assert caught.value.full_code == "output.unsupported_value_type"


@pytest.mark.parametrize(
    "name",
    ["", ".", "..", ".hidden", ".redshift-tmp-user", "a/b.csv", "a\\b.csv"],
)
def test_output_name_rejects_paths_and_hidden_names(name: str) -> None:
    with pytest.raises(SkillError) as caught:
        validate_output_name(name)
    assert caught.value.full_code == "output.path_not_allowed"


def test_output_name_is_not_silently_normalized() -> None:
    assert validate_output_name("payment-results.csv") == "payment-results.csv"
    assert validate_output_name(" report.csv ") == " report.csv "


def test_publish_records_is_no_overwrite_and_durable(tmp_path) -> None:
    os.chmod(tmp_path, 0o700)
    state = InvocationState()
    output_ref = publish_records(
        output_dir=tmp_path,
        final_name="results.ndjson",
        fmt="ndjson",
        columns=("id", "amount"),
        records=({"id": 1, "amount": Decimal("2.50")},),
        state=state,
    )
    final = tmp_path / "results.ndjson"
    assert output_ref == "results.ndjson"
    assert state.artifact_state == "durable_published"
    assert state.output_ref == "results.ndjson"
    assert final.read_text(encoding="utf-8") == '{"id":1,"amount":"2.50"}\n'
    assert final.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob(".redshift-tmp-*"))

    with pytest.raises(SkillError) as caught:
        publish_records(
            output_dir=tmp_path,
            final_name="results.ndjson",
            fmt="ndjson",
            columns=("id",),
            records=({"id": 2},),
            state=InvocationState(),
        )
    assert caught.value.full_code == "output.already_exists"
    assert final.read_text(encoding="utf-8") == '{"id":1,"amount":"2.50"}\n'


def test_fchmod_failure_closes_fd_and_removes_temp(tmp_path, monkeypatch) -> None:
    os.chmod(tmp_path, 0o700)
    fd_count_before = len(os.listdir("/dev/fd"))

    def fail_fchmod(_fd: int, _mode: int) -> None:
        raise OSError("injected fchmod failure")

    monkeypatch.setattr("scripts.rs.output.os.fchmod", fail_fchmod)

    with pytest.raises(SkillError) as caught:
        publish_records(
            output_dir=tmp_path,
            final_name="results.ndjson",
            fmt="ndjson",
            columns=("id",),
            records=({"id": 1},),
            state=InvocationState(),
        )

    assert caught.value.full_code == "output.write_failed"
    assert len(os.listdir("/dev/fd")) == fd_count_before
    assert not (tmp_path / "results.ndjson").exists()
    assert not list(tmp_path.glob(".redshift-tmp-*"))


def test_fchmod_control_exit_is_preserved_after_cleanup(tmp_path, monkeypatch) -> None:
    os.chmod(tmp_path, 0o700)
    control_exit = GeneratorExit()

    def fail_fchmod(_fd: int, _mode: int) -> None:
        raise control_exit

    monkeypatch.setattr("scripts.rs.output.os.fchmod", fail_fchmod)

    with pytest.raises(GeneratorExit) as caught:
        publish_records(
            output_dir=tmp_path,
            final_name="results.ndjson",
            fmt="ndjson",
            columns=("id",),
            records=({"id": 1},),
            state=InvocationState(),
        )

    assert caught.value is control_exit
    assert not (tmp_path / "results.ndjson").exists()
    assert not list(tmp_path.glob(".redshift-tmp-*"))


def test_post_link_directory_fsync_failure_keeps_final_and_is_unknown(tmp_path, monkeypatch) -> None:
    os.chmod(tmp_path, 0o700)
    real_fsync = os.fsync
    calls = 0

    def fail_second_fsync(fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected directory fsync failure")
        real_fsync(fd)

    monkeypatch.setattr("scripts.rs.output.os.fsync", fail_second_fsync)
    state = InvocationState()
    with pytest.raises(SkillError) as caught:
        publish_records(
            output_dir=tmp_path,
            final_name="may-exist.csv",
            fmt="csv",
            columns=("id",),
            records=({"id": 1},),
            state=state,
        )
    assert caught.value.full_code == "output.publish_unknown"
    assert caught.value.retry_class == "never"
    assert state.artifact_state == "final_link_created"
    assert (tmp_path / "may-exist.csv").exists()


def test_output_directory_requires_private_mode(tmp_path) -> None:
    os.chmod(tmp_path, 0o755)
    with pytest.raises(SkillError) as caught:
        publish_records(
            output_dir=tmp_path,
            final_name="unsafe.csv",
            fmt="csv",
            columns=("id",),
            records=({"id": 1},),
            state=InvocationState(),
        )
    assert caught.value.full_code == "output.path_not_allowed"
    assert not (tmp_path / "unsafe.csv").exists()


def test_output_directory_rejects_symlink(tmp_path) -> None:
    private_directory = tmp_path / "private"
    private_directory.mkdir(mode=0o700)
    symlink = tmp_path / "output-link"
    symlink.symlink_to(private_directory, target_is_directory=True)

    with pytest.raises(SkillError) as caught:
        validate_output_target(symlink, "unsafe.csv")

    assert caught.value.full_code == "output.path_not_allowed"


def test_output_directory_rejects_owner_mismatch(tmp_path, monkeypatch) -> None:
    os.chmod(tmp_path, 0o700)
    real_fstat = os.fstat

    def mismatched_owner(fd: int):
        info = real_fstat(fd)

        class OwnerMismatch:
            st_mode = info.st_mode
            st_uid = os.geteuid() + 1

        return OwnerMismatch()

    monkeypatch.setattr("scripts.rs.output.os.fstat", mismatched_owner)

    with pytest.raises(SkillError) as caught:
        validate_output_target(tmp_path, "unsafe.csv")

    assert caught.value.full_code == "output.path_not_allowed"


def test_success_envelope_failure_after_publish_is_unknown(tmp_path) -> None:
    os.chmod(tmp_path, 0o700)
    stdout = io.StringIO()

    def publish_then_return_unsupported(args, state):
        publish_records(
            output_dir=tmp_path,
            final_name="orphan.ndjson",
            fmt="ndjson",
            columns=("id",),
            records=({"id": 1},),
            state=state,
        )
        return CommandResult(data={"unsupported": object()})

    code = main(
        [
            "query",
            "--sql",
            "SELECT 1",
            "--format",
            "ndjson",
            "--output",
            "orphan.ndjson",
        ],
        dispatcher=publish_then_return_unsupported,
        stdout=stdout,
        stderr=io.StringIO(),
        environ={"REDSHIFT_OUTPUT_DIR": str(tmp_path)},
        install_signal_handlers=False,
    )
    payload = json.loads(stdout.getvalue())
    assert code == 8
    assert payload["error"]["code"] == "publish_unknown"
    assert payload["error"]["retryClass"] == "never"
    assert (tmp_path / "orphan.ndjson").exists()


def test_interruption_before_link_removes_only_temp(tmp_path, monkeypatch) -> None:
    os.chmod(tmp_path, 0o700)

    def interrupt_write(*args, **kwargs):
        raise Interrupted(15)

    monkeypatch.setattr("scripts.rs.output._write_records", interrupt_write)
    state = InvocationState()
    with pytest.raises(Interrupted):
        publish_records(
            output_dir=tmp_path,
            final_name="not-published.ndjson",
            fmt="ndjson",
            columns=("id",),
            records=({"id": 1},),
            state=state,
        )
    assert not (tmp_path / "not-published.ndjson").exists()
    assert not list(tmp_path.glob(".redshift-tmp-*"))


def test_interruption_after_link_keeps_final_and_reports_may_exist(tmp_path, monkeypatch) -> None:
    os.chmod(tmp_path, 0o700)
    real_unlink = os.unlink
    calls = 0

    def interrupt_first_unlink(path, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise Interrupted(15)
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr("scripts.rs.output.os.unlink", interrupt_first_unlink)
    state = InvocationState()
    with pytest.raises(Interrupted):
        publish_records(
            output_dir=tmp_path,
            final_name="may-exist.ndjson",
            fmt="ndjson",
            columns=("id",),
            records=({"id": 1},),
            state=state,
        )
    assert state.artifact_state == "final_link_created"
    assert state.interruption_details() == {"artifactState": "may_exist"}
    assert (tmp_path / "may-exist.ndjson").exists()
    assert not list(tmp_path.glob(".redshift-tmp-*"))


def test_csv_uses_the_shared_encoder_and_standard_quoting(tmp_path) -> None:
    os.chmod(tmp_path, 0o700)
    publish_records(
        output_dir=tmp_path,
        final_name="values.csv",
        fmt="csv",
        columns=("null", "bool", "decimal", "binary", "nested", "text"),
        records=(
            {
                "null": None,
                "bool": True,
                "decimal": Decimal("1.20"),
                "binary": b"\x00\xaf",
                "nested": {"value": float("inf")},
                "text": "line one\nline two",
            },
        ),
        state=InvocationState(),
    )
    assert (tmp_path / "values.csv").read_text(encoding="utf-8") == (
        "null,bool,decimal,binary,nested,text\n"
        ',true,1.20,00af,"{""value"":""Infinity""}","line one\nline two"\n'
    )


def test_csv_prefixes_spreadsheet_formula_strings_in_headers_and_values(tmp_path) -> None:
    os.chmod(tmp_path, 0o700)
    publish_records(
        output_dir=tmp_path,
        final_name="spreadsheet-safe.csv",
        fmt="csv",
        columns=("=header", "+header", "-header", "@header", "plain"),
        records=(
            {
                "=header": "=1+1",
                "+header": "+cmd",
                "-header": "-2+3",
                "@header": "@SUM(A1:A2)",
                "plain": "ordinary",
            },
        ),
        state=InvocationState(),
    )
    assert (tmp_path / "spreadsheet-safe.csv").read_text(encoding="utf-8") == (
        "'=header,'+header,'-header,'@header,plain\n"
        "'=1+1,'+cmd,'-2+3,'@SUM(A1:A2),ordinary\n"
    )


@pytest.mark.parametrize(
    "prefix",
    ["=", "+", "-", "@", "\t", "\r", "\n", "＝", "＋", "－", "＠"],
    ids=[
        "equals",
        "plus",
        "minus",
        "at",
        "tab",
        "carriage-return",
        "line-feed",
        "full-width-equals",
        "full-width-plus",
        "full-width-minus",
        "full-width-at",
    ],
)
def test_csv_uses_one_dangerous_prefix_policy_for_headers_and_string_values(
    tmp_path, prefix
) -> None:
    os.chmod(tmp_path, 0o700)
    column = f"{prefix}header"
    value = f"{prefix}value"
    publish_records(
        output_dir=tmp_path,
        final_name="spreadsheet-safe.csv",
        fmt="csv",
        columns=(column,),
        records=({column: value},),
        state=InvocationState(),
    )

    with (tmp_path / "spreadsheet-safe.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.reader(handle))
    assert rows == [[f"'{column}"], [f"'{value}"]]


def test_csv_leaves_non_strings_and_ordinary_strings_unchanged(tmp_path) -> None:
    os.chmod(tmp_path, 0o700)
    publish_records(
        output_dir=tmp_path,
        final_name="typed-values.csv",
        fmt="csv",
        columns=("integer", "float", "decimal", "boolean", "text"),
        records=(
            {
                "integer": -1,
                "float": -2.5,
                "decimal": Decimal("-3.25"),
                "boolean": False,
                "text": "safe text",
            },
        ),
        state=InvocationState(),
    )

    assert (tmp_path / "typed-values.csv").read_text(encoding="utf-8") == (
        "integer,float,decimal,boolean,text\n"
        "-1,-2.5,-3.25,false,safe text\n"
    )


def test_ndjson_preserves_formula_leading_strings(tmp_path) -> None:
    os.chmod(tmp_path, 0o700)
    publish_records(
        output_dir=tmp_path,
        final_name="byte-preserving.ndjson",
        fmt="ndjson",
        columns=("formula",),
        records=({"formula": "=1+1"},),
        state=InvocationState(),
    )

    assert (tmp_path / "byte-preserving.ndjson").read_bytes() == b'{"formula":"=1+1"}\n'


def test_unsupported_artifact_value_fails_before_link_and_cleans_temp(tmp_path) -> None:
    os.chmod(tmp_path, 0o700)
    with pytest.raises(SkillError) as caught:
        publish_records(
            output_dir=tmp_path,
            final_name="bad.ndjson",
            fmt="ndjson",
            columns=("value",),
            records=({"value": object()},),
            state=InvocationState(),
        )
    assert caught.value.full_code == "output.unsupported_value_type"
    assert not (tmp_path / "bad.ndjson").exists()
    assert not list(tmp_path.glob(".redshift-tmp-*"))


def test_artifact_byte_limit_counts_encoded_utf8_and_never_publishes_partial_file(
    tmp_path, monkeypatch
) -> None:
    os.chmod(tmp_path, 0o700)
    monkeypatch.setattr("scripts.rs.output.MAX_ARTIFACT_BYTES", 13, raising=False)

    with pytest.raises(SkillError) as caught:
        publish_records(
            output_dir=tmp_path,
            final_name="too-large.ndjson",
            fmt="ndjson",
            columns=("text",),
            records=({"text": "é"},),
            state=InvocationState(),
        )

    assert caught.value.full_code == "output.size_limit_exceeded"
    assert caught.value.retry_class == "after_change"
    assert not (tmp_path / "too-large.ndjson").exists()
    assert not list(tmp_path.glob(".redshift-tmp-*"))


def test_cleanup_interruption_does_not_replace_artifact_write_error(
    tmp_path, monkeypatch
) -> None:
    os.chmod(tmp_path, 0o700)
    monkeypatch.setattr("scripts.rs.output.MAX_ARTIFACT_BYTES", 1)

    def interrupt_cleanup(*_args, **_kwargs):
        raise Interrupted(15)

    monkeypatch.setattr("scripts.rs.output.os.unlink", interrupt_cleanup)

    with pytest.raises(SkillError) as caught:
        publish_records(
            output_dir=tmp_path,
            final_name="too-large.ndjson",
            fmt="ndjson",
            columns=("text",),
            records=({"text": "wide"},),
            state=InvocationState(),
        )

    assert caught.value.full_code == "output.size_limit_exceeded"


def test_csv_byte_limit_counts_header_quoting_commas_and_newlines(
    tmp_path, monkeypatch
) -> None:
    os.chmod(tmp_path, 0o700)
    monkeypatch.setattr("scripts.rs.output.MAX_ARTIFACT_BYTES", 15)

    with pytest.raises(SkillError) as caught:
        publish_records(
            output_dir=tmp_path,
            final_name="too-large.csv",
            fmt="csv",
            columns=("id", "text"),
            records=({"id": 1, "text": "a,b"},),
            state=InvocationState(),
        )

    assert caught.value.full_code == "output.size_limit_exceeded"
    assert not (tmp_path / "too-large.csv").exists()
    assert not list(tmp_path.glob(".redshift-tmp-*"))

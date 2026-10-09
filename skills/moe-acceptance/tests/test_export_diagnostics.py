import copy
import json
from pathlib import Path

import pytest
from PIL import Image

from scripts import delivery_artifacts as reports
from scripts import sites_report as sites
from scripts.report_diagnostics import ExportValidationError


def content(*ids, case_id="C1"):
    return {"title": "测试报告", "summary": "已有观察", "cases": [
        {"id": case_id, "title": "条件与结果", "claim": "目标状态可见", "observed": "实际可见",
         "verdict": "通过", "evidence_ids": list(ids)}], "ui_acceptance": []}


@pytest.fixture
def task(tmp_path):
    path = tmp_path / "diagnostics-test"
    path.mkdir()
    reports.initialize(path, path.name, content(), report_round={"id": "R1", "reason": "首次观察"})
    return path


def add_image(task, name="image.png", kind="image", metadata=None, size=(1080, 2400)):
    source = task.parent / name
    Image.new("RGB", size, "white").save(source)
    return reports.register_asset(task, task.name, source, kind, name, metadata=metadata or {"case_id": "C1"})


def stored(task):
    return json.loads((task / "manifest.json").read_text())


def save(task, data):
    (task / "manifest.json").write_text(json.dumps(data))


def codes(assessment):
    return {issue["code"] for issue in assessment["diagnostics"]}


@pytest.mark.parametrize("suffix", ["png", "jpg", "jpeg", "gif", "webp"])
def test_register_decodes_supported_images_without_inventing_capture_facts(task, suffix):
    item = add_image(task, f"shot.{suffix}", size=(48, 96))
    assert item["metadata"] == {"case_id": "C1", "width": 48, "height": 96}
    assert item["captured_at"] is None


def test_exif_orientation_matches_browser_axes(task):
    source = task.parent / "rotated.jpg"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (80, 40)).save(source, exif=exif)
    item = reports.register_asset(task, task.name, source, "image")
    assert item["metadata"] == {"width": 40, "height": 80}


@pytest.mark.parametrize("metadata", [{"width": 42}, {"height": True}, {"width": 1080.0}])
def test_wrong_dimensions_are_corrected_and_recorded(task, metadata):
    with pytest.warns(UserWarning, match="实际尺寸"):
        item = add_image(task, metadata=metadata)
    assert item["metadata"]["width"] == 1080
    assert item["metadata"]["height"] == 2400
    assert stored(task)["history"][-1]["corrections"][0]["before"] == next(iter(metadata.values()))
    assert stored(task)["history"][-1]["asset_id"] == item["asset_id"]


def test_corrupt_image_registration_is_rejected(task):
    source = task.parent / "bad.png"
    source.write_bytes(b"not an image")
    with pytest.raises(ValueError, match="无法解码"):
        reports.register_asset(task, task.name, source, "screenshot")
    assert stored(task)["assets"] == []


def test_missing_pillow_is_actionable_and_does_not_block_audio(task, monkeypatch):
    import builtins
    original = builtins.__import__
    def missing(name, *args, **kwargs):
        if name == "PIL":
            raise ImportError("not installed")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", missing)
    with pytest.raises(ValueError, match="requirements-report"):
        add_image(task)
    source = task.parent / "voice.mp3"
    source.write_bytes(b"audio fixture")
    assert reports.register_asset(task, task.name, source, "audio")["metadata"] == {}


def test_legacy_dimensions_are_completed_only_in_export_copy(task):
    item = add_image(task)
    reports.update(task, task.name, content(item["asset_id"]))
    raw = stored(task)
    raw["assets"][0]["metadata"] = {"case_id": "C1", "capture_mode": "viewport"}
    save(task, raw)
    before = (task / "manifest.json").read_bytes()
    assessment = sites.check_sites_export(task, task.name)
    assert assessment["can_export"] and not assessment["requires_review"]
    assert codes(assessment) == {"image_dimensions_completed"}
    assert not (task / "sites").exists()
    site = sites.export_sites(task, task.name)
    asset = json.loads((site / "public/report/report.json").read_text())["rounds"][0]["assets"][0]
    assert asset["metadata"]["width"] == 1080 and asset["metadata"]["height"] == 2400
    assert "viewport" not in asset["metadata"]
    assert (task / "manifest.json").read_bytes() == before


def test_diagnostics_aggregate_different_gaps_with_locations(task):
    first = add_image(task, "first.png")
    second = add_image(task, "second.png", metadata={"case_id": "C2"})
    report = content(first["asset_id"])
    report["cases"] += content(second["asset_id"], case_id="C2")["cases"]
    reports.update(task, task.name, report)
    site = sites.export_sites(task, task.name)
    previous = (site / "public/report/report.json").read_bytes()
    raw = stored(task)
    raw["assets"][1]["metadata"]["width"] = 50
    raw["manifest"]["cases"][0].update(claim="", limitation="需展示的限制")
    raw["manifest"]["cases"][1]["evidence_ids"].append("unknown")
    save(task, raw)
    (task / "assets" / Path(first["path"]).name).unlink()
    assessment = sites.check_sites_export(task, task.name)
    assert not assessment["can_export"] and assessment["requires_review"]
    assert codes(assessment) >= {"asset_missing", "image_dimensions_corrected", "asset_reference_invalid", "case_content_missing", "content_not_rendered"}
    assert {item["case_id"] for item in assessment["diagnostics"]} == {"C1", "C2"}
    assert all(item["round_id"] == "R1" and item["suggested_action"] and item["field"] for item in assessment["diagnostics"])
    with pytest.raises(FileNotFoundError) as caught:
        sites.export_sites(task, task.name)
    assert caught.value.diagnostics == assessment["diagnostics"]
    assert (site / "public/report/report.json").read_bytes() == previous


def test_pairing_is_review_only_and_supplement_is_not_auto_paired(task):
    before = add_image(task, "before.png", "before")
    after = add_image(task, "after.png", "after")
    supplement = add_image(task, "supplement.png", "after")
    reports.update(task, task.name, content(before["asset_id"], after["asset_id"], supplement["asset_id"]))
    assessment = sites.check_sites_export(task, task.name)
    assert assessment["can_export"] and assessment["requires_review"]
    assert codes(assessment) == {"comparison_unassigned"}
    with pytest.warns(sites.ExportDiagnosticsWarning):
        sites.export_sites(task, task.name)
    for item in (before, after):
        reports.update_asset_metadata(task, task.name, item["asset_id"], {"comparison_id": "same-scene"}, reason="已核对两侧")
    raw = stored(task)
    assert "comparison_id" not in raw["assets"][2]["metadata"]
    assessment = sites.check_sites_export(task, task.name)
    unpaired = next(item for item in assessment["diagnostics"] if item["code"] == "comparison_unassigned")
    assert unpaired["asset_ids"] == [supplement["asset_id"]]
    assert all(case["verdict"] == "通过" for case in raw["manifest"]["cases"])


def test_single_side_group_reports_warning_and_nonvisual_case_is_valid(task):
    assert sites.check_sites_export(task, task.name)["diagnostics"] == []
    before = add_image(task, "before.png", "before", {"case_id": "C1", "comparison_id": "only-one-side"})
    reports.update(task, task.name, content(before["asset_id"]))
    assert codes(sites.check_sites_export(task, task.name)) == {"comparison_ambiguous"}


def test_metadata_revision_preserves_identity_rounds_bytes_and_audits_change(task):
    before = add_image(task, "before.png", "before")
    reports.update(task, task.name, content(before["asset_id"]))
    reports.update(task, task.name, content(), report_round={"id": "R2", "reason": "补验"})
    after = add_image(task, "after.png", "after", {"case_id": "C1", "comparison_id": "pair"})
    reports.update(task, task.name, content(before["asset_id"], after["asset_id"]))
    raw = stored(task)
    raw["assets"][0]["metadata"].pop("width")
    raw["assets"][0]["metadata"].pop("height")
    save(task, raw)
    original = copy.deepcopy(raw)
    files = {p.name: p.read_bytes() for p in (task / "assets").iterdir()}
    corrected = reports.update_asset_metadata(task, task.name, before["asset_id"], {"comparison_id": "pair"}, reason="修正展示关系 token=redacted")
    result = stored(task)
    assert {k: v for k, v in corrected.items() if k != "metadata"} == {k: v for k, v in before.items() if k != "metadata"}
    assert result["manifest"] == original["manifest"] and result["rounds"] == original["rounds"]
    assert result["current_round"] == original["current_round"] and len(result["assets"]) == 2
    assert result["history"][-1]["before"] == {"case_id": "C1"}
    assert result["history"][-1]["after"] == {"case_id": "C1", "comparison_id": "pair", "width": 1080, "height": 2400}
    assert "redacted" not in result["history"][-1]["change"]
    assert files == {p.name: p.read_bytes() for p in (task / "assets").iterdir()}
    reports.update_asset_metadata(task, task.name, before["asset_id"], {}, reason="重复检查")
    assert stored(task) == result
    current = [item for item in sites.check_sites_export(task, task.name)["diagnostics"] if item["round_id"] == "R2"]
    assert current == []
    assert sites.check_sites_export(task, task.name)["diagnostics"] == []


@pytest.mark.parametrize("patch", [{"case_id": "other"}, {"captured_at": "invented"}, {"comparison_id": ""}])
def test_invalid_revision_leaves_metadata_and_history_unchanged(task, patch):
    item = add_image(task)
    reports.update(task, task.name, content(item["asset_id"]))
    before = (task / "manifest.json").read_bytes()
    with pytest.raises(ValueError):
        reports.update_asset_metadata(task, task.name, item["asset_id"], patch, reason="更正")
    assert (task / "manifest.json").read_bytes() == before


def test_revision_failure_is_atomic_and_can_clear_wrong_optional_fact(task, monkeypatch):
    item = add_image(task, metadata={"case_id": "C1", "viewport": "unknown-size"})
    before = (task / "manifest.json").read_bytes()
    with monkeypatch.context() as context:
        def fail(*args):
            raise OSError("写入失败")
        context.setattr(reports, "_write_manifest", fail)
        with pytest.raises(OSError):
            reports.update_asset_metadata(task, task.name, item["asset_id"], {"viewport": None}, reason="原 viewport 未记录")
    assert (task / "manifest.json").read_bytes() == before
    corrected = reports.update_asset_metadata(task, task.name, item["asset_id"], {"viewport": None}, reason="原 viewport 未记录")
    assert "viewport" not in corrected["metadata"]


def test_corrupt_unselected_asset_does_not_block_export(task):
    item = add_image(task)
    (task / "assets" / Path(item["path"]).name).write_bytes(b"broken")
    assert sites.check_sites_export(task, task.name)["can_export"]
    reports.update(task, task.name, content(item["asset_id"]))
    assert not sites.check_sites_export(task, task.name)["can_export"]


def test_presentation_and_destination_problems_are_structured(task):
    site = sites.export_sites(task, task.name)
    marker = json.loads((site / sites.MARKER).read_text())
    marker["template"]["version"] = "different"
    (site / sites.MARKER).write_text(json.dumps(marker))
    assessment = sites.check_sites_export(task, task.name, presentation={"rounds": {"unknown": {}}})
    assert codes(assessment) == {"export_input_invalid", "export_target_invalid"}
    with pytest.raises(ExportValidationError):
        sites.export_sites(task, task.name)


def test_html_checks_share_rules_and_complete_only_the_rendered_copy(task):
    item = add_image(task, size=(96, 144))
    value = content(item["asset_id"])
    value["cases"][0].update(claim="", limitation="需保留的说明")
    reports.update(task, task.name, value)
    raw = stored(task)
    raw["assets"][0]["metadata"].pop("width")
    raw["assets"][0]["metadata"].pop("height")
    save(task, raw)
    before = (task / "manifest.json").read_bytes()
    result = reports.check_html_export(task, task.name)
    assert {"case_content_missing", "content_not_rendered", "image_dimensions_completed"} <= codes(result)
    assert (task / "manifest.json").read_bytes() == before
    assert not (task / "report/index.html").exists()
    with pytest.warns(sites.ExportDiagnosticsWarning) as emitted:
        page = reports.render(task, task.name)
    assert emitted[0].message.diagnostics
    assert "96 × 144 px" in page.read_text()
    assert stored(task)["assets"] == raw["assets"]
    assert "viewport" not in stored(task)["assets"][0]["metadata"]


def test_html_missing_current_media_preserves_previous_page(task):
    item = add_image(task)
    reports.update(task, task.name, content(item["asset_id"]))
    page = reports.render(task, task.name)
    previous = page.read_bytes()
    (task / "assets" / Path(item["path"]).name).unlink()
    result = reports.check_html_export(task, task.name)
    assert not result["can_export"] and "asset_missing" in codes(result)
    with pytest.raises(ExportValidationError) as error:
        reports.render(task, task.name)
    assert isinstance(error.value, FileNotFoundError)
    assert error.value.diagnostics == result["diagnostics"]
    assert page.read_bytes() == previous


def test_html_legacy_image_does_not_require_round_upgrade(tmp_path):
    task = tmp_path / "legacy-html"
    task.mkdir()
    reports.initialize(task, task.name, {"title": "旧报告"})
    add_image(task, size=(64, 128))
    assert reports.check_html_export(task, task.name)["can_export"]
    assert "64 × 128 px" in reports.render(task, task.name).read_text()
    assert stored(task).get("schema_version", 1) == 1
    assert not sites.check_sites_export(task, task.name)["can_export"]


def test_html_destination_conflict_is_reported_before_enabling_render(task):
    destination = task / "report/index.html"
    destination.mkdir(parents=True)
    before = (task / "manifest.json").read_bytes()
    assert "export_target_invalid" in codes(reports.check_html_export(task, task.name))
    with pytest.raises(ExportValidationError):
        reports.render(task, task.name)
    assert destination.is_dir()
    assert (task / "manifest.json").read_bytes() == before


def test_html_historical_missing_media_keeps_business_snapshot(task):
    item = add_image(task)
    reports.update(task, task.name, content(item["asset_id"]))
    reports.update(task, task.name, content(), report_round={"id": "R2", "reason": "非视觉补验"})
    (task / "assets" / Path(item["path"]).name).unlink()
    result = reports.check_html_export(task, task.name)
    assert result["can_export"] and "asset_missing" in codes(result)
    with pytest.warns(sites.ExportDiagnosticsWarning):
        page = reports.render(task, task.name)
    assert "历史证据文件缺失" in page.read_text()
    assert stored(task)["rounds"][0]["manifest"]["cases"][0]["verdict"] == "通过"


def test_metadata_patch_records_rejected_dimension_even_when_result_is_unchanged(task):
    item = add_image(task)
    with pytest.warns(UserWarning, match="实际尺寸"):
        result = reports.update_asset_metadata(task, task.name, item["asset_id"], {"width": 1}, reason="补充尺寸")
    assert result["metadata"] == item["metadata"]
    assert stored(task)["history"][-1]["corrections"] == [{"field": "width", "before": 1, "after": 1080}]


@pytest.mark.parametrize("target", ["html", "sites"])
def test_export_corrects_stale_dimensions_without_writing_source(task, target):
    item = add_image(task)
    reports.update(task, task.name, content(item["asset_id"]))
    raw = stored(task)
    raw["assets"][0]["metadata"]["width"] = 99
    save(task, raw)
    with pytest.warns(UserWarning, match="实际尺寸"):
        check = reports.check_html_export(task, task.name) if target == "html" else sites.check_sites_export(task, task.name)
        output = reports.render(task, task.name) if target == "html" else sites.export_sites(task, task.name)
    assert check["can_export"] and "image_dimensions_corrected" in codes(check)
    assert stored(task)["assets"] == raw["assets"]
    if target == "html":
        assert "1080 × 2400 px" in output.read_text()
    else:
        payload = json.loads((output / "public/report/report.json").read_text())
        assert payload["rounds"][0]["assets"][0]["metadata"]["width"] == 1080

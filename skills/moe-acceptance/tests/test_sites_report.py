import json
import hashlib
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from scripts import delivery_artifacts as reports
from scripts import sites_report as sites


def content(*ids, verdict="通过"):
    return {"title": "模板测试", "summary": "测试数据", "cases": [
        {"id": "C 中文%", "title": "截图", "claim": "预期", "input": ["操作"],
         "observed": "实际观察", "verdict": verdict, "evidence_ids": list(ids)}],
        "ui_acceptance": [{"case_id": "C 中文%", "criterion": "可读", "verdict": verdict}]}


@pytest.fixture
def task(tmp_path):
    task = tmp_path / "task-1"
    task.mkdir()
    reports.initialize(task, task.name, content(verdict="信息不足"),
                       report_round={"id": "R1", "reason": "模板测试", "observed_at": None})
    return task


def asset(task, name, payload=b"test image", metadata=None):
    source = task.parent / name
    Image.new("RGB", (32, 48), tuple(hashlib.sha256(payload).digest()[:3])).save(source)
    return reports.register_asset(task, task.name, source, "image", name,
                                  metadata=metadata or {"case_id": "C 中文%"})


def output(site):
    return json.loads((site / "public/report/report.json").read_text())


def source_bytes(task):
    return {str(p.relative_to(task)): p.read_bytes()
            for p in [task / "manifest.json", task / "report/index.html", *list((task / "assets").iterdir())]
            if p.is_file()}


def test_both_renderers_share_selected_current_and_history_without_source_changes(task):
    old = asset(task, "old.png", b"old")
    reports.update(task, task.name, content(old["asset_id"], verdict="不通过"))
    reports.update(task, task.name, content(verdict="信息不足"),
                   report_round={"id": "R2", "reason": "补充证据"})
    current = asset(task, "current.png", b"new")
    duplicate = asset(task, "duplicate.png", b"new")
    unused = asset(task, "unused.png", b"unselected")
    reports.update(task, task.name, content(current["asset_id"], duplicate["asset_id"]))
    reports.render(task, task.name)
    before = source_bytes(task)
    site = sites.export_sites(task, task.name)
    data = output(site)
    assert data["current_round_id"] == "R2"
    assert [view["round"]["id"] for view in data["rounds"]] == ["R1", "R2"]
    for view in data["rounds"]:
        original = reports.read_report(task, task.name, round_id=view["round"]["id"])
        assert view["manifest"] == original["manifest"]
        assert view["round"] == original["round"]
        assert [a["asset_id"] for a in view["assets"]] == [a["asset_id"] for a in original["assets"]]
        for public, raw in zip(view["assets"], original["assets"]):
            assert public["captured_at"] == raw["captured_at"] is None
            assert public["round_id"] == raw["round_id"]
            assert (site / "public" / public["url"].lstrip("/")).read_bytes() == (task / "assets" / Path(raw["path"]).name).read_bytes()
    assert len(list((site / "public/report/assets").iterdir())) == 2
    assert unused["asset_id"] not in {a["asset_id"] for v in data["rounds"] for a in v["assets"]}
    assert source_bytes(task) == before
    assert "project_id" not in json.loads((site / ".openai/hosting.json").read_text())
    assert not (site / ".git").exists()


def test_repeat_export_updates_only_managed_data_and_removes_unused_public_copy(task):
    first = asset(task, "first.png")
    reports.update(task, task.name, content(first["asset_id"]))
    site = sites.export_sites(task, task.name)
    code = site / "app/page.tsx"
    code.write_text("// 用户的站点改动\n")
    hosting = site / ".openai/hosting.json"
    hosting.write_text('{"project_id":"retained-site","d1":null,"r2":null}')
    reports.update(task, task.name, content(verdict="信息不足"))
    before = source_bytes(task)
    assert sites.export_sites(task, task.name) == site
    assert code.read_text() == "// 用户的站点改动\n"
    assert json.loads(hosting.read_text())["project_id"] == "retained-site"
    assert output(site)["rounds"][0]["manifest"]["cases"][0]["verdict"] == "信息不足"
    assert list((site / "public/report/assets").iterdir()) == []
    assert source_bytes(task) == before


def test_export_does_not_enable_html(task):
    sites.export_sites(task, task.name)
    assert not json.loads((task / "manifest.json").read_text())["report_enabled"]
    assert not (task / "report").exists()


def test_missing_history_keeps_fact_and_warns_but_missing_current_fails(task):
    old = asset(task, "old.png", b"old")
    reports.update(task, task.name, content(old["asset_id"], verdict="不通过"))
    reports.update(task, task.name, content(), report_round={"id": "R2", "reason": "补验"})
    current = asset(task, "new.png", b"new")
    reports.update(task, task.name, content(current["asset_id"]))
    (task / "assets" / Path(old["path"]).name).unlink()
    with pytest.warns(sites.ExportDiagnosticsWarning):
        site = sites.export_sites(task, task.name)
    historical = output(site)["rounds"][0]
    assert historical["assets"] == []
    assert "文件缺失" in historical["warning"]
    assert historical["manifest"]["cases"][0]["verdict"] == "不通过"
    previous = (site / "public/report/report.json").read_bytes()
    (task / "assets" / Path(current["path"]).name).unlink()
    with pytest.raises(FileNotFoundError):
        sites.export_sites(task, task.name)
    assert (site / "public/report/report.json").read_bytes() == previous


def test_legacy_requires_explicit_upgrade_and_preserves_unreviewed_text(tmp_path):
    task = tmp_path / "legacy"
    task.mkdir()
    reports.initialize(task, task.name, content())
    asset(task, "old.png")
    before = source_bytes(task)
    with pytest.raises(ValueError, match="显式轮次"):
        sites.export_sites(task, task.name)
    assert source_bytes(task) == before
    reports.update(task, task.name, content(verdict="信息不足"),
                   report_round={"id": "R2", "reason": "人工复核后升级"})
    historical = output(sites.export_sites(task, task.name))["rounds"][0]
    assert historical["round"]["legacy"] is True
    assert historical["manifest"] == content()
    assert historical["assets"] == []
    assert "未复核" in historical["warning"]


@pytest.mark.parametrize("hints", [
    {"rounds": {"missing": {}}}, {"rounds": {"R1": {"C2": {}}}},
    {"rounds": {"R1": {"C 中文%": {"primary_evidence_id": "unknown"}}}},
    {"rounds": {"R1": {"C 中文%": {"short_title": ""}}}}, {"title": "不允许改写结论"},
])
def test_bad_presentation_cannot_replace_existing_output(task, hints):
    site = sites.export_sites(task, task.name)
    before = (site / "public/report/report.json").read_bytes()
    with pytest.raises(ValueError):
        sites.export_sites(task, task.name, presentation=hints)
    assert (site / "public/report/report.json").read_bytes() == before


def test_presentation_can_reorder_main_evidence_without_changing_fact(task):
    item = asset(task, "main.png")
    reports.update(task, task.name, content(item["asset_id"]))
    before = source_bytes(task)
    hints = {"rounds": {"R1": {"C 中文%": {"short_title": "主图", "primary_evidence_id": item["asset_id"]}}}}
    data = output(sites.export_sites(task, task.name, presentation=hints))
    assert data["presentation"] == hints["rounds"]
    assert source_bytes(task) == before


@pytest.mark.parametrize("part", ["sites", "sites/public", "sites/public/report"])
def test_generated_directory_symlink_refused(task, part, tmp_path):
    if part != "sites":
        sites.export_sites(task, task.name)
    target = task / part
    if target.exists():
        target.rename(tmp_path / "backup")
    external = tmp_path / "external"
    external.mkdir()
    target.symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        sites.export_sites(task, task.name)
    assert list(external.iterdir()) == []


@pytest.mark.parametrize("path", ["../../secret.png", "../assets/../../secret.png", "/tmp/secret.png"])
def test_selected_media_cannot_escape_assets(task, path):
    item = asset(task, "main.png")
    reports.update(task, task.name, content(item["asset_id"]))
    raw = json.loads((task / "manifest.json").read_text())
    raw["assets"][0]["path"] = path
    (task / "manifest.json").write_text(json.dumps(raw))
    with pytest.raises(ValueError):
        sites.export_sites(task, task.name)
    assert not (task / "sites").exists()


@pytest.mark.parametrize("metadata", [
    {"chapters": [{"time": -1, "label": "越界"}]},
    {"chapters": [{"time": float("nan"), "label": "无效"}]},
    {"chapters": [{"time": 2, "label": "越界"}], "duration_seconds": 1},
    {"chapters": [{"time": 0, "label": ""}]}, {"platform": {"invalid": True}},
])
def test_invalid_new_media_metadata_refused(task, metadata):
    with pytest.raises(ValueError):
        asset(task, "main.png", metadata={"case_id": "C 中文%", **metadata})
    assert list((task / "assets").iterdir()) == []


def test_copy_failure_leaves_previous_output_and_no_staging(task, monkeypatch):
    item = asset(task, "main.png")
    reports.update(task, task.name, content(item["asset_id"]))
    site = sites.export_sites(task, task.name)
    before = (site / "public/report/report.json").read_bytes()
    def fail(*args, **kwargs):
        raise OSError("模拟复制失败")
    monkeypatch.setattr(sites.shutil, "copy2", fail)
    with pytest.raises(OSError):
        sites.export_sites(task, task.name)
    assert (site / "public/report/report.json").read_bytes() == before
    assert not list(task.glob(".sites-export-*"))


@pytest.mark.parametrize("credential_key", ["Cookie", "token", "password", "Authorization", "secret"])
def test_internal_test_fields_survive_reports_while_credentials_are_filtered(task, credential_key):
    # 合成内部测试页面，验证登记和双端导出保留原图；媒体凭据检查仍由 Agent 负责。
    fields = ["Address: 123 Test Lane", "Customer: Demo Client",
              "Pet: Demo Pet", "Groomer: Demo Staff"]
    source = task.parent / "internal-test.png"
    picture = Image.new("RGB", (480, 160), "white")
    ImageDraw.Draw(picture).multiline_text((12, 12), "\n".join(fields), fill="black", spacing=12)
    picture.save(source)
    secret_value = "fixture-credential-value"
    item = reports.register_asset(
        task, task.name, source, "screenshot", "内部测试对照",
        note="; ".join(fields) + f"; {credential_key}={secret_value}",
        metadata={"case_id": "C 中文%", credential_key: secret_value})
    summary = content(item["asset_id"])
    summary["cases"][0]["observed"] = "; ".join(fields)
    summary[credential_key] = secret_value
    reports.update(task, task.name, summary)
    html_path = reports.render(task, task.name)
    site = sites.export_sites(task, task.name)
    public = output(site)["rounds"][-1]
    assert public["manifest"]["cases"][0]["evidence_ids"] == [item["asset_id"]]
    assert public["assets"][0]["asset_id"] == item["asset_id"]
    assert (task / "assets" / Path(item["path"]).name).read_bytes() == source.read_bytes()
    assert (site / "public" / public["assets"][0]["url"].lstrip("/")).read_bytes() == source.read_bytes()
    for text in [(task / "manifest.json").read_text(), html_path.read_text(),
                 (site / "public/report/report.json").read_text()]:
        assert all(field in text for field in fields)
        assert secret_value not in text

import copy
import json

import pytest
from PIL import Image

from scripts import delivery_artifacts as reports


def round_info(round_id):
    return {"id": round_id, "label": f"补验 {round_id}", "reason": "补充当前搜索证据",
            "observed_at": "2026-09-09T03:31:48Z"}


def content(*evidence_ids, case_id="C1", verdict="通过"):
    return {"title": "验收", "summary": "独立观察", "cases": [
        {"id": case_id, "claim": "条件与结果对应", "observed": "可见", "verdict": verdict,
         "evidence_ids": list(evidence_ids)}],
        "ui_acceptance": [{"case_id": case_id, "criterion": "可读", "verdict": verdict}]}


@pytest.fixture
def task(tmp_path):
    path = tmp_path / "task-1"
    path.mkdir()
    reports.initialize(path, "task-1", content(verdict="信息不足"), report_round=round_info("R1"))
    return path


def asset(task, name, **kwargs):
    source = task.parent / name
    Image.new("RGB", (32, 48)).save(source)
    return reports.register_asset(task, "task-1", source, kwargs.pop("kind", "screenshot"), name,
                                  metadata=kwargs.pop("metadata", {"case_id": "C1"}), **kwargs)


def stored(task):
    return json.loads((task / "manifest.json").read_text())


def rendered_rounds(page):
    return json.JSONDecoder().raw_decode(page.split("const roundViews=", 1)[1])[0]


def test_retest_replaces_fragments_without_changing_case_or_leaking_old_lightbox(task):
    old1 = asset(task, "keyword.png")
    old2 = asset(task, "name.png")
    reports.update(task, "task-1", content(old1["asset_id"], old2["asset_id"]))
    previous = reports.read_report(task, "task-1")
    reports.update(task, "task-1", content(verdict="信息不足"), report_round=round_info("R2"))
    new = asset(task, "complete.png", captured_at="2026-09-09T04:00:00+00:00",
                supersedes=[old1["asset_id"], old2["asset_id"]], replacement_reason="原图缺少条件与结果关系")
    reports.update(task, "task-1", content(new["asset_id"]))
    current = reports.read_report(task, "task-1")
    historical = reports.read_report(task, "task-1", round_id="R1")
    assert current["manifest"]["cases"][0]["id"] == historical["manifest"]["cases"][0]["id"] == "C1"
    assert current["assets"] == [new]
    assert historical["manifest"] == previous["manifest"]
    assert historical["assets"] == previous["assets"]
    assert historical["unassigned_assets"] == previous["unassigned_assets"]
    assert len(current["unassigned_assets"]) == 2
    assert new["round_id"] == "R2" and new["captured_at"] == "2026-09-09T04:00:00+00:00"
    page = reports.render(task, "task-1").read_text()
    current_html = page.split("</main>", 1)[0]
    initial_lightbox = page.split("let lightboxAssets=", 1)[1].split(";", 1)[0]
    assert new["path"] in current_html and new["path"] in initial_lightbox
    assert old1["path"] not in current_html and old2["path"] not in current_html
    assert old1["path"] not in initial_lightbox and old2["path"] not in initial_lightbox
    assert "未归类证据" not in current_html
    assert len(list((task / "assets").iterdir())) == 3


def test_same_round_edits_and_repeated_render_do_not_create_rounds(task):
    for index in range(3):
        reports.update(task, "task-1", {**content(), "summary": f"更新 {index}"},
                       report_round={"id": "R1"})
    reports.render(task, "task-1")
    before = (task / "manifest.json").read_bytes()
    reports.render(task, "task-1")
    assert before == (task / "manifest.json").read_bytes()
    assert stored(task)["rounds"] == []
    assert stored(task)["current_round"]["observed_at"] == round_info("R1")["observed_at"]
    assert len(stored(task)["history"]) == 3


def test_history_is_full_snapshot_and_cannot_be_overwritten(task):
    first = content(verdict="不通过")
    first["summary"] = "旧观察" * 300
    reports.update(task, "task-1", first)
    reports.update(task, "task-1", content(), report_round=round_info("R2"))
    historical = reports.read_report(task, "task-1", round_id="R1")
    assert historical["manifest"] == first
    historical["manifest"]["cases"].clear()
    assert reports.read_report(task, "task-1", round_id="R1")["manifest"] == first
    before = (task / "manifest.json").read_bytes()
    with pytest.raises(ValueError, match="历史轮次"):
        reports.update(task, "task-1", content(), report_round=round_info("R1"))
    assert before == (task / "manifest.json").read_bytes()
    page = reports.render(task, "task-1").read_text()
    assert 'aria-label="场景汇总：通过"' in page


def test_before_after_and_old_evidence_reuse_keep_original_capture_time(task):
    before = asset(task, "before.png", kind="before", captured_at="2026-09-08T09:00:00Z",
                   metadata={"case_id": "C1", "comparison_id": "search"})
    reports.update(task, "task-1", content(before["asset_id"]))
    reports.update(task, "task-1", content(before["asset_id"]), report_round=round_info("R2"))
    after = asset(task, "after.png", kind="after", metadata={"case_id": "C1", "comparison_id": "search"})
    reports.update(task, "task-1", content(before["asset_id"], after["asset_id"]))
    view = reports.read_report(task, "task-1")
    assert view["assets"][0]["captured_at"] == "2026-09-08T09:00:00Z"
    assert view["assets"][0]["round_id"] == "R1"
    assert view["assets"][1]["captured_at"] is None
    assert view["assets"][1]["registered_at"] is not None
    assert reports.render(task, "task-1").read_text().count('class="comparison"') == 1


def test_registration_does_not_implicitly_select_asset_or_refresh_current_report(task):
    page = reports.render(task, "task-1")
    before = page.read_bytes()
    item = asset(task, "pending.png", metadata={})
    assert reports.read_report(task, "task-1")["assets"] == []
    assert page.read_bytes() == before
    reports.update(task, "task-1", content(item["asset_id"]))
    assert item["path"] in page.read_text()
    assert reports.read_report(task, "task-1")["assets"][0]["metadata"]["case_id"] == "C1"
    assert stored(task)["assets"][0]["metadata"] == {"width": 32, "height": 48}


def test_legacy_read_is_non_mutating_and_upgrade_preserves_known_snapshot(tmp_path):
    task = tmp_path / "legacy-task"
    task.mkdir()
    old_content = {"title": "旧验收", "cases": [{"id": "C1", "verdict": "通过"}], "summary": "已知观察"}
    reports.initialize(task, "legacy-task", old_content)
    source = tmp_path / "old.png"
    Image.new("RGB", (32, 48)).save(source)
    reports.register_asset(task, "legacy-task", source, "image")
    raw = stored(task)
    for key in ("asset_id", "round_id", "captured_at", "registered_at", "supersedes", "replacement_reason"):
        raw["assets"][0].pop(key)
    raw["history"] = [{"change": "更早的摘要不完整", "summary": "截断"}]
    (task / "manifest.json").write_text(json.dumps(raw))
    before = (task / "manifest.json").read_bytes()
    view = reports.read_report(task, "legacy-task")
    assert (task / "manifest.json").read_bytes() == before
    assert view["round"] is None
    assert view["assets"][0]["captured_at"] is None
    asset_id = view["assets"][0]["asset_id"]
    reports.update(task, "legacy-task", content(), report_round=round_info("R2"))
    current = reports.read_report(task, "legacy-task")
    old = reports.read_report(task, "legacy-task", round_id="legacy")
    assert current["assets"] == []
    assert old["manifest"] == old_content
    assert old["assets"][0]["asset_id"] == asset_id
    assert old["round"]["observed_at"] is None and old["round"]["legacy"] is True
    assert stored(task)["history"][0] == raw["history"][0]
    assert len(stored(task)["rounds"]) == 1
    assert "schema_version" not in raw


@pytest.mark.parametrize("broken", [
    {"cases": [{"id": "C1", "verdict": "通过"}]},
    content("missing"), content("asset-1", "asset-1"),
    {"cases": [content()["cases"][0], content()["cases"][0]]},
    {**content(), "ui_acceptance": [{"case_id": "unknown"}]},
    {**content(), "ui_acceptance": [{"case_id": []}]},
    {"cases": "C1"}, {"cases": [None]},
])
def test_bad_references_do_not_replace_existing_manifest_or_html(task, broken):
    page = reports.render(task, "task-1")
    before = (task / "manifest.json").read_bytes(), page.read_bytes()
    with pytest.raises(ValueError):
        reports.update(task, "task-1", broken, report_round=round_info("R2"))
    assert before == ((task / "manifest.json").read_bytes(), page.read_bytes())


def test_cross_case_reference_is_rejected(task):
    other = asset(task, "other.png", metadata={"case_id": "C2"})
    with pytest.raises(ValueError, match="不属于"):
        reports.update(task, "task-1", content(other["asset_id"]))


@pytest.mark.parametrize("failure", ["missing", "symlink", "traversal", "absolute", "encoded", "backslash"])
def test_unsafe_or_missing_selected_file_is_rejected_before_write(task, failure):
    item = asset(task, "source.png")
    target = task / "assets" / item["path"].split("/")[-1]
    if failure in {"missing", "symlink"}:
        target.unlink()
        if failure == "symlink":
            target.symlink_to(task.parent / "source.png")
    else:
        data = stored(task)
        data["assets"][0]["path"] = {
            "traversal": "../assets/../../source.png", "absolute": str(target),
            "encoded": "../assets/%2e%2e%2fsource.png", "backslash": "../assets/..\\source.png",
        }[failure]
        (task / "manifest.json").write_text(json.dumps(data))
    before = (task / "manifest.json").read_bytes()
    with pytest.raises((FileNotFoundError, ValueError)):
        reports.update(task, "task-1", content(item["asset_id"]))
    assert before == (task / "manifest.json").read_bytes()


def test_missing_old_file_can_be_replaced_without_rebuilding_task(task):
    old = asset(task, "broken.png")
    reports.update(task, "task-1", content(old["asset_id"]))
    page = reports.render(task, "task-1")
    (task / "assets" / old["path"].split("/")[-1]).unlink()
    with pytest.raises(FileNotFoundError):
        reports.read_report(task, "task-1")
    new = asset(task, "replacement.png", supersedes=[old["asset_id"]], replacement_reason="文件已丢失，重新采集")
    reports.update(task, "task-1", content(new["asset_id"]))
    assert new["path"] in page.read_text() and old["path"] not in page.read_text()


@pytest.mark.parametrize("kwargs", [
    {"supersedes": ["unknown"], "replacement_reason": "替代"},
    {"supersedes": ["asset-1"]},
    {"supersedes": ["asset-1", "asset-1"], "replacement_reason": "替代"},
    {"captured_at": "2026-09-09T03:00:00"}, {"captured_at": "未知"},
    {"metadata": []},
])
def test_bad_asset_metadata_does_not_register_or_leave_file(task, kwargs):
    asset(task, "original.png")
    before = (task / "manifest.json").read_bytes()
    files = sorted((task / "assets").iterdir())
    with pytest.raises(ValueError):
        asset(task, "invalid.png", **kwargs)
    assert before == (task / "manifest.json").read_bytes()
    assert files == sorted((task / "assets").iterdir())


def test_cross_case_supersession_is_rejected(task):
    other = asset(task, "other.png", metadata={"case_id": "C2"})
    with pytest.raises(ValueError, match="其它 Case"):
        asset(task, "new.png", supersedes=[other["asset_id"]], replacement_reason="替代")


@pytest.mark.parametrize("info", [None, {}, {"id": "R2"}, {"id": "legacy", "reason": "覆盖"},
    {"id": "R2", "reason": "补验", "observed_at": "2026-09-09T03:00:00"}])
def test_invalid_round_metadata_rejected(task, info):
    if info is None:
        with pytest.raises(ValueError, match="未知轮次"):
            reports.read_report(task, "task-1", round_id="missing")
    else:
        before = (task / "manifest.json").read_bytes()
        with pytest.raises(ValueError):
            reports.update(task, "task-1", content(), report_round=info)
        assert before == (task / "manifest.json").read_bytes()


def test_write_failure_removes_only_new_asset(task, monkeypatch):
    original = asset(task, "original.png")
    before = (task / "manifest.json").read_bytes()
    def fail_write(*args):
        raise OSError("模拟磁盘写入失败")
    monkeypatch.setattr(reports, "_write_manifest", fail_write)
    with pytest.raises(OSError):
        asset(task, "new.png")
    assert (task / "manifest.json").read_bytes() == before
    assert [file.name for file in (task / "assets").iterdir()] == [original["path"].split("/")[-1]]


def test_round_history_and_asset_replacement_text_are_redacted(task):
    old = asset(task, "old.png")
    new = asset(task, "new.png", supersedes=[old["asset_id"]], replacement_reason="password=private-value")
    info = {**round_info("R2"), "reason": "token=private-value", "secret": "private-value"}
    reports.update(task, "task-1", {**content(new["asset_id"]), "password": "private-value"}, report_round=info)
    assert "private-value" not in (task / "manifest.json").read_text()
    assert "private-value" not in reports.render(task, "task-1").read_text()


def test_update_remains_full_replacement_not_automatic_case_inheritance(task):
    both = content()
    both["cases"].append(content(case_id="C2")["cases"][0])
    reports.update(task, "task-1", both)
    reports.update(task, "task-1", content(), report_round=round_info("R2"))
    assert len(reports.read_report(task, "task-1")["manifest"]["cases"]) == 1
    assert len(reports.read_report(task, "task-1", round_id="R1")["manifest"]["cases"]) == 2


def test_duplicate_asset_ids_and_unknown_schema_are_not_silently_repaired(task):
    first = asset(task, "first.png")
    original = stored(task)
    for bad in [{**original, "assets": [first, copy.deepcopy(first)]}, {**original, "schema_version": 99}]:
        (task / "manifest.json").write_text(json.dumps(bad))
        with pytest.raises(ValueError):
            reports.read_report(task, "task-1")


def test_registration_does_not_overwrite_unregistered_file(task):
    target = task / "assets" / "new_0.png"
    target.write_bytes(b"preserve this file")
    before = (task / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        asset(task, "new.png")
    assert target.read_bytes() == b"preserve this file"
    assert before == (task / "manifest.json").read_bytes()


def test_render_failure_preserves_saved_business_result(task, monkeypatch):
    reports.render(task, "task-1")
    def fail_render(*args):
        raise OSError("模拟呈现失败")
    monkeypatch.setattr(reports, "render", fail_render)
    with pytest.raises(OSError):
        reports.update(task, "task-1", content(verdict="不通过"))
    assert reports.read_report(task, "task-1")["manifest"]["cases"][0]["verdict"] == "不通过"


@pytest.mark.parametrize("mutate", [
    lambda data: data.update(current_round=None),
    lambda data: data["rounds"].append({**data["current_round"], "manifest": content(), "asset_ids": []}),
])
def test_invalid_round_structure_is_rejected_without_writing(task, mutate):
    data = stored(task)
    mutate(data)
    (task / "manifest.json").write_text(json.dumps(data))
    before = (task / "manifest.json").read_bytes()
    with pytest.raises(ValueError):
        reports.update(task, "task-1", content())
    assert before == (task / "manifest.json").read_bytes()


def test_rendered_history_has_its_own_summary_cases_and_gallery(task):
    old = asset(task, "old-round.png")
    reports.update(task, "task-1", {**content(old["asset_id"], verdict="不通过"), "summary": "旧失败观察"})
    reports.update(task, "task-1", content(), report_round=round_info("R2"))
    new = asset(task, "new-round.png")
    reports.update(task, "task-1", {**content(new["asset_id"]), "summary": "当前通过观察"})
    page = reports.render(task, "task-1").read_text()
    views = rendered_rounds(page)
    current = page.split("<main>", 1)[1].split("</main>", 1)[0]
    assert current == views["R2"]["html"]
    assert "旧失败观察" not in current and "当前通过观察" in current
    assert "历史快照，不代表当前结果" in views["R1"]["html"]
    assert 'aria-label="场景汇总：不通过"' in views["R1"]["html"]
    assert [(item["src"], item["label"]) for item in views["R1"]["assets"]] == [(old["path"], "old-round.png")]
    assert [(item["src"], item["label"]) for item in views["R2"]["assets"]] == [(new["path"], "new-round.png")]
    assert new["path"] not in views["R1"]["html"]


def test_legacy_snapshot_is_labeled_unreviewed_without_invented_time(tmp_path):
    task = tmp_path / "task-1"
    task.mkdir()
    reports.initialize(task, "task-1", {"title": "原报告", "cases": [{"id": "C1", "verdict": "通过"}]})
    old = asset(task, "fragment.png")
    reports.update(task, "task-1", content(), report_round=round_info("R2"))
    page = reports.render(task, "task-1").read_text()
    previous = rendered_rounds(page)["legacy"]
    assert "旧报告证据未复核" in previous["html"]
    assert "采集时间：未知" in previous["html"]
    assert "观察时间：未知" in previous["html"]
    assert old["path"] not in page.split("</main>", 1)[0]
    assert 'aria-label="场景汇总：通过"' in previous["html"]


def test_history_with_missing_media_does_not_block_current_replacement(task):
    old = asset(task, "missing-history.png")
    reports.update(task, "task-1", content(old["asset_id"]))
    reports.update(task, "task-1", content(), report_round=round_info("R2"))
    (task / "assets" / old["path"].split("/")[-1]).unlink()
    new = asset(task, "current.png")
    reports.update(task, "task-1", content(new["asset_id"]))
    page = reports.render(task, "task-1").read_text()
    views = rendered_rounds(page)
    assert [(item["src"], item["label"]) for item in views["R2"]["assets"]] == [(new["path"], "current.png")]
    assert views["R1"]["assets"] == []
    assert "历史证据文件缺失" in views["R1"]["html"]
    assert 'aria-label="场景汇总：通过"' in views["R1"]["html"]
    assert reports.read_report(task, "task-1")["manifest"]["cases"][0]["verdict"] == "通过"


def test_round_payload_and_attributes_escape_untrusted_html(task):
    hostile = '</script><script>alert("history")</script>'
    reports.update(task, "task-1", {**content(), "summary": hostile})
    reports.update(task, "task-1", content(), report_round={"id": hostile, "label": hostile, "reason": hostile})
    page = reports.render(task, "task-1").read_text()
    assert page.count("<script>") == 1
    assert hostile not in page
    views = rendered_rounds(page)
    assert hostile in views
    assert "&lt;/script&gt;" in views["R1"]["html"]


def test_current_proof_shows_capture_origin_and_replacement_without_deleting_history(task):
    old = asset(task, "before-proof.png")
    reports.update(task, "task-1", content(old["asset_id"]))
    reports.update(task, "task-1", content(), report_round=round_info("R2"))
    new = asset(task, "full-proof.png", captured_at="2026-09-09T03:31:48Z",
                supersedes=[old["asset_id"]], replacement_reason="旧图无法展示条件与结果关系")
    reports.update(task, "task-1", content(new["asset_id"]))
    page = reports.render(task, "task-1").read_text()
    current = page.split("</main>", 1)[0]
    assert "采集时间：2026-09-09T03:31:48Z" in current
    assert "来源轮次：R2" in current and "替代 asset-1" in current
    assert "旧图无法展示条件与结果关系" in current
    assert [(item["src"], item["label"]) for item in rendered_rounds(page)["R1"]["assets"]] == [(old["path"], "before-proof.png")]

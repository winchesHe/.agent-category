import json
import os
import tempfile
from pathlib import Path
import pytest
from PIL import Image

from scripts.delivery_artifacts import initialize, register_asset, update, render


def make_task(tmp_path):
    task = tmp_path / "task-1"
    task.mkdir()
    return task


def test_initialize_creates_single_report_and_redacts_fields(tmp_path):
    task = make_task(tmp_path)
    initialize(task, "task-1", {"title": "验收", "password": "secret", "summary": "https://x.test?a=1&token=abc"}, render_report=True)
    assert (task / "manifest.json").is_file()
    report = task / "report" / "index.html"
    assert report.is_file()
    text = report.read_text()
    assert "secret" not in text
    assert "token=abc" not in text
    assert "[已隐藏]" in text


def test_update_reuses_same_report_and_keeps_history(tmp_path):
    task = make_task(tmp_path)
    initialize(task, "task-1", {"title": "第一轮"}, render_report=True)
    report = render(task, "task-1")
    update(task, "task-1", {"title": "第二轮", "cases": [{"id": "C1", "claim": "结果可见", "observed": "显示 1 条", "verdict": "通过"}]}, "补充业务截图")
    assert render(task, "task-1") == report
    data = json.loads((task / "manifest.json").read_text())
    assert len(data["history"]) == 1
    assert "补充业务截图" in report.read_text()


def test_register_asset_copies_with_unique_relative_path_and_media_markup(tmp_path):
    task = make_task(tmp_path)
    initialize(task, "task-1", {"title": "媒体"}, render_report=True)
    source = tmp_path / "before.png"
    Image.new("RGB", (1280, 720)).save(source)
    item = register_asset(task, "task-1", source, "before", "修改前", "关键区域")
    assert item["path"].startswith("../assets/")
    assert (task / item["path"][3:]).is_file()
    assert '<img src="../assets/' in (task / "report/index.html").read_text()


def test_register_asset_disallows_unsupported_files_and_symlinks(tmp_path):
    task = make_task(tmp_path)
    initialize(task, "task-1", render_report=True)
    bad = tmp_path / "notes.txt"
    bad.write_text("x")
    with pytest.raises(ValueError):
        register_asset(task, "task-1", bad, "screenshot")
    link = tmp_path / "linked.png"
    link.symlink_to(bad)
    with pytest.raises(ValueError):
        register_asset(task, "task-1", link, "screenshot")


def test_manifest_and_task_id_are_validated(tmp_path):
    task = make_task(tmp_path)
    initialize(task, "task-1", render_report=True)
    with pytest.raises(ValueError):
        update(task, "other", {})
    with pytest.raises(ValueError):
        register_asset(task, "task-1", tmp_path / "missing.png", "unknown")


def test_html_escapes_user_content(tmp_path):
    task = make_task(tmp_path)
    initialize(task, "task-1", {"title": "<script>alert(1)</script>", "cases": [{"id": "C<1>", "observed": "<b>可见</b>", "verdict": "通过"}]}, render_report=True)
    text = (task / "report/index.html").read_text()
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;" in text
    assert "&lt;b&gt;可见&lt;/b&gt;" in text


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_business_summary_and_observations_render_complete_safe_paragraphs(tmp_path, newline):
    task = make_task(tmp_path)
    summary = newline.join([
        "背景：返回列表丢失筛选。需要重新操作。", " \t ",
        "用户预期：继续查看原记录。", "", "", "改动方案 InScope：恢复已有筛选。",
    ])
    observed = newline.join([
        "返回列表：筛选保留。", "列表仍有 2 条记录。", "",
        "重复进入：显示 <待处理> & 原记录。",
    ])
    initialize(task, "task-1", {
        "summary": summary,
        "cases": [{"id": "C1", "title": "返回列表", "claim": "返回后筛选与结果保留", "input": "筛选后进入详情再返回",
                   "observed": observed, "verdict": "通过", "evidence_ids": []}],
    }, render_report=True, report_round={"id": "R1", "reason": "首次验收\n\n版本：example"})
    page = (task / "report/index.html").read_text().split("<main>", 1)[1].split("</main>", 1)[0]
    intro = page.split('<div class="hero-sub">', 1)[1].split('</div>', 1)[0]
    assert intro.count('<p>') == 3
    assert '<details' not in intro
    assert '<p>背景：返回列表丢失筛选。需要重新操作。</p>' in intro
    assert '<p>用户预期：继续查看原记录。</p>' in intro
    assert '<p>改动方案 InScope：恢复已有筛选。</p>' in intro
    assert page.count('背景：返回列表丢失筛选') == 1
    observation = page.split('<section class="observation">', 1)[1].split('</section>', 1)[0]
    assert '<p>返回列表：筛选保留。\n列表仍有 2 条记录。</p>' in observation
    assert '<p>重复进入：显示 &lt;待处理&gt; &amp; 原记录。</p>' in observation
    assert observation.count('<p>') == 2
    assert '<summary>轮次说明</summary><p>首次验收</p><p>版本：example</p>' in page
    assert 'aria-label="场景汇总：通过"' in page


@pytest.mark.parametrize("summary", ["旧摘要首句。旧摘要后句。", "", None])
def test_legacy_summary_remains_complete_without_empty_round_details(tmp_path, summary):
    task = make_task(tmp_path)
    initialize(task, "task-1", {"summary": summary}, render_report=True)
    page = (task / "report/index.html").read_text().split("<main>", 1)[1].split("</main>", 1)[0]
    intro = page.split('<div class="hero-sub">', 1)[1].split('</div>', 1)[0]
    assert intro == (f'<p>{summary}</p>' if summary else '')
    assert '<details class="report-summary">' not in page


def test_audio_and_video_use_controls(tmp_path):
    task = make_task(tmp_path)
    initialize(task, "task-1", render_report=True)
    video = tmp_path / "run.mp4"
    audio = tmp_path / "note.mp3"
    video.write_bytes(b"video")
    audio.write_bytes(b"audio")
    register_asset(task, "task-1", video, "video", "录屏")
    register_asset(task, "task-1", audio, "audio", "旁白")
    text = (task / "report/index.html").read_text()
    assert "<video controls" in text
    assert "<audio controls" in text


def test_initialize_does_not_reset_existing_task(tmp_path):
    task = make_task(tmp_path)
    initialize(task, "task-1", {"title": "保留历史"}, render_report=True)
    with pytest.raises(FileExistsError):
        initialize(task, "task-1", {"title": "不应覆盖"}, render_report=True)

def test_render_rejects_tampered_asset_path(tmp_path):
    task = make_task(tmp_path)
    initialize(task, "task-1", render_report=True)
    manifest = json.loads((task / "manifest.json").read_text())
    manifest["assets"].append({"kind": "image", "path": "../../secret.txt", "label": "x"})
    (task / "manifest.json").write_text(json.dumps(manifest))
    previous = (task / "report/index.html").read_bytes()
    with pytest.raises(ValueError, match="asset_invalid"):
        render(task, "task-1")
    assert (task / "report/index.html").read_bytes() == previous
    assert "../../secret.txt" not in (task / "report/index.html").read_text()


def test_report_is_optional_until_explicit_render(tmp_path):
    task = make_task(tmp_path)
    initialize(task, "task-1", {"title": "轻量"})
    assert not (task / "report/index.html").exists()
    render(task, "task-1")
    assert (task / "report/index.html").is_file()

def test_before_after_assets_render_as_one_comparison(tmp_path):
    task = make_task(tmp_path)
    initialize(task, "task-1", {"title": "对比"}, render_report=True)
    before = tmp_path / "before.png"
    after = tmp_path / "after.png"
    Image.new("RGB", (1280, 720)).save(before)
    Image.new("RGB", (1280, 720)).save(after)
    register_asset(task, "task-1", before, "before", "修改前", metadata={"comparison_id": "cmp-1", "case_id": "C1", "page_ref": "clients"})
    register_asset(task, "task-1", after, "after", "修改后", metadata={"comparison_id": "cmp-1", "case_id": "C1", "page_ref": "clients"})
    text = (task / "report/index.html").read_text()
    assert text.count("前后对比：cmp-1") == 1
    assert text.count("<figure>") == 2
    assert text.count('src="../assets/before_0.png"') == 1
    assert text.count('src="../assets/after_1.png"') == 1
    manifest = json.loads((task / "manifest.json").read_text())
    assert manifest["assets"][0]["metadata"]["case_id"] == "C1"


def test_capture_metadata_accepts_fixed_viewport_and_full_page(tmp_path):
    task = make_task(tmp_path)
    initialize(task, "task-1", {"title": "规格"}, render_report=True)
    source = tmp_path / "full.png"
    Image.new("RGB", (1280, 2400)).save(source)
    item = register_asset(task, "task-1", source, "screenshot", metadata={"case_id": "C1", "viewport": "1280x720", "capture_mode": "full_page", "width": 1280, "height": 2400})
    assert item["metadata"]["capture_mode"] == "full_page"
    text = (task / "report/index.html").read_text()
    assert "全页截图" in text and "1280 × 2400 px" in text


def test_capture_metadata_rejects_invalid_mode_and_dimensions(tmp_path):
    task = make_task(tmp_path)
    initialize(task, "task-1")
    source = tmp_path / "shot.png"
    Image.new("RGB", (1280, 720)).save(source)
    with pytest.raises(ValueError):
        register_asset(task, "task-1", source, "screenshot", metadata={"capture_mode": "dom"})
    with pytest.warns(UserWarning, match="实际尺寸"):
        assert register_asset(task, "task-1", source, "screenshot", metadata={"width": 0})["metadata"]["width"] == 1280
    with pytest.raises(ValueError):
        register_asset(task, "task-1", source, "screenshot", metadata={"viewport": 1280})


def test_ui_acceptance_and_media_are_grouped_under_case(tmp_path):
    task = make_task(tmp_path)
    initialize(task, "task-1", {"title": "归属", "cases": [{"id": "C1", "title": "筛选", "claim": "结果", "input": "123", "observed": "1 条", "verdict": "通过", "limitation": "只读"}], "ui_acceptance": [{"case_id": "C1", "criterion": "列表可见", "observed": "可见", "verdict": "通过"}]}, render_report=True)
    source = tmp_path / "case.png"
    Image.new("RGB", (1280, 720)).save(source)
    register_asset(task, "task-1", source, "screenshot", "C1 截图", metadata={"case_id": "C1", "viewport": "1280x720", "capture_mode": "viewport"})
    text = (task / "report/index.html").read_text()
    case_block = text.split('id="case-C1"', 1)[1].split('</article>', 1)[0]
    assert "输入与操作" in case_block and "123" in case_block and "1 条" in case_block
    assert "UI 验收" in case_block and "C1 截图" in case_block


def test_unassigned_ui_acceptance_is_not_dropped(tmp_path):
    task = make_task(tmp_path)
    initialize(task, "task-1", {"title": "旧数据", "cases": [{"id": "C1", "title": "结果"}], "ui_acceptance": [{"criterion": "旧 UI 标准", "observed": "旧观察", "verdict": "信息不足"}]}, render_report=True)
    text = (task / "report/index.html").read_text()
    assert "未归类 UI 验收" in text and "旧 UI 标准" in text


def test_comparison_id_is_rendered_once_as_a_group(tmp_path):
    task = make_task(tmp_path)
    initialize(task, "task-1", {"title": "对比", "cases": [{"id": "C1", "title": "修复"}]}, render_report=True)
    before = tmp_path / "before.png"
    after = tmp_path / "after.png"
    Image.new("RGB", (1280, 720)).save(before)
    Image.new("RGB", (1280, 720)).save(after)
    register_asset(task, "task-1", before, "before", "修改前", "原始布局", {"case_id": "C1", "comparison_id": "cmp", "viewport": "1280x720", "width": 1280, "height": 720})
    register_asset(task, "task-1", after, "after", "修改后", "更新布局", {"case_id": "C1", "comparison_id": "cmp", "viewport": "1280x720", "width": 1280, "height": 720})
    text = (task / "report/index.html").read_text()
    assert text.count("前后对比：cmp") == 1
    assert text.count('class="comparison"') == 1
    assert text.count("<figcaption>修改前</figcaption>") == 1
    assert text.count("<figcaption>修改后</figcaption>") == 1


def test_lightbox_has_accessible_controls_and_keyboard_navigation(tmp_path):
    task = make_task(tmp_path)
    initialize(task, "task-1", {"title": "放大", "cases": [{"id": "C1", "title": "截图"}]}, render_report=True)
    source = tmp_path / "shot.png"
    Image.new("RGB", (1280, 720)).save(source)
    register_asset(task, "task-1", source, "screenshot", "截图", metadata={"case_id": "C1"})
    text = (task / "report/index.html").read_text()
    assert 'role="dialog"' in text and 'aria-modal="true"' in text
    assert 'aria-label="上一张"' in text and 'aria-label="下一张"' in text
    assert 'aria-label="关闭图片"' in text and 'aria-label="放大：截图"' in text
    assert '<button type="button" class="image-button"' in text


def test_report_resources_are_inline_and_independent_of_cwd(tmp_path, monkeypatch):
    task = make_task(tmp_path)
    monkeypatch.chdir(tmp_path)
    initialize(task, "task-1", {"title": "响应式"}, render_report=True)
    text = (task / "report/index.html").read_text()
    assert "<style>" in text and "<script>" in text
    assert "<script src=" not in text and 'rel="stylesheet"' not in text
    assert 'name="viewport"' in text


def test_tampered_absolute_and_nested_asset_paths_are_rejected(tmp_path):
    task = make_task(tmp_path)
    initialize(task, "task-1", {"title": "路径"}, render_report=True)
    manifest = json.loads((task / "manifest.json").read_text())
    manifest["assets"] = [{"kind": "image", "path": "../assets/../../secret.png", "label": "bad"}, {"kind": "image", "path": "/tmp/secret.png", "label": "bad2"}]
    (task / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="asset_invalid"):
        render(task, "task-1")
    text = (task / "report/index.html").read_text()
    assert "secret.png" not in text


def test_unknown_case_ui_is_preserved(tmp_path):
    task = make_task(tmp_path)
    initialize(task, "task-1", {"cases": [{"id": "C1"}], "ui_acceptance": [{"case_id": "C9", "criterion": "待归属标准"}]}, render_report=True)
    assert "待归属标准" in (task / "report/index.html").read_text()


def test_invalid_metadata_does_not_leave_asset_file(tmp_path):
    task = make_task(tmp_path)
    initialize(task, "task-1")
    source = tmp_path / "shot.png"
    Image.new("RGB", (1280, 720)).save(source)
    with pytest.raises(ValueError):
        register_asset(task, "task-1", source, "screenshot", metadata={"viewport": 123})
    assert list((task / "assets").iterdir()) == []


def test_gif_is_rendered_as_image(tmp_path):
    task = make_task(tmp_path)
    initialize(task, "task-1", render_report=True)
    source = tmp_path / "animation.gif"
    Image.new("RGB", (1280, 720)).save(source)
    register_asset(task, "task-1", source, "gif", "状态变化")
    text = (task / "report/index.html").read_text()
    assert '<img src="../assets/animation_0.gif"' in text
    assert '<video controls' not in text


@pytest.mark.parametrize("verdicts, expected", [
    ([], "信息不足"), (["通过"], "通过"), (["通过", "不通过"], "不通过"),
    (["通过", "信息不足"], "信息不足"), (["未通过验证"], "信息不足"),
    ([None], "信息不足"), (["不通过", "信息不足"], "不通过"),
])
def test_report_aggregates_only_explicit_verdicts(tmp_path, verdicts, expected):
    task = make_task(tmp_path)
    initialize(task, "task-1", {"cases": [
        {"id": f"C{i}", "verdict": verdict} for i, verdict in enumerate(verdicts)
    ]}, render_report=True)
    text = (task / "report/index.html").read_text()
    assert f'aria-label="场景汇总：{expected}"' in text


def test_all_ui_observations_remain_in_their_case(tmp_path):
    task = make_task(tmp_path)
    initialize(task, "task-1", {
        "cases": [{"id": "C1", "verdict": "通过"}, {"id": "C2"}],
        "ui_acceptance": [
            {"case_id": "C1", "criterion": "首项", "observed": "可见", "verdict": "通过"},
            {"case_id": "C1", "criterion": "后续项", "observed": "<内容被遮挡>", "verdict": "不通过"},
            {"case_id": "C2", "criterion": "另一个 Case"},
        ],
    }, render_report=True)
    text = (task / "report/index.html").read_text()
    block = text.split('id="case-C1"', 1)[1].split('</article>', 1)[0]
    assert "首项" in block and "后续项" in block
    assert "&lt;内容被遮挡&gt;" in block and "结论：不通过" in block
    assert "另一个 Case" not in block


def test_scope_exclusion_is_visible_without_rewriting_saved_result(tmp_path):
    task = make_task(tmp_path)
    content = {
        "cases": [{"id": "C1", "verdict": "通过"}],
        "excluded_cases": [{"title": "键盘场景", "reason": "明确跳过，原故障尚未修复"}],
    }
    initialize(task, "task-1", content)
    page = render(task, "task-1").read_text().split("</main>", 1)[0]
    assert "本轮范围说明 · 键盘场景" in page
    assert "明确跳过，原故障尚未修复" in page
    assert json.loads((task / "manifest.json").read_text())["manifest"] == content


def test_image_viewer_escapes_labels_and_preserves_unknown_capture_metadata(tmp_path):
    task = make_task(tmp_path)
    initialize(task, "task-1", render_report=True)
    source = tmp_path / "shot.png"
    Image.new("RGB", (1280, 720)).save(source)
    hostile = '</script><script>alert("media")</script>'
    register_asset(task, "task-1", source, "screenshot", hostile, hostile)
    page = (task / "report/index.html").read_text()
    assert hostile not in page and page.count("<script>") == 1
    assert "采集方式：未记录" in page
    assert "视口截图" not in page
    gallery = json.JSONDecoder().raw_decode(page.split("let lightboxAssets=", 1)[1])[0]
    assert gallery[0]["label"] == gallery[0]["note"] == hostile

import copy
import json

import pytest
from PIL import Image

from scripts import delivery_artifacts as reports
from scripts import sites_report as sites


@pytest.fixture
def review(tmp_path):
    task = tmp_path / "ui-review"
    task.mkdir()
    reports.initialize(task, task.name, report_round={"id": "R1", "reason": "设计对比"})
    assets = []
    for name, color in (("design", "white"), ("old", "red"), ("fixed", "green")):
        file = tmp_path / f"{name}.png"
        Image.new("RGB", (390, 844), color).save(file)
        assets.append(reports.register_asset(task, task.name, file, "image", name,
                                            metadata={"case_id": "UI1"}))
    design, old, fixed = [asset["asset_id"] for asset in assets]
    content = {"title": "UI 走查样例", "summary": "独立模板测试数据", "cases": [
        {"id": "UI1", "kind": "ui", "title": "地址标签", "claim": "图标与设计对应", "input": "样例",
         "observed": "第 4 轮后图标仍不符", "verdict": "不通过", "evidence_ids": [old, design],
         "ui_comparisons": [{"id": "ios-label", "platform": "iOS",
                             "design_url": "https://www.figma.com/design/example/UI?node-id=1-2",
                             "design_asset_id": design, "implementation_asset_id": old}]},
        {"id": "F1", "title": "功能", "claim": "能展开", "observed": "已展开", "verdict": "通过", "evidence_ids": []},
    ], "ui_acceptance": [{"case_id": "UI1", "ui_comparison_id": "ios-label", "criterion": "定位图标：采用设计节点中的轮廓", "observed": "仍有差异", "verdict": "不通过"}]}
    reports.update(task, task.name, content)
    return task, content, assets


def current_page(task):
    # 不让内联历史数据干扰当前正文断言。
    return reports.render(task, task.name).read_text().split('<div class="lightbox"')[0]


def test_pair_is_design_left_even_when_selected_order_is_reversed(review):
    task, content, assets = review
    page = current_page(task)
    assert page.index('id="case-F1"') < page.index('id="case-UI1"')
    assert page.count('id="case-UI1"') == 1
    assert "2</b> 个场景" in page
    assert 'id="section-functional"' in page and 'id="section-ui"' in page
    pair = page.split('class="ui-pair"')[1]
    assert pair.index(assets[0]["path"]) < pair.index(assets[1]["path"])
    assert pair.count('<img ') == 2
    assert 'Figma 设计稿' in pair and '实际实现' in pair
    assert '<details class="execution" open>' in page
    assert reports.check_html_export(task, task.name)["counts"] == {"error": 0, "warning": 0, "info": 0}
    site = sites.export_sites(task, task.name)
    payload = json.loads((site / 'public/report/report.json').read_text())
    assert payload['rounds'][0]['manifest']['cases'][0]['ui_comparisons'] == content['cases'][0]['ui_comparisons']
    assert payload['rounds'][0]['manifest']['cases'][0]['kind'] == 'ui'
    assert payload['rounds'][0]['manifest']['ui_acceptance'] == content['ui_acceptance']


def test_checks_follow_their_pair_and_are_not_duplicated(review):
    task, content, _ = review
    second = {**content["cases"][0]["ui_comparisons"][0], "id": "android-label", "platform": "Android"}
    content["cases"][0]["ui_comparisons"].append(second)
    content["ui_acceptance"].append({"case_id": "UI1", "ui_comparison_id": "android-label",
                                    "criterion": "Android 字号应为 14", "observed": "实际 12", "verdict": "不通过"})
    reports.update(task, task.name, content)
    page = current_page(task)
    ios, android = page.split('data-comparison-id="ios-label"')[1].split('data-comparison-id="android-label"')
    assert "定位图标" in ios and "Android 字号" not in ios
    assert "Android 字号" in android and "定位图标" not in android
    assert page.count("Android 字号") == page.count("采用设计节点中的轮廓") == 1


@pytest.mark.parametrize("missing", ["all", "ui_comparison_id", "criterion", "observed", "verdict"])
def test_incomplete_checks_remain_visible_draft_without_changing_verdict(review, missing):
    task, content, _ = review
    if missing == "all":
        content["ui_acceptance"] = []
    else:
        content["ui_acceptance"][0].pop(missing)
    reports.update(task, task.name, content)
    for check in (reports.check_html_export, sites.check_sites_export):
        result = check(task, task.name)
        assert result["can_export"] and result["requires_review"]
        assert "ui_checks_incomplete" in [item["code"] for item in result["diagnostics"]]
    with pytest.warns(UserWarning):
        page = current_page(task)
    assert "走查记录未齐备，交付未完成" in page
    assert reports.read_report(task, task.name)["manifest"]["cases"][0]["verdict"] == "不通过"
    if missing == "ui_comparison_id":
        assert "定位图标" in page.split('<details class="execution" open>')[1]


@pytest.mark.parametrize("mutation,code", [
    (lambda content: content["ui_acceptance"][0].update(ui_comparison_id="other-pair"), "ui_check_reference_invalid"),
    (lambda content: content["ui_acceptance"][0].update(ui_comparison_id=[]), "ui_check_reference_invalid"),
    (lambda content: content["cases"][0].update(verdict="通过"), "ui_verdict_conflict"),
    (lambda content: (content["cases"][0].update(verdict="通过"),
                      content["ui_acceptance"][0].update(verdict="信息不足")), "ui_verdict_conflict"),
])
def test_current_invalid_checks_block_both_exports_and_preserve_last_page(review, mutation, code):
    task, content, _ = review
    page = reports.render(task, task.name)
    before = page.read_bytes()
    mutation(content)
    # update 保存当前记录，但不能把矛盾内容覆盖为新的交付页面。
    with pytest.raises(ValueError, match=code):
        reports.update(task, task.name, content)
    for check in (reports.check_html_export, sites.check_sites_export):
        result = check(task, task.name)
        assert not result["can_export"]
        assert code in [item["code"] for item in result["diagnostics"]]
    with pytest.raises(ValueError, match=code):
        sites.export_sites(task, task.name)
    assert page.read_bytes() == before
    assert reports.read_report(task, task.name)["manifest"] == content


def test_historical_conflict_is_preserved_without_blocking_corrected_current_round(review):
    task, content, _ = review
    content["cases"][0]["verdict"] = "通过"
    reports.update(task, task.name, content)  # 尚未开启渲染，保留待纠正记录。
    content["cases"][0]["verdict"] = "不通过"
    reports.update(task, task.name, content, report_round={"id": "R2", "reason": "撤回不可靠结论"})
    assert reports.check_html_export(task, task.name)["can_export"]
    assert sites.check_sites_export(task, task.name)["can_export"]
    current_page(task)
    history = reports.read_report(task, task.name, round_id="R1")["manifest"]
    assert history["cases"][0]["verdict"] == "通过"
    assert history["ui_acceptance"][0]["verdict"] == "不通过"


def test_repair_selects_new_image_and_history_keeps_old_pair(review):
    task, content, assets = review
    content['cases'][0].update(verdict='通过', observed='图标符合设计', evidence_ids=[assets[0]['asset_id'], assets[2]['asset_id']])
    content['cases'][0]['ui_comparisons'][0]['implementation_asset_id'] = assets[2]['asset_id']
    content['ui_acceptance'][0].update(verdict='通过', observed='图标符合设计')
    reports.update(task, task.name, content, report_round={'id': 'R2', 'reason': '修复后复验'})
    page = current_page(task)
    assert assets[1]['path'] not in page and assets[2]['path'] in page
    old = reports.read_report(task, task.name, round_id='R1')
    assert old['manifest']['cases'][0]['verdict'] == '不通过'
    assert old['manifest']['cases'][0]['ui_comparisons'][0]['implementation_asset_id'] == assets[1]['asset_id']
    site = sites.export_sites(task, task.name)
    payload = json.loads((site / 'public/report/report.json').read_text())
    by_round = {view['round']['id']: view for view in payload['rounds']}
    assert assets[1]['asset_id'] not in [a['asset_id'] for a in by_round['R2']['assets']]
    assert assets[1]['asset_id'] in [a['asset_id'] for a in by_round['R1']['assets']]


@pytest.mark.parametrize('side', ['design_asset_id', 'implementation_asset_id', 'both'])
def test_missing_pair_is_visible_gap_without_rewriting_observation(review, side):
    task, content, _ = review
    case = content['cases'][0]
    case.update(verdict='通过', observed='对比已完成，交付图缺失，交付未完成')
    content['ui_acceptance'][0].update(verdict='通过', observed='图标符合设计，交付图片缺失')
    if side == 'both':
        case['ui_comparisons'] = []
        content['ui_acceptance'][0].pop('ui_comparison_id')
    else:
        case['ui_comparisons'][0].pop(side)
    reports.update(task, task.name, content)
    for check in (reports.check_html_export, sites.check_sites_export):
        result = check(task, task.name)
        assert result['can_export'] and result['requires_review']
        assert 'ui_comparison_incomplete' in [issue['code'] for issue in result['diagnostics']]
    with pytest.warns(UserWarning):
        page = current_page(task)
    assert ('尚未登记' if side == 'both' else '缺少图片') in page
    assert reports.read_report(task, task.name)['manifest']['cases'][0]['verdict'] == '通过'


@pytest.mark.parametrize('mutation', [
    lambda c: c.update(kind='invalid'),
    lambda c: c.update(kind='functional'),
    lambda c: c.update(ui_comparisons={}),
    lambda c: c['ui_comparisons'].append(copy.deepcopy(c['ui_comparisons'][0])),
    lambda c: c['ui_comparisons'][0].update(platform=''),
    lambda c: c['ui_comparisons'][0].update(design_asset_id='missing'),
    lambda c: c['ui_comparisons'][0].update(implementation_asset_id=c['ui_comparisons'][0]['design_asset_id']),
    lambda c: c['ui_comparisons'][0].update(design_url='javascript:alert(1)'),
    lambda c: c['ui_comparisons'][0].update(design_url='https://figma.com.evil.test/design/a'),
    lambda c: c['ui_comparisons'][0].update(design_url='https://user@figma.com/design/a'),
    lambda c: c['ui_comparisons'][0].update(unknown='silent loss'),
])
def test_invalid_ui_reference_cannot_replace_saved_report(review, mutation):
    task, content, _ = review
    before = (task / 'manifest.json').read_bytes()
    mutation(content['cases'][0])
    with pytest.raises(ValueError):
        reports.update(task, task.name, content)
    assert (task / 'manifest.json').read_bytes() == before


def test_non_image_reference_is_rejected(review):
    task, content, _ = review
    file = task.parent / 'audio.mp3'
    file.write_bytes(b'test audio')
    asset = reports.register_asset(task, task.name, file, 'audio', 'audio', metadata={'case_id': 'UI1'})
    content['cases'][0]['evidence_ids'].append(asset['asset_id'])
    content['cases'][0]['ui_comparisons'][0]['implementation_asset_id'] = asset['asset_id']
    with pytest.raises(ValueError, match='图片'):
        reports.update(task, task.name, content)


def test_tampered_pair_is_export_error_and_does_not_replace_html(review):
    task, _, _ = review
    page = reports.render(task, task.name)
    before = page.read_bytes()
    raw = json.loads((task / 'manifest.json').read_text())
    raw['manifest']['cases'][0]['ui_comparisons'][0]['implementation_asset_id'] = 'missing'
    (task / 'manifest.json').write_text(json.dumps(raw))
    for check in (reports.check_html_export, sites.check_sites_export):
        result = check(task, task.name)
        assert not result['can_export']
        assert 'ui_comparison_invalid' in [issue['code'] for issue in result['diagnostics']]
    assert page.read_bytes() == before


def test_ordinary_case_keeps_legacy_presentation(review):
    task, content, _ = review
    content['cases'] = [content['cases'][1]]
    content['ui_acceptance'] = []
    reports.update(task, task.name, content)
    page = current_page(task)
    assert 'UI 走查</h2>' not in page
    assert page.count('id="case-F1"') == 1


def test_ui_labels_are_escaped(review):
    task, content, _ = review
    content['cases'][0]['ui_comparisons'][0]['platform'] = '<img src=x onerror=alert(1)>'
    reports.update(task, task.name, content)
    assert '&lt;img src=x onerror=alert(1)&gt;' in current_page(task)


def test_legacy_update_requires_explicit_round_for_ui(review):
    task, content, _ = review
    legacy = task.parent / 'legacy'
    legacy.mkdir()
    reports.initialize(legacy, legacy.name)
    before = (legacy / 'manifest.json').read_bytes()
    with pytest.raises(ValueError, match='显式轮次'):
        reports.update(legacy, legacy.name, content)
    assert (legacy / 'manifest.json').read_bytes() == before


def test_legacy_html_cannot_bypass_ui_pair_validation(review):
    task, content, _ = review
    raw = json.loads((task / 'manifest.json').read_text())
    raw['schema_version'] = 1
    raw.pop('current_round')
    raw.pop('rounds')
    raw['manifest']['cases'][0]['ui_comparisons'][0]['design_url'] = 'javascript:alert(1)'
    (task / 'manifest.json').write_text(json.dumps(raw))
    result = reports.check_html_export(task, task.name)
    assert not result['can_export']
    assert 'ui_round_required' in [issue['code'] for issue in result['diagnostics']]
    with pytest.raises(ValueError):
        reports.render(task, task.name)

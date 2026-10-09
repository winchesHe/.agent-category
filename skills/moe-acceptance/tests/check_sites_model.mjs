import assert from "node:assert/strict";
import { evidenceGroups, canOverlay, mediaLabel, verdict } from "../templates/sites/app/reading/report-model.ts";

const photo = (id, metadata = {}) => ({ asset_id: id, kind: "image", url: `/report/assets/${id}.png`, metadata });
const frame = { width: 390, height: 780, viewport: "390x780", capture_mode: "viewport", comparison_id: "pair" };
const assets = [photo("before", frame), photo("after", frame), photo("single"), photo("unused")];
const selected = { id: "C 中文%", evidence_ids: ["single", "before", "after"] };
const groups = evidenceGroups(selected, assets, "after");
assert.deepEqual(groups.map(g => g.assets.map(a => a.asset_id)), [["before", "after"], ["single"]]);
assert.deepEqual(selected.evidence_ids, ["single", "before", "after"]);
assert.equal(canOverlay(groups[0].assets), true);
assert.equal(canOverlay([assets[0], photo("different", { ...frame, width: 400 })]), false);
assert.equal(canOverlay([photo("unknown"), photo("also-unknown")]), false);
assert.equal(canOverlay([...groups[0].assets, assets[2]]), false);
assert.equal(mediaLabel(photo("portrait", frame)), "截图");
assert.equal(mediaLabel(photo("mobile", { ...frame, platform: "ios" })), "App 截图");
assert.equal(mediaLabel({ ...photo("gif"), url: "/report/assets/animated.gif" }), "动图");
assert.equal(verdict("未确认"), "信息不足");

console.log("媒体分组、叠加条件与未知值检查通过");

const { uiComparisonGroups, orderedCases } = await import('../templates/sites/app/reading/report-model.ts');
const uiCase = { id: 'UI1', kind: 'ui', evidence_ids: ['after', 'before', 'single'], ui_comparisons: [{
  id: 'ios', platform: 'iOS', design_url: 'https://www.figma.com/design/example/UI?node-id=1-2',
  design_asset_id: 'before', implementation_asset_id: 'after',
}] };
const pairs = uiComparisonGroups(uiCase, assets);
assert.equal(pairs[0].design.asset_id, 'before');
assert.equal(pairs[0].implementation.asset_id, 'after');
assert.deepEqual(evidenceGroups(uiCase, assets).flatMap(g => g.assets.map(a => a.asset_id)), ['single']);
assert.equal(uiComparisonGroups({ ...uiCase, evidence_ids: ['before'] }, assets)[0].implementation, undefined);
assert.equal(uiComparisonGroups(uiCase, [assets[0]])[0].implementation, undefined);
assert.deepEqual(orderedCases([uiCase, selected]).map(c => c.id), [selected.id, uiCase.id]);
assert.deepEqual(uiCase.evidence_ids, ['after', 'before', 'single']);
console.log('UI 配对、缺图、分栏及重复展示检查通过');

export type Verdict = "通过" | "不通过" | "信息不足";
export type Asset = {
  asset_id: string;
  kind: string;
  label?: string;
  note?: string;
  url: string;
  captured_at?: string | null;
  registered_at?: string | null;
  round_id?: string | null;
  supersedes?: string[];
  replacement_reason?: string;
  metadata: {
    case_id?: string;
    comparison_id?: string;
    viewport?: string;
    capture_mode?: string;
    page_ref?: string;
    width?: number;
    height?: number;
    platform?: string;
    device?: string;
    duration_seconds?: number;
    chapters?: { time: number; label: string }[];
  };
};
export type Case = {
  id: string;
  kind?: "functional" | "ui";
  ui_comparisons?: UIComparison[];
  title?: string;
  problem?: string;
  claim?: unknown;
  input?: unknown;
  observed?: unknown;
  verdict?: string;
  evidence_ids?: string[];
};
export type UIComparison = {
  id: string;
  platform: string;
  design_url: string;
  design_asset_id?: string | null;
  implementation_asset_id?: string | null;
};
export type UICheck = {
  case_id: string;
  ui_comparison_id?: string;
  criterion?: unknown;
  observed?: unknown;
  verdict?: string;
};
export type Round = {
  round: {
    id: string;
    label?: string;
    reason?: string;
    observed_at?: string | null;
    legacy?: boolean;
  };
  manifest: {
    title?: string;
    summary?: string;
    cases: Case[];
    excluded_cases?: { title?: string; reason?: string }[];
    ui_acceptance?: UICheck[];
  };
  assets: Asset[];
  warning?: string;
};
export type Hints = { short_title?: string; primary_evidence_id?: string };
export type Report = {
  schema_version: number;
  task_id: string;
  current_round_id: string;
  rounds: Round[];
  presentation: Record<string, Record<string, Hints>>;
};
export type EvidenceGroup = {
  id: string;
  assets: Asset[];
  comparison: boolean;
};
export const verdict = (value?: string): Verdict =>
  value === "通过" || value === "不通过" ? value : "信息不足";
export function text(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}
export const isVideo = (asset: Asset) => /\.(mp4|webm|mov)$/i.test(asset.url);
export const isAudio = (asset: Asset) => /\.(mp3|wav|m4a)$/i.test(asset.url);
export const isPortrait = (asset: Asset) =>
  !!asset.metadata.width &&
  !!asset.metadata.height &&
  asset.metadata.height > asset.metadata.width;
export function mediaLabel(asset: Asset): string {
  if (isVideo(asset)) return "过程录屏";
  if (isAudio(asset)) return "音频";
  if (asset.kind === "gif" || /\.gif$/i.test(asset.url)) return "动图";
  if (["ios", "android", "mobile"].includes(asset.metadata.platform?.toLowerCase() || "")) {
    return "App 截图";
  }
  return "截图";
}
export const timestamp = (value?: string | null) =>
  value ? value.replace("T", " ") : "未知";
export const timecode = (seconds: number) =>
  `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;

export function evidenceGroups(
  testCase: Case,
  assets: Asset[],
  primary?: string,
): EvidenceGroup[] {
  const index = new Map(assets.map((asset) => [asset.asset_id, asset]));
  const groups: EvidenceGroup[] = [];
  const comparisons = new Map<string, EvidenceGroup>();
  const paired = new Set(
    testCase.kind === "ui" ? (testCase.ui_comparisons || []).flatMap(
      (pair) => [pair.design_asset_id, pair.implementation_asset_id],
    ) : [],
  );
  for (const id of testCase.evidence_ids || []) {
    if (paired.has(id)) continue;
    const asset = index.get(id);
    if (!asset) continue;
    const comparison = asset.metadata.comparison_id;
    if (comparison && !isVideo(asset) && !isAudio(asset)) {
      let group = comparisons.get(comparison);
      if (!group) {
        group = { id: `comparison:${comparison}`, assets: [], comparison: true };
        comparisons.set(comparison, group);
        groups.push(group);
      }
      group.assets.push(asset);
    } else groups.push({ id: `asset:${id}`, assets: [asset], comparison: false });
  }
  const main = groups.findIndex((group) =>
    group.assets.some((asset) => asset.asset_id === primary),
  );
  if (main > 0) groups.unshift(...groups.splice(main, 1));
  return groups;
}

export function uiComparisonGroups(testCase: Case, assets: Asset[]) {
  const selected = new Set(testCase.evidence_ids || []);
  const index = new Map(assets.filter((asset) => selected.has(asset.asset_id)).map((asset) => [asset.asset_id, asset]));
  return (testCase.ui_comparisons || []).map((pair) => ({
    ...pair,
    design: index.get(pair.design_asset_id || ""),
    implementation: index.get(pair.implementation_asset_id || ""),
  }));
}

export function orderedCases(cases: Case[]) {
  return [...cases.filter((c) => c.kind !== "ui"), ...cases.filter((c) => c.kind === "ui")];
}

export function canOverlay(assets: Asset[]) {
  if (assets.length !== 2) return false;
  const [a, b] = assets.map((asset) => asset.metadata);
  return (
    !!a.width &&
    !!a.height &&
    !!a.viewport &&
    !!a.capture_mode &&
    a.width === b.width &&
    a.height === b.height &&
    a.viewport === b.viewport &&
    a.capture_mode === b.capture_mode &&
    a.page_ref === b.page_ref
  );
}

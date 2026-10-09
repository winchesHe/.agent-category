"use client";
import { Fragment, useRef, useState } from "react";
import {
  Check,
  Minus,
  X,
  ChevronDown,
  ChevronUp,
  FileText,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from "@/components/ui/collapsible";
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui/select";
import { useCaseNavigation } from "./use-case-navigation";
import { Evidence, UIDesignReview, UIObservations } from "./evidence";
import { RichText } from "./rich-text";
import {
  evidenceGroups,
  mediaLabel,
  text,
  timestamp,
  verdict,
  orderedCases,
  type Report,
  type Round,
  type Verdict,
} from "./report-model";
import "./reading.css";

const verdicts = {
  通过: { className: "pass", icon: Check },
  不通过: { className: "fail", icon: X },
  信息不足: { className: "unknown", icon: Minus },
};
function VerdictLabel({ value }: { value: Verdict }) {
  const { className, icon: Icon } = verdicts[value];
  return (
    <Badge variant="outline" className={`ev-verdict ${className}`}>
      <Icon size={14} />
      {value}
    </Badge>
  );
}

export default function ReportPage({ report }: { report: Report }) {
  const [selected, setSelected] = useState(report.current_round_id);
  const round = report.rounds.find((item) => item.round.id === selected)!;
  return (
    <RoundReport
      key={selected}
      report={report}
      view={round}
      selectRound={setSelected}
    />
  );
}

function RoundReport({
  report,
  view,
  selectRound,
}: {
  report: Report;
  view: Round;
  selectRound: (id: string) => void;
}) {
  const root = useRef<HTMLDivElement | null>(null);
  const cases = orderedCases(view.manifest.cases);
  const hasUI = cases.some((c) => c.kind === "ui");
  const sectionLabels = cases.map((c, index) =>
    hasUI && (index === 0 || (c.kind === "ui") !== (cases[index - 1].kind === "ui"))
      ? c.kind === "ui" ? "UI 走查" : "功能验收"
      : null,
  );
  const { activeIndex, goToCase, returnToSummary } = useCaseNavigation(
    root,
    cases.length,
  );
  const current = cases[activeIndex];
  const hints = report.presentation[view.round.id] || {};
  const groups = cases.map((c) =>
    evidenceGroups(c, view.assets, hints[c.id]?.primary_evidence_id),
  );
  const counts = Object.fromEntries(
    (["通过", "不通过", "信息不足"] as Verdict[]).map((status) => [
      status,
      cases.filter((c) => verdict(c.verdict) === status).length,
    ]),
  );
  const overall: Verdict = counts["不通过"]
    ? "不通过"
    : !cases.length || counts["信息不足"]
      ? "信息不足"
      : "通过";
  const historical = view.round.id !== report.current_round_id;
  const label = (index: number) =>
    cases[index]?.kind === "ui" ? "UI 走查" : groups[index]?.some((group) => group.comparison && group.assets.length > 1)
      ? "前后对比"
      : groups[index]?.[0]?.assets[0]
        ? mediaLabel(groups[index][0].assets[0])
        : "观察记录";
  return (
    <div className="evidence-report" ref={root} data-round-id={view.round.id}>
      <header className="ev-header" id="summary">
        <div className="ev-topline">
          <span>
            {historical ? "历史快照" : "当前报告"} · {report.task_id}
          </span>
          <span>观察时间：{timestamp(view.round.observed_at)}</span>
        </div>
        <div className="ev-report-title">
          <h1 tabIndex={-1}>{view.manifest.title || report.task_id}</h1>
          <VerdictLabel value={overall} />
        </div>
        {view.manifest.summary && (
          <p className="ev-report-observation"><RichText>{view.manifest.summary}</RichText></p>
        )}
        {historical && (
          <p className="ev-history-warning">历史快照，不代表当前结果。</p>
        )}
        {view.warning && (
          <p className="ev-history-warning" role="status">
            <RichText>{view.warning}</RichText>
          </p>
        )}
        <Collapsible>
          <CollapsibleTrigger asChild>
            <Button variant="ghost" size="sm" className="ev-scope-trigger">
              <ChevronDown size={14} />
              范围与说明
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent className="ev-scope-content">
            <p><RichText>{view.round.reason || "未记录轮次说明。"}</RichText></p>
            {(view.manifest.excluded_cases || []).map((item, index) => (
              <p key={index}>
                <RichText>{item.title}</RichText>：<RichText>{item.reason}</RichText>
              </p>
            ))}
          </CollapsibleContent>
        </Collapsible>
        <div className="ev-report-bottom">
          <div className="ev-summary">
            <span>
              <b>{cases.length}</b>个场景
            </span>
            <span>
              <b>{counts["通过"]}</b>通过
            </span>
            <span>
              <b>{counts["不通过"]}</b>不通过
            </span>
            <span>
              <b>{counts["信息不足"]}</b>信息不足
            </span>
          </div>
          <div className="ev-report-round">
            <span>报告轮次</span>
            <Select value={view.round.id} onValueChange={selectRound}>
              <SelectTrigger aria-label="报告轮次">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="ev-popover">
                {report.rounds.map((item) => (
                  <SelectItem key={item.round.id} value={item.round.id}>
                    {item.round.id === report.current_round_id ? "当前 · " : ""}
                    {item.round.label || item.round.id}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      </header>
      {cases.length === 0 ? (
        <main className="ev-empty">
          本轮没有记录 Case，暂无法形成验收结论。
        </main>
      ) : (
        <main className="ev-workspace">
          <aside className="ev-sidebar">
            <div className="ev-nav-heading">
              检查清单<span>{String(cases.length).padStart(2, "0")}</span>
            </div>
            <nav className="ev-nav" aria-label="案例目录">
              {cases.map((c, index) => {
                const Icon = verdicts[verdict(c.verdict)].icon;
                return (
                  <Fragment key={c.id}>
                  {sectionLabels[index] && (
                    <div className="ev-nav-section" role="heading" aria-level={2}>
                      <span>{sectionLabels[index]}</span>
                      <span>{cases.filter((item) => (item.kind === "ui") === (c.kind === "ui")).length}</span>
                    </div>
                  )}
                  <Button
                    variant="ghost"
                    onClick={() => goToCase(index)}
                    aria-controls={`panel-${index}`}
                    aria-current={index === activeIndex ? "step" : undefined}
                    aria-label={`${c.id} ${hints[c.id]?.short_title || c.title || c.id}，${verdict(c.verdict)}`}
                  >
                    <span className="ev-nav-number">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <span className="ev-nav-title">
                      {hints[c.id]?.short_title || c.title || c.id}
                    </span>
                    <Icon
                      size={13}
                      className={`ev-nav-status ${verdicts[verdict(c.verdict)].className}`}
                    />
                  </Button>
                  </Fragment>
                );
              })}
            </nav>
            <div className="ev-nav-bottom">
              <Button
                variant="ghost"
                size="sm"
                onClick={returnToSummary}
                className="ev-back-summary"
              >
                <ChevronUp size={14} />
                报告概况
              </Button>
              <div className="ev-nav-controls">
                <span>
                  {String(activeIndex + 1).padStart(2, "0")} /{" "}
                  {String(cases.length).padStart(2, "0")}
                </span>
                <Button
                  variant="ghost"
                  aria-label="上一个案例"
                  disabled={activeIndex === 0}
                  onClick={() => goToCase(activeIndex - 1)}
                >
                  <ChevronUp size={18} />
                </Button>
                <Button
                  variant="ghost"
                  aria-label="下一个案例"
                  disabled={activeIndex === cases.length - 1}
                  onClick={() => goToCase(activeIndex + 1)}
                >
                  <ChevronDown size={18} />
                </Button>
              </div>
            </div>
          </aside>
          <section className="ev-stage" aria-label="案例证据">
            <div className="ev-panels">
              {cases.map((c, index) => {
                const assets = view.assets.filter((asset) => c.evidence_ids?.includes(asset.asset_id));
                const isUI = c.kind === "ui";
                const sectionCases = cases.filter((item) => (item.kind === "ui") === isUI);
                const ui = (view.manifest.ui_acceptance || []).filter(
                  (item) => item.case_id === c.id,
                );
                return (
                  <Fragment key={c.id}>
                  {sectionLabels[index] && <header className="ev-case-section">
                    <h2>{sectionLabels[index]}</h2>
                    <p>{(["通过", "不通过", "信息不足"] as Verdict[]).map((status) => `${sectionCases.filter((item) => verdict(item.verdict) === status).length} ${status}`).join(" · ")}</p>
                  </header>}
                  <article
                    className="ev-panel"
                    id={`panel-${index}`}
                    data-case-id={c.id}
                    key={c.id}
                    data-active={index === activeIndex}
                    aria-labelledby={`title-${index}`}
                  >
                    <div
                      className="ev-case-scroll"
                    >
                      <div className="ev-case">
                        <header className="ev-case-header">
                          <div className="ev-case-meta">
                            <span>
                              {c.id}
                              <span className="ev-meta-divider">/</span>
                              {label(index)}
                            </span>
                            <VerdictLabel value={verdict(c.verdict)} />
                          </div>
                          <h2 id={`title-${index}`} tabIndex={-1}>
                            {c.title || c.id}
                          </h2>
                          <div className="ev-observation">
                            {c.problem ? (
                              <>
                                <p><strong>修复前问题：</strong><RichText>{c.problem}</RichText></p>
                                <p><strong>修复后预期：</strong><RichText>{text(c.claim) || "尚未记录预期。"}</RichText></p>
                              </>
                            ) : (text(c.observed) || "尚未记录实际观察。")
                              .split(/\n+|(?<=[。！？])/u)
                              .filter((part) => part.trim())
                              .map((part, i) => <p key={i}><RichText>{part.trim()}</RichText></p>)}
                          </div>
                        </header>
                        {isUI && <UIDesignReview testCase={c} assets={assets} checks={ui} />}
                        {(!isUI || groups[index].length > 0) && <Evidence groups={groups[index]} />}
                        <Collapsible className="ev-details" defaultOpen={isUI}>
                          <CollapsibleTrigger asChild>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="ev-details-trigger"
                            >
                              <FileText size={14} />
                              实际观察与操作记录
                              <ChevronDown size={14} />
                            </Button>
                          </CollapsibleTrigger>
                          <CollapsibleContent className="ev-detail-body">
                            {c.problem && (
                              <div className="ev-observation">
                                <strong>实际观察：</strong>
                                {text(c.observed).split(/\n+|(?<=[。！？])/u).filter((part) => part.trim()).map((part, i) => <p key={i}><RichText>{part.trim()}</RichText></p>)}
                              </div>
                            )}
                            <p>
                              <strong>预期：</strong>
                              <RichText>{text(c.claim) || "未记录"}</RichText>
                            </p>
                            <p className="ev-preserve">
                              <strong>输入与操作：</strong>
                              <RichText>{text(c.input) || "未记录"}</RichText>
                            </p>
                            <UIObservations checks={ui.filter((item) =>
                              !isUI || !(c.ui_comparisons || []).some((pair) => pair.id === item.ui_comparison_id),
                            )} />
                          </CollapsibleContent>
                        </Collapsible>
                        {assets.length > 0 && (
                          <Collapsible className="ev-details">
                            <CollapsibleTrigger asChild>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="ev-details-trigger"
                              >
                                证据来源 · {assets.length}
                                <ChevronDown size={14} />
                              </Button>
                            </CollapsibleTrigger>
                            <CollapsibleContent className="ev-detail-body">
                              {assets.map((asset) => (
                                <div
                                  className="ev-asset-detail"
                                  key={asset.asset_id}
                                >
                                  <p>
                                    <strong>
                                      {asset.label || asset.asset_id}
                                    </strong>{" "}
                                    · {asset.asset_id}
                                  </p>
                                  <p>
                                    采集：{timestamp(asset.captured_at)} ·
                                    来源轮次：{asset.round_id || "未知"}
                                  </p>
                                  {(asset.metadata.platform ||
                                    asset.metadata.device) && (
                                    <p>
                                      {[
                                        asset.metadata.platform,
                                        asset.metadata.device,
                                      ]
                                        .filter(Boolean)
                                        .join(" · ")}
                                    </p>
                                  )}
                                  {asset.metadata.page_ref && (
                                    <p><RichText>{asset.metadata.page_ref}</RichText></p>
                                  )}
                                  <p>
                                    尺寸：
                                    {asset.metadata.width &&
                                    asset.metadata.height
                                      ? `${asset.metadata.width} × ${asset.metadata.height}`
                                      : "未知"}{" "}
                                    · 视口：{asset.metadata.viewport || "未知"}{" "}
                                    · 采集范围：
                                    {asset.metadata.capture_mode || "未知"}
                                  </p>
                                  {!!asset.supersedes?.length && (
                                    <p>
                                      替代：{asset.supersedes.join("、")} ·{" "}
                                      <RichText>{asset.replacement_reason}</RichText>
                                    </p>
                                  )}
                                  <a
                                    href={asset.url}
                                    target="_blank"
                                    rel="noreferrer"
                                  >
                                    打开原始证据 ↗
                                  </a>
                                </div>
                              ))}
                            </CollapsibleContent>
                          </Collapsible>
                        )}
                        <footer className="ev-case-foot">
                          <span>
                            {c.id} · {view.round.label || view.round.id}
                          </span>
                          <span>{assets.length} 项证据</span>
                        </footer>
                      </div>
                    </div>
                  </article>
                  </Fragment>
                );
              })}
            </div>
            <footer className="ev-stage-foot">
              <span>{label(activeIndex)}</span>
              <span>已展示本轮全部案例</span>
            </footer>
          </section>
        </main>
      )}
      <div className="ev-sr-only" role="status" aria-live="polite">
        {current
          ? `当前案例 ${activeIndex + 1} / ${cases.length}：${current.title || current.id}，${verdict(current.verdict)}`
          : "本轮没有 Case"}
      </div>
    </div>
  );
}

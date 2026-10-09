"use client";
import { useRef, useState } from "react";
import { Expand } from "lucide-react";
import { Button } from "@/components/ui/button";
import { RichText } from "./rich-text";
import {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Slider } from "@/components/ui/slider";
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui/select";
import {
  canOverlay,
  isAudio,
  isPortrait,
  isVideo,
  timecode,
  timestamp,
  uiComparisonGroups,
  text,
  verdict,
  type UICheck,
  type Asset,
  type Case,
  type EvidenceGroup,
} from "./report-model";

export function UIObservations({ checks }: { checks: UICheck[] }) {
  return checks.map((item, i) => <div key={i} className="ev-ui-observation">
    <p><strong>检查点与预期：<RichText>{text(item.criterion) || "未记录"}</RichText></strong> · {verdict(item.verdict)}</p>
    <p className="ev-preserve">实际观察：<RichText>{text(item.observed) || "未记录"}</RichText></p>
  </div>);
}

export function UIDesignReview({ testCase, assets, checks }: { testCase: Case; assets: Asset[]; checks: UICheck[] }) {
  const pairs = uiComparisonGroups(testCase, assets);
  if (!pairs.length) return <p className="ev-boundary neutral">尚未登记设计稿与实现的配对证据，交付未完成。</p>;
  return <div className="ev-ui-comparisons">
    {pairs.map((pair) => {
      const related = checks.filter((item) => item.ui_comparison_id === pair.id);
      return <section className="ev-ui-comparison" key={pair.id} data-comparison-id={pair.id}>
      <header><strong>{pair.platform}</strong> · <a href={pair.design_url} target="_blank" rel="noreferrer">查看 Figma 节点 ↗</a></header>
      <div className="ev-ui-pair">
        {([['Figma 设计稿', pair.design], ['实际实现', pair.implementation]] as const).map(([label, asset]) =>
          <div className="ev-ui-side" key={label}>
            <h3>{label}</h3>
            {asset ? <Photo asset={asset} /> : <p className="ev-boundary neutral">缺少图片，当前对比证据未齐备。</p>}
          </div>,
        )}
      </div>
      <UIObservations checks={related} />
      {(!related.length || related.some((item) =>
        [item.criterion, item.observed].some((value) => typeof value !== "string" || !value.trim()) ||
        !["通过", "不通过", "信息不足"].includes(item.verdict || ""),
      )) && <p className="ev-boundary neutral">本组走查记录未齐备，交付未完成。</p>}
    </section>; })}
    {checks.some((item) => !pairs.some((pair) => pair.id === item.ui_comparison_id)) &&
      <p className="ev-boundary neutral">存在未关联到图片的检查点，详见操作记录；走查记录未齐备，交付未完成。</p>}
  </div>;
}

export function Photo({ asset, compact = false }: { asset: Asset; compact?: boolean }) {
  const [error, setError] = useState(false);
  const portrait = isPortrait(asset);
  const title = asset.label || asset.asset_id;
  return (
    <figure
      className={`ev-photo ${portrait ? "portrait" : ""}`}
      data-evidence-id={asset.asset_id}
    >
      <figcaption>
        <strong>{title}</strong>
      </figcaption>
      {error ? (
        <p className="ev-error">
          图片暂时无法加载。<a href={asset.url}>打开原图</a>
        </p>
      ) : (
        <Dialog>
          <DialogTrigger asChild>
            <Button
              variant="ghost"
              className="ev-image-button"
              aria-label={`放大：${title}`}
            >
              <img
                src={asset.url}
                alt={title}
                width={asset.metadata.width}
                height={asset.metadata.height}
                loading="lazy"
                onError={() => setError(true)}
              />
              <span className="ev-expand">
                <Expand size={14} />
                <span>放大</span>
              </span>
            </Button>
          </DialogTrigger>
          <DialogContent
            className={`ev-modal ${portrait ? "portrait-modal" : ""}`}
          >
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>
              {asset.note || "原始证据"} · 采集时间：
              {timestamp(asset.captured_at)}
            </DialogDescription>
            <img src={asset.url} alt={title} />
            <a href={asset.url} target="_blank" rel="noreferrer">
              打开原图 ↗
            </a>
          </DialogContent>
        </Dialog>
      )}
      {!compact && asset.note && asset.note !== title && (
        <details className="ev-evidence-notes"><summary>查看图片说明</summary><p>{asset.note}</p></details>
      )}
    </figure>
  );
}

function Recording({ asset }: { asset: Asset }) {
  const media = useRef<HTMLVideoElement | null>(null);
  const [error, setError] = useState(false);
  const [active, setActive] = useState(-1);
  const [speed, setSpeed] = useState("1");
  const chapters = asset.metadata.chapters || [];
  const duration = asset.metadata.duration_seconds;
  return (
    <div
      className={`ev-recording ${isPortrait(asset) ? "ev-portrait-recording" : ""}`}
      data-evidence-id={asset.asset_id}
    >
      <div className="ev-evidence-toolbar">
        <span>
          {asset.label || "过程录屏"}
          {duration ? ` · ${timecode(duration)}` : ""}
        </span>
        <Select
          value={speed}
          onValueChange={(value) => {
            setSpeed(value);
            if (media.current) media.current.playbackRate = Number(value);
          }}
        >
          <SelectTrigger className="ev-speed" aria-label="播放速度">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="ev-popover">
            {["0.5", "1", "1.5", "2"].map((value) => (
              <SelectItem key={value} value={value}>
                {value}×
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <video
        ref={media}
        controls
        preload="metadata"
        src={asset.url}
        aria-label={asset.label || "过程录屏"}
        onError={() => setError(true)}
        onTimeUpdate={() => {
          const time = media.current?.currentTime || 0;
          let index = -1;
          chapters.forEach((chapter, i) => {
            if (chapter.time <= time) index = i;
          });
          setActive(index);
        }}
      />
      {error && (
        <p className="ev-error">
          视频暂时无法播放。<a href={asset.url}>打开原始视频</a>
        </p>
      )}
      {chapters.length > 0 && (
        <div className="ev-moments" role="group" aria-label="视频关键时刻">
          {chapters.map((chapter, index) => (
            <Button
              variant="ghost"
              key={index}
              disabled={error}
              aria-pressed={active === index}
              onClick={() => {
                if (media.current) media.current.currentTime = chapter.time;
              }}
            >
              <span>{timecode(chapter.time)}</span>
              {chapter.label}
            </Button>
          ))}
        </div>
      )}
      {asset.note && <p className="ev-caption">{asset.note}</p>}
    </div>
  );
}

function Comparison({ assets }: { assets: Asset[] }) {
  const [split, setSplit] = useState(50);
  const parallel = (
    <div className="ev-comparison-block">
      <div className={`ev-pair ${assets.every(isPortrait) ? "ev-phone-pair" : ""}`}>
        {assets.map((asset) => <Photo key={asset.asset_id} asset={asset} compact />)}
      </div>
      {assets.some((asset) => asset.note && asset.note !== asset.label) && (
        <details className="ev-evidence-notes">
          <summary>查看对比说明</summary>
          {assets.filter((asset) => asset.note && asset.note !== asset.label).map((asset) => (
            <p key={asset.asset_id}><strong>{asset.label}</strong><br />{asset.note}</p>
          ))}
        </details>
      )}
    </div>
  );
  if (!canOverlay(assets)) return parallel;
  return (
    <Tabs defaultValue="side" className="ev-comparison">
      <div className="ev-evidence-toolbar">
        <span>前后对比</span>
        <TabsList>
          <TabsTrigger value="side">并排</TabsTrigger>
          <TabsTrigger value="overlay">叠加</TabsTrigger>
        </TabsList>
      </div>
      <TabsContent value="side">{parallel}</TabsContent>
      <TabsContent
        value="overlay"
        className={assets.every(isPortrait) ? "ev-portrait-overlay" : undefined}
      >
        <div className="ev-overlay-labels">
          <span>{assets[0].label}</span>
          <span>{assets[1].label}</span>
        </div>
        <div className="ev-overlay">
          <img src={assets[1].url} alt={assets[1].label || "第二张证据"} />
          <img
            className="ev-overlay-before"
            src={assets[0].url}
            alt={assets[0].label || "第一张证据"}
            style={{ clipPath: `inset(0 ${100 - split}% 0 0)` }}
          />
          <span className="ev-divider" style={{ left: `${split}%` }} />
        </div>
        <div className="ev-slider">
          <span>拖动分界</span>
          <Slider
            aria-label="对比分界位置"
            min={0}
            max={100}
            step={1}
            value={[split]}
            onValueChange={(value) => setSplit(value[0])}
          />
          <span>{split}%</span>
        </div>
      </TabsContent>
    </Tabs>
  );
}

function AudioEvidence({ asset }: { asset: Asset }) {
  const [error, setError] = useState(false);
  return (
    <figure className="ev-audio" data-evidence-id={asset.asset_id}>
      <figcaption>{asset.label || "音频证据"}</figcaption>
      <audio
        controls
        src={asset.url}
        preload="metadata"
        aria-label={asset.label || "音频证据"}
        onError={() => setError(true)}
      />
      {error && (
        <p className="ev-error">
          音频暂时无法播放。<a href={asset.url}>打开原始音频</a>
        </p>
      )}
      {asset.note && <p className="ev-caption">{asset.note}</p>}
    </figure>
  );
}

export function Evidence({ groups }: { groups: EvidenceGroup[] }) {
  if (!groups.length)
    return (
      <div className="ev-boundary neutral">
        <strong>本案例没有可展示的媒体</strong>
        <p>可展开操作记录查看已有观察与结论。</p>
      </div>
    );
  return (
    <div className="ev-evidence-stack">
      {groups.map((group) => (
        <section
          key={group.id}
          className={
            group.assets.length === 1 &&
            !isVideo(group.assets[0]) &&
            !isAudio(group.assets[0])
              ? "ev-single"
              : ""
          }
        >
          {group.comparison && group.assets.length > 1 ? (
            <Comparison assets={group.assets} />
          ) : (
            group.assets.map((asset) =>
              isVideo(asset) ? (
                <Recording key={asset.asset_id} asset={asset} />
              ) : isAudio(asset) ? (
                <AudioEvidence key={asset.asset_id} asset={asset} />
              ) : (
                <Photo key={asset.asset_id} asset={asset} />
              ),
            )
          )}
        </section>
      ))}
    </div>
  );
}

"use client";

import { useEffect, useState, type RefObject } from "react";

export function useCaseNavigation(root: RefObject<HTMLDivElement | null>, count: number) {
  const [activeIndex, setActiveIndex] = useState(0);
  useEffect(() => {
    const panels = Array.from(root.current?.querySelectorAll<HTMLElement>(".ev-panel") || []);
    let frame = 0;
    function update() {
      frame = 0;
      const nav = root.current?.querySelector<HTMLElement>(".ev-sidebar");
      // 目录过长时随文档滚动，避免再创建局部滚动条或遮住案例正文。
      const availableHeight = window.innerWidth <= 680 ? window.innerHeight / 2 : window.innerHeight - 32;
      const sticky = !!nav && nav.offsetHeight < availableHeight;
      if (nav) nav.dataset.sticky = String(sticky);
      const margin = window.innerWidth <= 680 && sticky ? nav.offsetHeight + 16 : 24;
      root.current?.style.setProperty("--ev-case-offset", `${margin}px`);
      const offset = margin + 32;
      let active = 0;
      panels.forEach((panel, index) => {
        if (panel.getBoundingClientRect().top <= offset) active = index;
      });
      if (window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 2) {
        active = Math.max(0, panels.length - 1);
      }
      setActiveIndex(active);
    }
    function schedule() {
      if (!frame) frame = requestAnimationFrame(update);
    }
    // 只观察文档滚动，不接管滚轮、触摸或键盘的原生阅读行为。
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    const resize = new ResizeObserver(schedule);
    if (root.current) resize.observe(root.current);
    update();
    return () => {
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      resize.disconnect();
      cancelAnimationFrame(frame);
    };
  }, [root, count]);

  function goToCase(index: number) {
    const panel = root.current?.querySelectorAll<HTMLElement>(".ev-panel")[index];
    if (!panel) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    panel.scrollIntoView({ block: "start", behavior: reduce ? "instant" : "smooth" });
    panel.querySelector<HTMLElement>("h2")?.focus({ preventScroll: true });
  }
  function returnToSummary() {
    root.current?.querySelector<HTMLElement>(".ev-header h1")?.focus({ preventScroll: true });
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    window.scrollTo({ top: 0, behavior: reduce ? "instant" : "smooth" });
  }
  return { activeIndex, goToCase, returnToSummary };
}

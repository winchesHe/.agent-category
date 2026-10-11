# PNG Export

Load this reference when exporting PNG or choosing between native and Chromium rendering. The unified command validates the SVG root/canvas, limits output to 64 megapixels and 32768px per side, writes atomically, and reads PNG dimensions back.

## Renderer Choice

| Tool | Install | Use when |
| --- | --- | --- |
| CairoSVG | `python3 -m pip install cairosvg` | Default; good CSS support |
| `rsvg-convert` | `brew install librsvg` or `apt install librsvg2-bin` | Simple SVGs without complex CSS |
| Puppeteer | Node.js plus Chromium | Browser-generated SVG, CJK/emoji fallback, or pixel fidelity |

Prefer the bundled validation/export entry point:

```bash
SKILL_ROOT="${CLAUDE_SKILL_DIR:-/absolute/path/from-codex-skill-metadata}"
python3 "$SKILL_ROOT/scripts/fireworks.py" export-png ./diagram.svg ./diagram.png --width 1920
```

## Manual CairoSVG

```bash
python3 -c "import cairosvg; cairosvg.svg2png(url='input.svg', write_to='output.png', output_width=1920)"
```

## Manual librsvg

```bash
rsvg-convert -w 1920 input.svg -o output.png
```

## Puppeteer

Use Node.js 22.12+ and Puppeteer with Chrome/Chromium. The bundled converter exports intrinsic root-canvas dimensions at 2×; a viewBox-only SVG uses the root viewBox, never an inner shape. It blocks external network requests and uses an isolated headless browser. Sandbox disabling is explicit via `FIREWORKS_CHROME_NO_SANDBOX=1` only for a runtime that requires it.

Install Puppeteer outside the user's project and run the converter:

```bash
SKILL_ROOT="${CLAUDE_SKILL_DIR:-/absolute/path/from-codex-skill-metadata}"
npm install --prefix /tmp/fireworks-tech-graph-puppeteer puppeteer
NODE_PATH=/tmp/fireworks-tech-graph-puppeteer/node_modules node "$SKILL_ROOT/scripts/svg2png.js" ./output
```

## Known Limits

- `rsvg-convert` can omit complex CSS, filters, and `<foreignObject>` content.
- CairoSVG can miss CJK or emoji glyphs when the selected system font lacks them.
- Use Puppeteer when browser rendering is required; its viewport path preserves the SVG dimensions more reliably than a raw Chrome `--window-size` screenshot.

## 本地补充：中文缺字与 Chrome 无头导出

> 本节为 `.agent-category` 仓库的本地补充，不属于上游内容；升级本 skill 后需确认仍然保留。基于 fireworks-tech-graph 1.2.0 在 macOS 上验证（2026-10-11）。

- `export-png` 默认走 CairoSVG。系统字体缺少 CJK 回退时，中文会渲染成方框；`doctor` 显示 Puppeteer 不可用时无法切换到浏览器渲染。导出后必须打开 PNG 确认中文正常显示。
- 没有 Puppeteer 时，可用本机 Chrome 无头截图导出 2 倍图。先写一个 wrapper HTML，用 `<img src="diagram.svg" width="W" height="H">` 固定图片尺寸，`body` 设 `margin:0`，背景色设为图的底色，避免边缘露白：

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --disable-gpu \
  --hide-scrollbars --force-device-scale-factor=2 --window-size=W,H \
  --screenshot=diagram.png file:///absolute/path/wrapper.html
```

- `W`、`H` 取 SVG 根节点的宽高；输出 PNG 应为 `2W × 2H`，导出后核对尺寸，并确认四边没有被裁切或多出空白。

# Style 5: Glassmorphism

Frosted glass cards on dark gradient. Designed for product sites, keynotes, and hero sections.

## Colors

```
Background gradient: #0d1117 → #161b22 → #0d1117 (diagonal)

Glass card:
  fill:           rgba(255,255,255,0.05)
  stroke:         rgba(255,255,255,0.15)
  backdrop-filter: blur(12px)  [SVG: use feGaussianBlur]
  box-radius:     12px

Text primary:   #f0f6fc  (near-white)
Text secondary: #8b949e  (muted)
Text gradient:  use linearGradient on text fill for hero labels

Accent glows (one per layer):
  Blue glow:    #58a6ff  / rgba(88,166,255,0.3)
  Purple glow:  #bc8cff  / rgba(188,140,255,0.3)
  Green glow:   #3fb950  / rgba(63,185,80,0.3)
  Orange glow:  #f78166  / rgba(247,129,102,0.3)
```

## Background

```xml
<defs>
  <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
    <stop offset="0%"   stop-color="#0d1117"/>
    <stop offset="50%"  stop-color="#161b22"/>
    <stop offset="100%" stop-color="#0d1117"/>
  </linearGradient>
  <!-- Ambient glow spots -->
  <radialGradient id="glow-blue" cx="30%" cy="40%" r="40%">
    <stop offset="0%" stop-color="rgba(88,166,255,0.15)"/>
    <stop offset="100%" stop-color="rgba(88,166,255,0)"/>
  </radialGradient>
  <radialGradient id="glow-purple" cx="70%" cy="60%" r="35%">
    <stop offset="0%" stop-color="rgba(188,140,255,0.12)"/>
    <stop offset="100%" stop-color="rgba(188,140,255,0)"/>
  </radialGradient>
</defs>
<rect width="960" height="600" fill="url(#bg)"/>
<rect width="960" height="600" fill="url(#glow-blue)"/>
<rect width="960" height="600" fill="url(#glow-purple)"/>
```

## Glass Card Effect

SVG cannot do real backdrop-filter, so simulate with:

```xml
<defs>
  <filter id="glass-blur">
    <feGaussianBlur in="SourceGraphic" stdDeviation="0.5"/>
  </filter>
</defs>

<!-- Glass card: layered rects -->
<!-- 1. Subtle inner shadow -->
<rect rx="12" fill="rgba(255,255,255,0.03)" stroke="none"/>
<!-- 2. Glass body -->
<rect rx="12" fill="rgba(255,255,255,0.06)"
      stroke="rgba(255,255,255,0.15)" stroke-width="1"/>
<!-- 3. Top highlight line -->
<line stroke="rgba(255,255,255,0.25)" stroke-width="1"/>
```

## Typography

```
font-family: 'Inter', -apple-system, 'SF Pro Display', 'PingFang SC', 'Microsoft YaHei', 'Microsoft JhengHei', 'SimHei', sans-serif
font-size:   14px labels, 12px sublabels, 20px hero title
font-weight: 400 normal, 600 semi-bold, 700 bold titles
```

## Gradient Text (for hero labels)

```xml
<defs>
  <linearGradient id="text-grad-blue" x1="0%" y1="0%" x2="100%" y2="0%">
    <stop offset="0%"   stop-color="#58a6ff"/>
    <stop offset="100%" stop-color="#bc8cff"/>
  </linearGradient>
</defs>
<text fill="url(#text-grad-blue)" font-weight="700" font-size="20">
  AI Pipeline
</text>
```

## Arrows

```xml
<defs>
  <marker id="arrow-blue" markerWidth="8" markerHeight="6"
          refX="7" refY="3" orient="auto">
    <polygon points="0 0, 8 3, 0 6" fill="#58a6ff"/>
  </marker>
</defs>
<!-- Slightly glowing line -->
<path stroke="#58a6ff" stroke-width="1.5" fill="none"
      opacity="0.8" marker-end="url(#arrow-blue)"/>
```

## SVG Template

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 600"
     width="960" height="600">
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
    text { font-family: 'Inter', -apple-system, 'SF Pro Display', 'PingFang SC', 'Microsoft YaHei', 'Microsoft JhengHei', 'SimHei', sans-serif; fill: #f0f6fc; }
  </style>
  <defs>
    <!-- bg gradients, glow gradients, glass filter, arrow markers -->
  </defs>
  <!-- background layers -->
  <!-- glass cards (nodes) -->
  <!-- glowing edges -->
  <!-- labels with gradient text for heroes -->
</svg>
```

## 本地补充：文档嵌图的玻璃感增强

> 本节为 `.agent-category` 仓库的本地补充，不属于上游内容；升级本 skill 后需确认仍然保留。

按上方默认参数生成的图玻璃感偏弱。用于飞书等文档的展示型总览时，以下调整经实际验证效果更好：

- 背景：深蓝到深紫的线性渐变，再叠加蓝、紫两个 `radialGradient` 光晕。
- 卡片：`fill` 改为白色纵向渐变，透明度从顶部 0.11 过渡到底部 0.035；描边 `rgba(255,255,255,0.16)`；卡片顶部加 1px `rgba(255,255,255,0.42)` 高光线。
- 分区标题使用 `#93c5fd`。
- 连线语义色要拉开距离：data 流 `#fb923c` 与 feedback 流默认的 `#f59e0b` 过于接近，feedback 流改用 `#f87171`。

渐变、半透明和滤镜在飞书白板中都会丢失，此风格嵌入飞书时导出为 PNG 图片，不转白板。导出方法见 [png-export.md](png-export.md)。

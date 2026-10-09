# Opportunity 编写指南

## 定义

**Opportunity = 一类客户的 desire 或 fear，如果被解决，会产生业务/产品层面的 outcome。**

它必须是 problem-shaped：如果它规定了答案而非问题空间，就是伪装成机会的解决方案。

## 三要素

| 要素 | 定义 | 好的例子 | 坏的例子 |
|------|------|----------|----------|
| Customer class | 一类人，具体到能想象出一个人 | "使用 MoeGo 的日本宠物美容店主" | "用户" |
| Desire or fear | 一个需求或一个痛点 | "fear: 面对全英文界面时操作犹豫、效率低、易出错" | "需要多语言支持" |
| Business outcome | 公司获得什么 | "日本市场的注册→激活转化率不因语言折损" | "扩大用户基数" |

## "Solved well" bar

不含 solution、客户可验证的证明标准：

- ✅ "非英语用户可以用母语完成核心业务流程，无需依赖翻译工具或猜测"
- ❌ "接入 i18next 并部署 Tolgee"（这是 solution）
- ❌ "用户满意度提升"（不可验证、无标准）

## 测试方法

写完 Opportunity 后，执行三要素测试：

1. 能否只看这段话就想象出一个具体的人？→ 否则 customer class 不够具体
2. 能否只看 desire/fear 那一项就感受到痛？→ 否则不够聚焦
3. 把 desire/fear 删掉，剩下的是否还有意义？→ 否则 business outcome 是空话
4. 是否能不知道 solution 就判断"解决好了没"？→ 否则 "solved well" 混入了 solution

## 常见错误

### 错误 1: Solution 伪装成 Opportunity

- ❌ "我们需要一个翻译管理平台"
- ✅ "非英语用户面对全英文界面时操作犹豫、效率低" → 翻译平台是解决方案之一

### 错误 2: Customer class 太笼统

- ❌ "我们的客户"
- ✅ "月均服务 50+ 只宠物的中型美容店主，主要分布在日本和东南亚"

### 错误 3: 多个 desire/fear 混在一起

- ❌ "用户看不懂界面且担心数据安全且觉得价格贵"
- ✅ 拆成三个独立 Opportunity，按优先级排序

### 错误 4: Business outcome 不属于公司

- ❌ "用户更开心" → 这是用户的 outcome，不是公司的
- ✅ "日本市场付费转化率从 X% 提升到 Y%" → 这是公司的 outcome

## 模板

```text
Customer class:   <一类人——具体到能想象出一个人>
Desire or fear:   [desire | fear] — <单一最大的那个，命名为一个>
Business outcome: <如果解决了，公司获得什么>
"Solved well":    <不含 solution、客户可验证的证明标准>
```

## 技术项目也必须有 Opportunity

技术项目通过它赋能的产品工作链接到 Opportunity：一个 refactor 如果解锁了未来的 feature，就继承那个 feature 的 Opportunity（按置信度和时间折扣）。

如果你无法命名下游的 Opportunity，这是一个信号——这项工作可能不值得做。

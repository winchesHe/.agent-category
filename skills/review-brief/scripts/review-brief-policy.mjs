// 共享给生产渲染器与确定性 grader，避免两边对禁止内容的判断漂移。
export const FORBIDDEN_VISIBLE_PATTERNS = [
  ["非目标说明", /(?:非目标|范围外|不在(?:本次)?范围|(?:本次|此次)(?:改动|变更)?(?:范围)?(?:不包含|不包括|不涉及|未覆盖|未纳入)|(?:本次|此次|这次).{0,12}(?:不改|不处理|不调整|不动|保持(?:不变|原样)|维持不变)|未纳入.{0,12}(?:本次|此次)(?:改动|变更|范围)|不覆盖(?:旧|原有|既有).{0,12}(?:页面|页|流程|功能|模块|场景)|(?:页面|页|功能|模块|流程).{0,12}(?:留待|放到)(?:后续|以后)|(?:旧|原有|既有).{0,4}(?:页面|页|功能|模块|流程).{0,8}(?:保持(?:原样|不变)|没有变化|不受影响|不动)|(?:其余|其他|剩余).{0,12}(?:保持(?:原样|不变)|没有变化|不受影响|不做调整|不调整|不动)|除.{1,12}外.{0,8}(?:不做|没有)(?:改动|调整|变化)|out\s+of\s+scope|not\s+in\s+scope|non[- ]?goals?)/i],
  ["验证结果", /(?:(?:(?:单测|单元|集成|端到端|e2e|回归|自动化)?测试|单测|tests?|CI|流水线).{0,16}(?:(?:均|全部|已经|已)?(?:通过|成功|失败|绿灯|全绿|全过(?:了)?|正常|异常)(?!时|后|则|会|处理|回调|路径|分支|场景)|(?:passed|failed)(?!\s+(?:when|if|then))|(?:正在|仍在)(?:执行|运行)|(?:are|is)\s+(?:pending|running)|pending|(?:(?:还没|尚未|未|没有)(?:执行|运行|跑(?:过)?)|(?:已经|已)(?:执行|运行|跑过)|跑过))|(?:(?:还没|尚未|未|没有)(?:执行|运行|跑(?:过)?)|(?:已经|已)(?:执行|运行|跑过)|跑过|(?:正在|仍在)(?:执行|运行)|(?:通过|成功|失败|绿灯|全绿|全过(?:了)?|正常|异常)(?!时|后|则|会|处理|回调|路径|分支|场景)|(?:passed|failed)(?!\s+(?:when|if|then))|pending).{0,8}(?:(?:单测|单元|集成|端到端|e2e|回归|自动化)?测试|单测|tests?|CI|流水线))/i],
  ["验证结果", /(?:(?:单测|单元|集成|端到端|e2e|回归|自动化)?测试|单测|tests?|CI|流水线).{0,8}(?:均|全部|已经|已)(?:通过|成功|失败)后(?!端|台)/i],
  ["验证结果", /(?:(?:单测|单元|集成|端到端|e2e|回归|自动化)?测试|单测|tests?|CI|流水线).{0,16}(?:(?:正在|仍在|尚在)(?:执行|运行|跑)(?:中)?|还在跑|没跑(?:完)?|没过|红了|挂了|(?:排队|等待)(?:执行|运行)?(?:中)?|(?:尚未|还没|未)(?:完成|结束)|queued|waiting)/i],
  ["验证结果", /(?:(?:当前|本次|此次)?(?:改动|变更).{0,12}(?:(?:尚未|未|没有|待|尚待|有待)(?:验证|校验)|(?:没有经过|未经)(?:验证|校验))|(?:验证|校验|视觉检查).{0,12}(?:尚未|未|没有)(?:完成|结束|通过)|(?:验证|校验|视觉检查)(?:已经|已)?通过(?:[。.!！]|$))/i],
  ["Review 工作量或复杂度评分", /(?:(?:Review|代码审查|评审|审查).{0,16}(?:预计|估计|大约|约|耗时|工作量|\d+\s*(?:分钟|小时|天)|半(?:个)?小时)|(?:预计|估计|大约|约).{0,16}(?:Review|代码审查|评审|审查)|复杂度.{0,8}(?:评分|得分|分数|等级|\d+\s*\/\s*\d+))/i],
  ["代码审查 finding 或 verdict", /(?:\bfinding(?:s)?\b|\bverdict\b|(?:^|[。！？\n]\s*)[【\[(（]?\s*P[0-3](?:\s*[】\])）])?\s*(?:[：:-]|$)|(?:优先级|严重级别|finding).{0,8}\bP[0-3]\b|\bP[0-3]\b.{0,8}(?:finding|优先级|严重级别)|\bLGTM\b|Request\s+changes|审查结论|合并结论|(?:存在|发现|这里有|此处有).{0,20}(?:正确性|可靠性|性能|安全|兼容|维护性)?(?:问题|缺陷|漏洞|bug)|(?:这里|此处|该实现|该逻辑|当前实现|当前逻辑|[\w.()]+\s+在).{0,20}(?:会|可能|将)(?:导致|触发|造成|出现|除零).{0,24}(?:错误|异常|死循环|数据丢失|除零|必须修复|需要修复)?|(?:错误|异常|死循环|数据丢失|除零|该实现|该逻辑|当前实现|当前逻辑).{0,20}(?:需要|必须|应当|应该)(?:处理|修复|修正|修改)|(?:会|可能|将).{0,16}(?:必须|需要|应当|应该)(?:修复|修正|修改)|(?:建议.{0,80})?(?:修复|修正|修改|修好|解决).{0,80}后.{0,24}(?:再审|重新审查|才(?:能)?合并|方能合并)|建议.{0,16}(?:批准|合并)|需要.{0,80}(?:修复|修正|修改).{0,40}后(?:才|方)?能合并|(?:本次PR|此PR|该PR|PR|代码审查).{0,12}(?:可以|建议|允许|应该|可)合并|(?:审查|评审)(?:结论)?(?:为|是|[：:])?(?:建议)?通过(?:[。.!！]|$)|(?:^|[。！？\n]\s*)(?:可以|建议|允许|应该|可)合并(?:[。.!！？]|$)|(?:^|[：:]\s*)Approve(?:[。.!]|$))/im],
  ["内部交付状态", /(?:\bvisual_review\b|校验命令|未执行.{0,24}(?:GitHub|Slack)|(?:PNG|技术图|截图|产物).{0,10}(?:(?:已经|已)(?:生成|完成|通过(?:视觉)?检查)|生成完成)|(?:已经|已)生成.{0,10}(?:PNG|技术图|截图|产物)|视觉检查通过(?:[。.!！]|$))/i],
];

export function collectVisibleBriefFields(brief) {
  const values = [
    { role: "change_description", value: brief?.overview },
    ...(Array.isArray(brief?.reading_route)
      ? brief.reading_route.map((value) => ({ role: "reading_route", value }))
      : []),
    ...(Array.isArray(brief?.review_focus)
      ? brief.review_focus.map((value) => ({ role: "review_focus", value }))
      : []),
    ...(Array.isArray(brief?.risk_release)
      ? brief.risk_release.map((value) => ({ role: "risk_release", value }))
      : []),
    ...(Array.isArray(brief?.related)
      ? brief.related.map((value) => ({ role: "related", value }))
      : []),
    { role: "alt_text", value: brief?.diagram?.alt_text },
  ];
  for (const change of Array.isArray(brief?.main_changes) ? brief.main_changes : []) {
    if (!change || typeof change !== "object" || Array.isArray(change)) continue;
    values.push(
      { role: "change_description", value: change.title },
      { role: "change_description", value: change.description },
    );
    for (const point of Array.isArray(change.points) ? change.points : []) {
      if (point && typeof point === "object" && !Array.isArray(point)) {
        values.push(
          { role: "change_description", value: point.title },
          { role: "change_description", value: point.description },
        );
      }
    }
    if (Array.isArray(change.code_refs)) {
      values.push(...change.code_refs.map((value) => ({ role: "code_ref", value })));
    }
    for (const attachment of Array.isArray(change.attachments) ? change.attachments : []) {
      if (attachment && typeof attachment === "object" && !Array.isArray(attachment)) {
        values.push({ role: "alt_text", value: attachment.alt_text });
      }
    }
  }
  return values.filter((item) => typeof item.value === "string");
}

export function collectVisibleBriefStrings(brief) {
  return collectVisibleBriefFields(brief).map((item) => item.value);
}

function findingCandidate(item) {
  const role = typeof item === "string" ? "unstructured" : item.role;
  const value = typeof item === "string" ? item : item.value;
  const priority = /\bP[0-3]\b|[【\[(（]\s*P[0-3]\s*[】\])）]/i;
  const reviewDecision = /finding|verdict|LGTM|Request\s+changes|(?:需要|必须|应当|应该|建议).{0,24}(?:修复|修正|修改|解决|批准|合并)|(?:修复|修正|修改|修好|解决).{0,80}后.{0,24}(?:再审|重新审查|才(?:能)?合并|方能合并)|再审|(?:可以|允许|建议|能够|可)合并|审查通过|批准/i;
  const defectSignal = /(?:错误|异常|死循环|数据丢失|除零|bug|缺陷|漏洞|问题|(?:空数组|空集合).{0,20}NaN|NaN.{0,20}(?:空数组|空集合))/i;
  const assertiveDefectSignal = /(?:(?:存在|发现|这里有|此处有|有).{0,20}(?:问题|缺陷|漏洞|bug)|错误|异常|死循环|数据丢失|除零|(?:空数组|空集合).{0,20}NaN|NaN.{0,20}(?:空数组|空集合))/i;
  const maskExpectedErrorContract = (text) => text
    .replace(/(?:进入|走|使用)(?:预期的?)?(?:错误处理|异常处理)(?:分支)?/gi, "")
    .replace(/(?:返回|映射为|转换为|转为)(?:\s+[A-Z][A-Z0-9_]{1,63})?\s*(?:参数错误|错误码|异常状态)/g, "");
  const hasAssertiveDefect = (text) => assertiveDefectSignal.test(maskExpectedErrorContract(text));
  const hasDefectSignal = (text) => defectSignal.test(maskExpectedErrorContract(text));
  const causalSignal = /(?:会|可能|将).{0,20}(?:导致|触发|造成|出现)/;
  const completedChangePrefix = /^(?:新增|支持|实现|调整|更新|统一|迁移|移除|补齐|关联|同步|修复|解决)/;
  const stripMarkdownPrefix = (text) => text.trim()
    .replace(/^[-*]\s+/, "")
    .replace(/^#{1,6}\s+/, "")
    .replace(/^\*\*[^*]+\*\*[：:]?\s*/, "")
    .replace(/^\*[^*]+\*[：:]?\s*/, "");
  const isCompletedChange = (text) => {
    const normalized = stripMarkdownPrefix(text);
    const completedTicketMatch = normalized.match(/^(?:关联|同步|补齐)(?:了)?(?:已存在|历史|既有)?的?.{0,24}P[0-3].{0,24}?工单/i);
    const completedTicketReference = completedTicketMatch !== null;
    const repairBody = normalized.replace(/[。！!]$/, "");
    const completedRepair = /^(?:修复|解决)[\s\S]+的(?:bug|缺陷|漏洞|问题)$/i.test(repairBody);
    const prematurelyCompleted = [...repairBody.matchAll(/[，,；;。！？!?：:—–-]/g)].some(
      (separator) => /(?:bug|缺陷|漏洞|问题)$/i.test(repairBody.slice(0, separator.index).trim()),
    ) || /^(?:修复|解决).{0,80}(?:bug|缺陷|漏洞|问题)\s*(?:并且|并|且|同时|之后)\s*.+/i.test(repairBody);
    if (
      !completedChangePrefix.test(normalized)
      || reviewDecision.test(normalized)
      || (priority.test(normalized) && !completedTicketReference)
    ) {
      return false;
    }
    // 完成态描述可以说明修复了什么，但不能在逗号等分隔符后追加新的 finding 断言。
    const trailingClause = normalized.match(/[，,；;。！？!?：:—–-]\s*(.+)$/)?.[1] ?? "";
    if (completedRepair && !prematurelyCompleted) return true;
    if (completedTicketReference) {
      const ticketTail = normalized.slice(completedTicketMatch[0].length)
        .replace(/^[，,；;。！？!?：:—–\s-]+/, "");
      return !ticketTail
        || (
          !reviewDecision.test(ticketTail)
          && !priority.test(ticketTail)
          && !hasDefectSignal(ticketTail)
          && !causalSignal.test(ticketTail)
        );
    }
    if (causalSignal.test(normalized) || hasAssertiveDefect(normalized)) return false;
    return !trailingClause
      || (!hasAssertiveDefect(trailingClause) && !causalSignal.test(trailingClause));
  };
  const isOpenQuestion = (text) => {
    const trimmed = stripMarkdownPrefix(text);
    const withoutTerminal = trimmed.replace(/[。？?]$/, "");
    const markers = [...withoutTerminal.matchAll(/是否|不会|能够|可以/g)];
    const questionTail = markers.length
      ? withoutTerminal.slice(markers[0].index + markers[0][0].length)
      : "";
    return /^(?:请\s*(?:Reviewer\s*)?)?(?:确认|核对).{0,160}(?:是否|不会|能够|可以).{0,160}$/.test(withoutTerminal)
      && !/[；;。！？?]/.test(withoutTerminal)
      && !/[，,：:—–-]/.test(questionTail)
      && !reviewDecision.test(withoutTerminal)
      && !priority.test(withoutTerminal);
  };
  const isRenderedChangeLine = (text) => {
    const trimmed = text.trim().replace(/^[-*]\s+/, "");
    const match = trimmed.match(/^\*([^*]+)\*[：:]\s*(.+)$/);
    if (!match || !isCompletedChange(match[1])) return false;
    const description = match[2];
    return isCompletedChange(description)
      || (
        !reviewDecision.test(description)
        && !priority.test(description)
        && !hasDefectSignal(description)
        && !causalSignal.test(description)
      );
  };
  if (role === "review_focus") {
    if (isOpenQuestion(value)) return "";
    if (
      reviewDecision.test(value)
      || priority.test(value)
      || defectSignal.test(value)
      || causalSignal.test(value)
    ) return "finding";
  }
  const questionSafeValue = role === "unstructured" ? value.split("\n").map((line) => {
    if (isOpenQuestion(line)) return "";
    if (isRenderedChangeLine(line)) return "";
    return isCompletedChange(line) ? "" : line;
  }).join("\n") : value;
  if (
    role === "unstructured"
    && (
      reviewDecision.test(questionSafeValue)
      || priority.test(questionSafeValue)
      || hasDefectSignal(questionSafeValue)
    )
  ) return "finding";
  if (role === "change_description" || role === "unstructured") {
    if (role === "change_description" && isCompletedChange(questionSafeValue)) {
      return "";
    }
    const containsDecision = reviewDecision.test(questionSafeValue)
      || priority.test(questionSafeValue);
    if (!containsDecision) {
      const completedChangeMasked = questionSafeValue
        .replace(/(?:修复|解决)(?:了)?(?:已发现|已存在|历史|既有)?的?[^。；;，,！？!?：:—–\n-]{0,80}?(?:bug|缺陷|漏洞|问题)(?=\s*(?:[。；;，,！？!?：:—–-]|并且|并|且|同时|之后|$))/gi, "")
        .replace(/(?:关联|同步|补齐)(?:了)?(?:已存在|历史|既有)?的?[^。；;，,！？!?：:—–\n-]{0,80}?工单(?=\s*(?:[。；;，,！？!?：:—–-]|并且|并|且|同时|之后|$))/gi, "");
      if (
        role === "change_description"
        && (hasDefectSignal(completedChangeMasked) || causalSignal.test(completedChangeMasked))
      ) return "finding";
      return completedChangeMasked;
    }
  }
  return questionSafeValue;
}

function scopeCandidate(item) {
  const role = typeof item === "string" ? "unstructured" : item.role;
  const value = typeof item === "string" ? item : item.value;
  const explicitScope = /(?:非目标|范围外|不在(?:本次)?范围|(?:本次|此次)(?:改动|变更)?(?:范围)?(?:不包含|不包括|不涉及|未覆盖|未纳入)|(?:本次|此次|这次).{0,12}(?:不改|不处理|不调整|不动)|(?:页面|页|功能|模块|流程).{0,12}(?:留待|放到)(?:后续|以后)|out\s+of\s+scope|not\s+in\s+scope|non[- ]?goals?)/i;
  const compatibilityContext = /(?:灰度|回滚|兼容|迁移|放量|降级|切换|新旧版本|旧版)/;
  const genericScope = /(?:(?:(?:其余|其他|剩余).{0,12}|.{0,12}(?:页面|页|接口|业务|调用方|路径|功能|模块|流程).{0,8})(?:保持(?:原样|不变)|没有变化|不受影响|不做调整|不调整|不动)|保持.{0,12}(?:其余|其他|剩余).{0,12}(?:原样|不变))/;
  const strongNamedScope = /.{0,12}(?:页面|页|接口|业务|调用方|路径|功能|模块|流程).{0,8}(?:没有变化|不受影响|不做调整|不调整|不动)/;
  const classifyClause = (clause) => {
    if (explicitScope.test(clause)) return clause;
    if (compatibilityContext.test(clause)) return "";
    if (role === "risk_release" || role === "unstructured") {
      return genericScope.test(clause) ? "非目标" : clause;
    }
    return strongNamedScope.test(clause) ? "非目标" : clause;
  };
  // 兼容/回滚事实只豁免自身子句，标点或常见连接词后的范围说明仍单独检查。
  return value.split("\n").map((line) => (
    line
      .replace(/(?:并且|同时|之后|且|并(?=.{0,24}(?:不受影响|不做调整|不调整|保持|没有变化|不动)))/g, "；")
      .match(/[^，,；;。！？!?：:—–-]+[，,；;。！？!?：:—–-]?/g) ?? [line]
  ).map(classifyClause).join("")).join("\n");
}

function verificationCandidate(item) {
  const role = typeof item === "string" ? "unstructured" : item.role;
  const value = typeof item === "string" ? item : item.value;
  if (role !== "change_description" && role !== "unstructured") return value;
  return value.split("\n").map((line) => {
    const normalized = line.trim()
      .replace(/^[-*]\s+/, "")
      .replace(/^#{1,6}\s+/, "")
      .replace(/^\*\*[^*]+\*\*[：:]?\s*/, "")
      .replace(/^\*[^*]+\*[：:]?\s*/, "");
    // 只移除能力变化子句，保留逗号或分号后的真实测试/CI 状态供验证结果门禁检查。
    const clauses = normalized
      .replace(/(?:并且|同时|之后|且|并(?=.{0,24}(?:CI|流水线|测试|单测|回归|通过|失败|运行)))/g, "；")
      .match(/[^，,；;。！？!?]+[，,；;。！？!?]?/g) ?? [normalized];
    return clauses.map((clause) => {
      const retrySubject = /(?:单测|单元测试|集成测试|端到端测试|e2e|测试|CI|流水线)/i.test(clause);
      const retryFailure = /失败/i.test(clause);
      const retryBehavior = /(?:重试|重跑)/i.test(clause);
      const capabilityChange = /(?:新增|调整|更新|支持|实现|修改|优化|自动|能力|机制|次数|策略|规则|配置|退避|上限|改为)/i.test(clause);
      const failureArtifactBehavior = /(?:失败测试|测试失败时|测试失败后).{0,24}(?:保留|归档|记录|收集|上传|发送|同步).{0,24}(?:日志|诊断|产物|结果|信息)/i.test(clause);
      if (retrySubject && retryFailure && retryBehavior && capabilityChange) return "";
      if (failureArtifactBehavior) return "";
      // “通过某渠道/机制执行动作”里的“通过”是介词，不是测试结论。
      return clause.replace(/通过(?=.{0,24}(?:注入|发送|同步|传递|写入|发布|上报))/g, (
        match,
        offset,
        source,
      ) => {
        const before = source.slice(0, offset);
        const after = source.slice(offset + match.length);
        const hasCompletedPrefix = /(?:均|全部|已经|已)$/.test(before);
        const startsWithBackendNoun = /^(?:后端|后台)/.test(after);
        const startsWithResultContinuation = /^(?:了|后(?!端|台)|[，,。；;且并])/.test(after);
        return !startsWithResultContinuation && (!hasCompletedPrefix || startsWithBackendNoun)
          ? "经由"
          : match;
      });
    }).join("");
  }).join("\n");
}

export function findForbiddenVisibleContent(values) {
  return [...new Set(FORBIDDEN_VISIBLE_PATTERNS
    .filter(([label, pattern]) => values.some(
      (item) => {
        const value = typeof item === "string" ? item : item?.value;
        if (typeof value !== "string") return false;
        const candidate = label === "代码审查 finding 或 verdict"
          ? findingCandidate(item)
          : label === "非目标说明"
            ? scopeCandidate(item)
            : label === "验证结果"
              ? verificationCandidate(item)
            : value;
        return pattern.test(candidate);
      },
    ))
    .map(([label]) => label))];
}

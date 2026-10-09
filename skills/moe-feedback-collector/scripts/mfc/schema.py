SCHEMA_VERSION = 17


def describe_schema():
    return {
        "schemaVersion": SCHEMA_VERSION,
        "storage": "wiki-weekly-documents",
        "wikiStructure": [
            "<年份>",
            "<月份>",
            "<YYYY-MM｜范围 反馈重点汇总>",
            "<ISO 周反馈总览｜范围>",
            "<Canny|Intercom|Jira|Facebook 来源看板>",
            "<分类与主题明细>",
        ],
        "dashboard": {
            "storage": "docx",
            "current": "月份目录下的周总看板是该周唯一入口",
            "history": "月份下按自然周并列归档",
            "sourceChildren": ["canny", "intercom", "jira", "facebook"],
            "analysisChildren": ["category"],
            "sourceStates": ["ready", "missing"],
            "formalCompleteness": (
                "四源均有入选数据 + AI analysis + 四个来源子看板；"
                "Canny 来源子看板包含来源专用 AI 复筛"
            ),
            "partialPolicy": "仅 --allow-partial --dry-run；缺失或 0 条来源不能正式发布",
            "totalPolicy": "来源入选数相加，跨来源未去重",
            "sections": [
                "周环比",
                "本周反馈概览",
                "产品/设计关注点",
                "Quick Win 候选",
                "原始证据",
            ],
            "readingLayers": {
                "parent": "关键指标、周环比摘要、七分类概览、最多三项产品关注点、Quick Win 分布与来源入口；长叙述收敛",
                "categoryChild": (
                    "完整周环比证据，以及各分类的主题、代表反馈、产品/设计动作、"
                    "可保留勾选状态的 Quick Win 候选和待复核项"
                ),
            },
            "legacySections": [
                "本周总览",
                "本周 AI 摘要",
                "跨渠道主题",
                "AI 洞察",
                "建议动作",
                "重点反馈",
                "源周报入口",
            ],
            "analysis": {
                "schemaVersion": 2,
                "evidencePolicy": "摘要、主题、洞察和建议全部引用本周已入选 evidenceId",
                "confidence": ["high", "medium", "low"],
            },
            "analysisInput": {
                "schemaVersion": 1,
                "command": "analysis-input",
                "currentRecords": "只包含本周四源已入选且已脱敏的归一化 evidence",
                "excludedFields": [
                    "quickWinSelected",
                    "businessCategory",
                    "auxiliaryCategories",
                    "classificationConfidence",
                ],
                "previousBaseline": (
                    "只读取紧邻上周已校验并发布的 v3 baselineExport；"
                    "不重新读取或分类上周原始 records"
                ),
                "ruleVersion": "grooming-weekly-analysis-v4",
            },
            "analysisBuild": {
                "promptCommand": "analysis-prompt",
                "buildCommand": "analysis-build",
                "modelOutputSchemaVersion": 1,
                "finalSchemaVersion": 3,
                "modelBinding": "由 Agent 调用当前可用模型，Collector 不绑定模型厂商",
                "deterministicFields": [
                    "categoryOverview",
                    "reviewQueue",
                    "comparisonBaseline",
                    "baselineExport",
                ],
                "othersPolicy": "AI 不得确认；仅独立人工复核可以确认",
                "quickWin": {
                    "coverage": "逐条覆盖本周四源全部 records",
                    "criteria": ["诉求明确", "范围集中", "预估改动较小"],
                    "grouping": "通过标准的 evidence 按同一用户任务做跨源语义归并",
                    "cannyEngagement": "Vote 与评论仅作热度证据，不是准入门槛",
                },
            },
            "ruleVersion": "cross-source-dashboard-v10",
        },
        "weeklyDocument": {
            "sections": ["本周概览", "Quick Win 候选", "Canny 源数据"],
            "sourcePolicy": {
                "firstRun": "只展示周期内新增；全量基线仅保存在本地状态",
                "laterRuns": "只展示本期新增及 Vote、评论、状态或正文变化",
            },
            "quickWin": {
                "prefilter": [
                    "Vote >= 3",
                    "Vote delta >= 5",
                    "Comment delta >= 3",
                ],
                "aiReview": "诉求明确、范围集中、预估改动较小",
                "label": "Quick Win 候选，待产品/工程确认",
                "ruleVersion": "canny-qw-v2",
            },
        },
        "sources": {
            "canny": {
                "collection": "全量基线 + 周度新增与变化",
                "publish": "Quick Win 候选与源数据周报",
            },
            "intercom": {
                "collection": "Datadog Actions Datastore 周期快照",
                "publish": {
                    "sections": ["本周概览", "功能反馈", "功能需求"],
                    "squadConfig": "MFC_SQUAD",
                    "squadMatch": "case-insensitive exact",
                    "feedbackTypes": ["feature_feedback", "feature_request"],
                    "ruleVersion": "intercom-squad-features-v1",
                },
                "forbiddenFields": ["email", "conversation_id", "quote"],
            },
            "jira": {
                "collection": "Jira skill 的 CS 周期快照",
                "publish": {
                    "sections": [
                        "本周概览",
                        "功能需求",
                        "关联设计单反馈",
                        "待人工复核",
                    ],
                    "squadConfig": "MFC_SQUAD",
                    "scope": {
                        "strongSignals": [
                            "Squad case-insensitive exact",
                            "Summary explicit Grooming/groomer semantics",
                        ],
                        "weakSignals": "shared Components -> manual review",
                        "exclusions": "explicit non-Grooming service semantics",
                    },
                    "selection": {
                        "project": "CS",
                        "featureRequestIssueType": "Feature Request",
                        "designTarget": {
                            "project": "DES",
                            "issueType": "Design Issue",
                        },
                    },
                    "businessCategories": [
                        "scheduling",
                        "fulfillment",
                        "communication",
                        "management",
                        "payment",
                        "van-staff-shift-management",
                        "others",
                    ],
                    "ruleVersion": "jira-grooming-journey-v2",
                },
                "forbiddenFields": [
                    "description",
                    "comments",
                    "attachments",
                    "reporter",
                    "customerEmail",
                    "intercom",
                ],
            },
            "facebook": {
                "collection": "Slack #community-pending-posts 周期快照",
                "feeds": [
                    "group_post",
                    "campaign_comment_summary",
                    "group_comment_summary",
                ],
                "domainConfig": "MFC_DOMAIN",
                "channelConfig": "MFC_FACEBOOK_SLACK_CHANNEL",
                "coverage": "channel-summary",
                "publish": {
                    "sections": ["本周概览", "频道汇总反馈", "口径说明"],
                    "parent": "同周期周总看板",
                    "ruleVersion": "facebook-channel-summary-v1",
                },
                "forbiddenFields": [
                    "emailHtml",
                    "emailRecipient",
                    "emailSender",
                    "trackingUrl",
                ],
            },
        },
        "monthlyDocument": {
            "storage": "docx",
            "command": "monthly-dashboard",
            "auditCommand": "monthly-audit",
            "analysisCommands": [
                "monthly-analysis-input",
                "monthly-analysis-prompt",
                "monthly-analysis-build",
            ],
            "sections": [
                "本月结论",
                "本月最重要的三件事",
                "周度脉络",
                "分类与 Quick Win",
                "周报入口与口径",
            ],
            "coverage": "默认自然月完整覆盖；显式月末覆盖例外必须公开列出",
            "aggregation": "只汇总已托管周总览与 weekly-analysis v3，不复制四源长正文",
            "deduplication": {
                "crossSource": False,
                "crossWeek": False,
            },
            "managedMarker": "MFC_MANAGED_MONTHLY_V1",
            "ruleVersion": "grooming-monthly-analysis-v2",
        },
        "yearlyDocument": "年份索引，不复制月度或周源数据",
        "larkRole": "总看板、来源周报与历史归档，不作为规则配置后台",
        "secretsInLark": False,
    }

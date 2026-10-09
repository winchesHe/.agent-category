from __future__ import annotations

import sys
import unittest
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from mfc.errors import BusinessError, TimeoutError as MfcTimeoutError
from mfc.dashboard import DASHBOARD_DETAIL_MARKER
from mfc.lark import LarkWeeklyPublisher
from mfc.report import INTERCOM_MANAGED_CHILD_MARKER


class LarkPublisherTests(unittest.TestCase):
    def _complete_source_reports(self):
        return [
            {
                "sourceKey": "canny",
                "status": "ready",
                "included": 1,
                "reportTitle": "2026-W34｜08.17–08.23｜Canny 用户反馈",
                "markers": ["Canny 用户反馈", "Quick Win 候选", "Canny 源数据"],
                "managedMarker": "managed-canny",
            },
            {
                "sourceKey": "intercom",
                "status": "ready",
                "included": 1,
                "reportTitle": "2026-W34｜08.17–08.23｜Intercom 用户反馈｜Grooming",
                "markers": [],
                "managedMarker": "managed-intercom",
            },
            {
                "sourceKey": "jira",
                "status": "ready",
                "included": 1,
                "reportTitle": "2026-W34｜08.17–08.23｜Jira CS 反馈｜Grooming",
                "markers": [],
                "managedMarker": "managed-jira",
            },
            {
                "sourceKey": "facebook",
                "status": "ready",
                "included": 1,
                "reportTitle": "2026-W34｜08.17–08.23｜Facebook Community｜grooming",
                "markers": [],
                "managedMarker": "managed-facebook",
            },
        ]

    def test_stale_managed_children_are_cleared_without_touching_other_docs(self):
        publisher = object.__new__(LarkWeeklyPublisher)
        publisher._list_children = Mock(
            return_value=[
                {
                    "title": "Intercom｜Grooming｜功能需求｜1-100",
                    "obj_type": "docx",
                    "obj_token": "current",
                },
                {
                    "title": "Intercom｜Grooming｜功能需求｜101-150",
                    "obj_type": "docx",
                    "obj_token": "stale",
                },
                {
                    "title": "人工说明",
                    "obj_type": "docx",
                    "obj_token": "manual",
                },
            ]
        )
        publisher._fetch = Mock(
            side_effect=[
                f"<p>{INTERCOM_MANAGED_CHILD_MARKER}</p><p>旧数据</p>",
                f"<p>{INTERCOM_MANAGED_CHILD_MARKER}</p><p>本页已失效</p>",
            ]
        )
        publisher._overwrite = Mock()

        retired = publisher._retire_stale_child_documents(
            {"node_token": "week"},
            expected_titles={"Intercom｜Grooming｜功能需求｜1-100"},
            managed_child_prefix="Intercom｜Grooming｜",
            managed_child_marker=INTERCOM_MANAGED_CHILD_MARKER,
        )

        self.assertEqual(["Intercom｜Grooming｜功能需求｜101-150"], retired)
        publisher._overwrite.assert_called_once()
        self.assertEqual("stale", publisher._overwrite.call_args.args[0])
        self.assertIn("本页已失效", publisher._overwrite.call_args.args[1])
        self.assertNotIn("旧数据", publisher._overwrite.call_args.args[1])

    def test_unmarked_child_with_managed_prefix_is_not_modified(self):
        publisher = object.__new__(LarkWeeklyPublisher)
        publisher._list_children = Mock(
            return_value=[
                {
                    "title": "Intercom｜Grooming｜人工页",
                    "obj_type": "docx",
                    "obj_token": "manual",
                }
            ]
        )
        publisher._fetch = Mock(return_value="<p>人工内容</p>")
        publisher._overwrite = Mock()

        retired = publisher._retire_stale_child_documents(
            {"node_token": "week"},
            expected_titles=set(),
            managed_child_prefix="Intercom｜Grooming｜",
            managed_child_marker=INTERCOM_MANAGED_CHILD_MARKER,
        )

        self.assertEqual([], retired)
        publisher._overwrite.assert_not_called()

    def test_dashboard_links_only_current_managed_source_reports(self):
        publisher = object.__new__(LarkWeeklyPublisher)
        publisher.config = SimpleNamespace(
            wiki_url="https://mengshikeji.feishu.cn/wiki/root"
        )
        publisher.root = {"nodeToken": "root", "spaceId": "space"}
        year_node = {"node_token": "year-node", "obj_token": "year-doc"}
        month_node = {"node_token": "month-node", "obj_token": "month-doc"}
        week_node = {"node_token": "week-node", "obj_token": "week-doc"}
        publisher._find_doc_node = Mock(side_effect=[year_node, month_node, week_node])
        publisher._list_children = Mock(
            return_value=[
                {
                    "title": item["reportTitle"],
                    "obj_type": "docx",
                    "obj_token": f"{item['sourceKey']}-doc",
                    "node_token": f"{item['sourceKey']}-node",
                }
                for item in self._complete_source_reports()
            ]
        )
        publisher._overwrite = Mock()
        publisher._fetch = Mock(
            side_effect=[
                "由 Moe Feedback Collector 自动生成的全渠道反馈总看板。",
                "managed-canny",
                "managed-intercom",
                "managed-jira",
                "managed-facebook",
                "周标题 自动标记 本周总览 源周报入口",
            ]
        )

        result = publisher.publish_dashboard(
            year_title="2026",
            month_title="08",
            week_title="2026-W34｜08.17–08.23｜Grooming 反馈总览",
            content="<title>周标题</title><p>__SOURCE_REPORTS__</p>",
            markers=["周标题", "自动标记", "本周总览", "源周报入口"],
            managed_marker="由 Moe Feedback Collector 自动生成的全渠道反馈总看板。",
            source_reports=self._complete_source_reports(),
        )

        self.assertTrue(result["verified"])
        self.assertEqual("canny-doc", result["linkedSourceReports"]["canny"]["documentToken"])
        self.assertEqual([], result["missingSourceReports"])
        weekly_content = publisher._overwrite.call_args.args[1]
        self.assertIn('doc-id="canny-doc"', weekly_content)
        self.assertIn('doc-id="facebook-doc"', weekly_content)

    def test_dashboard_publishes_managed_detail_children_and_links_them(self):
        publisher = object.__new__(LarkWeeklyPublisher)
        publisher.config = SimpleNamespace(
            wiki_url="https://mengshikeji.feishu.cn/wiki/root"
        )
        publisher.root = {"nodeToken": "root", "spaceId": "space"}
        year_node = {"node_token": "year-node", "obj_token": "year-doc"}
        month_node = {"node_token": "month-node", "obj_token": "month-doc"}
        week_node = {"node_token": "week-node", "obj_token": "week-doc"}
        category_node = {
            "title": "2026-W34｜分类与主题明细",
            "node_token": "category-node",
            "obj_token": "category-doc",
            "obj_type": "docx",
        }
        quick_win_node = {
            "title": "2026-W34｜Quick Win 候选清单",
            "node_token": "quick-win-node",
            "obj_token": "quick-win-doc",
            "obj_type": "docx",
        }
        source_nodes = [
            {
                "title": item["reportTitle"],
                "obj_type": "docx",
                "obj_token": f"{item['sourceKey']}-doc",
                "node_token": f"{item['sourceKey']}-node",
            }
            for item in self._complete_source_reports()
        ]
        category_owner = "managed-category"
        quick_win_owner = "managed-quick-win"
        store = {
            "week-doc": "自动标记",
            "canny-doc": "managed-canny",
            "intercom-doc": "managed-intercom",
            "jira-doc": "managed-jira",
            "facebook-doc": "managed-facebook",
            "category-doc": f"{DASHBOARD_DETAIL_MARKER} {category_owner}",
            "quick-win-doc": (
                f"{DASHBOARD_DETAIL_MARKER} {quick_win_owner}"
                '<checkbox done="true">[QW-AAAAAAAA] 已选择候选</checkbox>'
            ),
        }
        publisher._find_doc_node = Mock(
            side_effect=[
                year_node,
                month_node,
                week_node,
                category_node,
                category_node,
            ]
        )
        publisher._list_children = Mock(
            return_value=[*source_nodes, category_node, quick_win_node]
        )
        publisher._fetch = Mock(side_effect=lambda token: store[token])
        timed_out = {"category-doc": False}

        def overwrite(token, child_content):
            store[token] = child_content
            if token == "category-doc" and not timed_out[token]:
                timed_out[token] = True
                raise MfcTimeoutError("结果未知")

        publisher._overwrite = Mock(side_effect=overwrite)
        detail_documents = [
            {
                "key": "category",
                "title": category_node["title"],
                "placeholder": "<p>__CATEGORY_DETAIL_REPORT__</p>",
                "content": (
                    f"<title>{category_node['title']}</title>"
                    f"<p>{DASHBOARD_DETAIL_MARKER}</p><p>{category_owner}</p>"
                    "<h2>Quick Win 候选</h2>"
                    '<checkbox done="false">[QW-AAAAAAAA] 已选择候选</checkbox>'
                    '<checkbox done="false">[QW-BBBBBBBB] 新候选</checkbox>'
                    "<p>__SOURCE_REPORTS__</p>"
                ),
                "ownershipMarker": category_owner,
                "markers": [
                    DASHBOARD_DETAIL_MARKER,
                    category_owner,
                    "Quick Win 候选",
                ],
            },
        ]

        result = publisher.publish_dashboard(
            year_title="2026",
            month_title="08",
            week_title="2026-W34｜08.17–08.23｜Grooming 反馈总览",
            content=(
                "<title>周标题</title><p>自动标记</p>"
                "<p>__CATEGORY_DETAIL_REPORT__</p>"
                "<p>__CATEGORY_DETAIL_REPORT__</p>"
                "<p>__SOURCE_REPORTS__</p>"
            ),
            markers=["周标题", "自动标记"],
            managed_marker="自动标记",
            source_reports=self._complete_source_reports(),
            child_documents=detail_documents,
            managed_child_marker=DASHBOARD_DETAIL_MARKER,
        )

        self.assertEqual("category-doc", result["linkedDetailDocuments"]["category"]["documentToken"])
        self.assertEqual(2, store["week-doc"].count('doc-id="category-doc"'))
        self.assertNotIn('doc-id="quick-win-doc"', store["week-doc"])
        self.assertNotIn("__CATEGORY_DETAIL_REPORT__", store["week-doc"])
        self.assertNotIn("__SOURCE_REPORTS__", store["category-doc"])
        self.assertIn('doc-id="canny-doc"', store["category-doc"])
        self.assertIn('doc-id="facebook-doc"', store["category-doc"])
        self.assertIn(
            '<checkbox done="true">[QW-AAAAAAAA]', store["category-doc"]
        )
        self.assertIn(
            '<checkbox done="false">[QW-BBBBBBBB]', store["category-doc"]
        )
        self.assertEqual(["QW-AAAAAAAA"], result["preservedCheckedQuickWinIds"])
        self.assertEqual(
            [quick_win_node["title"]],
            [item["title"] for item in result["staleManagedDetailDocuments"]],
        )

    def test_dashboard_detail_pending_node_can_be_recovered_after_interruption(self):
        publisher = object.__new__(LarkWeeklyPublisher)
        pending_node = {
            "title": "pending",
            "node_token": "pending-node",
            "obj_token": "pending-doc",
        }
        publisher._find_doc_node = Mock(return_value=None)
        publisher._ensure_doc_node = Mock(return_value=(pending_node, False))

        title = "2026-W34｜分类与主题明细"
        ownership_marker = "managed-category"
        identity = sha256(
            f"{title}\0{ownership_marker}".encode("utf-8")
        ).hexdigest()[:12]
        publisher._fetch = Mock(
            return_value=(
                f"{DASHBOARD_DETAIL_MARKER} {ownership_marker} "
                f"MFC_PENDING_DASHBOARD_DETAIL_V1|identity={identity}"
            )
        )

        node, created, needs_rename = publisher._prepare_dashboard_detail_node(
            "week-node",
            title=title,
            ownership_marker=ownership_marker,
            managed_child_marker=DASHBOARD_DETAIL_MARKER,
        )

        self.assertEqual(pending_node, node)
        self.assertFalse(created)
        self.assertTrue(needs_rename)
        pending_title = publisher._ensure_doc_node.call_args.args[1]
        self.assertRegex(
            pending_title,
            r"^2026-W34｜分类与主题明细｜MFC-pending-[0-9a-f]{12}$",
        )

    def test_ensure_doc_node_recovers_create_that_committed_before_timeout(self):
        publisher = object.__new__(LarkWeeklyPublisher)
        recovered = {
            "title": "pending",
            "node_token": "pending-node",
            "obj_token": "pending-doc",
        }
        publisher._find_doc_node = Mock(side_effect=[None, recovered])
        publisher._run = Mock(
            side_effect=[{"ok": True}, MfcTimeoutError("创建结果未知")]
        )

        node, created = publisher._ensure_doc_node(
            "week-node", "pending", recover_timeout=True
        )

        self.assertEqual(recovered, node)
        self.assertTrue(created)

    def test_ensure_doc_node_does_not_recover_timeout_for_generic_callers(self):
        publisher = object.__new__(LarkWeeklyPublisher)
        publisher._find_doc_node = Mock(return_value=None)
        publisher._run = Mock(
            side_effect=[{"ok": True}, MfcTimeoutError("创建结果未知")]
        )

        with self.assertRaisesRegex(MfcTimeoutError, "创建结果未知"):
            publisher._ensure_doc_node("week-node", "source-page")

        publisher._find_doc_node.assert_called_once_with("week-node", "source-page")

    def test_dashboard_detail_claims_blank_pending_after_process_exit(self):
        publisher = object.__new__(LarkWeeklyPublisher)
        title = "2026-W34｜分类与主题明细"
        identity = sha256(
            f"{title}\0managed-category".encode("utf-8")
        ).hexdigest()[:12]
        pending_title = f"{title}｜MFC-pending-{identity}"
        pending_node = {
            "title": pending_title,
            "node_token": "pending-node",
            "obj_token": "pending-doc",
        }
        publisher._find_doc_node = Mock(return_value=None)
        publisher._ensure_doc_node = Mock(return_value=(pending_node, False))
        publisher._fetch = Mock(return_value=f"<title>{pending_title}</title>")
        publisher._overwrite = Mock()

        node, created, needs_rename = publisher._prepare_dashboard_detail_node(
            "week-node",
            title=title,
            ownership_marker="managed-category",
            managed_child_marker=DASHBOARD_DETAIL_MARKER,
        )

        self.assertEqual(pending_node, node)
        self.assertFalse(created)
        self.assertTrue(needs_rename)
        self.assertIn(
            "MFC_PENDING_DASHBOARD_DETAIL_V1",
            publisher._overwrite.call_args.args[1],
        )

    def test_dashboard_detail_rechecks_unmanaged_node_created_after_preflight(self):
        publisher = object.__new__(LarkWeeklyPublisher)
        manual_node = {
            "title": "2026-W34｜分类与主题明细",
            "node_token": "manual-node",
            "obj_token": "manual-doc",
        }
        publisher._find_doc_node = Mock(return_value=manual_node)
        publisher._fetch = Mock(return_value="人工内容")
        publisher._ensure_doc_node = Mock()

        with self.assertRaisesRegex(BusinessError, "不是 Collector 托管文档"):
            publisher._prepare_dashboard_detail_node(
                "week-node",
                title=manual_node["title"],
                ownership_marker="managed-category",
                managed_child_marker=DASHBOARD_DETAIL_MARKER,
            )

        publisher._ensure_doc_node.assert_not_called()

    def test_dashboard_detail_refuses_unclaimed_pending_node(self):
        publisher = object.__new__(LarkWeeklyPublisher)
        pending_node = {
            "title": "pending",
            "node_token": "pending-node",
            "obj_token": "pending-doc",
        }
        publisher._find_doc_node = Mock(return_value=None)
        publisher._ensure_doc_node = Mock(return_value=(pending_node, False))
        publisher._fetch = Mock(return_value="人工编辑内容")

        with self.assertRaisesRegex(BusinessError, "pending.*不是 Collector"):
            publisher._prepare_dashboard_detail_node(
                "week-node",
                title="2026-W34｜分类与主题明细",
                ownership_marker="managed-category",
                managed_child_marker=DASHBOARD_DETAIL_MARKER,
            )

    def test_dashboard_detail_does_not_treat_non_text_blocks_as_blank(self):
        title = "2026-W34｜分类与主题明细"
        identity = sha256(
            f"{title}\0managed-category".encode("utf-8")
        ).hexdigest()[:12]
        pending_title = f"{title}｜MFC-pending-{identity}"
        content = (
            f"<title>{pending_title}</title>"
            '<whiteboard token="human-board"></whiteboard>'
        )

        self.assertFalse(
            LarkWeeklyPublisher._is_blank_pending_content(content, pending_title)
        )

        publisher = object.__new__(LarkWeeklyPublisher)
        pending_node = {
            "title": pending_title,
            "node_token": "pending-node",
            "obj_token": "pending-doc",
        }
        publisher._find_doc_node = Mock(return_value=None)
        publisher._ensure_doc_node = Mock(return_value=(pending_node, True))
        publisher._fetch = Mock(return_value=content)
        publisher._overwrite = Mock()
        with self.assertRaisesRegex(BusinessError, "pending.*不是 Collector"):
            publisher._prepare_dashboard_detail_node(
                "week-node",
                title=title,
                ownership_marker="managed-category",
                managed_child_marker=DASHBOARD_DETAIL_MARKER,
            )
        publisher._overwrite.assert_not_called()

    def test_dashboard_detail_does_not_swallow_failed_or_uncommitted_overwrite(self):
        publisher = object.__new__(LarkWeeklyPublisher)
        publisher._fetch = Mock(return_value="old managed content")

        publisher._overwrite = Mock(side_effect=BusinessError("确定性失败"))
        with self.assertRaisesRegex(BusinessError, "确定性失败"):
            publisher._overwrite_with_attempt_marker(
                "detail-doc", "new content", "attempt-new"
            )

        publisher._overwrite = Mock(side_effect=MfcTimeoutError("结果未知"))
        with self.assertRaisesRegex(MfcTimeoutError, "结果未知"):
            publisher._overwrite_with_attempt_marker(
                "detail-doc", "new content", "attempt-new"
            )

    def test_dashboard_detail_updates_wiki_node_title_with_documented_api(self):
        publisher = object.__new__(LarkWeeklyPublisher)
        publisher.root = {"spaceId": "space-id"}
        publisher._run = Mock(return_value={"ok": True})

        publisher._update_wiki_node_title(
            "week-node", "pending-node", "2026-W34｜分类与主题明细"
        )

        self.assertEqual(2, publisher._run.call_count)
        command = publisher._run.call_args_list[1].args[0]
        self.assertEqual("api", command[0])
        self.assertEqual("POST", command[1])
        self.assertEqual(
            "/open-apis/wiki/v2/spaces/space-id/nodes/pending-node/update_title",
            command[2],
        )

    def test_dashboard_first_detail_publish_claims_writes_and_renames_pending_node(self):
        publisher = object.__new__(LarkWeeklyPublisher)
        publisher.config = SimpleNamespace(
            wiki_url="https://mengshikeji.feishu.cn/wiki/root"
        )
        publisher.root = {"nodeToken": "root", "spaceId": "space"}
        year_node = {"node_token": "year-node", "obj_token": "year-doc"}
        month_node = {"node_token": "month-node", "obj_token": "month-doc"}
        week_node = {"node_token": "week-node", "obj_token": "week-doc"}
        pending_node = {
            "title": "pending",
            "node_token": "detail-node",
            "obj_token": "detail-doc",
        }
        final_node = dict(
            pending_node,
            title="2026-W34｜分类与主题明细",
        )
        source_nodes = [
            {
                "title": item["reportTitle"],
                "obj_type": "docx",
                "obj_token": f"{item['sourceKey']}-doc",
                "node_token": f"{item['sourceKey']}-node",
            }
            for item in self._complete_source_reports()
        ]
        store = {
            "week-doc": "自动标记",
            **{
                f"{item['sourceKey']}-doc": item["managedMarker"]
                for item in self._complete_source_reports()
            },
            "detail-doc": "",
        }
        publisher._find_doc_node = Mock(
            side_effect=[year_node, month_node, week_node, None, final_node]
        )
        publisher._list_children = Mock(return_value=source_nodes)
        publisher._ensure_doc_node = Mock(return_value=(pending_node, True))
        publisher._fetch = Mock(side_effect=lambda token: store[token])
        publisher._overwrite = Mock(
            side_effect=lambda token, value: store.__setitem__(token, value)
        )
        publisher._update_wiki_node_title = Mock()
        detail = {
            "key": "category",
            "title": final_node["title"],
            "placeholder": "<p>__CATEGORY_DETAIL_REPORT__</p>",
            "content": (
                f"<title>{final_node['title']}</title>"
                f"<p>{DASHBOARD_DETAIL_MARKER}</p><p>managed-category</p>"
                "<h1>分类导航</h1>"
            ),
            "ownershipMarker": "managed-category",
            "markers": [DASHBOARD_DETAIL_MARKER, "managed-category", "分类导航"],
        }

        result = publisher.publish_dashboard(
            year_title="2026",
            month_title="08",
            week_title="2026-W34｜Grooming 反馈总览",
            content=(
                "<title>周标题</title><p>自动标记</p>"
                "<p>__CATEGORY_DETAIL_REPORT__</p><p>__SOURCE_REPORTS__</p>"
            ),
            markers=["周标题", "自动标记"],
            managed_marker="自动标记",
            source_reports=self._complete_source_reports(),
            child_documents=[detail],
            managed_child_marker=DASHBOARD_DETAIL_MARKER,
        )

        self.assertTrue(result["verified"])
        publisher._update_wiki_node_title.assert_called_once_with(
            "week-node", "detail-node", final_node["title"]
        )
        self.assertIn("MFC_PENDING_DASHBOARD_DETAIL_V1", publisher._overwrite.call_args_list[0].args[1])
        self.assertIn("MFC_DETAIL_CONTENT_SHA256", store["detail-doc"])
        self.assertIn("MFC_PENDING_DASHBOARD_DETAIL_V1", store["detail-doc"])

    def test_dashboard_refuses_unmanaged_existing_detail_before_writes(self):
        publisher = object.__new__(LarkWeeklyPublisher)
        publisher.root = {"nodeToken": "root", "spaceId": "space"}
        year_node = {"node_token": "year", "obj_token": "year-doc"}
        month_node = {"node_token": "month", "obj_token": "month-doc"}
        week_node = {"node_token": "week", "obj_token": "week-doc"}
        manual_detail = {
            "title": "2026-W34｜分类与主题明细",
            "obj_type": "docx",
            "obj_token": "manual-detail",
            "node_token": "manual-node",
        }
        source_nodes = [
            {
                "title": item["reportTitle"],
                "obj_type": "docx",
                "obj_token": f"{item['sourceKey']}-doc",
                "node_token": f"{item['sourceKey']}-node",
            }
            for item in self._complete_source_reports()
        ]
        store = {
            "week-doc": "自动标记",
            "canny-doc": "managed-canny",
            "intercom-doc": "managed-intercom",
            "jira-doc": "managed-jira",
            "facebook-doc": "managed-facebook",
            "manual-detail": "人工内容",
        }
        publisher._find_doc_node = Mock(side_effect=[year_node, month_node, week_node])
        publisher._list_children = Mock(return_value=[*source_nodes, manual_detail])
        publisher._fetch = Mock(side_effect=lambda token: store[token])
        publisher._overwrite = Mock()

        with self.assertRaisesRegex(BusinessError, "不是 Collector 托管文档"):
            publisher.publish_dashboard(
                year_title="2026",
                month_title="08",
                week_title="2026-W34｜Grooming 反馈总览",
                content=(
                    "<title>周标题</title><p>__CATEGORY_DETAIL_REPORT__</p>"
                    "<p>__SOURCE_REPORTS__</p>"
                ),
                markers=["周标题"],
                managed_marker="自动标记",
                source_reports=self._complete_source_reports(),
                child_documents=[
                    {
                        "key": "category",
                        "title": manual_detail["title"],
                        "placeholder": "<p>__CATEGORY_DETAIL_REPORT__</p>",
                        "content": (
                            f"<p>{DASHBOARD_DETAIL_MARKER}</p><p>managed-category</p>"
                        ),
                        "ownershipMarker": "managed-category",
                        "markers": [DASHBOARD_DETAIL_MARKER],
                    }
                ],
                managed_child_marker=DASHBOARD_DETAIL_MARKER,
            )
        publisher._overwrite.assert_not_called()

    def test_dashboard_refuses_missing_or_empty_source_before_writes(self):
        publisher = object.__new__(LarkWeeklyPublisher)
        publisher._find_doc_node = Mock()

        with self.assertRaisesRegex(BusinessError, "四个已就绪来源：facebook"):
            publisher.publish_dashboard(
                year_title="2026",
                month_title="08",
                week_title="2026-W34｜Grooming 反馈总览",
                content="<title>周标题</title>",
                markers=["周标题"],
                managed_marker="自动标记",
                source_reports=self._complete_source_reports()[:3],
            )
        publisher._find_doc_node.assert_not_called()

        reports = self._complete_source_reports()
        reports[2]["included"] = 0
        with self.assertRaisesRegex(BusinessError, "必须有入选数据：jira"):
            publisher.publish_dashboard(
                year_title="2026",
                month_title="08",
                week_title="2026-W34｜Grooming 反馈总览",
                content="<title>周标题</title>",
                markers=["周标题"],
                managed_marker="自动标记",
                source_reports=reports,
            )
        publisher._find_doc_node.assert_not_called()

        publisher._find_doc_node = Mock(return_value=None)
        publisher.root = {"nodeToken": "root"}
        with self.assertRaisesRegex(BusinessError, "缺少年份目录"):
            publisher.publish_dashboard(
                year_title="2026",
                month_title="08",
                week_title="2026-W31｜Grooming 反馈总览",
                content="<title>周标题</title>",
                markers=["周标题"],
                managed_marker="自动标记",
                source_reports=reports,
                allow_empty_sources=True,
            )
        publisher._find_doc_node.assert_called_once()

    def test_dashboard_refuses_when_ready_source_report_is_absent(self):
        publisher = object.__new__(LarkWeeklyPublisher)
        publisher.config = SimpleNamespace(
            wiki_url="https://mengshikeji.feishu.cn/wiki/root"
        )
        publisher.root = {"nodeToken": "root", "spaceId": "space"}
        publisher._find_doc_node = Mock(
            side_effect=[
                {"node_token": "year", "obj_token": "year-doc"},
                {"node_token": "month", "obj_token": "month-doc"},
                {"node_token": "week", "obj_token": "week-doc"},
            ]
        )
        publisher._fetch = Mock(return_value="自动标记")
        publisher._list_children = Mock(return_value=[])
        publisher._overwrite = Mock()

        with self.assertRaisesRegex(BusinessError, "缺少来源子看板：canny"):
            publisher.publish_dashboard(
                year_title="2026",
                month_title="08",
                week_title="2026-W34｜Grooming 反馈总览",
                content="<title>周标题</title><p>__SOURCE_REPORTS__</p>",
                markers=["周标题"],
                managed_marker="自动标记",
                source_reports=self._complete_source_reports(),
            )
        publisher._overwrite.assert_not_called()

    def test_dashboard_refuses_to_overwrite_unmanaged_existing_document(self):
        publisher = object.__new__(LarkWeeklyPublisher)
        publisher.root = {"nodeToken": "root", "spaceId": "space"}
        publisher._find_doc_node = Mock(
            side_effect=[
                {"node_token": "year", "obj_token": "year-doc"},
                {"node_token": "month", "obj_token": "month-doc"},
                {"node_token": "week", "obj_token": "week-doc"},
            ]
        )
        publisher._fetch = Mock(return_value="人工维护内容")
        publisher._overwrite = Mock()

        with self.assertRaisesRegex(BusinessError, "不是 Collector 托管文档"):
            publisher.publish_dashboard(
                year_title="2026",
                month_title="08",
                week_title="2026-W34｜Grooming 反馈总览",
                content="<title>周标题</title>",
                markers=[],
                managed_marker="自动标记",
                source_reports=self._complete_source_reports(),
            )
        publisher._overwrite.assert_not_called()

    def test_dashboard_rejects_stale_source_page_before_overwrite(self):
        publisher = object.__new__(LarkWeeklyPublisher)
        publisher.root = {"nodeToken": "root", "spaceId": "space"}
        publisher._find_doc_node = Mock(
            side_effect=[
                {"node_token": "year", "obj_token": "year-doc"},
                {"node_token": "month", "obj_token": "month-doc"},
                {"node_token": "week", "obj_token": "week-doc"},
            ]
        )
        publisher._list_children = Mock(
            return_value=[
                {
                    "title": item["reportTitle"],
                    "obj_type": "docx",
                    "obj_token": f"{item['sourceKey']}-doc",
                    "node_token": f"{item['sourceKey']}-node",
                }
                for item in self._complete_source_reports()
            ]
        )
        publisher._fetch = Mock(
            side_effect=[
                "自动标记",
                "managed-canny",
                "旧的 intercom run",
            ]
        )
        publisher._overwrite = Mock()

        with self.assertRaisesRegex(BusinessError, "manifest 不一致：intercom"):
            publisher.publish_dashboard(
                year_title="2026",
                month_title="08",
                week_title="2026-W34｜Grooming 反馈总览",
                content="<title>周标题</title><p>__SOURCE_REPORTS__</p>",
                markers=["周标题"],
                managed_marker="自动标记",
                source_reports=self._complete_source_reports(),
            )
        publisher._overwrite.assert_not_called()

    def test_source_publish_refuses_unmanaged_same_title_before_writes(self):
        publisher = object.__new__(LarkWeeklyPublisher)
        publisher.root = {"nodeToken": "root", "spaceId": "space"}
        year = {"node_token": "year", "obj_token": "year-doc"}
        month = {"node_token": "month", "obj_token": "month-doc"}
        week = {"node_token": "week", "obj_token": "week-doc"}
        source = {"node_token": "source", "obj_token": "source-doc"}
        publisher._find_doc_node = Mock(
            side_effect=[year, month, week, source, None]
        )
        publisher._fetch = Mock(side_effect=["周托管标记", "人工维护内容"])
        publisher._ensure_doc_node = Mock()
        publisher._overwrite = Mock()
        publisher._move_node = Mock()

        with self.assertRaisesRegex(BusinessError, "来源页不是 Collector 托管文档"):
            publisher.publish(
                year_title="2026",
                month_title="08",
                week_container_title="2026-W34｜Grooming 反馈总览",
                source_title="2026-W34｜Canny 用户反馈",
                content="<title>来源</title>",
                markers=["managed-run"],
                managed_week_marker="周托管标记",
                source_marker="managed-owner|runId=new",
                source_ownership_marker="managed-owner",
            )
        publisher._ensure_doc_node.assert_not_called()
        publisher._overwrite.assert_not_called()
        publisher._move_node.assert_not_called()

    def test_monthly_publish_requires_exact_hash_to_adopt_existing_page(self):
        publisher = object.__new__(LarkWeeklyPublisher)
        publisher.config = SimpleNamespace(
            wiki_url="https://mengshikeji.feishu.cn/wiki/root"
        )
        publisher.root = {"nodeToken": "root", "spaceId": "space"}
        year = {"node_token": "year", "obj_token": "year-doc"}
        month = {"node_token": "month", "obj_token": "month-doc"}
        week = {
            "title": "2026-W32｜08.03–08.09｜Grooming 反馈总览",
            "node_token": "week-node",
            "obj_token": "week-doc",
            "obj_type": "docx",
        }
        monthly = {
            "title": "2026-08｜Grooming 反馈重点汇总",
            "node_token": "monthly-node",
            "obj_token": "monthly-doc",
            "obj_type": "docx",
        }
        publisher._find_doc_node = Mock(side_effect=[year, month])
        publisher._list_children = Mock(return_value=[week, monthly])
        publisher._fetch = Mock(side_effect=["周托管标记", "人工月报"])
        publisher._overwrite = Mock()

        with self.assertRaisesRegex(BusinessError, "不是 Collector 托管文档"):
            publisher.publish_monthly(
                year_title="2026",
                month_title="08",
                title=monthly["title"],
                content="<title>月报</title><p>月度标记</p>",
                markers=["月报"],
                monthly_marker="月度标记",
                weekly_marker="周托管标记",
                weekly_pages=[
                    {
                        "title": week["title"],
                        "nodeToken": week["node_token"],
                        "documentToken": week["obj_token"],
                    }
                ],
            )
        publisher._overwrite.assert_not_called()

    def test_monthly_publish_can_adopt_matching_existing_page(self):
        publisher = object.__new__(LarkWeeklyPublisher)
        publisher.config = SimpleNamespace(
            wiki_url="https://mengshikeji.feishu.cn/wiki/root"
        )
        publisher.root = {"nodeToken": "root", "spaceId": "space"}
        year = {"node_token": "year", "obj_token": "year-doc"}
        month = {"node_token": "month", "obj_token": "month-doc"}
        week = {
            "title": "2026-W32｜08.03–08.09｜Grooming 反馈总览",
            "node_token": "week-node",
            "obj_token": "week-doc",
            "obj_type": "docx",
        }
        monthly = {
            "title": "2026-08｜Grooming 反馈重点汇总",
            "node_token": "monthly-node",
            "obj_token": "monthly-doc",
            "obj_type": "docx",
        }
        existing = "人工月报"
        final_content = "<title>月报</title><p>月度标记</p>"
        publisher._find_doc_node = Mock(side_effect=[year, month])
        publisher._list_children = Mock(return_value=[week, monthly])
        publisher._fetch = Mock(
            side_effect=["周托管标记", existing, final_content]
        )
        publisher._overwrite = Mock()

        result = publisher.publish_monthly(
            year_title="2026",
            month_title="08",
            title=monthly["title"],
            content=final_content,
            markers=["月报"],
            monthly_marker="月度标记",
            weekly_marker="周托管标记",
            weekly_pages=[
                {
                    "title": week["title"],
                    "nodeToken": week["node_token"],
                    "documentToken": week["obj_token"],
                }
            ],
            adopt_existing_hash=sha256(existing.encode("utf-8")).hexdigest(),
        )

        self.assertTrue(result["adopted"])
        publisher._overwrite.assert_called_once_with("monthly-doc", final_content)


if __name__ == "__main__":
    unittest.main()

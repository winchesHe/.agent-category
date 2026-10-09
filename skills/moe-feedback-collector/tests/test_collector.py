import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from mfc.canny import BrowserTransport, CannyCollector, FixtureTransport, scan_cumulative
from mfc.store import LocalStore
from mfc.errors import BusinessError


FIXTURE = Path(__file__).parent / "fixtures" / "canny.json"


class CollectorTests(unittest.TestCase):
    def test_browser_start_marks_session_started_before_open(self):
        transport = BrowserTransport.__new__(BrowserTransport)
        transport._started = False
        transport.config = Mock(canny_board_url="https://moego.canny.io/feature-request")
        transport._run = Mock(side_effect=RuntimeError("open failed after creating session"))

        with self.assertRaises(RuntimeError):
            transport.start()

        self.assertTrue(transport._started)

    def test_cumulative_scan_keeps_latest_response_instead_of_appending(self):
        calls = []

        def fetch(pages):
            calls.append(pages)
            posts = [{"_id": str(index), "score": 20} for index in range(pages * 10)]
            return {"posts": posts, "hasNextPage": pages < 4}

        result = scan_cumulative(fetch, lambda posts, more: not more, 8)

        self.assertEqual([1, 2, 4], calls)
        self.assertEqual(40, len(result))

    def test_first_collection_builds_full_baseline_and_keeps_every_scanned_post(self):
        collector = CannyCollector(
            FixtureTransport(FIXTURE),
            board_url="https://moego.canny.io/feature-request",
            min_vote=10,
            page_cap=8,
        )

        result = collector.collect(
            {"schemaVersion": 1, "sourceKey": "canny", "posts": {}},
            "incremental",
        )

        self.assertEqual(3, result["observed"])
        self.assertTrue(result["baseline"])
        self.assertEqual(3, result["baselineCount"])
        self.assertEqual(0, result["newCount"])
        self.assertEqual(3, len(result["evidence"]))
        self.assertEqual(
            {"post-new", "post-top", "post-low"},
            {item["sourceObjectId"] for item in result["evidence"]},
        )
        top = next(
            item for item in result["evidence"] if item["sourceObjectId"] == "post-top"
        )
        self.assertTrue(top["quickWinPrefilter"])

    def test_incremental_bootstrap_scans_all_newest_pages_for_baseline(self):
        calls = []

        class Transport:
            def fetch_posts(self, pages, sort):
                calls.append((sort, pages))
                if sort == "newest":
                    return {
                        "posts": [{"_id": "new", "created": "2026-08-25", "score": 1}],
                        "hasNextPage": pages < 4,
                    }
                return {
                    "posts": [{"_id": "tail", "created": "2026-01-01", "score": 1}],
                    "hasNextPage": True,
                }

            def fetch_detail(self, _post):
                return {}

        collector = CannyCollector(
            Transport(),
            board_url="https://moego.canny.io/feature-request",
            min_vote=10,
            page_cap=32,
        )
        collector.collect(
            {"schemaVersion": 1, "sourceKey": "canny", "posts": {}},
            "incremental",
        )

        self.assertEqual(
            [("newest", 1), ("newest", 2), ("newest", 4)],
            [call for call in calls if call[0] == "newest"],
        )

    def test_probe_keeps_every_scanned_post_without_fetching_comment_details(self):
        detail_calls = []

        class Transport:
            def fetch_posts(self, _pages, sort):
                score = 20 if sort == "score" else 1
                return {
                    "posts": [
                        {
                            "_id": "post-1",
                            "created": "2026-08-25",
                            "score": score,
                            "urlName": "post-1",
                        }
                    ],
                    "hasNextPage": True,
                }

            def fetch_detail(self, _post):
                detail_calls.append(_post)
                return {
                    "comments": {
                        f"comment-{index}": {
                            "_id": f"comment-{index}",
                            "value": "内容",
                        }
                        for index in range(5)
                    }
                }

        collector = CannyCollector(
            Transport(),
            board_url="https://moego.canny.io/feature-request",
            min_vote=10,
            page_cap=32,
        )

        result = collector.collect(
            {"schemaVersion": 1, "sourceKey": "canny", "posts": {}}, "probe"
        )

        self.assertEqual(1, len(result["evidence"]))
        self.assertEqual([], detail_calls)

    def test_unchanged_second_run_emits_no_duplicate_events(self):
        collector = CannyCollector(
            FixtureTransport(FIXTURE),
            board_url="https://moego.canny.io/feature-request",
            min_vote=10,
            page_cap=8,
        )
        first = collector.collect(
            {"schemaVersion": 1, "sourceKey": "canny", "posts": {}},
            "incremental",
        )

        second = collector.collect(first["checkpoint"], "incremental")

        self.assertEqual(0, second["newCount"])
        self.assertEqual(0, second["changedCount"])
        self.assertEqual(3, len(second["evidence"]))
        self.assertEqual([], second["reportRows"])

    def test_period_rows_only_include_posts_created_in_requested_week(self):
        current_posts = [
            {
                "_id": "known-in-week",
                "created": "2026-09-06T23:30:00Z",
                "score": 1,
                "commentCount": 0,
                "status": "open",
                "title": "本周已见",
                "urlName": "known-in-week",
            },
            {
                "_id": "historical-discovery",
                "created": "2026-06-01T08:00:00Z",
                "score": 1,
                "commentCount": 0,
                "status": "open",
                "title": "历史首次发现",
                "urlName": "historical-discovery",
            },
            {
                "_id": "next-week",
                "created": "2026-09-13T16:00:00Z",
                "score": 1,
                "commentCount": 0,
                "status": "open",
                "title": "下周新帖",
                "urlName": "next-week",
            },
            {
                "_id": "historical-change",
                "created": "2026-05-01T08:00:00Z",
                "score": 2,
                "commentCount": 0,
                "status": "open",
                "title": "历史变化",
                "urlName": "historical-change",
            },
        ]

        class Transport:
            def fetch_posts(self, _pages, _sort):
                return {"posts": current_posts, "hasNextPage": False}

        checkpoint = {
            "lastCreated": "2026-09-06T23:30:00Z",
            "posts": {
                "known-in-week": {
                    "snapshot": {
                        "score": 1,
                        "commentCount": 0,
                        "status": "open",
                        "title": "本周已见",
                        "detailsHash": "e3b0c44298fc1c149afbf4c8996fb924"
                        "27ae41e4649b934ca495991b7852b855",
                    }
                },
                "historical-change": {
                    "snapshot": {
                        "score": 1,
                        "commentCount": 0,
                        "status": "open",
                        "title": "历史变化",
                        "detailsHash": "e3b0c44298fc1c149afbf4c8996fb924"
                        "27ae41e4649b934ca495991b7852b855",
                    }
                },
            },
        }
        result = CannyCollector(
            Transport(),
            board_url="https://moego.canny.io/feature-request",
            min_vote=10,
            page_cap=8,
        ).collect(
            checkpoint,
            "incremental",
            period_start=date(2026, 9, 7),
            period_end=date(2026, 9, 13),
        )

        self.assertEqual(
            ["known-in-week"],
            [item["sourceObjectId"] for item in result["reportRows"]],
        )
        self.assertTrue(result["reportRows"][0]["isNew"])
        self.assertEqual("new", result["reportRows"][0]["changeKind"])
        self.assertEqual(1, result["newCount"])
        self.assertEqual(0, result["changedCount"])
        self.assertEqual(2, result["discoveredCount"])
        self.assertEqual(1, result["snapshotChangedCount"])

    def test_incremental_scan_uses_period_start_instead_of_checkpoint_boundary(self):
        calls = []

        class Transport:
            def fetch_posts(self, pages, sort):
                calls.append((sort, pages))
                if sort == "score":
                    return {"posts": [], "hasNextPage": False}
                posts = [
                    {
                        "_id": "after-checkpoint",
                        "created": "2026-09-10T08:00:00Z",
                        "score": 1,
                    },
                    {
                        "_id": "before-checkpoint-in-week",
                        "created": "2026-09-07T08:00:00Z",
                        "score": 1,
                    },
                ]
                if pages >= 2:
                    posts.append(
                        {
                            "_id": "before-period",
                            "created": "2026-09-06T15:59:59Z",
                            "score": 1,
                        }
                    )
                return {"posts": posts, "hasNextPage": pages < 2}

        checkpoint = {
            "lastCreated": "2026-09-09T00:00:00Z",
            "posts": {"existing": {"snapshot": {"score": 1}}},
        }
        result = CannyCollector(
            Transport(),
            board_url="https://moego.canny.io/feature-request",
            min_vote=10,
            page_cap=8,
        ).collect(
            checkpoint,
            "incremental",
            period_start=date(2026, 9, 7),
            period_end=date(2026, 9, 13),
        )

        self.assertEqual(
            [("newest", 1), ("newest", 2)],
            [call for call in calls if call[0] == "newest"],
        )
        self.assertEqual(
            {"after-checkpoint", "before-checkpoint-in-week"},
            {item["sourceObjectId"] for item in result["reportRows"]},
        )

    def test_store_writes_private_atomic_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LocalStore(directory)
            manifest_path, saved = store.save_run(
                "canny",
                "run-1",
                {"runId": "run-1"},
                [
                    {
                        "evidenceId": "canny:post-1",
                        "sourceObjectId": "post-1",
                        "objectType": "post",
                        "title": "需求",
                    }
                ],
                {"schemaVersion": 1, "sourceKey": "canny", "posts": {}},
            )

            self.assertTrue(Path(manifest_path).is_file())
            self.assertTrue(Path(saved["checkpointArtifact"]).is_file())
            self.assertEqual(0o600, os.stat(manifest_path).st_mode & 0o777)
            self.assertEqual(
                0o700,
                os.stat(Path(directory) / "evidence").st_mode & 0o777,
            )
            self.assertEqual(
                0o700,
                os.stat(Path(directory) / "runs").st_mode & 0o777,
            )
            self.assertEqual(
                "run-1", json.loads(Path(manifest_path).read_text())["runId"]
            )

    def test_source_lock_rejects_concurrent_collector(self):
        with tempfile.TemporaryDirectory() as directory:
            first = LocalStore(directory)
            second = LocalStore(directory)
            descriptor = first.acquire_source_lock("canny")
            try:
                with self.assertRaisesRegex(BusinessError, "已有采集任务"):
                    second.acquire_source_lock("canny")
            finally:
                first.release_source_lock(descriptor)


if __name__ == "__main__":
    unittest.main()

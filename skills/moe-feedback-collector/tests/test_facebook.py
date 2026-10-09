import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from mfc.errors import BusinessError
from mfc.facebook import FacebookCollector, FixtureTransport

FIXTURE = Path(__file__).parent / "fixtures" / "facebook.json"
CHANNEL_ID = "C0BEL8Y0Y74"


class FacebookCollectorTests(unittest.TestCase):
    def test_collects_group_post_and_campaign_summary_but_skips_chatter(self):
        result = FacebookCollector(
            FixtureTransport(FIXTURE),
            channel_id=CHANNEL_ID,
            domain="grooming",
        ).collect(date(2026, 8, 17), date(2026, 8, 23))

        self.assertEqual(3, result["observed"])
        self.assertEqual(1, result["skipped"])
        self.assertEqual(
            {"group_post": 1, "campaign_comment_summary": 1},
            result["feedCounts"],
        )
        post = next(item for item in result["evidence"] if item["feedType"] == "group_post")
        self.assertEqual("grooming", post["domain"])
        self.assertEqual("moego", post["groupRef"])
        self.assertEqual(
            "https://www.facebook.com/groups/moego/pending_posts",
            post["sourceUrl"],
        )
        summary = next(
            item
            for item in result["evidence"]
            if item["feedType"] == "campaign_comment_summary"
        )
        self.assertEqual(
            "https://www.facebook.com/groups/moego/posts/123456",
            summary["sourceUrl"],
        )

    def test_evidence_drops_email_envelope_and_tracking_data(self):
        result = FacebookCollector(
            FixtureTransport(FIXTURE),
            channel_id=CHANNEL_ID,
            domain="grooming",
        ).collect(date(2026, 8, 17), date(2026, 8, 23))

        serialized = json.dumps(result["evidence"], ensure_ascii=False)
        self.assertNotIn("owner@example.com", serialized)
        self.assertNotIn("customer@example.com", serialized)
        self.assertNotIn("facebookmail.com", serialized)
        self.assertNotIn("unsubscribe", serialized)
        self.assertNotIn("tracking=secret", serialized)
        self.assertIn("[EMAIL]", serialized)

    def test_rejects_incomplete_period_search(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        payload["total"] = 4
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "facebook.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            collector = FacebookCollector(
                FixtureTransport(path),
                channel_id=CHANNEL_ID,
                domain="grooming",
            )
            with self.assertRaisesRegex(BusinessError, "搜索结果不完整"):
                collector.collect(date(2026, 8, 17), date(2026, 8, 23))

    def test_rejects_message_from_another_channel(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        payload["matches"][0]["channel_id"] = "COTHER"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "facebook.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            collector = FacebookCollector(
                FixtureTransport(path),
                channel_id=CHANNEL_ID,
                domain="grooming",
            )
            with self.assertRaisesRegex(BusinessError, "不属于目标频道"):
                collector.collect(date(2026, 8, 17), date(2026, 8, 23))

    def test_summary_drops_unsubscribe_and_redirect_urls(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        payload["matches"] = [payload["matches"][1]]
        payload["matches"][0]["text_raw"] = (
            "Facebook comment summary: Customer asked for labels. "
            "https://www.facebook.com/o.php?unsubscribe=secret "
            "https://www.facebook.com/l.php?u=tracking"
        )
        payload["total"] = payload["returned"] = 1
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "facebook.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = FacebookCollector(
                FixtureTransport(path),
                channel_id=CHANNEL_ID,
                domain="grooming",
            ).collect(date(2026, 8, 17), date(2026, 8, 23))

        serialized = json.dumps(result["evidence"], ensure_ascii=False)
        self.assertNotIn("unsubscribe", serialized)
        self.assertNotIn("/o.php", serialized)
        self.assertNotIn("/l.php", serialized)

    def test_stable_ids_are_repeatable(self):
        collector = FacebookCollector(
            FixtureTransport(FIXTURE),
            channel_id=CHANNEL_ID,
            domain="grooming",
        )
        first = collector.collect(date(2026, 8, 17), date(2026, 8, 23))
        second = collector.collect(date(2026, 8, 17), date(2026, 8, 23))

        self.assertEqual(
            [item["evidenceId"] for item in first["evidence"]],
            [item["evidenceId"] for item in second["evidence"]],
        )


if __name__ == "__main__":
    unittest.main()

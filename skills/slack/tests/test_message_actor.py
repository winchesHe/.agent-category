from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from sk.message import build_author  # noqa: E402
from sk.render import render_blocks  # noqa: E402


class MessageAuthorTests(unittest.TestCase):
    def test_bot_id_wins_when_message_also_has_user_id(self) -> None:
        author = build_author(
            {"bot_id": "B1", "user": "U-BOT", "username": "helper"},
            {"U-BOT": "Helper Bot"},
        )
        self.assertTrue(author["is_bot"])
        self.assertEqual(author["bot_id"], "B1")
        self.assertEqual(author["user_id"], "U-BOT")

    def test_known_user_actor_wins_over_app_bot_id(self) -> None:
        author = build_author(
            {"bot_id": "B-APP", "user": "U1", "username": "alice"},
            {"U1": "Alice"},
            known_actor={
                "selected": "user",
                "user_id": "U1",
                "bot_id": None,
            },
        )

        self.assertFalse(author["is_bot"])
        self.assertEqual(author["id"], "U1")
        self.assertEqual(author["user_id"], "U1")
        self.assertEqual(author["bot_id"], "B-APP")

    def test_markdown_block_is_rendered_instead_of_reported_unknown(self) -> None:
        rendered = render_blocks(
            [{"type": "markdown", "text": "# Title\n\n| A | B |\n| - | - |\n| 1 | <@U1> |"}],
            user_lookup=lambda value: "Alice" if value == "U1" else None,
        )

        self.assertIn("# Title", rendered)
        self.assertIn("| 1 | @Alice |", rendered)
        self.assertNotIn("unknown block", rendered)


if __name__ == "__main__":
    unittest.main()

import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from mgrey.formatter import output


class FormatterTests(unittest.TestCase):
    def test_json_recursively_redacts_sensitive_fields(self):
        stream = io.StringIO()
        with redirect_stdout(stream):
            output({"nested": [{"token": "secret-value"}]})

        self.assertEqual(
            {"nested": [{"token": "[REDACTED]"}]},
            json.loads(stream.getvalue()),
        )

    def test_summary_redacts_sensitive_fields_on_stderr(self):
        stream = io.StringIO()
        with redirect_stderr(stream):
            output({"authorization": "secret-value"}, "summary")

        self.assertNotIn("secret-value", stream.getvalue())
        self.assertIn("[REDACTED]", stream.getvalue())


if __name__ == "__main__":
    unittest.main()

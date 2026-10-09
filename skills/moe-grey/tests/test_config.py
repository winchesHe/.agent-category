import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from mgrey.config import load_config


class ConfigTests(unittest.TestCase):
    def test_runtime_config_uses_fixed_values(self):
        with patch.dict(
            "os.environ",
            {
                "MIO_GREY_BASE_URL": "https://legacy.example",
                "MIO_GREY_NAMESPACE": "legacy",
                "MOE_GREY_BASE_URL": "https://current.example/",
                "MOE_GREY_NAMESPACE": "current",
                "MOE_GREY_TIMEOUT": "99",
            },
            clear=False,
        ):
            config = load_config()
        self.assertEqual("https://grey.devops.moego.pet", config.grey_base_url)
        self.assertEqual("ns-testing", config.grey_namespace)
        self.assertEqual(30.0, config.timeout)


if __name__ == "__main__":
    unittest.main()

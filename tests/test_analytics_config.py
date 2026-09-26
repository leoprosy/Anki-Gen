import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from analytics_config import load_configuration, write_build_config


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_packaged_public_configuration_round_trip(self):
        os.environ["ANKIGEN_POSTHOG_TOKEN"] = "phc_example"
        os.environ["ANKIGEN_POSTHOG_REGION"] = "eu"
        write_build_config(self.root / "analytics_config.json")
        (self.root / "version.json").write_text('{"version":"1.2.1"}')
        config = load_configuration(self.root, packaged=True)
        self.assertEqual(config, {"project_token": "phc_example", "region": "eu", "app_version": "1.2.1"})

    def test_development_requires_explicit_enablement(self):
        os.environ["ANKIGEN_POSTHOG_TOKEN"] = "phc_example"
        self.assertIsNone(load_configuration(self.root, packaged=False))
        os.environ["ANKIGEN_ANALYTICS_DEV"] = "1"
        self.assertIsNotNone(load_configuration(self.root, packaged=False))

    def test_missing_token_disables_collection(self):
        write_build_config(self.root / "analytics_config.json")
        self.assertIsNone(load_configuration(self.root, packaged=True))

    def test_secret_tokens_and_arbitrary_hosts_cannot_ship(self):
        os.environ["ANKIGEN_POSTHOG_TOKEN"] = "phx_private"
        with self.assertRaises(ValueError):
            write_build_config(self.root / "analytics_config.json")
        os.environ["ANKIGEN_POSTHOG_TOKEN"] = "phc_example"
        os.environ["ANKIGEN_POSTHOG_REGION"] = "https://another-host.invalid"
        with self.assertRaises(ValueError):
            write_build_config(self.root / "analytics_config.json")

    def test_corrupt_config_and_version_content_fail_safely(self):
        (self.root / "analytics_config.json").write_text('[]')
        self.assertIsNone(load_configuration(self.root, packaged=True))
        (self.root / "analytics_config.json").write_text(json.dumps({"project_token": "phc_example", "region": "eu"}))
        (self.root / "version.json").write_text('{"version":"private course content"}')
        self.assertEqual(load_configuration(self.root, packaged=True)["app_version"], "unknown")

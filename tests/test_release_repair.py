import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common


class RequiredAssetsTests(unittest.TestCase):
    def test_required_assets_cover_every_font_of_an_action(self):
        # fluent builds both the 3D sbix and the flat OT-SVG font: both primaries
        self.assertEqual(common.required_assets("fluent"), ["fluent.ttf", "fluent-flat.ttf"])

    def test_single_font_action(self):
        self.assertEqual(common.required_assets("noto-mono"), ["noto-mono.ttf"])


class MissingAssetsTests(unittest.TestCase):
    def test_missing_release_assets_reports_absent_primaries(self):
        with mock.patch.object(common, "release_assets", return_value={"fluent-mono.ttf", "noto.ttf"}):
            missing = common.missing_release_assets("fluent")
        self.assertEqual(missing, ["fluent.ttf", "fluent-flat.ttf"])

    def test_complete_release_reports_nothing_missing(self):
        with mock.patch.object(common, "release_assets", return_value={"fluent.ttf", "fluent-flat.ttf"}):
            self.assertEqual(common.missing_release_assets("fluent"), [])

    def test_no_release_at_all_means_everything_missing(self):
        # a wiped `latest` (empty asset set) must force a rebuild of every primary
        with mock.patch.object(common, "release_assets", return_value=set()):
            self.assertEqual(common.missing_release_assets("twemoji"), ["twemoji.ttf"])


class ChangedCommandTests(unittest.TestCase):
    def test_changed_prints_action_when_upstream_moved(self):
        with mock.patch.object(common, "upstream_ref", return_value="newsha"), \
             mock.patch.object(common, "stored_ref", return_value="oldsha"):
            self.assertEqual(common.cli("twemoji", ["changed"]), 0)

    def test_changed_prints_repair_note_when_assets_missing_only(self):
        with mock.patch.object(common, "upstream_ref", return_value="same"), \
             mock.patch.object(common, "stored_ref", return_value="same"), \
             mock.patch.object(common, "release_assets", return_value=set()):
            captured = []
            with mock.patch("builtins.print", side_effect=captured.append):
                code = common.cli("fluent", ["changed"])
        self.assertEqual(code, 0)
        self.assertEqual(len(captured), 1)
        self.assertIn("fluent", captured[0])
        self.assertIn("missing", captured[0])

    def test_changed_prints_nothing_when_healthy(self):
        with mock.patch.object(common, "upstream_ref", return_value="same"), \
             mock.patch.object(common, "stored_ref", return_value="same"), \
             mock.patch.object(common, "release_assets", return_value={"fluent.ttf", "fluent-flat.ttf"}):
            captured = []
            with mock.patch("builtins.print", side_effect=captured.append):
                code = common.cli("fluent", ["changed"])
        self.assertEqual(code, 0)
        self.assertEqual(captured, [])


class ReleaseAssetsProbeTests(unittest.TestCase):
    def test_release_assets_handles_missing_gh(self):
        with mock.patch.object(
            subprocess, "run",
            side_effect=FileNotFoundError("gh"),
        ):
            self.assertEqual(common.release_assets(), set())


if __name__ == "__main__":
    unittest.main()

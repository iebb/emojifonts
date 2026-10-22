import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import common


EMOJI_18 = """# emoji-test.txt
# Version: 18.0
1F600 ; fully-qualified # 😀 E1.0 grinning face
1FAEB ; fully-qualified # 🫫 E18.0 cracking face
1F46F 1F3FB ; fully-qualified # 👯🏻 E18.0 people with bunny ears: light skin tone
263A FE0F ; fully-qualified # ☺️ E0.6 smiling face
263A ; unqualified # ☺ E0.6 smiling face
"""


class EmojiDataTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.data = Path(directory.name)
        self.cache = self.data / "emoji-test.txt"
        patcher = patch.object(common, "DATA", self.data)
        patcher.start()
        self.addCleanup(patcher.stop)

    def download(self, responses):
        responses = iter(responses)

        def run(args):
            status, data = next(responses)
            Path(args[args.index("-o") + 1]).write_text(data, encoding="utf-8")
            return subprocess.CompletedProcess(args, status)

        return patch.object(common.subprocess, "run", side_effect=run)

    def test_valid_cache_needs_no_download(self):
        self.cache.write_text(EMOJI_18, encoding="utf-8")
        with patch.object(common.subprocess, "run") as run:
            self.assertEqual(common.ensure_emoji_test(), self.cache)
        run.assert_not_called()

    def test_old_cache_is_replaced_with_emoji_18(self):
        self.cache.write_text(EMOJI_18.replace("18.0", "17.0"), encoding="utf-8")
        with self.download([(0, EMOJI_18)]):
            self.assertEqual(common.ensure_emoji_test(), self.cache)
        self.assertEqual(self.cache.read_text(encoding="utf-8"), EMOJI_18)

    def test_html_success_and_failed_partial_download_are_rejected(self):
        with self.download([(0, "<html>directory listing</html>"),
                            (18, EMOJI_18), (0, EMOJI_18)]) as run:
            common.ensure_emoji_test()
        self.assertEqual(run.call_count, 3)
        self.assertFalse(self.cache.with_suffix(".tmp").exists())
        self.assertTrue(common.valid_emoji_test(self.cache))

    def test_unavailable_sources_fail_without_poisoning_cache(self):
        with self.download([(22, ""), (0, "# Version: 18.0\n"), (0, "bad data")]):
            with self.assertRaisesRegex(RuntimeError, "valid Emoji 18"):
                common.ensure_emoji_test()
        self.assertFalse(self.cache.exists())
        self.assertFalse(self.cache.with_suffix(".tmp").exists())

    def test_invalid_utf8_cache_is_refreshed(self):
        self.cache.write_bytes(b"\xff")
        with self.download([(0, EMOJI_18)]):
            common.ensure_emoji_test()
        self.assertTrue(common.valid_emoji_test(self.cache))

    def test_index_includes_emoji_18_singles_and_ignores_sequences(self):
        self.cache.write_text(EMOJI_18, encoding="utf-8")
        self.assertEqual(common.emoji_version_index(), {
            1.0: [0x1F600], 18.0: [0x1FAEB], 0.6: [0x263A],
        })

    def test_newer_versions_are_accepted(self):
        self.cache.write_text(EMOJI_18.replace("18.0", "19.0"), encoding="utf-8")
        self.assertTrue(common.valid_emoji_test(self.cache))


if __name__ == "__main__":
    unittest.main()

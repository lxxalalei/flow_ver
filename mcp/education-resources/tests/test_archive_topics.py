"""Topic-reuse facts for archive classification.

The Agent coining near-duplicate topic directories (e.g. a fresh
「动物王国纪录片」 next to an existing 「动物与植物」) was a real regression:
the taxonomy's suggested topics were never visible to the Agent. These
tests pin the mechanics that fix it: disk directories first, taxonomy
suggestions second, format directories excluded, and the hint surfaced in
the archive tool description.
"""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.archive import (  # noqa: E402
    archive_domains,
    domain_directory,
    domain_topics,
    topic_directory,
)
from education_resource_mcp.errors import DomainError  # noqa: E402
from education_resource_mcp.server import _archive_topic_hint  # noqa: E402


class DomainTopicsTests(unittest.TestCase):
    def test_existing_disk_directories_come_first(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            domain = root / domain_directory("natural_science")
            (domain / "动物与植物").mkdir(parents=True)
            (domain / "动物王国记录片").mkdir()  # user-organized manual topic
            (domain / "视频").mkdir()  # structural format dir, not a topic
            (domain / "a-file.txt").write_text("not a directory")

            topics = domain_topics("natural_science", root)

        self.assertEqual("动物与植物", topics[0])
        self.assertIn("动物王国记录片", topics)
        self.assertNotIn("视频", topics)
        # taxonomy suggestions without a directory come after existing ones
        self.assertGreater(topics.index("动物与植物"), -1)
        self.assertIn("天文与宇宙", topics)  # suggested, not on disk
        self.assertEqual(topics.index("动物与植物"), 0)

    def test_suggestions_only_when_domain_dir_absent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            topics = domain_topics("natural_science", Path(td))
        self.assertIn("动物与植物", topics)
        self.assertEqual("动物与植物", topics[0])

    def test_unknown_domain_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(DomainError) as ctx:
                domain_topics("no_such_domain", Path(td))
        self.assertEqual("INVALID_ARGUMENT", ctx.exception.code)

    def test_unclassified_domain_lists_its_topics(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "99-待分类" / "待整理主题").mkdir(parents=True)
            topics = domain_topics("", root)
        self.assertEqual(["待整理主题"], topics)


class TopicDirectoryTests(unittest.TestCase):
    def test_empty_topic_falls_back(self) -> None:
        self.assertEqual("其他", topic_directory(""))

    def test_topic_component_sanitized(self) -> None:
        self.assertEqual("a_b", topic_directory("a/b"))


class ArchiveTopicHintTests(unittest.TestCase):
    def test_hint_lists_every_domain_with_suggestions(self) -> None:
        hint = _archive_topic_hint()
        for item in archive_domains():
            self.assertIn(str(item.get("id")), hint)
        self.assertIn("动物与植物", hint)

    def test_hint_survives_taxonomy_errors(self) -> None:
        import education_resource_mcp.server as server_mod

        original = server_mod.archive_domains
        try:
            server_mod.archive_domains = lambda: (_ for _ in ()).throw(RuntimeError("x"))
            self.assertEqual("", server_mod._archive_topic_hint())
        finally:
            server_mod.archive_domains = original


if __name__ == "__main__":
    unittest.main()

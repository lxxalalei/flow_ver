"""Golden cases for stable internal candidate de-duplication."""

from __future__ import annotations

import unittest

from education_resource_mcp.retrieval import (
    CandidateDeduplicator,
    deduplicate_candidate_mappings,
    deduplicate_candidates,
)


class RetrievalDedupTests(unittest.TestCase):
    def test_bv_duplicate_keeps_first_order_and_fills_missing_fields(self) -> None:
        candidates = [
            {
                "resource_id": "res_first",
                "platform": "bilibili",
                "title": "太阳系",
                "source_url": "https://www.bilibili.com/video/BV1Test?spm_id_from=333#one",
                "resource_type": "video",
                "summary": "首个摘要",
                "metadata": {"origin": "first", "nested": {"title": "known"}},
            },
            {
                "resource_id": "res_second",
                "platform": "bilibili",
                "title": "太阳系（重复）",
                "source_url": "https://www.bilibili.com/video/BV1Test?vd_source=tracking#two",
                "resource_type": "video",
                "author": "科普作者",
                "metadata": {"origin": "second", "nested": {"title": "known", "author": "filled"}},
            },
        ]
        result = deduplicate_candidates(candidates)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].resource_id, "res_first")
        self.assertEqual(result[0].title, "太阳系")
        self.assertEqual(result[0].summary, "首个摘要")
        self.assertEqual(result[0].author, "科普作者")
        self.assertEqual(result[0].metadata["origin"], "first")
        self.assertEqual(result[0].metadata["nested"]["author"], "filled")

    def test_fragment_only_difference_deduplicates_but_query_difference_does_not(self) -> None:
        same_url = deduplicate_candidates(
            [
                {"platform": "generic", "title": "A", "source_url": "https://example.com/a#one"},
                {"platform": "generic", "title": "A", "source_url": "https://example.com/a#two"},
            ]
        )
        different_query = deduplicate_candidates(
            [
                {"platform": "generic", "title": "A", "source_url": "https://example.com/a?id=1"},
                {"platform": "generic", "title": "A", "source_url": "https://example.com/a?id=2"},
            ]
        )
        self.assertEqual(len(same_url), 1)
        self.assertEqual(len(different_query), 2)

    def test_strong_native_conflict_does_not_merge(self) -> None:
        result = deduplicate_candidates(
            [
                {
                    "platform": "bilibili",
                    "title": "同名课程",
                    "author": "同一作者",
                    "source_url": "https://www.bilibili.com/video/BV1First",
                },
                {
                    "platform": "bilibili",
                    "title": "同名课程",
                    "author": "同一作者",
                    "source_url": "https://www.bilibili.com/video/BV1Second",
                },
            ]
        )
        self.assertEqual(len(result), 2)

    def test_isbn_dedup_can_merge_different_locator_representations(self) -> None:
        result = deduplicate_candidates(
            [
                {
                    "platform": "nlc",
                    "title": "学习方法",
                    "source_url": "https://catalog.example/book/1",
                    "isbn": "0-306-40615-2",
                },
                {
                    "platform": "annas-archive",
                    "title": "学习方法",
                    "source_url": "https://annas-archive.gl/md5/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "isbn": "978-0-306-40615-7",
                },
            ]
        )
        # The two forms above are the same ISBN-10/ISBN-13 pair.
        self.assertEqual(len(result), 1)

    def test_same_isbn_merges_incomparable_cross_platform_native_ids(self) -> None:
        result = deduplicate_candidates(
            [
                {
                    "platform": "nlc",
                    "native_type": "document",
                    "native_id": "nlc-42",
                    "isbn": "0-306-40615-2",
                    "title": "Theoretical Physics",
                    "source_url": "https://example.test/nlc/42",
                },
                {
                    "platform": "annas-archive",
                    "native_type": "md5",
                    "native_id": "0123456789abcdef0123456789abcdef",
                    "isbn": "978-0-306-40615-7",
                    "title": "Theoretical Physics",
                    "source_url": "https://example.test/anna/42",
                    "metadata": {"format": "epub"},
                },
            ]
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].platform, "nlc")
        self.assertEqual(result[0].metadata["format"], "epub")

    def test_doi_dedup_merges_case_and_url_forms(self) -> None:
        result = deduplicate_candidates(
            [
                {"platform": "generic", "title": "论文", "doi": "10.1000/XYZ.1"},
                {"platform": "generic", "title": "论文", "source_url": "https://doi.org/10.1000/xyz.1"},
            ]
        )
        self.assertEqual(len(result), 1)

    def test_title_alone_or_different_edition_is_not_enough(self) -> None:
        same_title = deduplicate_candidates(
            [
                {"platform": "generic", "title": "通用数学"},
                {"platform": "generic", "title": "通用数学"},
            ]
        )
        different_edition = deduplicate_candidates(
            [
                {
                    "platform": "generic",
                    "title": "通用数学",
                    "author": "作者",
                    "edition": "第一版",
                    "source_url": "https://example.com/math/1",
                },
                {
                    "platform": "generic",
                    "title": "通用数学",
                    "author": "作者",
                    "edition": "第二版",
                    "source_url": "https://example.com/math/2",
                },
            ]
        )
        self.assertEqual(len(same_title), 2)
        self.assertEqual(len(different_edition), 2)

    def test_limit_is_applied_after_duplicate_enrichment(self) -> None:
        result = deduplicate_candidates(
            [
                {"platform": "generic", "title": "A", "source_url": "https://example.com/a#first"},
                {"platform": "generic", "title": "B", "source_url": "https://example.com/b"},
                {
                    "platform": "generic",
                    "title": "A later label",
                    "source_url": "https://example.com/a#second",
                    "author": "作者 A",
                },
                {"platform": "generic", "title": "C", "source_url": "https://example.com/c"},
            ],
            limit=2,
        )
        self.assertEqual([item.title for item in result], ["A", "B"])
        self.assertEqual(result[0].author, "作者 A")

    def test_public_resource_id_does_not_control_dedup(self) -> None:
        result = deduplicate_candidate_mappings(
            [
                {
                    "resource_id": "res_one",
                    "platform": "generic",
                    "title": "A",
                    "source_url": "https://example.com/a",
                },
                {
                    "resource_id": "res_two",
                    "platform": "generic",
                    "title": "A later",
                    "source_url": "https://example.com/a#fragment",
                },
            ]
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["resource_id"], "res_one")

    def test_incremental_deduplicator_has_same_first_seen_order(self) -> None:
        deduplicator = CandidateDeduplicator()
        deduplicator.extend(
            [
                {"platform": "generic", "title": "B", "source_url": "https://example.com/b"},
                {"platform": "generic", "title": "A", "source_url": "https://example.com/a"},
                {"platform": "generic", "title": "B second", "source_url": "https://example.com/b#x"},
            ]
        )
        result = deduplicator.results()
        self.assertEqual([item.title for item in result], ["B", "A"])


if __name__ == "__main__":
    unittest.main()

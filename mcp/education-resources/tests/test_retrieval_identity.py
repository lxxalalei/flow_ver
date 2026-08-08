"""Golden cases for the internal retrieval identity resolver."""

from __future__ import annotations

import unittest

from education_resource_mcp.retrieval import (
    CandidateResourceInternal,
    Representation,
    ResolvedResource,
    identities_match,
    normalize_doi,
    normalize_isbn,
    normalize_native_identity,
    normalize_url,
    resolve_identity,
)


class RetrievalIdentityTests(unittest.TestCase):
    def test_default_url_removes_fragment_but_keeps_query(self) -> None:
        value = "https://Example.COM/item?contentId=A&utm_source=feed#section"
        self.assertEqual(
            normalize_url(value),
            "https://example.com/item?contentId=A&utm_source=feed",
        )

    def test_explicit_profile_can_remove_query_keys(self) -> None:
        value = "https://example.com/item?id=42&utm_source=feed#section"
        self.assertEqual(
            normalize_url(value, {"remove_query_keys": ["utm_source"]}),
            "https://example.com/item?id=42",
        )

    def test_bilibili_bv_identity_is_platform_namespaced(self) -> None:
        identity = resolve_identity(
            {
                "platform": "bilibili",
                "title": "太阳系",
                "source_url": "https://www.bilibili.com/video/BV1AbC9?spm_id_from=333#part",
            }
        )
        self.assertEqual(identity.native_type, "video")
        self.assertEqual(identity.native_id, "BV1AbC9")
        self.assertEqual(identity.key, ("platform_id", "bilibili", "video", "BV1AbC9"))
        self.assertEqual(identity.canonical_url, "https://www.bilibili.com/video/BV1AbC9")

    def test_aweme_identity_is_extracted_from_douyin_url(self) -> None:
        identity = resolve_identity(
            {
                "platform": "douyin",
                "title": "科学实验",
                "source_url": "https://www.douyin.com/video/123456789?mode=app",
            }
        )
        self.assertEqual(identity.native_type, "video")
        self.assertEqual(identity.native_id, "123456789")

    def test_zhihu_answer_object_identity_keeps_object_type(self) -> None:
        identity = resolve_identity(
            {
                "platform": "zhihu",
                "title": "为什么会下雨",
                "source_url": "https://www.zhihu.com/question/100/answer/200?utm_source=feed",
            }
        )
        self.assertEqual(identity.native_type, "answer")
        self.assertEqual(identity.native_id, "200")
        self.assertEqual(identity.canonical_url, "https://www.zhihu.com/question/100/answer/200")

    def test_ximalaya_album_identity(self) -> None:
        identity = resolve_identity(
            {
                "platform": "ximalaya",
                "source_url": "https://www.ximalaya.com/album/987654?from=share",
            }
        )
        self.assertEqual(identity.native_type, "album")
        self.assertEqual(identity.native_id, "987654")

    def test_annas_archive_md5_identity_is_lowercase(self) -> None:
        md5 = "ABCDEF0123456789ABCDEF0123456789"
        identity = resolve_identity(
            {
                "platform": "annas-archive",
                "source_url": f"https://annas-archive.gl/md5/{md5}",
            }
        )
        self.assertEqual(identity.native_type, "md5")
        self.assertEqual(identity.native_id, md5.lower())

    def test_smartedu_query_is_identity_bearing(self) -> None:
        first = resolve_identity(
            {
                "platform": "smartedu",
                "source_url": (
                    "https://basic.smartedu.cn/tchMaterial/detail?"
                    "contentType=teaching_material&contentId=book-1&catalogType=tchMaterial#top"
                ),
            }
        )
        second = resolve_identity(
            {
                "platform": "smartedu",
                "source_url": (
                    "https://basic.smartedu.cn/tchMaterial/detail?"
                    "contentType=teaching_material&contentId=book-2&catalogType=tchMaterial"
                ),
            }
        )
        self.assertEqual(first.native_id, "book-1")
        self.assertEqual(first.canonical_url.endswith("contentId=book-1&catalogType=tchMaterial"), True)
        self.assertNotEqual(first.canonical_url, second.canonical_url)
        self.assertFalse(identities_match(first, second))

    def test_isbn_10_and_isbn_13_normalize(self) -> None:
        self.assertEqual(normalize_isbn("ISBN-10: 0-306-40615-2"), "0306406152")
        self.assertEqual(normalize_isbn("978-0-306-40615-7"), "9780306406157")
        isbn10_identity = resolve_identity({"isbn": "0-306-40615-2"})
        isbn13_identity = resolve_identity({"isbn": "978-0-306-40615-7"})
        self.assertEqual(isbn10_identity.isbn, "9780306406157")
        self.assertEqual(isbn10_identity.isbn, isbn13_identity.isbn)
        self.assertTrue(identities_match(isbn10_identity, isbn13_identity))
        self.assertIsNone(normalize_isbn("0-306-40615-3"))
        invalid_first = resolve_identity({"isbn": "0-306-40615-3"})
        invalid_second = resolve_identity({"isbn": "0-306-40615-3"})
        self.assertIsNone(invalid_first.isbn)
        self.assertFalse(identities_match(invalid_first, invalid_second))

    def test_doi_label_and_url_normalize_to_same_value(self) -> None:
        first = normalize_doi("doi:10.1000/XYZ.1")
        second = normalize_doi("https://doi.org/10.1000/xyz.1.")
        self.assertEqual(first, "10.1000/xyz.1")
        self.assertEqual(first, second)
        doi_org = resolve_identity(
            {"source_url": "https://doi.org/10.1000/XYZ.1?source=resolver"}
        )
        dx_doi_org = resolve_identity(
            {"source_url": "https://dx.doi.org/10.1000/xyz.1#abstract"}
        )
        self.assertEqual(doi_org.kind, "doi")
        self.assertEqual(doi_org.doi, "10.1000/xyz.1")
        self.assertEqual(doi_org.doi, dx_doi_org.doi)
        self.assertTrue(identities_match(doi_org, dx_doi_org))

    def test_explicit_native_identity_is_normalized(self) -> None:
        identity = normalize_native_identity("bilibili", " bv1Test ", "video")
        self.assertIsNotNone(identity)
        assert identity is not None
        self.assertEqual(identity.native_id, "BV1Test")
        self.assertEqual(identity.platform, "bilibili")

    def test_same_native_value_on_different_platforms_does_not_match(self) -> None:
        bilibili = resolve_identity(
            {"platform": "bilibili", "native_id": "123", "native_type": "video"}
        )
        douyin = resolve_identity(
            {"platform": "douyin", "native_id": "123", "native_type": "video"}
        )
        self.assertFalse(identities_match(bilibili, douyin))

    def test_models_keep_public_id_separate_from_identity(self) -> None:
        candidate = CandidateResourceInternal(
            resource_id="res_public_1",
            platform="bilibili",
            title="太阳系",
            canonical_url="https://www.bilibili.com/video/BV1AbC9",
        )
        self.assertEqual(candidate.identity.native_id, "BV1AbC9")
        public_mapping = candidate.to_mapping()
        self.assertEqual(public_mapping["resource_id"], "res_public_1")
        self.assertNotIn("native_identity", public_mapping)

        resolved = ResolvedResource.from_candidate(candidate)
        self.assertEqual(resolved.identity, candidate.identity)
        representation = Representation(
            representation_id="repr_video",
            kind="video",
            container="mp4",
            materializable=True,
        )
        self.assertTrue(representation.to_mapping()["materializable"])


if __name__ == "__main__":
    unittest.main()

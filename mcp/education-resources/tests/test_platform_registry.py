from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import sys
import unittest


SERVICE_ROOT = Path(__file__).resolve().parents[1]
SRC = SERVICE_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from education_resource_mcp.retrieval.registry import (  # noqa: E402
    CREATOR_BROWSE_PLATFORM_IDS,
    DEFAULT_REGISTRY_PATH,
    DEFAULT_SCHEMA_PATH,
    EXPECTED_PLATFORM_IDS,
    INSPECTION_PLATFORM_IDS,
    LEGAL_RESOURCE_TYPES,
    PlatformRegistryError,
    load_platform_registry,
    validate_platform_registry,
)
from education_resource_mcp.retrieval.identity import (  # noqa: E402
    get_url_identity_profile,
    normalize_url,
)
from education_resource_mcp.adapters.base import descriptor_for_platform  # noqa: E402


EXPECTED_REMOVABLE_QUERY_PARAMETERS = {
    "generic": {
        "fbclid",
        "gclid",
        "msclkid",
        "utm_campaign",
        "utm_content",
        "utm_medium",
        "utm_source",
        "utm_term",
    },
    "bilibili": {"from", "spm_id_from", "vd_source", "share_source", "share_medium"},
    "douyin": {"from_tab", "previous_page", "mode", "enter_from", "share_token"},
    "zhihu": {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"},
    "smartedu": set(),
    "ximalaya": {"from", "source", "utm_source"},
    "cctv": set(),
    "yixi": set(),
    "kepu": set(),
    "baiduwenku": set(),
    "runoob": set(),
    "nlc": set(),
    "open163": set(),
    "annas-archive": set(),
    "weibo": set(),
    "wechat": set(),
    "shuge": set(),
}


class PlatformRegistryTests(unittest.TestCase):
    def test_registry_json_and_schema_are_valid_and_cover_active_platforms(self) -> None:
        schema = json.loads(DEFAULT_SCHEMA_PATH.read_text(encoding="utf-8"))
        payload = json.loads(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))

        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertIs(schema["additionalProperties"], False)
        self.assertEqual(payload["$schema"], "../schemas/platform-registry.schema.json")
        validate_platform_registry(payload, schema_path=DEFAULT_SCHEMA_PATH)

        registry = load_platform_registry()
        self.assertEqual(registry["registry_version"], "1.0.0")
        self.assertEqual(len(registry["platforms"]), 17)
        self.assertEqual(
            {item["platform_id"] for item in registry["platforms"]},
            EXPECTED_PLATFORM_IDS,
        )

    def test_capability_boundaries_and_specialized_acquisition_are_truthful(self) -> None:
        registry = load_platform_registry()
        for platform in registry["platforms"]:
            platform_id = platform["platform_id"]
            capabilities = platform["capabilities"]
            self.assertTrue(capabilities["search"], platform_id)
            self.assertEqual(capabilities["inspect"], platform_id in INSPECTION_PLATFORM_IDS)
            self.assertEqual(platform["inspection"]["supported"], platform_id in INSPECTION_PLATFORM_IDS)
            self.assertEqual(capabilities["browse_creator"], platform_id in CREATOR_BROWSE_PLATFORM_IDS)
            self.assertEqual(capabilities["search"], platform["search"]["enabled"])
            self.assertIn("webpage", platform["acquisition"]["strategies"])

            for strategy in platform["acquisition"]["strategies"]:
                if strategy != "webpage":
                    self.assertIn(
                        platform_id,
                        {
                            "platform_video": {"bilibili", "douyin"},
                            "platform_audio": {"ximalaya"},
                            "platform_resource": {"smartedu"},
                            "platform_book": {"annas-archive"},
                        }[strategy],
                    )

    def test_inspection_platform_set_matches_code_constant(self) -> None:
        registry = load_platform_registry()
        enabled = {
            item["platform_id"]
            for item in registry["platforms"]
            if item["capabilities"]["inspect"]
        }
        self.assertEqual(enabled, INSPECTION_PLATFORM_IDS)
        self.assertEqual(len(enabled), 9)
        self.assertEqual(
            EXPECTED_PLATFORM_IDS - enabled,
            {
                "cctv",
                "yixi",
                "kepu",
                "baiduwenku",
                "runoob",
                "open163",
                "weibo",
                "wechat",
            },
        )

    def test_schema_allows_boolean_inspection_capabilities(self) -> None:
        schema = json.loads(DEFAULT_SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            schema["$defs"]["capabilities"]["properties"]["inspect"],
            {"type": "boolean"},
        )
        self.assertEqual(
            schema["$defs"]["inspection"]["properties"]["supported"],
            {"type": "boolean"},
        )

    def test_loader_rejects_capability_and_inspection_mismatch(self) -> None:
        registry = load_platform_registry()
        mismatch = copy.deepcopy(registry)
        mismatch["platforms"][0]["inspection"]["supported"] = False
        with self.assertRaisesRegex(PlatformRegistryError, "must match capabilities.inspect"):
            validate_platform_registry(mismatch)

    def test_descriptors_expose_registry_inspection_capability(self) -> None:
        for platform_id in EXPECTED_PLATFORM_IDS:
            with self.subTest(platform=platform_id):
                descriptor = descriptor_for_platform(platform_id)
                self.assertEqual(
                    descriptor.capabilities["inspect"],
                    platform_id in INSPECTION_PLATFORM_IDS,
                )

    def test_resource_types_identity_profiles_and_security_shape(self) -> None:
        registry = load_platform_registry()
        for platform in registry["platforms"]:
            self.assertTrue(set(platform["resource_types"]) <= LEGAL_RESOURCE_TYPES)
            profile = platform["identity_profile"]
            self.assertEqual(
                set(profile["strong_identity_sources"]),
                {"native_id", "isbn", "doi", "canonical_url"},
            )
            self.assertEqual(set(profile["weak_identity_fields"]), {"title", "creator", "edition"})
            self.assertTrue(profile["canonical_url"]["remove_fragment"])

        serialized = json.dumps(registry, ensure_ascii=False)
        self.assertIsNone(re.search(r"(?:^|[\\/])(?:Users|home|tmp)[\\/]", serialized))
        self.assertNotIn("file://", serialized.lower())
        self.assertNotIn("data:", serialized.lower())

    def test_url_identity_profiles_are_exact_and_match_builtin_fallbacks(self) -> None:
        registry = load_platform_registry()
        profiles = {
            item["platform_id"]: item["identity_profile"]["canonical_url"]["removable_query_parameters"]
            for item in registry["platforms"]
        }

        self.assertEqual(set(profiles), set(EXPECTED_REMOVABLE_QUERY_PARAMETERS))
        for platform_id, expected in EXPECTED_REMOVABLE_QUERY_PARAMETERS.items():
            self.assertEqual(set(profiles[platform_id]), expected, platform_id)

            builtin = get_url_identity_profile(platform_id)
            if platform_id == "generic":
                self.assertIsNone(builtin)
            elif builtin is None:
                self.assertEqual(expected, set(), platform_id)
            else:
                self.assertEqual(set(builtin.remove_query_keys), expected, platform_id)

        smartedu_url = (
            "https://basic.smartedu.cn/resource?contentId=book-1&catalogType=tchMaterial#shared"
        )
        self.assertEqual(
            normalize_url(smartedu_url, platform="smartedu"),
            "https://basic.smartedu.cn/resource?contentId=book-1&catalogType=tchMaterial",
        )

    def test_loader_rejects_a_known_key_on_the_wrong_platform(self) -> None:
        registry = load_platform_registry()
        wrong_platform_profile = next(
            item for item in registry["platforms"] if item["platform_id"] == "bilibili"
        )
        wrong_platform_profile["identity_profile"]["canonical_url"]["removable_query_parameters"] = [
            "utm_source"
        ]
        with self.assertRaises(PlatformRegistryError):
            validate_platform_registry(registry)

    def test_loader_rejects_duplicate_ids_illegal_types_and_unsafe_fields(self) -> None:
        registry = load_platform_registry()

        duplicate = copy.deepcopy(registry)
        duplicate["platforms"][1]["platform_id"] = duplicate["platforms"][0]["platform_id"]
        with self.assertRaises(PlatformRegistryError):
            validate_platform_registry(duplicate)

        illegal_type = copy.deepcopy(registry)
        illegal_type["platforms"][0]["resource_types"] = ["pdf"]
        with self.assertRaises(PlatformRegistryError):
            validate_platform_registry(illegal_type)

        inspect_enabled = copy.deepcopy(registry)
        wrong_inspection_platform = next(
            item for item in inspect_enabled["platforms"] if item["platform_id"] == "cctv"
        )
        wrong_inspection_platform["capabilities"]["inspect"] = True
        wrong_inspection_platform["inspection"]["supported"] = True
        with self.assertRaisesRegex(PlatformRegistryError, "extra=.*cctv"):
            validate_platform_registry(inspect_enabled)

        unsafe = copy.deepcopy(registry)
        unsafe["platforms"][0]["session_token"] = "must-not-be-present"
        with self.assertRaises(PlatformRegistryError):
            validate_platform_registry(unsafe)

    def test_loader_returns_a_copy(self) -> None:
        first = load_platform_registry()
        first["platforms"][0]["display_name"] = "mutated"
        second = load_platform_registry()
        self.assertNotEqual(second["platforms"][0]["display_name"], "mutated")


if __name__ == "__main__":
    unittest.main()

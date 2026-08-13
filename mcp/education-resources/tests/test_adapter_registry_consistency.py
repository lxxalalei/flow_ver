"""Machine checks that built-in adapters and the Platform Registry agree."""

from __future__ import annotations

import importlib
import unittest

from education_resource_mcp.adapters.base import (
    AdapterDescriptor,
    descriptor_for_platform,
)
from education_resource_mcp.retrieval.registry import EXPECTED_PLATFORM_IDS
from education_resource_mcp.search import (
    GenericWebSearchProvider,
    MultiPlatformSearchProvider,
    SearXNGSearchProvider,
)


ADAPTER_CLASSES = {
    "bilibili": ("bilibili", "BilibiliSearchAdapter"),
    "douyin": ("douyin", "DouyinSearchAdapter"),
    "zhihu": ("zhihu", "ZhihuSearchAdapter"),
    "smartedu": ("smartedu", "SmartEduSearchAdapter"),
    "ximalaya": ("ximalaya", "XimalayaSearchAdapter"),
    "cctv": ("cctv", "CctvSearchAdapter"),
    "yixi": ("yixi", "YixiSearchAdapter"),
    "kepu": ("kepu", "KepuSearchAdapter"),
    "baiduwenku": ("baiduwenku", "BaiduwenkuSearchAdapter"),
    "runoob": ("runoob", "RunoobSearchAdapter"),
    "nlc": ("nlc", "NlcSearchAdapter"),
    "open163": ("open163", "Open163SearchAdapter"),
    "annas-archive": ("annas_archive", "AnnasArchiveSearchAdapter"),
    "weibo": ("weibo", "WeiboSearchAdapter"),
    "wechat": ("wechat", "WechatSearchAdapter"),
    "shuge": ("shuge", "ShugeSearchAdapter"),
}


class AdapterRegistryConsistencyTests(unittest.TestCase):
    def test_all_active_platforms_have_exact_descriptors(self) -> None:
        self.assertEqual(set(ADAPTER_CLASSES) | {"generic"}, EXPECTED_PLATFORM_IDS)

        for platform_id, (module_name, class_name) in ADAPTER_CLASSES.items():
            with self.subTest(platform=platform_id):
                module = importlib.import_module(
                    f"education_resource_mcp.adapters.{module_name}"
                )
                adapter_class = getattr(module, class_name)
                descriptor = adapter_class.descriptor
                self.assertIsInstance(descriptor, AdapterDescriptor)
                self.assertEqual(adapter_class.platform_id, platform_id)
                self.assertEqual(descriptor.platform_id, platform_id)
                self.assertEqual(descriptor, descriptor_for_platform(platform_id))
                hash(descriptor)

    def test_generic_backends_share_the_registry_descriptor(self) -> None:
        expected = descriptor_for_platform("generic")
        self.assertEqual(GenericWebSearchProvider.descriptor, expected)
        self.assertEqual(SearXNGSearchProvider.descriptor, expected)

    def test_registration_requires_descriptors_only_for_builtins(self) -> None:
        provider = object.__new__(MultiPlatformSearchProvider)
        provider._adapters = {}

        class LegacyStub:
            platform_id = "legacy"

        legacy = LegacyStub()
        provider.register_adapter(legacy)
        self.assertIs(provider._adapters["legacy"], legacy)
        with self.assertRaises(TypeError):
            provider.register_adapter(legacy, require_descriptor=True)

        class MismatchedStub:
            platform_id = "bilibili"
            descriptor = descriptor_for_platform("generic")

        with self.assertRaises(ValueError):
            provider.register_adapter(MismatchedStub(), require_descriptor=True)


if __name__ == "__main__":
    unittest.main()

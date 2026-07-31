"""Bilibili WBI signing helper.

实现 B站 Web 接口的 WBI 签名算法，用于搜索 API 鉴权。
参考：https://github.com/SocialSisterYi/bilibili-API-collect
"""

from __future__ import annotations

import hashlib
from urllib.parse import urlencode

# WBI 密钥表（固定排列，用于混淆原密钥）
WBI_KEY_TABLE = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]


def wbi_sign(params: dict, img_key: str, sub_key: str) -> dict:
    """对请求参数添加 WBI 签名。

    Args:
        params: 原始请求参数（不含 w_rid 和 wts）
        img_key: 从 nav API 获取的 img_url 提取的 key
        sub_key: 从 nav API 获取的 sub_url 提取的 key

    Returns:
        添加了 wts 和 w_rid 的完整参数字典
    """
    import time

    # 混淆密钥
    mixin_key = _get_mixin_key(img_key + sub_key)

    # 添加时间戳
    params = dict(params)
    params["wts"] = int(time.time())

    # 按 key 排序后拼接
    query = urlencode(sorted(params.items()))

    # 计算 MD5 签名
    w_rid = hashlib.md5((query + mixin_key).encode()).hexdigest()
    params["w_rid"] = w_rid

    return params


def _get_mixin_key(orig: str) -> str:
    """通过 WBI_KEY_TABLE 混淆原始密钥。"""
    return "".join(orig[i] for i in WBI_KEY_TABLE[:64])[:32]

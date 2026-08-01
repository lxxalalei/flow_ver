"""Bilibili WBI signing algorithm.

Implements the WBI signature used by Bilibili's web search API for
request authentication.  Ported verbatim from the legacy script
``legacy/.../bilibili/wbi_sign.py``; pure stdlib (``hashlib`` +
``urllib.parse``).

Reference: https://github.com/SocialSisterYi/bilibili-API-collect
"""

from __future__ import annotations

import hashlib
import time
from urllib.parse import urlencode


# Fixed permutation table used to derive the mixin key from the raw
# img/sub keys fetched from the nav API.
WBI_KEY_TABLE = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]


def _get_mixin_key(orig: str) -> str:
    """Derive the 32-char mixin key from *orig* using the fixed table."""
    return "".join(orig[i] for i in WBI_KEY_TABLE[:64])[:32]


def wbi_sign(params: dict, img_key: str, sub_key: str) -> dict:
    """Sign request *params* with WBI, adding ``wts`` and ``w_rid``.

    Args:
        params: original request parameters (without ``w_rid`` / ``wts``).
        img_key: key extracted from the nav API ``wbi_img.img_url``.
        sub_key: key extracted from the nav API ``wbi_img.sub_url``.

    Returns:
        A new dict with all original params plus ``wts`` (timestamp) and
        ``w_rid`` (MD5 signature).
    """
    mixin_key = _get_mixin_key(img_key + sub_key)
    signed = dict(params)
    signed["wts"] = int(time.time())
    query = urlencode(sorted(signed.items()))
    signed["w_rid"] = hashlib.md5((query + mixin_key).encode()).hexdigest()
    return signed

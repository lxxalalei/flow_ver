#!/usr/bin/env python3
"""SmartEdu 全资源下载器。

支持从 SmartEdu 详情页链接或资源 ID 下载所有类型资源：
  - PDF 文档（教材、课件、教学设计等）
  - m3u8 视频（精品课、同步课堂等课程视频）
  - MP3/OGG 音频（课文朗读、诵读库）
  - JPG 图片、白板、SRT 字幕

核心机制（参考 hantang/smartedu-dl-go）：
  1. 解析详情页 URL → 提取 catalog + resource_id
  2. 裸 GET（无业务 header）获取详情 JSON
  3. 解析 ResourceItemExt → 提取 relations.* 中的所有 ResourceItem
  4. 每个 ResourceItem 的 ti_items → 提取下载链接
  5. 私有 CDN URL → 转为公开 CDN URL
  6. m3u8 视频 → TS 分片下载 + AES-CBC 解密 + 合并

用法：
  # 下载整课（视频+课件+字幕等全部资源）
  python smartedu_download.py download "https://basic.smartedu.cn/qualityCourse?courseId=xxx"

  # 下载教材 PDF
  python smartedu_download.py download "https://basic.smartedu.cn/tchMaterial/detail?contentType=assets_document&contentId=xxx"

  # 只列出可用资源（不下载）
  python smartedu_download.py list "https://basic.smartedu.cn/qualityCourse?courseId=xxx"

  # 指定输出目录
  python smartedu_download.py download "https://..." --output-dir ./downloads

  # 只下载特定格式
  python smartedu_download.py download "https://..." --formats pdf,m3u8

  # 指定 m3u8 下载并发数和输出格式
  python smartedu_download.py download "https://..." --video-concurrency 8 --video-output mp4

架构详情（含下载流程图、CDN 认证机制、错误处理策略）见 ``../references/architecture.md``。
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# 添加脚本目录到路径
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

SKILLS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SKILLS_ROOT / "resource-platforms" / "scripts"))
sys.path.insert(0, str(SKILLS_ROOT / "resource-platforms" / "scripts" / "smartedu"))

from shared.logger import getLogger
log = getLogger("smartedu")

from _auth_http import bare_request_json, load_local_env
from _text_utils import norm

# 加载 .env.local（含 SMARTEDU_ACCESS_TOKEN 等）
load_local_env()

# ============================================================================
# 常量
# ============================================================================

SERVER_LIST = ("s-file-1", "s-file-2", "s-file-3")

# catalog → 详情 JSON URL 模板
RESOURCES_MAP: dict[str, dict[str, Any]] = {
    "/tchMaterial/detail": {
        "name": "教材",
        "param": "contentId",
        "require_content_type": "assets_document",
        "basic": "https://{server}.ykt.cbern.com.cn/zxx/ndrv2/resources/tch_material/details/{id}.json",
        "backup": [
            "https://{server}.ykt.cbern.com.cn/zxx/ndrs/special_edu/resources/details/{id}.json",
            "https://{server}.ykt.cbern.com.cn/zxx/ndrs/resources/tch_material/details/{id}.json",
        ],
        "audio": "https://{server}.ykt.cbern.com.cn/zxx/ndrs/resources/{id}/relation_audios.json",
    },
    "/syncClassroom/classActivity": {
        "name": "学生自主学习/课程包",
        "param": "activityId",
        "basic": "https://{server}.ykt.cbern.com.cn/zxx/ndrv2/national_lesson/resources/details/{id}.json",
    },
    "/syncClassroom/prepare/detail": {
        "name": "教师备课",
        "param": "resourceId",
        "basic": "https://{server}.ykt.cbern.com.cn/zxx/ndrv2/prepare_sub_type/resources/details/{id}.json",
    },
    "/qualityCourse": {
        "name": "精品课",
        "param": "courseId",
        "basic": "https://{server}.ykt.cbern.com.cn/zxx/ndrv2/resources/{id}.json",
    },
}

# 支持的格式列表（与 Go 项目一致）
SUPPORTED_FORMATS = ["pdf", "mp3", "ogg", "jpg", "whiteboard", "srt", "m3u8"]

# HTTP User-Agent（模拟 Go 项目 Go-http-client/1.1）
M3U8_USER_AGENT = "Go-http-client/1.1"

def fulfill_token(token: str | None) -> str | None:
    """将 Access Token 包装为 x-nd-auth 完整格式。

    参考 Go 项目 util.FulfillToken：
      MAC id="<ACCESS_TOKEN>",nonce="0",mac="0"
    """
    if not token:
        return None
    token = token.strip()
    if not token:
        return None
    if not token.startswith("MAC id"):
        token = f'MAC id="{token}",nonce="0",mac="0"'
    return token


def build_auth_headers(access_token: str | None) -> dict[str, str]:
    """构建带认证的 headers（用于私有 CDN 文件下载）。

    SmartEdu 私有 CDN 需要 Authorization Bearer + accessToken 双重 header：
      Authorization: Bearer <ACCESS_TOKEN>
      accessToken: <ACCESS_TOKEN>

    注意：Go 项目用的 x-nd-auth MAC 格式只对教材 PDF 有效，
    课件/视频等其他资源必须用 Bearer + accessToken 方式。
    """
    headers: dict[str, str] = {"User-Agent": M3U8_USER_AGENT}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
        headers["accessToken"] = access_token
    return headers

# AES 解密需要 PyCryptodome（或 cryptography）
_HAS_CRYPTO = False
try:
    from Crypto.Cipher import AES  # type: ignore

    _HAS_CRYPTO = True
except ImportError:
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes  # type: ignore

        _HAS_CRYPTO = True
    except ImportError:
        pass


# ============================================================================
# URL 解析
# ============================================================================


def parse_detail_url(url: str) -> dict[str, str]:
    """解析 SmartEdu 详情页 URL，提取 catalog path 和 resource id。

    支持：
      https://basic.smartedu.cn/tchMaterial/detail?contentType=assets_document&contentId=xxx
      https://basic.smartedu.cn/qualityCourse?courseId=xxx&chapterId=yyy
      https://basic.smartedu.cn/syncClassroom/classActivity?activityId=xxx
      https://basic.smartedu.cn/syncClassroom/prepare/detail?resourceId=xxx
    """
    parsed = urllib.parse.urlparse(url)
    path = parsed.path
    query = urllib.parse.parse_qs(parsed.query)

    # 匹配已知 catalog path
    for catalog_path, config in RESOURCES_MAP.items():
        if path == catalog_path:
            param = config["param"]
            resource_id = query.get(param, [""])[0]
            content_type = query.get("contentType", [""])[0]
            if config.get("require_content_type") and content_type != config["require_content_type"]:
                raise ValueError(
                    f"tchMaterial 需要 contentType=assets_document，当前为 {content_type}"
                )
            if not resource_id:
                raise ValueError(f"URL 缺少 {param} 参数: {url}")
            return {
                "catalog_path": catalog_path,
                "catalog_name": config["name"],
                "resource_id": resource_id,
                "param_name": param,
            }

    # 也可能是直接给资源 ID
    raise ValueError(f"无法识别的 SmartEdu URL 路径: {path}\n支持: {list(RESOURCES_MAP.keys())}")


def build_detail_json_urls(catalog_path: str, resource_id: str, use_backup: bool = True) -> list[str]:
    """构建详情 JSON URL 列表（多个 server + 可选 backup 模板）。"""
    config = RESOURCES_MAP[catalog_path]
    urls: list[str] = []
    for server in SERVER_LIST:
        urls.append(config["basic"].format(server=server, id=resource_id))
    if use_backup:
        for backup_template in config.get("backup", []):
            for server in SERVER_LIST:
                url = backup_template.format(server=server, id=resource_id)
                if url not in urls:
                    urls.append(url)
    return urls


def fetch_detail_json(catalog_path: str, resource_id: str, timeout: int = 20) -> dict[str, Any]:
    """获取详情 JSON（裸 GET，多个 server + backup 轮询）。"""
    urls = build_detail_json_urls(catalog_path, resource_id)
    errors: list[str] = []
    for url in urls:
        try:
            data = bare_request_json(url, timeout=timeout)
            if isinstance(data, dict):
                return data
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            errors.append(f"{url}: {exc}")
    raise RuntimeError(f"获取详情 JSON 失败:\n" + "\n".join(errors))


# ============================================================================
# 资源提取（从详情 JSON 中提取所有可下载文件）
# ============================================================================


def convert_cdn_url(raw_url: str, to_public: bool = True) -> str:
    """私有 CDN → 公开 CDN 转换。

    参考 Go 项目 convertURL：
      r*-ndr-private.ykt.cbern.com.cn → r*-ndr.ykt.cbern.com.cn
      /xxx.pkg/xxx_timestamp.pdf → /xxx.pdf
    """
    link = raw_url
    # 简化 .pkg/filename.pdf → .pdf
    link = re.sub(r"(/[\w\-]+)\.pkg/[\w\-]+\.pdf$", r"\1.pdf", link)
    if to_public:
        link = link.replace("ndr-private.", "ndr.")
    return link


def get_teacher_names(detail: dict[str, Any]) -> str:
    """从详情 JSON 提取教师名拼接。"""
    teachers = detail.get("teacher_list") or []
    names = [norm(t.get("name")) for t in teachers if isinstance(t, dict) and norm(t.get("name"))]
    return " ".join(names)


def build_full_title(
    title: str,
    book_name: str = "",
    school_name: str = "",
    teacher_names: str = "",
    index: int = 0,
) -> str:
    """构建完整的资源标题。

    格式：教材名-课程名 (学校_教师)
    """
    base = title
    if book_name:
        base = f"{book_name}-{title}" if title else book_name
    suffix_parts: list[str] = []
    if school_name:
        suffix_parts.append(school_name)
    if teacher_names:
        suffix_parts.append(teacher_names)
    if suffix_parts:
        base = f"{base} ({ '_'.join(suffix_parts) })"
    if not base:
        base = f"未命名-{index:03d}"
    # 文件名安全化
    return sanitize_filename(base)


def sanitize_filename(name: str) -> str:
    """文件名安全化：去除非法字符。"""
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    if not name:
        name = "unnamed"
    return name[:200]  # 限制长度


def parse_resource_items(
    detail: dict[str, Any],
    format_list: list[str],
    use_random_server: bool = False,
) -> list[dict[str, Any]]:
    """从详情 JSON 解析出所有可下载资源。

    返回列表中每个元素：
      {
        "format": "pdf" | "m3u8" | ...,
        "title": "...",
        "raw_url": "私有 CDN 原始 URL",
        "backup_url": "公开 CDN URL",
        "size": int,
        "id": "...",
        "ti_item": {...},  # 原始 ti_item
      }
    """
    result: list[dict[str, Any]] = []
    teacher_names = get_teacher_names(detail)
    custom = detail.get("custom_properties") if isinstance(detail.get("custom_properties"), dict) else {}
    school_name = norm(custom.get("school_name"))
    book_info = custom.get("teachingmaterial_info") or {}
    book_name = norm(book_info.get("title")) if isinstance(book_info, dict) else ""

    # 提取 ResourceItem 列表
    items: list[dict[str, Any]] = []
    relations = detail.get("relations") if isinstance(detail.get("relations"), dict) else {}

    # 课程类：从 relations 中提取
    for relation_key in ("national_course_resource", "course_resource"):
        relation_items = relations.get(relation_key)
        if isinstance(relation_items, list) and relation_items:
            items = relation_items
            break

    # 教材类：detail 本身就是 ResourceItem（有 ti_items）
    if not items and isinstance(detail.get("ti_items"), list):
        items = [detail]

    # 处理每个 ResourceItem
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue

        item_custom = item.get("custom_properties") if isinstance(item.get("custom_properties"), dict) else {}
        title = norm(item_custom.get("original_title")) or norm(item.get("title"))
        alias = norm(item_custom.get("alias_name"))
        if alias:
            title = f"{title}-{alias}" if title else alias

        if not title:
            resource_type = norm(item.get("resource_type_code_name"))
            title = f"{resource_type}-{i:03d}" if resource_type else f"未命名-{i:03d}"

        # 遍历 ti_items
        ti_items = item.get("ti_items") or []
        for ti_item in ti_items:
            if not isinstance(ti_item, dict):
                continue
            fmt = norm(ti_item.get("ti_format") or ti_item.get("lc_ti_format")).lower()
            # 格式标准化
            if fmt in {"application/x-mpegurl", "application/vnd.apple.mpegurl"}:
                fmt = "m3u8"
            if "/" in fmt:
                fmt = fmt.rsplit("/", 1)[-1]
            if fmt == "jpeg":
                fmt = "jpg"

            if fmt not in format_list:
                continue

            storages = ti_item.get("ti_storages") or []
            if not storages:
                continue

            # 随机或固定选择第一个存储
            storage_idx = 0
            raw_url = storages[storage_idx] if storages else ""
            if not raw_url:
                continue

            # 获取文件大小
            size = ti_item.get("ti_size", 0) or 0
            ti_custom = ti_item.get("custom_properties") or {}
            for req in ti_custom.get("requirements") or []:
                if isinstance(req, dict) and req.get("name") == "total_size":
                    try:
                        size = int(req.get("value", 0))
                    except (ValueError, TypeError):
                        pass

            backup_url = convert_cdn_url(raw_url, to_public=True)
            full_title = build_full_title(title, book_name, school_name, teacher_names, i)

            result.append(
                {
                    "format": fmt,
                    "title": full_title,
                    "raw_url": raw_url,
                    "backup_url": backup_url,
                    "size": size,
                    "id": norm(item.get("id")),
                    "ti_item": ti_item,
                }
            )

    # 去重
    result = deduplicate(result)
    # 重名处理
    result = resolve_name_conflicts(result)
    return result


def deduplicate(resources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 URL path 去重。"""
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for res in resources:
        try:
            parsed = urllib.parse.urlparse(res["backup_url"])
            key = parsed.path
        except Exception:
            key = res["backup_url"]
        if key not in seen:
            seen.add(key)
            unique.append(res)
    return unique


def resolve_name_conflicts(resources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """处理同名资源，添加序号或 ID 后缀。"""
    counts: dict[str, int] = {}
    result: list[dict[str, Any]] = []
    for res in resources:
        key = res["title"]
        if counts.get(key, 0) > 0:
            new_title = ""
            if res.get("id"):
                new_title = f"{res['title']}_{res['id'][:8]}"
            else:
                idx = 1
                while True:
                    new_title = f"{res['title']} ({idx})"
                    if counts.get(new_title, 0) == 0:
                        break
                    idx += 1
            res = dict(res)
            res["title"] = new_title
            key = new_title
        result.append(res)
        counts[key] = counts.get(key, 0) + 1
    return result


# ============================================================================
# 通用文件下载
# ============================================================================


def download_file(url: str, save_path: Path, timeout: int = 60) -> bool:
    """下载普通文件（PDF/MP3/JPG 等）。"""
    request = Request(url, headers={"User-Agent": M3U8_USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                log.error("HTTP %s: %s", response.status, url)
                return False
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, "wb") as f:
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
            return True
    except (HTTPError, URLError, TimeoutError) as exc:
        log.error("%s: %s", exc, url)
        return False


def try_download_with_fallback(
    raw_url: str, backup_url: str, save_path: Path, access_token: str | None = None
) -> bool:
    """尝试下载：有 token → 私有 CDN 优先；无 token → 公开 CDN 优先。

    参考 Go 项目 download_manager.go 的 BackupURL/RawURL 策略：
    有 auth header 时用 RawURL（私有 CDN），否则用 BackupURL（公开 CDN）。
    """
    # 有 token → 私有 CDN 优先（Go 项目策略）
    if access_token:
        headers = build_auth_headers(access_token)
        request = Request(raw_url, headers=headers)
        try:
            with urlopen(request, timeout=120) as response:
                if response.status == 200:
                    save_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(save_path, "wb") as f:
                        while True:
                            chunk = response.read(65536)
                            if not chunk:
                                break
                            f.write(chunk)
                    return True
        except (HTTPError, URLError, TimeoutError):
            pass  # 私有 CDN 失败，fallback 到公开 CDN

    # 公开 CDN（backup_url）
    if download_file(backup_url, save_path):
        return True

    # 无 token 但公开 CDN 也失败 → 尝试私有 CDN（不带 token）
    if raw_url != backup_url:
        if download_file(raw_url, save_path):
            return True

    return False


# ============================================================================
# M3U8 视频下载（TS 分片 + AES-CBC 解密 + 合并）
# ============================================================================


def _aes_ecb_decrypt(ciphertext: bytes, key: bytes) -> bytes:
    """AES-ECB 解密 + PKCS7 去填充。"""
    try:
        from Crypto.Cipher import AES

        cipher = AES.new(key, AES.MODE_ECB)
        plaintext = cipher.decrypt(ciphertext)
    except ImportError:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        cipher = Cipher(algorithms.AES(key), modes.ECB())
        decryptor = cipher.decryptor()
        plaintext = decryptor.update(ciphertext) + decryptor.finalize()

    # PKCS7 去填充
    if plaintext:
        pad_len = plaintext[-1]
        if 0 < pad_len <= 16:
            plaintext = plaintext[:-pad_len]
    return plaintext


def _aes_cbc_decrypt(ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
    """AES-CBC 解密 + PKCS7 去填充。"""
    try:
        from Crypto.Cipher import AES

        cipher = AES.new(key, AES.MODE_CBC, iv)
        plaintext = cipher.decrypt(ciphertext)
    except ImportError:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        plaintext = decryptor.update(ciphertext) + decryptor.finalize()

    # PKCS7 去填充
    if plaintext:
        pad_len = plaintext[-1]
        if 0 < pad_len <= 16:
            plaintext = plaintext[:-pad_len]
    return plaintext


def _md5_hex(text: str) -> str:
    """MD5 哈希，返回十六进制字符串。"""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _get_json_key(url: str, key: str, headers: dict[str, str] | None = None) -> str:
    """GET 一个 JSON，返回指定 key 的值。

    对于 ndvideo-key.ykt.eduyun.cn 的密钥交换接口，不加 auth header
    （加了反而 403），使用裸 GET。
    """
    # ndvideo-key 接口不能用 Authorization header，必须裸 GET
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    if host.startswith("ndvideo-key"):
        req_headers: dict[str, str] = {"User-Agent": M3U8_USER_AGENT}
    else:
        req_headers = headers or {"User-Agent": M3U8_USER_AGENT}
    request = Request(url, headers=req_headers)
    with urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data.get(key, "")


def get_decryption_key(key_url: str, key_id: str, headers: dict[str, str]) -> bytes:
    """获取视频解密 key。

    SmartEdu 视频使用自定义密钥交换协议：
    1. GET {key_url}/signs → {"nonce": "..."}
    2. sign = MD5(nonce + key_id)[:16]
    3. GET {key_url}?nonce=...&sign=... → {"key": "base64..."}
    4. AES-ECB 解密 base64(key) 得到最终 key
    """
    sign_url = key_url.rstrip("/") + "/signs"
    nonce = _get_json_key(sign_url, "nonce", headers)
    if not nonce:
        raise RuntimeError(f"获取 nonce 失败: {sign_url}")

    sign = _md5_hex(nonce + key_id)[:16]
    key_id_url = f"{key_url}?nonce={urllib.parse.quote(nonce)}&sign={sign}"
    key_data = _get_json_key(key_id_url, "key", headers)
    if not key_data:
        raise RuntimeError(f"获取 key 数据失败: {key_id_url}")

    import base64

    key_text = base64.b64decode(key_data)
    decryption_key = _aes_ecb_decrypt(key_text, sign.encode("utf-8"))
    return decryption_key


def parse_m3u8_playlist(content: str) -> dict[str, Any]:
    """解析 M3U8 播放列表，提取分段 URL 和加密信息。

    返回:
      {
        "segments": ["url1", "url2", ...],
        "key_url": "...",  # EXT-X-KEY URI（如有加密）
        "key_id": "...",   # key URL 最后一段
        "iv": bytes/None,  # IV（如有）
        "method": "AES-128"/"NONE",
      }
    """
    lines = content.strip().split("\n")
    segments: list[str] = []
    key_url = ""
    key_id = ""
    iv: bytes | None = None
    method = "NONE"

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXT-X-KEY"):
            # #EXT-X-KEY:METHOD=AES-128,URI="https://...",IV=0x...
            method_match = re.search(r'METHOD=([^,]+)', line)
            if method_match:
                method = method_match.group(1).strip()
            uri_match = re.search(r'URI="([^"]+)"', line)
            if uri_match:
                key_url = uri_match.group(1)
                # key_id = key_url 最后一段
                key_id = key_url.rstrip("/").rsplit("/", 1)[-1]
            iv_match = re.search(r'IV=0x([0-9a-fA-F]+)', line)
            if iv_match:
                iv = bytes.fromhex(iv_match.group(1))
        elif not line.startswith("#"):
            # 这是一个分段的 URL
            segments.append(line)

    return {
        "segments": segments,
        "key_url": key_url,
        "key_id": key_id,
        "iv": iv,
        "method": method,
    }


def download_ts_segment(
    segment_url: str, save_path: Path, headers: dict[str, str], timeout: int = 60
) -> bool:
    """下载单个 TS 分片。

    SmartEdu 对象存储在高并发时会返回 400 InvalidArgument，
    本函数内置多主机轮转 + 指数退避重试。
    """
    # 提取主机前缀（如 r1-ndr-private），用于切换 r1/r2/r3
    parsed = urllib.parse.urlparse(segment_url)
    host = parsed.hostname or ""
    # r1-ndr-private → (r1, ndr-private)
    host_prefix = ""
    host_suffix = ""
    m = re.match(r"(r[123])-(ndr(?:-private)?)", host)
    if m:
        host_prefix = m.group(1)  # r1
        host_suffix = m.group(2)  # ndr-private

    # 构建候选主机列表（轮换顺序）
    host_candidates = [host]
    if host_prefix:
        for prefix in ["r1", "r2", "r3"]:
            alt_host = f"{prefix}-{host_suffix}"
            if alt_host not in host_candidates:
                host_candidates.append(alt_host)

    last_error: Exception | None = None
    for attempt in range(4):  # 最多4次尝试
        # 每次尝试用不同的主机
        idx = attempt % len(host_candidates)
        try_host = host_candidates[idx]
        attempt_url = segment_url.replace(host, try_host, 1) if try_host != host else segment_url

        try:
            request = Request(attempt_url, headers=headers)
            with urlopen(request, timeout=timeout) as response:
                if response.status != 200:
                    last_error = HTTPError(attempt_url, response.status, "non-200", response.headers, None)
                    continue
                with open(save_path, "wb") as f:
                    while True:
                        chunk = response.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                return True
        except (HTTPError, URLError, TimeoutError) as exc:
            last_error = exc
            # 400 时切换主机，其他错误也要重试
            import time as _time
            _time.sleep(0.3 * (attempt + 1))
    return False


def download_m3u8_video(
    m3u8_url: str,
    save_path: Path,
    headers: dict[str, str] | None = None,
    max_concurrency: int = 5,
    timeout: int = 60,
) -> bool:
    """下载 M3U8 视频：获取播放列表 → 解密 → 并发下载 TS → 合并。

    参考 Go 项目 DownloadM3U8 实现。
    """
    headers = headers or {"User-Agent": M3U8_USER_AGENT}
    save_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. 获取 M3U8 播放列表
    log.info("获取播放列表...")
    request = Request(m3u8_url, headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                log.error("获取 M3U8 失败: HTTP %s", response.status)
                return False
            m3u8_content = response.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError) as exc:
        log.error("获取 M3U8 失败: %s", exc)
        return False

    # 2. 解析播放列表
    playlist = parse_m3u8_playlist(m3u8_content)
    segments = playlist["segments"]
    if not segments:
        log.error("播放列表中无分段")
        return False
    log.info("播放列表解析完成: %d 个分段", len(segments))

    # 构建 segment URL（处理相对路径）
    base_url = m3u8_url[: m3u8_url.rfind("/") + 1]
    segment_urls: list[str] = []
    for seg in segments:
        if seg.startswith("http"):
            segment_urls.append(seg)
        else:
            segment_urls.append(base_url + seg)

    # 3. 获取解密 key（如果加密）
    key: bytes | None = None
    iv = playlist["iv"]
    if playlist["key_url"]:
        log.info("视频已加密，获取解密密钥...")
        try:
            key = get_decryption_key(playlist["key_url"], playlist["key_id"], headers)
            log.info("解密密钥获取成功 (%d bytes)", len(key))
        except Exception as exc:
            log.error("获取解密密钥失败: %s", exc)
            return False
    else:
        log.info("视频未加密")

    # 4. 并发下载 TS 分片
    log.info("开始下载 %d 个分片（并发=%d）...", len(segment_urls), max_concurrency)
    temp_dir = save_path.parent / f".{save_path.stem}_ts_temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    failed_indices: list[int] = []

    def _download_one(index_url: tuple[int, str]) -> tuple[int, bool]:
        index, url = index_url
        ts_path = temp_dir / f"{index:05d}.ts"
        if ts_path.exists() and ts_path.stat().st_size > 0:
            return index, True
        # 首次尝试 + 2次即时重试
        for attempt in range(3):
            ok = download_ts_segment(url, ts_path, headers, timeout)
            if ok:
                return index, True
            import time as _time
            _time.sleep(0.3 * (attempt + 1))
        return index, False

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrency) as executor:
        futures = {
            executor.submit(_download_one, (i, url)): i
            for i, url in enumerate(segment_urls)
        }
        completed = 0
        for future in concurrent.futures.as_completed(futures):
            index, ok = future.result()
            completed += 1
            if completed % 10 == 0 or completed == len(segment_urls):
                log.info("进度: %d/%d (%d%%)", completed, len(segment_urls), completed*100//len(segment_urls))
            if not ok:
                failed_indices.append(index)

    if failed_indices:
        # 重试所有失败的分片（逐个重试，降低并发避免限流）
        max_retries = 3
        for retry_round in range(max_retries):
            if not failed_indices:
                break
            log.info("重试 %d/%d: %d 个分片重试中...", retry_round+1, max_retries, len(failed_indices))
            still_failed: list[int] = []
            for idx in failed_indices:
                url = segment_urls[idx]
                ts_path = temp_dir / f"{idx:05d}.ts"
                # 重试时增加超时和延迟
                if download_ts_segment(url, ts_path, headers, timeout * 2):
                    pass  # 成功
                else:
                    still_failed.append(idx)
            failed_indices = still_failed
            if failed_indices and retry_round < max_retries - 1:
                import time as _time
                _time.sleep(1)  # 重试间隔
        if failed_indices:
            log.error("%d 个分片在 %d 次重试后仍失败", len(failed_indices), max_retries)
            return False

    # 5. 合并 + 解密
    log.info("合并 %d 个分片...", len(segment_urls))
    with open(save_path, "wb") as out:
        for i in range(len(segment_urls)):
            ts_path = temp_dir / f"{i:05d}.ts"
            ts_data = ts_path.read_bytes()
            if key is not None:
                # AES-CBC 解密
                if iv is None:
                    # 无 IV，使用分段序号作为 IV（常见做法）
                    iv = b"\x00" * 16
                ts_data = _aes_cbc_decrypt(ts_data, key, iv)
            out.write(ts_data)

    # 清理临时目录
    try:
        for ts_file in temp_dir.glob("*.ts"):
            ts_file.unlink()
        temp_dir.rmdir()
    except Exception:
        pass

    file_size = save_path.stat().st_size
    log.info("完成 %s (%.1f MB)", save_path.name, file_size / 1024 / 1024)
    return True


# ============================================================================
# 主下载流程
# ============================================================================


def get_unique_save_path(save_path: Path) -> Path:
    """如果文件已存在，添加 (1), (2) 等后缀。"""
    if not save_path.exists():
        return save_path
    stem = save_path.stem
    suffix = save_path.suffix
    parent = save_path.parent
    i = 1
    while True:
        candidate = parent / f"{stem} ({i}){suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def download_resource(
    resource: dict[str, Any],
    output_dir: Path,
    access_token: str | None = None,
    video_concurrency: int = 5,
) -> bool:
    """下载单个资源。"""
    fmt = resource["format"]
    title = resource["title"]
    raw_url = resource["raw_url"]
    backup_url = resource["backup_url"]
    size_mb = resource.get("size", 0) / 1024 / 1024

    ext = fmt if fmt != "m3u8" else "ts"  # m3u8 合并后输出为 ts（可直接播放）
    save_path = output_dir / f"{title}.{ext}"
    save_path = get_unique_save_path(save_path)

    size_str = f"{size_mb:.1f} MB" if size_mb > 0 else "未知大小"
    log.info("下载 [%s] %s (%s)", fmt.upper(), title, size_str)

    if fmt == "m3u8":
        # m3u8 视频特殊处理：有 token → 私有 CDN 优先
        headers = build_auth_headers(access_token) if access_token else {"User-Agent": M3U8_USER_AGENT}
        if access_token:
            # 有 token：私有 CDN 优先
            if download_m3u8_video(raw_url, save_path, headers, video_concurrency):
                return save_path.exists()
            # 私有 CDN 失败 → 公开 CDN
            if raw_url != backup_url:
                download_m3u8_video(backup_url, save_path, headers, video_concurrency)
        else:
            # 无 token：公开 CDN
            if download_m3u8_video(backup_url, save_path, headers, video_concurrency):
                return save_path.exists()
            # 公开 CDN 失败 → 尝试私有 CDN（不带 token）
            if raw_url != backup_url:
                download_m3u8_video(raw_url, save_path, headers, video_concurrency)
        return save_path.exists()
    else:
        # 普通文件下载
        return try_download_with_fallback(raw_url, backup_url, save_path, access_token)


def cmd_download(args: argparse.Namespace) -> None:
    """download 子命令：下载指定 URL 的所有资源。"""
    url = args.url
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    format_list = args.formats.split(",") if args.formats else list(SUPPORTED_FORMATS)

    # 检查 AES 解密库
    has_m3u8 = "m3u8" in format_list
    if has_m3u8 and not _HAS_CRYPTO:
        log.warning("未安装 PyCryptodome 或 cryptography 库，m3u8 视频解密功能不可用")
        log.warning("安装: pip install pycryptodome 或 pip install cryptography")
        format_list = [f for f in format_list if f != "m3u8"]
        if not format_list:
            log.error("没有可下载的格式")
            return

    access_token = os.environ.get("SMARTEDU_ACCESS_TOKEN") or getattr(args, "cookie", None)

    # 1. 解析 URL
    log.info("解析 URL: %s", url)
    try:
        parsed = parse_detail_url(url)
    except ValueError as exc:
        log.error("%s", exc)
        return
    catalog_name = parsed["catalog_name"]
    resource_id = parsed["resource_id"]
    log.info("类型: %s", catalog_name)
    log.info("资源ID: %s", resource_id)

    # 2. 获取详情 JSON
    log.info("获取详情 JSON...")
    try:
        detail = fetch_detail_json(parsed["catalog_path"], resource_id, timeout=args.timeout)
    except RuntimeError as exc:
        log.error("%s", exc)
        return

    # 3. 解析资源
    resources = parse_resource_items(detail, format_list)
    if not resources:
        log.info("未找到可下载的资源")
        log.info("尝试的格式: %s", format_list)
        # 打印所有 ti_format 让用户知道有哪些
        all_items = detail.get("ti_items") or []
        relations = detail.get("relations") if isinstance(detail.get("relations"), dict) else {}
        relation_items = []
        for key in ("national_course_resource", "course_resource"):
            items = relations.get(key, [])
            if items:
                relation_items = items
                break
        source_items = relation_items if relation_items else all_items
        if isinstance(source_items, list):
            for item in source_items[:3]:
                if isinstance(item, dict):
                    for ti in item.get("ti_items", []):
                        if isinstance(ti, dict):
                            log.info("可用格式: %s", ti.get('ti_format'))
        return

    log.info("找到 %d 个资源:", len(resources))
    for i, res in enumerate(resources, 1):
        size_str = f"{res['size'] / 1024 / 1024:.1f} MB" if res.get("size", 0) > 0 else "?"
        log.info("  %d. [%s] %s (%s)", i, res['format'].upper(), res['title'], size_str)

    if getattr(args, "list_only", False):
        return

    # 4. 下载
    log.info("开始下载到: %s", output_dir)
    success_count = 0
    fail_count = 0
    for res in resources:
        try:
            if download_resource(res, output_dir, access_token, args.video_concurrency):
                success_count += 1
            else:
                fail_count += 1
        except Exception as exc:
            log.error("%s: %s", res['title'], exc)
            fail_count += 1

    log.info("下载完成: 成功 %d, 失败 %d", success_count, fail_count)
    log.info("输出目录: %s", output_dir)


def cmd_list(args: argparse.Namespace) -> None:
    """list 子命令：列出可用资源但不下载。"""
    args.list_only = True
    args.formats = ""
    args.output_dir = "./smartedu_downloads"
    args.video_concurrency = 5
    if not hasattr(args, "cookie"):
        args.cookie = None
    cmd_download(args)


def cmd_formats(args: argparse.Namespace) -> None:
    """formats 子命令：列出某 URL 的所有可用格式。"""
    url = args.url
    try:
        parsed = parse_detail_url(url)
    except ValueError as exc:
        log.error("%s", exc)
        return

    log.info("获取详情 JSON...")
    try:
        detail = fetch_detail_json(parsed["catalog_path"], parsed["resource_id"], timeout=args.timeout)
    except RuntimeError as exc:
        log.error("%s", exc)
        return

    # 收集所有 ti_format
    formats_seen: dict[str, int] = {}
    items = detail.get("ti_items") or []
    relations = detail.get("relations") if isinstance(detail.get("relations"), dict) else {}
    relation_items = []
    for key in ("national_course_resource", "course_resource"):
        rel_items = relations.get(key, [])
        if rel_items:
            relation_items = rel_items
            break
    source_items = relation_items if relation_items else items
    if isinstance(source_items, list):
        for item in source_items:
            if isinstance(item, dict):
                for ti in item.get("ti_items", []):
                    if isinstance(ti, dict):
                        fmt = norm(ti.get("ti_format") or ti.get("lc_ti_format"))
                        formats_seen[fmt] = formats_seen.get(fmt, 0) + 1

    log.info("资源类型: %s", parsed['catalog_name'])
    log.info("资源ID: %s", parsed['resource_id'])
    log.info("可用格式:")
    for fmt, count in sorted(formats_seen.items(), key=lambda x: -x[1]):
        supported = "✓" if fmt in SUPPORTED_FORMATS else "✗"
        log.info("  %s %s: %d 个", supported, fmt, count)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SmartEdu 全资源下载器 — 支持视频/教材/音频/课件等所有资源类型",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 下载精品课全部资源（视频+课件+字幕）
  python smartedu_download.py download "https://basic.smartedu.cn/qualityCourse?courseId=xxx"

  # 下载教材 PDF
  python smartedu_download.py download "https://basic.smartedu.cn/tchMaterial/detail?contentType=assets_document&contentId=xxx"

  # 列出可用资源
  python smartedu_download.py list "https://basic.smartedu.cn/qualityCourse?courseId=xxx"

  # 查看所有可用格式
  python smartedu_download.py formats "https://basic.smartedu.cn/qualityCourse?courseId=xxx"

  # 只下载 PDF
  python smartedu_download.py download "https://..." --formats pdf

  # 指定输出目录和视频并发数
  python smartedu_download.py download "https://..." --output-dir ./downloads --video-concurrency 8
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # download
    dl_parser = subparsers.add_parser("download", help="下载资源")
    dl_parser.add_argument("url", help="SmartEdu 详情页 URL")
    dl_parser.add_argument("-o", "--output-dir", default="./smartedu_downloads", help="输出目录（默认: ./smartedu_downloads）")
    dl_parser.add_argument("-f", "--formats", default="", help="只下载指定格式（逗号分隔，如 pdf,m3u8）")
    dl_parser.add_argument("--video-concurrency", type=int, default=5, help="m3u8 视频下载并发数（默认: 5）")
    dl_parser.add_argument("--timeout", type=int, default=20, help="请求超时秒数")
    dl_parser.add_argument("--cookie", default=None, help="访问令牌/Cookie（可选，用于私有资源）")
    dl_parser.add_argument("--cdp", default=None, help="CDP URL（可选，本平台通常不需要）")
    dl_parser.set_defaults(func=cmd_download)

    # list
    list_parser = subparsers.add_parser("list", help="列出可用资源（不下载）")
    list_parser.add_argument("url", help="SmartEdu 详情页 URL")
    list_parser.add_argument("--timeout", type=int, default=20)
    list_parser.set_defaults(func=cmd_list)

    # formats
    fmt_parser = subparsers.add_parser("formats", help="查看某 URL 的所有可用格式")
    fmt_parser.add_argument("url", help="SmartEdu 详情页 URL")
    fmt_parser.add_argument("--timeout", type=int, default=20)
    fmt_parser.set_defaults(func=cmd_formats)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()

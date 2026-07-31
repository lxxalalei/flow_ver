"""Library Manager content and index deduplication engine.

提供三种互补的去重策略，按优先级自动组合使用：

1. **内容指纹去重（精确）** — 基于文件内容 hash（MD5/SHA256），
   字节级完全相同即为重复。适用于已下载到本地的资源文件。

2. **URL 结构化去重** — 基于 URL 域名 + 标准化路径的指纹，
   同一页面不同追踪参数视为重复。适用于搜索阶段同平台跨页去重。

3. **标题相似度去重（近似）** — 基于编辑距离 + Jaccard/TF-IDF
   相似度，标题高度相似即为可能重复。适用于跨平台语义近似检测。

去重处理策略（检测到重复后怎么办）：
  - ``keep_best_quality``（默认）：保留质量等级最高的版本
  - ``keep_earliest``：保留最早归档/获取的版本
  - ``keep_latest``：保留最新版本
  - ``mark_and_keep_all``：都保留，但在元数据中标记为重复

用法示例::

    from dedup import DedupEngine, DedupConfig

    engine = DedupEngine()                        # 使用默认配置
    # 或自定义
    config = DedupConfig(
        strategy="keep_best_quality",
        title_similarity_threshold=0.85,
        enable_content_fingerprint=True,
    )
    engine = DedupEngine(config)

    result = engine.check(new_resource, existing_resources)
    if result.is_duplicate:
        print(f"与 {result.matched_resource_id} 重复，策略: {result.match_type}")

    # 批量去重
    groups = engine.find_duplicates(all_resources)
    for group in groups:
        action = engine.resolve_duplicate_group(group)
        print(action)

集成入归档工作流::

    # library-manager 归档前
    dedup_result = engine.check_before_archive(
        new_resource,
        library_index=loaded_index,
    )
    if dedup_result.should_skip:
        logger.info(f"跳过归档（重复）: {dedup_result.reason}")
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

# ═══════════════════════════════════════════════════════════════
#  日志
# ═══════════════════════════════════════════════════════════════

_log = logging.getLogger("dedup")
if not _log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    _log.addHandler(_h)
    _log.setLevel(logging.INFO)


# ═══════════════════════════════════════════════════════════════
#  常量与枚举
# ═══════════════════════════════════════════════════════════════

class MatchType(str, Enum):
    """去重匹配类型。"""
    EXACT = "exact"           # 内容指纹完全匹配
    URL = "url"               # URL 结构化匹配
    SIMILAR_TITLE = "similar_title"  # 标题近似匹配
    RESOURCE_ID = "resource_id"      # resource_id 完全一致


class DedupStrategy(str, Enum):
    """检测到重复后的处理策略。"""
    KEEP_BEST_QUALITY = "keep_best_quality"   # 保留最高质量版本（默认）
    KEEP_EARLIEST = "keep_earliest"           # 保留最早版本
    KEEP_LATEST = "keep_latest"               # 保留最新版本
    MARK_AND_KEEP_ALL = "mark_and_keep_all"   # 都保留，标记为重复


# 质量等级映射为数值，用于排序
_QUALITY_RANK = {"S": 4, "A": 3, "B": 2, "C": 1}


# ═══════════════════════════════════════════════════════════════
#  配置数据类
# ═══════════════════════════════════════════════════════════════

@dataclass
class DedupConfig:
    """去重引擎配置。

    可从 config/settings.yaml 的 ``dedup`` 段加载，也支持环境变量覆盖。
    """

    # ── 总开关 ──────────────────────────────────
    enabled: bool = True                          # 是否启用去重

    # ── 处理策略 ────────────────────────────────
    strategy: str = "keep_best_quality"           # DedupStrategy 值

    # ── 内容指纹去重 ────────────────────────────
    enable_content_fingerprint: bool = True       # 启用内容指纹
    hash_algorithm: str = "md5"                   # md5 或 sha256

    # ── URL 结构化去重 ──────────────────────────
    enable_url_dedup: bool = True                 # 启用 URL 去重
    url_normalize_ignore_params: bool = True      # 标准化时忽略追踪参数

    # 追踪参数白名单（这些参数会被去除，不影响 URL 一致性判断）
    url_tracking_params: tuple[str, ...] = (
        "utm_source", "utm_medium", "utm_campaign", "utm_term",
        "utm_content", "spm", "share_source", "share_medium",
        "share_token", "bbid", "from", "isBdtf", "refer", "ref",
        "source", "timestamp", "sign", "ts",
    )

    # ── 标题相似度去重 ──────────────────────────
    enable_title_similarity: bool = True          # 启用标题相似度检测
    title_similarity_threshold: float = 0.85      # 标题相似度阈值（0-1）
    title_min_length_for_similarity: int = 4      # 标题最短长度（过短不做相似度）
    use_tfidf: bool = True                        # 是否使用 TF-IDF 辅助（默认 True）

    @classmethod
    def from_config_dict(cls, data: dict[str, Any]) -> "DedupConfig":
        """从配置字典构造 DedupConfig。"""
        known_keys = {
            "enabled", "strategy",
            "enable_content_fingerprint", "hash_algorithm",
            "enable_url_dedup", "url_normalize_ignore_params",
            "url_tracking_params",
            "enable_title_similarity",
            "title_similarity_threshold",
            "title_min_length_for_similarity",
            "use_tfidf",
        }
        kwargs: dict[str, Any] = {}
        for key in known_keys:
            if key in data:
                val = data[key]
                if key == "url_tracking_params" and isinstance(val, list):
                    val = tuple(val)
                kwargs[key] = val
        return cls(**kwargs)


# ═══════════════════════════════════════════════════════════════
#  结果数据类
# ═══════════════════════════════════════════════════════════════

@dataclass
class DedupMatch:
    """单条去重匹配结果。"""

    is_duplicate: bool = False
    matched_resource_id: str | None = None
    match_type: MatchType | None = None
    similarity_score: float = 0.0    # 标题相似度时填充
    detail: str = ""                 # 人可读的说明

    @property
    def should_skip(self) -> bool:
        """是否应跳过归档（取决于策略）。"""
        return self.is_duplicate and self._action == "skip"

    # 内部用，resolve 阶段设置
    _action: str = field(default="", repr=False)

    def __str__(self) -> str:
        if not self.is_duplicate:
            return "DedupMatch(no duplicate)"
        return (
            f"DedupMatch(duplicate, type={self.match_type.value}, "
            f"matched={self.matched_resource_id}, "
            f"score={self.similarity_score:.2f}, action={self._action})"
        )


@dataclass
class DuplicateGroup:
    """一组被判定为互相重复的资源。"""

    canonical_id: str                # 被选中的"正本" resource_id
    duplicate_ids: list[str]         # 被判定为重复的其他 resource_id
    match_type: MatchType            # 最强的匹配类型
    strategy: DedupStrategy          # 应用的处理策略
    reason: str = ""                 # 人可读的原因

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "duplicate_ids": self.duplicate_ids,
            "match_type": self.match_type.value,
            "strategy": self.strategy.value,
            "reason": self.reason,
        }


# ═══════════════════════════════════════════════════════════════
#  算法实现：标题相似度
# ═══════════════════════════════════════════════════════════════

# 中文/英文 token 化：按非字母数字字符切分，保留 CJK 连续段
_TOKEN_SPLIT_RE = re.compile(r"[^\w\u4e00-\u9fff]+", re.UNICODE)
# CJK 字符范围
_CJK_RANGE = re.compile(r"[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    """将文本切分为 token 列表。

    对于中文，逐字切分（每个汉字一个 token）；
    对于英文/数字，按单词切分。
    混合文本自动适配。
    """
    if not text:
        return []
    raw_tokens = _TOKEN_SPLIT_RE.split(text.strip().lower())
    result: list[str] = []
    for tok in raw_tokens:
        if not tok:
            continue
        # 如果 token 中包含 CJK 字符，逐字拆分
        if _CJK_RANGE.search(tok):
            # 英文部分保留，中文部分逐字
            buf = ""
            for ch in tok:
                if _CJK_RANGE.match(ch):
                    if buf:
                        result.append(buf)
                        buf = ""
                    result.append(ch)
                else:
                    buf += ch
            if buf:
                result.append(buf)
        else:
            result.append(tok)
    return result


def levenshtein_distance(s1: str, s2: str) -> int:
    """计算两个字符串的编辑距离（Levenshtein distance）。

    使用动态规划，O(m*n) 时间和空间。
    """
    if s1 == s2:
        return 0
    if len(s1) < len(s2):
        s1, s2 = s2, s1
    if not s2:
        return len(s1)

    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insert = prev_row[j + 1] + 1
            delete = curr_row[j] + 1
            substitute = prev_row[j] + (0 if c1 == c2 else 1)
            curr_row.append(min(insert, delete, substitute))
        prev_row = curr_row

    return prev_row[-1]


def edit_distance_similarity(s1: str, s2: str) -> float:
    """基于编辑距离的相似度（0-1）。

    similarity = 1 - distance / max(len)
    """
    if not s1 and not s2:
        return 1.0
    max_len = max(len(s1), len(s2))
    if max_len == 0:
        return 1.0
    dist = levenshtein_distance(s1, s2)
    return 1.0 - (dist / max_len)


def jaccard_similarity(tokens1: list[str], tokens2: list[str]) -> float:
    """Jaccard 相似度（基于 token 集合的交并比）。

    J = |A ∩ B| / |A ∪ B|
    """
    if not tokens1 and not tokens2:
        return 1.0
    set1 = set(tokens1)
    set2 = set(tokens2)
    union = set1 | set2
    if not union:
        return 1.0
    intersection = set1 & set2
    return len(intersection) / len(union)


def tfidf_cosine_similarity(
    tokens1: list[str],
    tokens2: list[str],
    idf_map: dict[str, float] | None = None,
) -> float:
    """基于 TF-IDF 加权的余弦相似度。

    如果没有提供 idf_map，使用均匀权重（退化为向量余弦）。
    中文逐字 token 时 IDF 意义不大，但加权后效果优于纯 Jaccard。

    Args:
        tokens1: 第一个文本的 token 列表
        tokens2: 第二个文本的 token 列表
        idf_map: 词 → IDF 权重映射（可选）

    Returns:
        余弦相似度（0-1）
    """
    if not tokens1 or not tokens2:
        return 0.0

    # 计算 TF
    def _term_freq(tokens: list[str]) -> dict[str, float]:
        counts: dict[str, int] = defaultdict(int)
        for t in tokens:
            counts[t] += 1
        total = len(tokens)
        return {t: c / total for t, c in counts.items()}

    tf1 = _term_freq(tokens1)
    tf2 = _term_freq(tokens2)

    # 合并词汇表
    vocab = set(tf1.keys()) | set(tf2.keys())

    # 构建加权向量
    vec1: list[float] = []
    vec2: list[float] = []
    for term in vocab:
        idf = idf_map.get(term, 1.0) if idf_map else 1.0
        vec1.append(tf1.get(term, 0.0) * idf)
        vec2.append(tf2.get(term, 0.0) * idf)

    # 余弦相似度
    dot = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = math.sqrt(sum(a * a for a in vec1))
    norm2 = math.sqrt(sum(b * b for b in vec2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)


def title_similarity(
    title1: str,
    title2: str,
    *,
    use_tfidf: bool = True,
    idf_map: dict[str, float] | None = None,
) -> float:
    """综合标题相似度计算。

    取编辑距离相似度和 token 级相似度（Jaccard 或 TF-IDF 余弦）的最大值。

    设计理由：
    - 编辑距离擅长检测字符级的微调（如"三年级" vs "3年级"）
    - token 级擅长检测词序变化（如"数学练习题" vs "练习题数学"）
    - 取两者最大值以覆盖两种场景

    Returns:
        相似度（0-1）
    """
    if not title1 or not title2:
        return 0.0

    # 归一化：去除首尾空白和标点
    norm1 = re.sub(r"[\s\W_]+", "", title1).lower()
    norm2 = re.sub(r"[\s\W_]+", "", title2).lower()

    # 如果归一化后完全一致
    if norm1 == norm2:
        return 1.0

    # 编辑距离相似度
    ed_sim = edit_distance_similarity(norm1, norm2)

    # token 级相似度
    tokens1 = tokenize(title1)
    tokens2 = tokenize(title2)
    if use_tfidf:
        tok_sim = tfidf_cosine_similarity(tokens1, tokens2, idf_map)
    else:
        tok_sim = jaccard_similarity(tokens1, tokens2)

    return max(ed_sim, tok_sim)


# ═══════════════════════════════════════════════════════════════
#  算法实现：URL 结构化去重
# ═══════════════════════════════════════════════════════════════

def normalize_url(
    url: str,
    *,
    ignore_tracking_params: bool = True,
    tracking_params: set[str] | None = None,
) -> str:
    """标准化 URL，用于去重比较。

    标准化步骤：
    1. 解析 URL
    2. 域名转小写
    3. 去除默认端口（:80 / :443）
    4. 去除追踪参数（utm_* 等）
    5. 参数排序（保证顺序一致性）
    6. 路径去除尾部冗余斜杠
    7. 去除 fragment

    Args:
        url: 原始 URL
        ignore_tracking_params: 是否去除追踪参数
        tracking_params: 追踪参数集合（默认使用 DedupConfig 中的值）

    Returns:
        标准化后的 URL 字符串
    """
    if not url:
        return ""

    if tracking_params is None:
        tracking_params = set(DedupConfig().url_tracking_params)

    try:
        parsed = urlparse(url)
    except Exception:
        return url.strip().lower()

    # 域名小写
    netloc = parsed.netloc.lower()

    # 去除默认端口
    if netloc.endswith(":80"):
        netloc = netloc[:-3]
    elif netloc.endswith(":443") and parsed.scheme == "https":
        netloc = netloc[:-4]

    # 路径标准化
    path = parsed.path or "/"
    # 去除尾部多余斜杠（但保留根路径 /）
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    # 参数处理
    query_params = parse_qs(parsed.query, keep_blank_values=False)
    if ignore_tracking_params:
        filtered = {
            k: v for k, v in query_params.items()
            if k.lower() not in tracking_params
        }
    else:
        filtered = query_params

    # 排序参数
    sorted_params = sorted(
        (k, v[0] if len(v) == 1 else v) for k, v in filtered.items()
    )
    normalized_query = urlencode(sorted_params, doseq=True)

    # 重组（不含 fragment）
    normalized = urlunparse((
        parsed.scheme.lower(),
        netloc,
        path,
        parsed.params,   # params 段（很少用，保留）
        normalized_query,
        "",              # 去掉 fragment
    ))

    return normalized


def url_fingerprint(
    url: str,
    *,
    ignore_tracking_params: bool = True,
    tracking_params: set[str] | None = None,
) -> str:
    """计算 URL 的指纹（标准化后的 MD5）。

    同一页面不同追踪参数 → 相同指纹。
    """
    normalized = normalize_url(
        url,
        ignore_tracking_params=ignore_tracking_params,
        tracking_params=tracking_params,
    )
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


# ═══════════════════════════════════════════════════════════════
#  算法实现：内容指纹去重
# ═══════════════════════════════════════════════════════════════

def compute_file_hash(
    file_path: str | Path,
    algorithm: str = "md5",
    chunk_size: int = 65536,
) -> str | None:
    """计算文件内容的 hash 值。

    Args:
        file_path: 文件路径
        algorithm: 哈希算法（md5 / sha256）
        chunk_size: 分块读取大小（字节）

    Returns:
        hex 摘要字符串，文件不存在或读取失败返回 None
    """
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        return None

    try:
        hasher = hashlib.new(algorithm)
        with open(path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest()
    except (OSError, PermissionError) as e:
        _log.warning("计算文件 hash 失败 (%s): %s", path, e)
        return None


def compute_text_hash(text: str, algorithm: str = "md5") -> str:
    """计算文本内容的 hash 值。"""
    hasher = hashlib.new(algorithm)
    hasher.update(text.encode("utf-8"))
    return hasher.hexdigest()


# ═══════════════════════════════════════════════════════════════
#  去重引擎
# ═══════════════════════════════════════════════════════════════

class DedupEngine:
    """跨平台内容级去重引擎。

    组合三种去重策略，按优先级自动检测：

    1. resource_id 完全一致（最强信号）
    2. 内容指纹完全匹配（精确）
    3. URL 结构化匹配
    4. 标题相似度匹配（近似）

    用法::

        engine = DedupEngine()
        result = engine.check(new_resource, existing_resources)
    """

    def __init__(self, config: DedupConfig | None = None) -> None:
        self.config = config or DedupConfig()
        self.strategy = DedupStrategy(self.config.strategy)

    # ── 单条资源检查 ─────────────────────────────

    def check(
        self,
        new_resource: dict[str, Any],
        existing_resources: list[dict[str, Any]],
    ) -> DedupMatch:
        """检查单个新资源是否与已有资源重复。

        Args:
            new_resource: 新资源元数据
            existing_resources: 已有资源列表

        Returns:
            DedupMatch 结果
        """
        if not self.config.enabled:
            return DedupMatch(is_duplicate=False)

        new_id = new_resource.get("resource_id", "")

        # ── 策略 1: resource_id 完全一致 ──
        for existing in existing_resources:
            existing_id = existing.get("resource_id", "")
            if new_id and existing_id and new_id == existing_id:
                return DedupMatch(
                    is_duplicate=True,
                    matched_resource_id=existing_id,
                    match_type=MatchType.RESOURCE_ID,
                    detail=f"resource_id 完全一致: {new_id}",
                )

        # ── 策略 2: 内容指纹去重 ──
        if self.config.enable_content_fingerprint:
            new_hash = self._get_content_hash(new_resource)
            if new_hash:
                for existing in existing_resources:
                    existing_hash = self._get_content_hash(existing)
                    if existing_hash and new_hash == existing_hash:
                        return DedupMatch(
                            is_duplicate=True,
                            matched_resource_id=existing.get("resource_id"),
                            match_type=MatchType.EXACT,
                            detail=(
                                f"内容指纹匹配 ({self.config.hash_algorithm}): "
                                f"{new_hash}"
                            ),
                        )

        # ── 策略 3: URL 结构化去重 ──
        if self.config.enable_url_dedup:
            new_url = new_resource.get("source_url", "")
            if new_url:
                tracking_set = set(self.config.url_tracking_params)
                new_url_fp = url_fingerprint(
                    new_url,
                    ignore_tracking_params=self.config.url_normalize_ignore_params,
                    tracking_params=tracking_set,
                )
                if new_url_fp:
                    for existing in existing_resources:
                        existing_url = existing.get("source_url", "")
                        if not existing_url:
                            continue
                        existing_url_fp = url_fingerprint(
                            existing_url,
                            ignore_tracking_params=self.config.url_normalize_ignore_params,
                            tracking_params=tracking_set,
                        )
                        if new_url_fp == existing_url_fp:
                            return DedupMatch(
                                is_duplicate=True,
                                matched_resource_id=existing.get("resource_id"),
                                match_type=MatchType.URL,
                                detail=f"URL 结构化匹配: {new_url}",
                            )

        # ── 策略 4: 标题相似度去重 ──
        if self.config.enable_title_similarity:
            new_title = new_resource.get("title", "")
            if (
                len(new_title) >= self.config.title_min_length_for_similarity
            ):
                best_match: DedupMatch | None = None
                for existing in existing_resources:
                    existing_title = existing.get("title", "")
                    if len(existing_title) < self.config.title_min_length_for_similarity:
                        continue

                    sim = title_similarity(
                        new_title,
                        existing_title,
                        use_tfidf=self.config.use_tfidf,
                    )
                    if sim >= self.config.title_similarity_threshold:
                        if (
                            best_match is None
                            or sim > best_match.similarity_score
                        ):
                            best_match = DedupMatch(
                                is_duplicate=True,
                                matched_resource_id=existing.get("resource_id"),
                                match_type=MatchType.SIMILAR_TITLE,
                                similarity_score=sim,
                                detail=(
                                    f"标题相似度 {sim:.2f}: "
                                    f"'{new_title}' ≈ '{existing_title}'"
                                ),
                            )
                if best_match:
                    return best_match

        return DedupMatch(is_duplicate=False)

    # ── 批量去重 ─────────────────────────────────

    def find_duplicates(
        self,
        resources: list[dict[str, Any]],
    ) -> list[DuplicateGroup]:
        """在资源列表中找出所有重复组。

        使用并查集（Union-Find）合并传递性重复。

        Args:
            resources: 资源元数据列表

        Returns:
            重复组列表（每组 2+ 个资源）
        """
        if len(resources) < 2:
            return []

        n = len(resources)

        # 并查集
        parent = list(range(n))

        def _find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def _union(x: int, y: int) -> None:
            px, py = _find(x), _find(y)
            if px != py:
                parent[px] = py

        # 记录匹配类型（取最强的）
        match_type_map: dict[int, MatchType] = {}

        def _record_match(idx: int, mtype: MatchType) -> None:
            """记录某个资源参与的匹配类型（优先级高覆盖低）。"""
            priority = {
                MatchType.RESOURCE_ID: 4,
                MatchType.EXACT: 3,
                MatchType.URL: 2,
                MatchType.SIMILAR_TITLE: 1,
            }
            existing = match_type_map.get(idx)
            if existing is None or priority.get(mtype, 0) > priority.get(existing, 0):
                match_type_map[idx] = mtype

        # 两两比较
        # 先构建快速索引加速精确匹配
        id_index: dict[str, int] = {}
        hash_index: dict[str, int] = {}
        url_index: dict[str, int] = {}

        for i, res in enumerate(resources):
            # resource_id
            rid = res.get("resource_id", "")
            if rid:
                if rid in id_index:
                    _union(i, id_index[rid])
                    _record_match(i, MatchType.RESOURCE_ID)
                    _record_match(id_index[rid], MatchType.RESOURCE_ID)
                else:
                    id_index[rid] = i

            # 内容 hash
            if self.config.enable_content_fingerprint:
                content_hash = self._get_content_hash(res)
                if content_hash:
                    if content_hash in hash_index:
                        _union(i, hash_index[content_hash])
                        _record_match(i, MatchType.EXACT)
                        _record_match(hash_index[content_hash], MatchType.EXACT)
                    else:
                        hash_index[content_hash] = i

            # URL 指纹
            if self.config.enable_url_dedup:
                url = res.get("source_url", "")
                if url:
                    tracking_set = set(self.config.url_tracking_params)
                    url_fp = url_fingerprint(
                        url,
                        ignore_tracking_params=self.config.url_normalize_ignore_params,
                        tracking_params=tracking_set,
                    )
                    if url_fp:
                        if url_fp in url_index:
                            _union(i, url_index[url_fp])
                            _record_match(i, MatchType.URL)
                            _record_match(url_index[url_fp], MatchType.URL)
                        else:
                            url_index[url_fp] = i

        # 标题相似度（O(n^2)，数量大时可优化）
        if self.config.enable_title_similarity:
            for i in range(n):
                title_i = resources[i].get("title", "")
                if len(title_i) < self.config.title_min_length_for_similarity:
                    continue
                for j in range(i + 1, n):
                    title_j = resources[j].get("title", "")
                    if len(title_j) < self.config.title_min_length_for_similarity:
                        continue
                    # 已经在同一组了可以跳过
                    if _find(i) == _find(j):
                        continue
                    sim = title_similarity(
                        title_i,
                        title_j,
                        use_tfidf=self.config.use_tfidf,
                    )
                    if sim >= self.config.title_similarity_threshold:
                        _union(i, j)
                        _record_match(i, MatchType.SIMILAR_TITLE)
                        _record_match(j, MatchType.SIMILAR_TITLE)

        # 提取重复组
        groups_map: dict[int, list[int]] = defaultdict(list)
        for i in range(n):
            root = _find(i)
            groups_map[root].append(i)

        result: list[DuplicateGroup] = []
        for indices in groups_map.values():
            if len(indices) < 2:
                continue

            # 选择 canonical（根据策略）
            group_resources = [resources[i] for i in indices]
            canonical_idx_in_group = self._select_canonical(group_resources)
            canonical = group_resources[canonical_idx_in_group]

            duplicates = [
                resources[i].get("resource_id", f"unknown-{i}")
                for i in indices
                if resources[i] is not canonical
            ]

            # 取组内最强匹配类型
            strongest = MatchType.SIMILAR_TITLE
            for idx in indices:
                mt = match_type_map.get(idx)
                if mt:
                    priority = {
                        MatchType.RESOURCE_ID: 4,
                        MatchType.EXACT: 3,
                        MatchType.URL: 2,
                        MatchType.SIMILAR_TITLE: 1,
                    }
                    if priority.get(mt, 0) > priority.get(strongest, 0):
                        strongest = mt

            result.append(DuplicateGroup(
                canonical_id=canonical.get("resource_id", ""),
                duplicate_ids=duplicates,
                match_type=strongest,
                strategy=self.strategy,
                reason=f"检测到 {len(indices)} 个重复资源",
            ))

        return result

    # ── 归档前检查 ────────────────────────────────

    def check_before_archive(
        self,
        new_resource: dict[str, Any],
        library_index: dict[str, Any] | list[dict[str, Any]],
    ) -> DedupMatch:
        """归档入库前去重检查（便捷方法）。

        Args:
            new_resource: 待归档的新资源
            library_index: 资料库索引（dict 或 list 格式）

        Returns:
            DedupMatch，如果 is_duplicate=True 则按 strategy 决定是否跳过
        """
        # 提取已有资源列表
        if isinstance(library_index, dict):
            existing = library_index.get("resources", [])
        else:
            existing = library_index

        if not existing:
            return DedupMatch(is_duplicate=False)

        match = self.check(new_resource, existing)

        # 根据 strategy 决定 action
        if match.is_duplicate:
            match._action = self._resolve_action(match)
            if match._action == "skip":
                match.detail = (
                    f"归档跳过（{self.strategy.value}）: "
                    f"{match.detail}"
                )

        return match

    # ── 解决重复组 ────────────────────────────────

    def resolve_duplicate_group(
        self,
        group: DuplicateGroup,
        resources: dict[str, dict[str, Any]] | list[dict[str, Any]],
    ) -> dict[str, Any]:
        """对重复组执行解决策略，返回操作指令。

        Args:
            group: 重复组
            resources: 资源映射（resource_id → 资源元数据）或列表

        Returns:
            操作指令字典::
                {
                    "action": "keep_canonical" / "keep_all_marked",
                    "canonical_id": "...",
                    "to_remove": ["id1", "id2"],
                    "to_mark": ["id1", "id2"],
                    "reason": "...",
                }
        """
        # 获取资源映射
        if isinstance(resources, list):
            res_map = {r.get("resource_id", ""): r for r in resources}
        else:
            res_map = resources

        all_ids = [group.canonical_id] + group.duplicate_ids

        if group.strategy == DedupStrategy.MARK_AND_KEEP_ALL:
            return {
                "action": "keep_all_marked",
                "canonical_id": group.canonical_id,
                "to_remove": [],
                "to_mark": group.duplicate_ids,
                "reason": group.reason,
            }

        # keep_best_quality / keep_earliest / keep_latest → 移除非 canonical
        return {
            "action": "keep_canonical",
            "canonical_id": group.canonical_id,
            "to_remove": group.duplicate_ids,
            "to_mark": [],
            "reason": group.reason,
        }

    # ── 内部工具方法 ──────────────────────────────

    def _get_content_hash(self, resource: dict[str, Any]) -> str | None:
        """从资源元数据获取内容 hash。

        优先使用 checksum 字段；如果没有，尝试计算 files 中首个文件的 hash。
        """
        # 优先使用已有的 checksum
        checksum = resource.get("checksum", "")
        if checksum:
            # 格式可能是 "md5:xxxxx" 或 "sha256:xxxxx"
            parts = checksum.split(":", 1)
            if len(parts) == 2:
                algo, hash_val = parts[0].strip().lower(), parts[1].strip()
                if algo == self.config.hash_algorithm:
                    return hash_val
                # 算法不同，返回原始值用于比较
                return checksum
            return checksum

        # 新契约使用 files/library_paths 数组；保留旧单路径索引兼容。
        files = resource.get("files") or resource.get("library_paths") or []
        file_path = files[0] if isinstance(files, list) and files else None
        file_path = file_path or resource.get("file_path") or resource.get("library_path")
        if file_path:
            return compute_file_hash(file_path, self.config.hash_algorithm)

        return None

    def _select_canonical(
        self, group: list[dict[str, Any]]
    ) -> int:
        """根据策略选择 canonical 资源，返回组内索引。"""
        if self.strategy == DedupStrategy.KEEP_BEST_QUALITY:
            # 新契约直接使用 Selector 的 quality_score；旧索引字段仅作兼容回退。
            def _quality_key(r: dict[str, Any]) -> tuple[int, int]:
                score = r.get("quality_score")
                if isinstance(score, (int, float)) and not isinstance(score, bool):
                    return (int(score), 0)
                ql = r.get("quality_level", "C")
                rank = _QUALITY_RANK.get(ql, 0)
                pqs = r.get("platform_quality_score", 0) or 0
                return (rank, pqs)
            best_idx = 0
            best_key = _quality_key(group[0])
            for i, res in enumerate(group[1:], 1):
                k = _quality_key(res)
                if k > best_key:
                    best_key = k
                    best_idx = i
            return best_idx

        elif self.strategy == DedupStrategy.KEEP_EARLIEST:
            # 调用者可把阶段文件时间作为 created_at 传入。
            def _time_key(r: dict[str, Any]) -> str:
                return (
                    r.get("created_at")
                    or r.get("fetch_time")
                    or r.get("archive_time")
                    or ""
                )
            best_idx = 0
            best_time = _time_key(group[0])
            for i, res in enumerate(group[1:], 1):
                t = _time_key(res)
                if t and (not best_time or t < best_time):
                    best_time = t
                    best_idx = i
            return best_idx

        elif self.strategy == DedupStrategy.KEEP_LATEST:
            # 调用者可把阶段文件时间作为 created_at 传入。
            def _time_key(r: dict[str, Any]) -> str:
                return (
                    r.get("created_at")
                    or r.get("fetch_time")
                    or r.get("archive_time")
                    or ""
                )
            best_idx = 0
            best_time = _time_key(group[0])
            for i, res in enumerate(group[1:], 1):
                t = _time_key(res)
                if t and (not best_time or t > best_time):
                    best_time = t
                    best_idx = i
            return best_idx

        else:
            # MARK_AND_KEEP_ALL: 选第一个作为标记的"正本"
            return 0

    def _resolve_action(self, match: DedupMatch) -> str:
        """根据匹配类型和策略决定操作。

        Returns:
            "skip"（跳过归档）/ "replace"（替换）/ "mark"（标记但保留）
        """
        if self.strategy == DedupStrategy.MARK_AND_KEEP_ALL:
            return "mark"

        # resource_id 完全一致 → 必定跳过或替换
        if match.match_type == MatchType.RESOURCE_ID:
            return "skip"

        # 内容完全匹配 → 跳过
        if match.match_type == MatchType.EXACT:
            return "skip"

        # URL 匹配 → 跳过（同一页面不同追踪参数）
        if match.match_type == MatchType.URL:
            return "skip"

        # 标题近似 → 根据策略
        # keep_best_quality: 如果新资源质量更高则替换，否则跳过
        # keep_earliest: 跳过（已有的是更早的）
        # keep_latest: 替换（新的是最新的）
        if match.match_type == MatchType.SIMILAR_TITLE:
            if self.strategy == DedupStrategy.KEEP_LATEST:
                return "replace"
            return "skip"

        return "skip"


# ═══════════════════════════════════════════════════════════════
#  便捷函数
# ═══════════════════════════════════════════════════════════════

def dedup_resources(
    resources: list[dict[str, Any]],
    config: DedupConfig | None = None,
) -> tuple[list[dict[str, Any]], list[DuplicateGroup]]:
    """便捷函数：对资源列表执行去重。

    Args:
        resources: 待去重的资源列表
        config: 去重配置（None 使用默认）

    Returns:
        (去重后的资源列表, 被移除的重复组列表)
    """
    engine = DedupEngine(config)
    groups = engine.find_duplicates(resources)

    if not groups:
        return resources, []

    # 收集要移除的 resource_id
    to_remove: set[str] = set()
    for group in groups:
        action = engine.resolve_duplicate_group(group, resources)
        to_remove.update(action.get("to_remove", []))

    deduped = [
        r for r in resources
        if r.get("resource_id", "") not in to_remove
    ]

    return deduped, groups


def quick_is_duplicate(
    new_resource: dict[str, Any],
    existing_resources: list[dict[str, Any]],
    config: DedupConfig | None = None,
) -> bool:
    """快速判断新资源是否重复。"""
    engine = DedupEngine(config)
    match = engine.check(new_resource, existing_resources)
    return match.is_duplicate

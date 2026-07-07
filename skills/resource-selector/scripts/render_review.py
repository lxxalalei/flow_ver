#!/usr/bin/env python3
"""Render a validated Selector review as a stable numbered candidate list."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: 根节点必须是 object")
    return value


def level(score: int) -> str:
    if score >= 90:
        return "S"
    if score >= 75:
        return "A"
    if score >= 60:
        return "B"
    return "C"


def known_facts(resource: dict[str, Any]) -> list[str]:
    facts: list[str] = []
    if resource.get("is_free") is True:
        facts.append("平台标记免费")
    elif resource.get("is_free") is False:
        facts.append("平台标记付费")
    if resource.get("duration") not in (None, ""):
        facts.append(f"时长 {resource['duration']}")
    if resource.get("download_feasibility"):
        facts.append(f"下载可行性 {resource['download_feasibility']}")
    signals = resource.get("platform_signals") or {}
    if isinstance(signals, dict):
        for key, label in (("lessons", "课时"), ("tracks_count", "集数"), ("views", "播放/访问")):
            if signals.get(key) is not None:
                facts.append(f"{label} {signals[key]}")
    return facts


def build_summary(resource: dict[str, Any], max_len: int = 80) -> str:
    """从 description 提取摘要，超长截断并加省略号；无则返回空串。"""
    import re as _re
    desc = resource.get("description") or ""
    if not desc.strip():
        return ""
    # 去 HTML 标签
    desc = _re.sub(r"<[^>]+>", "", desc)
    # 合并多余空白
    desc = _re.sub(r"\s+", " ", desc).strip()
    if len(desc) > max_len:
        return desc[:max_len].rstrip() + "…"
    return desc


def build_source_line(resource: dict[str, Any]) -> str:
    """构建来源行：来源：【平台】类型 · 免费/付费。"""
    platform = resource.get("platform", "未知平台")
    resource_type = resource.get("type", "类型未知")
    parts = [f"来源：【{platform}】{resource_type}"]
    if resource.get("is_free") is True:
        parts.append("免费")
    elif resource.get("is_free") is False:
        parts.append("付费")
    return " · ".join(parts)


def type_icon(resource_type: str) -> str:
    """根据资源类型返回 emoji 图标。"""
    t = resource_type.lower()
    if "视频" in t:
        return "🎬"
    if "音频" in t:
        return "🎵"
    if any(value in t for value in ("实验", "活动", "手工", "实践", "项目", "制作")):
        return "🔬"
    if any(value in t for value in ("互动", "游戏", "习题", "练习", "试题", "试卷", "题库", "软件", "应用")):
        return "🧩"
    if any(value in t for value in ("图书", "绘本", "电子书", "文章", "文档", "阅读", "pdf", "doc", "ppt")):
        return "📖"
    if any(value in t for value in ("课程", "公开课", "讲座")) or t == "课":
        return "📚"
    if any(value in t for value in ("网页", "工具")):
        return "🛠️"
    return "📌"


def _category_for(resource: dict[str, Any]) -> str:
    """将资源归入大类，用于分组展示。"""
    t = (resource.get("type") or "").lower()
    title = (resource.get("title") or "").lower()
    text = f"{t} {title}"
    if "视频" in t:
        return "视频资源"
    if "音频" in t:
        return "音频资源"
    if any(value in text for value in ("实验", "活动", "手工", "实践", "项目", "制作", "观察任务")):
        return "实验与活动"
    if any(value in text for value in ("互动", "游戏", "习题", "练习", "试题", "试卷", "题库", "问答", "模拟", "软件", "应用")):
        return "互动与练习"
    if any(value in t for value in ("课程", "公开课", "讲座")) or t == "课":
        return "课程资源"
    if any(value in text for value in ("图书", "绘本", "电子书", "文章", "文档", "阅读", "百科", "指南", "讲义", "pdf", "doc", "ppt", "可打印", "电子版")):
        return "图书与阅读"
    return "网页与工具"


CATEGORY_ORDER = ["视频资源", "音频资源", "图书与阅读", "互动与练习", "实验与活动", "课程资源", "网页与工具"]
CATEGORY_HEADER_ICON = {
    "视频资源": "🎬",
    "音频资源": "🎵",
    "图书与阅读": "📖",
    "互动与练习": "🧩",
    "实验与活动": "🔬",
    "课程资源": "📚",
    "网页与工具": "🛠️",
}


def _render_candidate(index: int, review_item: dict[str, Any], resource: dict[str, Any]) -> list[str]:
    """渲染单条候选，严格四行模板格式。"""
    score = review_item["quality_score"]
    resource_type = resource.get("type", "")
    icon = type_icon(resource_type)
    lines = [f"{index}. 🏷️ [{level(score)}级 · {score}分] {resource.get('title', review_item.get('resource_id'))}"]
    summary_text = review_item.get("summary", "")
    if summary_text:
        lines.append(f"   📝 {summary_text}")
    else:
        lines.append("   📝 （暂无摘要）")
    lines.append(f"   {icon} {build_source_line(resource)}")
    if resource.get("source_url"):
        lines.append(f"   🔗 {resource['source_url']}")
    else:
        lines.append("   🔗 （无链接）")
    return lines


def render(session_dir: Path, offset: int, limit: int, group_by_type: bool = True) -> str:
    selector_input = load_object(session_dir / "selector_input.json")
    review = load_object(session_dir / "selector_review.json")
    stage3 = load_object(session_dir / "stage3_search_results.json")
    resources = {
        item.get("resource_id"): item for item in stage3.get("data", {}).get("resources", [])
        if isinstance(item, dict)
    }
    candidates = review.get("data", {}).get("candidates", [])
    excluded = review.get("data", {}).get("excluded", [])
    summary = selector_input.get("_summary", {})
    lines = [
        f"共搜索到 {summary.get('raw_count', 0)} 条；精确去重 {summary.get('exact_duplicate_count', 0)} 条，"
        f"过滤 {len(excluded)} 条，保留 {len(candidates)} 条。"
    ]
    platform_errors = selector_input.get("data", {}).get("platform_errors", [])
    if platform_errors:
        errors = "、".join(f"{item.get('platform')}（{item.get('error_code')}）" for item in platform_errors)
        lines.append(f"平台异常：{errors}")
    lines.append("")

    if group_by_type:
        # 按资源类型分组展示，编号保持与 candidates 列表一致
        groups: dict[str, list[tuple[int, dict, dict]]] = {}
        for index, review_item in enumerate(candidates, start=1):
            resource = resources.get(review_item.get("resource_id"), {})
            cat = _category_for(resource)
            groups.setdefault(cat, []).append((index, review_item, resource))

        first_group = True
        for cat in CATEGORY_ORDER:
            if cat not in groups:
                continue
            if not first_group:
                lines.append("")
            first_group = False
            header_icon = CATEGORY_HEADER_ICON.get(cat, "📌")
            lines.append(f"{header_icon} {cat}（{len(groups[cat])} 条）")
            lines.append("")
            for index, review_item, resource in groups[cat]:
                lines.extend(_render_candidate(index, review_item, resource))
                lines.append("")

        # 输出不在标准分类中的组
        for cat, items in groups.items():
            if cat in CATEGORY_ORDER:
                continue
            lines.append("")
            header_icon = CATEGORY_HEADER_ICON.get(cat, "📌")
            lines.append(f"{header_icon} {cat}（{len(items)} 条）")
            lines.append("")
            for index, review_item, resource in items:
                lines.extend(_render_candidate(index, review_item, resource))
                lines.append("")
    else:
        for index, review_item in enumerate(candidates[offset:offset + limit], start=offset + 1):
            resource = resources.get(review_item.get("resource_id"), {})
            lines.extend(_render_candidate(index, review_item, resource))
            lines.append("")
    lines.append("回复编号选择，例如\u201c1,3\u201d；也可以回复\u201c全部\u201d\u201c只要视频\u201d或\u201c取消\u201d。")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="渲染 Selector 候选")
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--group-by-type", action="store_true", default=True, help="按资源类型分组展示（默认开启）")
    parser.add_argument("--no-group", action="store_true", help="禁用分组，使用平铺模式")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    group = args.group_by_type and not args.no_group
    text = render(args.session_dir, max(0, args.offset), max(1, args.limit), group_by_type=group)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

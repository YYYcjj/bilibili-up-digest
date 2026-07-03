#!/usr/bin/env python3
"""
B站UP主视频智能摘要工具
输入UP主名字 → 获取所有投稿视频 → AI概括 → 输出评级报告

用法:
    python digest.py --up "影视飓风"
    python digest.py --up "影视飓风" --pages 3 --output markdown
    python digest.py --up "影视飓风" --no-ai    # 不用AI，仅做规则概括
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

from dotenv import load_dotenv

from bilibili import BilibiliAPI
from summarizer import VideoSummarizer

load_dotenv()

# ── 推荐度映射 ──────────────────────────────────────────
REC_ICONS = {
    "强烈推荐": "⭐",
    "推荐": "👍",
    "可选": "💡",
    "可跳过": "⏭️",
}

REC_SORT = {"强烈推荐": 0, "推荐": 1, "可选": 2, "可跳过": 3}


def print_banner(up_info: dict, total: int):
    """打印UP主信息横幅"""
    print()
    print("=" * 60)
    print(f"  📺 {up_info['uname']}")
    if up_info.get("sign"):
        print(f"  📝 {up_info['sign'][:60]}")
    print(f"  👥 {up_info.get('fans', '?'):,} 粉丝  |  "
          f"🎬 {total} 个视频")
    print("=" * 60)
    print()


def progress_bar(current: int, total: int, label: str = ""):
    """简易进度条"""
    pct = current / total if total > 0 else 0
    bar_len = 30
    filled = int(bar_len * pct)
    bar = "█" * filled + "░" * (bar_len - filled)
    print(f"\r  [{bar}] {current}/{total} {label}", end="", flush=True)


def main():
    parser = argparse.ArgumentParser(
        description="B站UP主视频智能摘要工具"
    )
    parser.add_argument(
        "--up", "-u", type=str, required=True,
        help="UP主名字（如：影视飓风）",
    )
    parser.add_argument(
        "--mid", type=int, default=None,
        help="直接指定UP主mid（跳过搜索）",
    )
    parser.add_argument(
        "--pages", "-p", type=int, default=20,
        help="最大抓取页数（每页50个），默认20",
    )
    parser.add_argument(
        "--no-ai", action="store_true",
        help="不使用AI概括，仅用规则推断",
    )
    parser.add_argument(
        "--model", type=str, default=None,
        help="LLM模型名（覆盖.env中的LLM_MODEL）",
    )
    parser.add_argument(
        "--output", "-o", type=str, default="markdown",
        choices=["markdown", "json", "text"],
        help="输出格式（默认markdown）",
    )
    parser.add_argument(
        "--sort-by", type=str, default="recommendation",
        choices=["recommendation", "date", "views"],
        help="排序方式（默认按推荐度排序）",
    )
    args = parser.parse_args()

    api = BilibiliAPI()

    # ── 1. 查找UP主 ────────────────────────────────
    if args.mid:
        mid = args.mid
        up_info = {"mid": mid, "uname": f"UID:{mid}",
                   "sign": "", "fans": "?", "videos": "?"}
    else:
        print(f"🔍 正在搜索UP主: {args.up} ...", end="", flush=True)
        up_info = api.search_up(args.up)
        if not up_info:
            print(f"\n❌ 未找到UP主: {args.up}")
            sys.exit(1)
        mid = up_info["mid"]
        print(f" 找到! (UID: {mid})")

    # ── 2. 获取视频列表 ─────────────────────────────
    print(f"📥 正在获取视频列表 ...")
    all_videos = api.get_all_videos(mid, max_pages=args.pages)
    print(f"  共获取 {len(all_videos)} 个视频")

    if not all_videos:
        print("❌ 该UP主没有公开视频")
        sys.exit(1)

    # ── 3. 补充详细信息 ─────────────────────────────
    print(f"📝 正在获取详细信息 ...")
    detailed = []
    total = len(all_videos)
    for i, v in enumerate(all_videos):
        progress_bar(i + 1, total, v["title"][:30])
        detail = api.get_video_detail(v["bvid"])
        if detail:
            duration_str = api.format_duration(detail["duration"])
            detailed.append({
                **v,
                **detail,
                "duration": duration_str,
                "category": detail.get("tname", ""),
                "created_str": datetime.fromtimestamp(
                    v["created"]
                ).strftime("%Y-%m-%d"),
            })
        else:
            detailed.append({
                **v,
                "duration": v.get("length", "?"),
                "category": "",
                "created_str": datetime.fromtimestamp(
                    v["created"]
                ).strftime("%Y-%m-%d"),
                "tags": [],
                "desc": v.get("description", ""),
                "view": v.get("play", 0),
                "like": 0,
            })
        time.sleep(0.3)  # 礼貌间隔
    print()

    # ── 4. AI概括 ──────────────────────────────────
    if not args.no_ai:
        model_str = f" ({args.model})" if args.model else ""
        print(f"🤖 正在进行AI内容概括{model_str} ...")
        summarizer = VideoSummarizer(
            api_key=os.getenv("LLM_API_KEY"),
            api_base=os.getenv("LLM_API_BASE"),
            model=args.model,
        )
        summaries = []
        for i, v in enumerate(detailed):
            progress_bar(i + 1, total, v["title"][:30])
            summary = summarizer.summarize(v)
            v.update({
                "ai_topic": summary.get("topic", ""),
                "ai_category": summary.get("category_tag", ""),
                "ai_summary": summary.get("summary", ""),
                "ai_highlights": summary.get("highlights", []),
                "ai_audience": summary.get("target_audience", ""),
                "ai_recommendation": summary.get("recommendation", "可选"),
                "ai_reason": summary.get("recommendation_reason", ""),
            })
            summaries.append(v)
            time.sleep(0.1)
        detailed = summaries
        print()
    else:
        # 无AI模式：用规则填充
        for v in detailed:
            v["ai_topic"] = v["title"][:20]
            v["ai_category"] = v.get("category", "其他")
            v["ai_summary"] = (v.get("desc", "") or
                               v.get("description", ""))[:150]
            v["ai_highlights"] = []
            v["ai_audience"] = "一般观众"
            v["ai_recommendation"] = "可选"
            v["ai_reason"] = "未使用AI分析"

    # ── 5. 排序 ────────────────────────────────────
    if args.sort_by == "recommendation":
        detailed.sort(key=lambda v: REC_SORT.get(
            v.get("ai_recommendation", "可选"), 3
        ))
    elif args.sort_by == "date":
        detailed.sort(key=lambda v: v.get("created", 0), reverse=True)
    elif args.sort_by == "views":
        detailed.sort(key=lambda v: v.get("view", 0), reverse=True)

    # ── 6. 输出 ────────────────────────────────────
    print_banner(up_info, len(detailed))

    if args.output == "json":
        print(json.dumps(detailed, ensure_ascii=False, indent=2))
    elif args.output == "markdown":
        print_markdown(detailed, up_info)
    else:
        print_text(detailed)

    # 保存文件
    safe_name = "".join(
        c for c in up_info["uname"] if c.isalnum() or c in "_- "
    ).strip()[:30]
    out_dir = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")

    md_path = os.path.join(out_dir, f"{safe_name}_{ts}.md")
    json_path = os.path.join(out_dir, f"{safe_name}_{ts}.json")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(generate_markdown(detailed, up_info))
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(detailed, f, ensure_ascii=False, indent=2)

    print(f"\n📁 报告已保存:")
    print(f"   Markdown: {md_path}")
    print(f"   JSON:     {json_path}")


# ── 输出格式化 ──────────────────────────────────────

def print_markdown(videos: list[dict], up_info: dict):
    """终端Markdown风格输出"""
    current_rec = None
    for v in videos:
        rec = v.get("ai_recommendation", "可选")
        if rec != current_rec:
            current_rec = rec
            icon = REC_ICONS.get(rec, "❓")
            print(f"\n## {icon} {rec}")
            print()
        print(f"### [{v['ai_category']}] {v['title']}")
        print(f"> 📅 {v['created_str']}  |  ⏱ {v['duration']}  |  "
              f"👁 {v.get('view', 0):,}  |  👍 {v.get('like', 0):,}")
        print(f"> {v['ai_summary']}")
        if v.get("ai_highlights"):
            for h in v["ai_highlights"]:
                print(f">   • {h}")
        print(f"> 🎯 {v.get('ai_audience', '')}  |  "
              f"📌 {v.get('ai_reason', '')}")
        print(f"> 🔗 https://www.bilibili.com/video/{v['bvid']}")
        print()


def print_text(videos: list[dict]):
    """纯文本输出"""
    current_rec = None
    for v in videos:
        rec = v.get("ai_recommendation", "可选")
        if rec != current_rec:
            current_rec = rec
            icon = REC_ICONS.get(rec, "❓")
            print(f"\n{'─' * 50}")
            print(f"  {icon} {rec}")
            print(f"{'─' * 50}")
        print(f"\n📺 [{v['ai_category']}] {v['title']}")
        print(f"   📅 {v['created_str']} | ⏱ {v['duration']} | "
              f"👁 {v.get('view', 0):,}")
        print(f"   📝 {v['ai_summary']}")
        print(f"   🔗 https://www.bilibili.com/video/{v['bvid']}")


def generate_markdown(videos: list[dict], up_info: dict) -> str:
    """生成完整Markdown报告"""
    lines = [
        f"# 📺 {up_info['uname']} - 视频摘要报告",
        "",
        f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"> 粉丝: {up_info.get('fans', '?'):,}  |  "
        f"视频总数: {len(videos)}",
        f"> UP主页: https://space.bilibili.com/{up_info['mid']}",
        "",
        "---",
        "",
    ]

    # 统计
    rec_count = {"强烈推荐": 0, "推荐": 0, "可选": 0, "可跳过": 0}
    cat_count = {}
    for v in videos:
        rec = v.get("ai_recommendation", "可选")
        rec_count[rec] = rec_count.get(rec, 0) + 1
        cat = v.get("ai_category", "其他")
        cat_count[cat] = cat_count.get(cat, 0) + 1

    lines.append("## 📊 概览")
    lines.append("")
    lines.append("| 推荐度 | 数量 | 占比 |")
    lines.append("|--------|------|------|")
    for rec in ["强烈推荐", "推荐", "可选", "可跳过"]:
        count = rec_count.get(rec, 0)
        pct = f"{count / len(videos) * 100:.1f}%" if videos else "0%"
        icon = REC_ICONS.get(rec, "")
        lines.append(f"| {icon} {rec} | {count} | {pct} |")
    lines.append("")

    lines.append("## 📂 内容分类")
    lines.append("")
    sorted_cats = sorted(cat_count.items(), key=lambda x: x[1], reverse=True)
    for cat, count in sorted_cats[:10]:
        lines.append(f"- **{cat}**: {count} 个")
    lines.append("")

    lines.append("---")
    lines.append("")

    # 按推荐度分组
    current_rec = None
    for v in videos:
        rec = v.get("ai_recommendation", "可选")
        if rec != current_rec:
            current_rec = rec
            icon = REC_ICONS.get(rec, "❓")
            lines.append(f"## {icon} {rec}")
            lines.append("")

        lines.append(f"### [{v.get('ai_category', '其他')}] {v['title']}")
        lines.append("")
        lines.append(
            f"> 📅 {v['created_str']}  |  ⏱ {v['duration']}  |  "
            f"👁 {v.get('view', 0):,}  |  👍 {v.get('like', 0):,}"
        )
        lines.append("")
        lines.append(f"{v.get('ai_summary', '暂无摘要')}")
        lines.append("")
        if v.get("ai_highlights"):
            for h in v["ai_highlights"]:
                lines.append(f"- ✨ {h}")
            lines.append("")
        lines.append(
            f"🎯 **受众**: {v.get('ai_audience', '一般观众')}  |  "
            f"📌 {v.get('ai_reason', '')}"
        )
        lines.append("")
        lines.append(f"🔗 https://www.bilibili.com/video/{v['bvid']}")
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    main()

"""
AI 视频概括模块
使用 OpenAI 兼容 API 对视频信息进行智能概括
"""

import json
import os
from typing import Optional

import requests


class VideoSummarizer:
    """AI视频内容概括器"""

    PROMPT_TEMPLATE = """你是一个专业的内容评审员。请根据以下B站视频信息，生成结构化的内容摘要。

视频信息：
- 标题：{title}
- 时长：{duration}
- 分区：{category}
- 播放量：{views}
- 简介：{desc}
- 标签：{tags}

请以JSON格式输出（只输出JSON，不要其他内容）：
{{
    "topic": "一句话主题概述（20字以内）",
    "category_tag": "分类标签（如：科技/知识/生活/游戏/影视/财经/编程/评测/Vlog/教程/其他）",
    "summary": "核心内容概括（80-150字，提炼视频讨论了什么、核心观点/结论是什么）",
    "highlights": ["亮点1", "亮点2", "亮点3"],
    "target_audience": "目标受众（10字以内）",
    "recommendation": "推荐度",
    "recommendation_reason": "推荐理由（30字以内）"
}}

推荐度规则：
- "强烈推荐"：干货极多、内容独特、信息密度高
- "推荐"：内容有价值，值得一看
- "可选"：内容尚可，但信息密度一般
- "可跳过"：水视频、广告、内容重复、时效性过强"""

    def __init__(self, api_key: Optional[str] = None,
                 api_base: Optional[str] = None,
                 model: Optional[str] = None):
        self.api_key = api_key or os.getenv("LLM_API_KEY", "")
        self.api_base = (api_base or
                         os.getenv("LLM_API_BASE",
                                   "https://api.openai.com/v1"))
        self.model = model or os.getenv("LLM_MODEL", "gpt-4o-mini")

    def _call_llm(self, prompt: str) -> str:
        """调用LLM"""
        resp = requests.post(
            f"{self.api_base}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [
                    {"role": "system",
                     "content": "你是一个视频内容评审专家，输出简洁准确的视频摘要。"},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 600,
            },
            timeout=30,
        )
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def summarize(self, video: dict) -> dict:
        """概括单个视频"""
        prompt = self.PROMPT_TEMPLATE.format(
            title=video.get("title", ""),
            duration=video.get("duration", ""),
            category=video.get("category", ""),
            views=video.get("views", "未知"),
            desc=(video.get("desc", "") or
                  video.get("description", ""))[:200],
            tags=", ".join(video.get("tags", [])[:10]),
        )
        try:
            result = self._call_llm(prompt)
            # 清洗可能的 markdown 包裹
            result = result.strip()
            if result.startswith("```"):
                result = result.split("\n", 1)[1]
                if result.endswith("```"):
                    result = result[:-3]
            return json.loads(result)
        except (json.JSONDecodeError, KeyError, requests.RequestException):
            return self._fallback_summary(video)

    def _fallback_summary(self, video: dict) -> dict:
        """LLM不可用时的降级摘要（基于规则）"""
        title = video.get("title", "")
        desc = video.get("desc", "") or video.get("description", "")
        duration_str = video.get("duration", "0:00")
        category = video.get("category", "")

        # 时长分析
        from bilibili import BilibiliAPI
        api = BilibiliAPI()
        secs = api.length_to_seconds(duration_str)

        # 猜测分类
        cat_map = {
            "科技": ["AI", "科技", "程序", "代码", "算法", "硬件", "芯片",
                     "开发", "软件", "编程", "Python", "JS", "GitHub"],
            "知识": ["历史", "经济", "哲学", "心理", "社会", "法律",
                     "数学", "物理", "化学"],
            "生活": ["Vlog", "日常", "美食", "旅行", "探店", "健身"],
            "游戏": ["游戏", "攻略", "实况", "电竞", "主机"],
            "影视": ["电影", "剧集", "动漫", "番剧", "解说"],
            "财经": ["股票", "基金", "投资", "理财", "经济", "商业"],
            "编程": ["前端", "后端", "全栈", "架构", "开源", "Github"],
            "评测": ["评测", "开箱", "体验", "对比", "横评"],
        }

        guessed_cat = "其他"
        for cat, keywords in cat_map.items():
            for kw in keywords:
                if kw.lower() in (title + desc).lower():
                    guessed_cat = cat
                    break
            if guessed_cat != "其他":
                break

        # 推荐度估计
        if secs < 120:
            rec = "可跳过"
            rec_reason = "视频较短，信息量有限"
        elif secs > 1800:
            rec = "推荐"
            rec_reason = "深度内容，信息量可能较大"
        else:
            rec = "可选"
            rec_reason = "中等长度，建议预览判断"

        return {
            "topic": title[:20],
            "category_tag": category or guessed_cat,
            "summary": desc[:150] if desc else f"视频标题：{title}",
            "highlights": [],
            "target_audience": "一般观众",
            "recommendation": rec,
            "recommendation_reason": rec_reason,
        }

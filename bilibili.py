"""
B站 API 封装模块
- 搜索UP主
- 获取UP主投稿视频列表
- 获取视频详细信息
- WBI签名处理
"""

import hashlib
import re
import time
from typing import Optional
from urllib.parse import urlencode

import requests

# WBI签名混排表（固定）
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 52, 44, 34,
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
}


class BilibiliAPI:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._mixin_key: Optional[str] = None
        self._img_key: Optional[str] = None
        self._sub_key: Optional[str] = None

    # ── WBI 签名 ────────────────────────────────────────────

    def _get_mixin_key(self, orig_key: str) -> str:
        return "".join(orig_key[i] for i in MIXIN_KEY_ENC_TAB)[:32]

    def _fetch_wbi_keys(self):
        """从导航接口获取 WBI 密钥"""
        resp = self.session.get(
            "https://api.bilibili.com/x/web-interface/nav",
            timeout=10,
        )
        data = resp.json()
        wbi_img = data["data"]["wbi_img"]
        self._img_key = re.search(r"wbi/(.*?)\.",
                                  wbi_img["img_url"]).group(1)
        self._sub_key = re.search(r"wbi/(.*?)\.",
                                  wbi_img["sub_url"]).group(1)
        self._mixin_key = self._get_mixin_key(
            self._img_key + self._sub_key
        )

    def _sign_params(self, params: dict) -> dict:
        """对参数进行 WBI 签名"""
        if not self._mixin_key:
            self._fetch_wbi_keys()
        params["wts"] = int(time.time())
        params = dict(sorted(params.items()))
        query = urlencode(params)
        w_rid = hashlib.md5((query + self._mixin_key).encode()).hexdigest()
        params["w_rid"] = w_rid
        return params

    # ── 核心 API ────────────────────────────────────────────

    def search_up(self, name: str) -> Optional[dict]:
        """搜索UP主，返回第一个匹配结果 {mid, uname, face, sign}"""
        params = {
            "search_type": "bili_user",
            "keyword": name,
        }
        resp = self.session.get(
            "https://api.bilibili.com/x/web-interface/search/type",
            params=params,
            timeout=10,
        )
        data = resp.json()
        results = data.get("data", {}).get("result", [])
        if not results:
            return None
        user = results[0]
        return {
            "mid": user["mid"],
            "uname": user["uname"],
            "face": user.get("upic", ""),
            "sign": user.get("usign", ""),
            "fans": user.get("fans", 0),
            "videos": user.get("videos", 0),
        }

    def get_user_videos(self, mid: int, page: int = 1,
                        page_size: int = 50) -> dict:
        """获取UP主投稿视频列表（分页）"""
        params = self._sign_params({
            "mid": mid,
            "ps": page_size,
            "pn": page,
            "order": "pubdate",
        })
        resp = self.session.get(
            "https://api.bilibili.com/x/space/wbi/arc/search",
            params=params,
            timeout=15,
        )
        data = resp.json()
        page_info = data["data"]["page"]
        vlist = data["data"]["list"]["vlist"]

        videos = []
        for v in vlist:
            videos.append({
                "bvid": v["bvid"],
                "title": v["title"],
                "description": v.get("description", ""),
                "length": v["length"],          # 时长字符串 mm:ss
                "created": v["created"],         # Unix时间戳
                "play": v.get("play", 0),
                "comment": v.get("comment", 0),
                "video_review": v.get("video_review", 0),   # 弹幕数
                "pic": v.get("pic", ""),
                "typeid": v.get("typeid", 0),
                "is_union_video": v.get("is_union_video", 0),
            })

        return {
            "videos": videos,
            "count": page_info["count"],
            "page": page_info["pn"],
            "page_size": page_info["ps"],
        }

    def get_all_videos(self, mid: int, max_pages: int = 20) -> list[dict]:
        """获取UP主全部投稿视频"""
        all_videos = []
        page = 1
        while page <= max_pages:
            result = self.get_user_videos(mid, page=page, page_size=50)
            all_videos.extend(result["videos"])
            if len(all_videos) >= result["count"]:
                break
            page += 1
            time.sleep(0.5)  # 礼貌间隔
        return all_videos

    def get_video_detail(self, bvid: str) -> Optional[dict]:
        """获取视频详细信息（含stat数据）"""
        resp = self.session.get(
            "https://api.bilibili.com/x/web-interface/view",
            params={"bvid": bvid},
            timeout=10,
        )
        data = resp.json()
        if data["code"] != 0:
            return None
        info = data["data"]
        stat = info.get("stat", {})
        return {
            "bvid": bvid,
            "title": info["title"],
            "desc": info.get("desc", ""),
            "duration": info["duration"],      # 秒
            "pic": info.get("pic", ""),
            "pubdate": info.get("pubdate", 0),
            "tid": info.get("tid", 0),
            "tname": info.get("tname", ""),    # 分区名
            "view": stat.get("view", 0),
            "danmaku": stat.get("danmaku", 0),
            "reply": stat.get("reply", 0),
            "favorite": stat.get("favorite", 0),
            "coin": stat.get("coin", 0),
            "share": stat.get("share", 0),
            "like": stat.get("like", 0),
            "tags": [t["tag_name"]
                     for t in info.get("tags", [])],
        }

    @staticmethod
    def length_to_seconds(length_str: str) -> int:
        """将'MM:SS'或'HH:MM:SS'转为秒"""
        parts = length_str.split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3:
            return (int(parts[0]) * 3600 +
                    int(parts[1]) * 60 +
                    int(parts[2]))
        return 0

    @staticmethod
    def format_duration(seconds: int) -> str:
        """秒转为可读时长"""
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

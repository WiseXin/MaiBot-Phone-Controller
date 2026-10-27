"""网易云音乐控制与歌词查询模块 (公开 API + ADB 真机控制)

支持：
1. 公开 Web API: 搜歌、查歌词、查精选热评 (无需登录/开箱即用)
2. 真机 ADB 控制: 唤起手机网易云、媒体键切歌/暂停、一起听房间打字交流
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
import aiohttp
from .adb_engine import AdbEngine

logger = logging.getLogger("plugin.phone_controller.music")


class MusicClient:
    """网易云音乐服务与真机交互器"""

    def __init__(self, adb: AdbEngine, package_name: str = "com.netease.cloudmusic"):
        self.adb = adb
        self.package_name = package_name

    # -------------------------------------------------------------------------
    # 1. 公开 Web API (免登录)
    # -------------------------------------------------------------------------

    async def search_song(self, keyword: str, limit: int = 5) -> Tuple[bool, List[Dict[str, Any]], str]:
        """搜索歌曲，获取歌曲 ID、歌名、歌手与专辑"""
        url = "https://music.163.com/api/search/get"
        params = {"s": keyword, "type": 1, "limit": max(1, min(limit, 10)), "offset": 0}
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://music.163.com/",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        return False, [], f"搜索失败 HTTP {resp.status}"
                    data = await resp.json()
                    songs = data.get("result", {}).get("songs", [])
                    res = []
                    for s in songs:
                        artists = ", ".join(a.get("name", "") for a in s.get("artists", []))
                        res.append({
                            "id": s.get("id"),
                            "name": s.get("name"),
                            "artist": artists,
                            "album": s.get("album", {}).get("name", ""),
                            "duration_ms": s.get("duration", 0),
                        })
                    return True, res, ""
        except Exception as e:
            logger.error("网易云搜歌异常: %s", e)
            return False, [], str(e)

    async def get_lyrics(self, song_id: int) -> Tuple[bool, str, str]:
        """获取指定歌曲的歌词文本 (自动清洗时间轴标签)"""
        url = f"https://music.163.com/api/song/lyric?id={song_id}&lv=1&kv=1&tv=-1"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://music.163.com/",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        return False, "", f"获取歌词失败 HTTP {resp.status}"
                    data = await resp.json()
                    lrc = data.get("lrc", {}).get("lyric", "")
                    if not lrc:
                        return False, "", "暂无歌词或为纯音乐"

                    # 去除时间轴 [00:12.34]
                    clean_lrc = re.sub(r"\[\d{2}:\d{2}\.\d{2,3}\]", "", lrc).strip()
                    # 去除多余空行
                    lines = [line.strip() for line in clean_lrc.splitlines() if line.strip()]
                    return True, "\n".join(lines), ""
        except Exception as e:
            return False, "", str(e)

    async def get_hot_comments(self, song_id: int, limit: int = 5) -> Tuple[bool, List[Dict[str, str]], str]:
        """获取歌曲的热门乐评"""
        url = f"https://music.163.com/api/v1/resource/comments/R_SO_4_{song_id}"
        params = {"limit": max(1, min(limit, 10)), "offset": 0}
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://music.163.com/",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        return False, [], f"获取评论失败 HTTP {resp.status}"
                    data = await resp.json()
                    hot = data.get("hotComments", [])
                    results = []
                    for c in hot[:limit]:
                        results.append({
                            "user": c.get("user", {}).get("nickname", "未知用户"),
                            "content": c.get("content", ""),
                            "liked_count": str(c.get("likedCount", 0)),
                        })
                    return True, results, ""
        except Exception as e:
            return False, [], str(e)

    # -------------------------------------------------------------------------
    # 2. 真机 ADB 媒体交互
    # -------------------------------------------------------------------------

    async def launch_app(self) -> Tuple[bool, str]:
        """拉起手机端网易云音乐"""
        return await self.adb.open_app(self.package_name)

    async def control_playback(self, action: str) -> Tuple[bool, str]:
        """
        通过系统多媒体控制键控制播放。
        :param action: play_pause(播放/暂停), next(下一首), prev(上一首)
        """
        action = action.lower().strip()
        if action in ("play_pause", "toggle", "play", "pause"):
            return await self.adb.press_key("85")  # KEYCODE_MEDIA_PLAY_PAUSE
        elif action in ("next", "下一首"):
            return await self.adb.press_key("87")  # KEYCODE_MEDIA_NEXT
        elif action in ("prev", "previous", "上一首"):
            return await self.adb.press_key("88")  # KEYCODE_MEDIA_PREVIOUS
        else:
            return False, f"未知的媒体控制动作: {action}"

    async def room_say(self, text: str) -> Tuple[bool, str]:
        """
        在手机网易云「一起听」聊天室发言 (模拟点击输入框 + ADBKeyboard 中文打字 + 发送)
        """
        # 1. 尝试寻找界面中的聊天输入框
        coords = await self.adb.find_element_by_text("说点什么")
        if not coords:
            coords = await self.adb.find_element_by_text("发条消息")

        if coords:
            await self.adb.tap(coords[0], coords[1])
            await asyncio.sleep(0.5)

        # 2. 打字
        ok, msg = await self.adb.input_text(text)
        if not ok:
            return False, f"输入消息失败: {msg}"

        await asyncio.sleep(0.3)
        # 3. 点击发送按钮或回车
        send_coords = await self.adb.find_element_by_text("发送")
        if send_coords:
            await self.adb.tap(send_coords[0], send_coords[1])
        else:
            await self.adb.press_key("enter")

        return True, f"已在网易云一起听发送: {text}"

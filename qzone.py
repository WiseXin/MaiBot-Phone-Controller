"""QQ 空间联动模块 (基于 OneBot 11 / NapCat HTTP API)

支持：
1. 发送空间说说 (可带文本与图片)
2. 空间点赞与最新动态检索
3. 查看好友说说或自己发布的说说
4. 内置内存频控安全限制，防止刷屏封号
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Tuple
import aiohttp

logger = logging.getLogger("plugin.phone_controller.qzone")


class QzoneClient:
    """基于 OneBot HTTP 接口的 QQ 空间客户端"""

    def __init__(self, base_url: str = "http://100.115.30.64:3000", token: str = ""):
        self.base_url = base_url.rstrip("/")
        self.token = token.strip()
        # 内存频控队列 [timestamp]
        self._post_timestamps: List[float] = []

    def _check_rate_limit(self, max_per_day: int = 8) -> Tuple[bool, str]:
        now = time.time()
        # 过滤出 24 小时内的发说说时间戳
        self._post_timestamps = [t for t in self._post_timestamps if now - t < 86400]
        if len(self._post_timestamps) >= max_per_day:
            return False, f"已达每日安全限额 ({max_per_day} 条/天)，请明天再试"
        return True, ""

    async def _call_api(self, endpoint: str, payload: Dict[str, Any]) -> Tuple[bool, Any, str]:
        """向 NapCat 发送 POST 协议请求"""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    txt = await resp.text()
                    if resp.status != 200:
                        return False, None, f"HTTP {resp.status}: {txt[:200]}"
                    data = await resp.json()
                    status = data.get("status")
                    retcode = data.get("retcode")
                    if status == "ok" or retcode == 0:
                        return True, data.get("data"), ""
                    return False, None, f"接口返回错误: {data.get('message', txt[:200])}"
        except Exception as e:
            logger.error("Qzone API 请求异常 %s: %s", endpoint, e)
            return False, None, str(e)

    async def publish_feed(self, content: str, images: Optional[List[str]] = None, max_daily: int = 8) -> Tuple[bool, str]:
        """发布一条 QQ 空间说说"""
        ok, limit_msg = self._check_rate_limit(max_daily)
        if not ok:
            return False, limit_msg

        payload: Dict[str, Any] = {"content": content}
        if images:
            payload["images"] = images

        # 尝试标准 OneBot 扩展接口 send_qzone_msg
        ok, res, err = await self._call_api("send_qzone_msg", payload)
        if ok:
            self._post_timestamps.append(time.time())
            return True, f"成功发布说说: {content[:30]}..."
        return False, f"发说说失败: {err}"

    async def like_feed(self, feed_id: str = "", user_id: str = "") -> Tuple[bool, str]:
        """为一条说说点赞"""
        payload: Dict[str, Any] = {}
        if feed_id:
            payload["feed_id"] = feed_id
            payload["tid"] = feed_id
        if user_id:
            payload["user_id"] = user_id

        ok, res, err = await self._call_api("set_qzone_like", payload)
        if not ok:
            # 兼容尝试 like_qzone 接口
            ok, res, err = await self._call_api("like_qzone", payload)

        if ok:
            return True, "点赞成功"
        return False, f"点赞失败: {err}"

    async def get_feeds(self, count: int = 5) -> Tuple[bool, List[Dict[str, Any]], str]:
        """获取好友空间最新说说列表"""
        payload = {"count": max(1, min(count, 20))}
        ok, data, err = await self._call_api("get_qzone_feeds", payload)
        if not ok:
            # 尝试备用命名
            ok, data, err = await self._call_api("get_qzone_msg_list", payload)

        if ok and isinstance(data, list):
            return True, data, ""
        elif ok and isinstance(data, dict) and "feeds" in data:
            return True, data["feeds"], ""
        return False, [], f"获取动态失败: {err}"

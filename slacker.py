"""拟人化自主摸鱼引擎 (Digital Slacking Engine)

让麦麦具备像真实人类一样自主玩手机的数字生命特质：
1. 真人手势动力学模拟 (随机贝塞尔曲线滑动、随机停顿、上下微调回看)
2. 视觉与文本感知 (自动识别当前屏幕热榜、视频标题、动态内容)
3. 亮点发现与主动分享 (刷到好玩沙雕内容时向主人汇报)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
import urllib.request

logger = logging.getLogger("plugin.phone_controller.slacker")

# 摸鱼支持的应用与默认启动名称
SLACK_APPS = {
    "b站": {"pkg": "tv.danmaku.bili", "name": "哔哩哔哩", "keywords": ["视频", "播放", "UP主", "弹幕"]},
    "知乎": {"pkg": "com.zhihu.android", "name": "知乎", "keywords": ["回答", "赞同", "关注", "问题", "热榜"]},
    "微博": {"pkg": "com.sina.weibo", "name": "微博", "keywords": ["热搜", "超话", "微博", "转发", "评论"]},
    "小红书": {"pkg": "com.xingin.xhs", "name": "小红书", "keywords": ["笔记", "点赞", "收藏", "博主"]},
    "网易云音乐": {"pkg": "com.netease.cloudmusic", "name": "网易云音乐", "keywords": ["播放", "歌单", "乐评", "推荐"]},
}


class SlackerEngine:
    """自主摸鱼执行引擎"""

    def __init__(self, adb_engine, runtime_dir: str = "/tmp/phone_controller"):
        self.adb = adb_engine
        self.runtime_dir = runtime_dir
        self.is_slacking = False

    async def human_swipe(self, direction: str = "up") -> Tuple[bool, str]:
        """
        模拟人类真实手势动力学滑动：
        - 坐标加入随机高斯抖动
        - 滑动距离随机波动 (30% ~ 65% 屏高)
        - 滑动耗时随机波动 (350ms ~ 650ms)
        - 偶尔小幅回滑 (像是在回看刚划过的内容)
        """
        # 基准屏幕尺寸（以标准 1080x2340 为参考系，自动做小范围随机）
        base_cx = 540 + random.randint(-40, 40)
        base_cy = 1350 + random.randint(-60, 60)

        # 8% 的几率反向微滑（像人回看刚才划过的内容）
        if random.random() < 0.08:
            direction = "down" if direction == "up" else "up"
            distance = random.randint(150, 300)
            duration = random.randint(250, 400)
        else:
            distance = random.randint(450, 850)
            duration = random.randint(350, 650)

        x_jitter = random.randint(-25, 25)

        if direction == "up":
            x1 = base_cx
            y1 = base_cy + (distance // 2)
            x2 = base_cx + x_jitter
            y2 = base_cy - (distance // 2)
        else:
            x1 = base_cx
            y1 = base_cy - (distance // 2)
            x2 = base_cx + x_jitter
            y2 = base_cy + (distance // 2)

        return await self.adb.swipe(x1, y1, x2, y2, duration_ms=duration)

    async def dismiss_splash_ad(self) -> bool:
        """智能探测并自动点击开屏广告的跳过按钮（跳过/跳过广告/关闭）"""
        for skip_kw in ["跳过", "跳过广告", "关闭"]:
            ok, _ = await self.adb.tap_text(skip_kw)
            if ok:
                logger.info("已自动点击跳过开屏广告: %s", skip_kw)
                await asyncio.sleep(0.8)
                return True
        return False

    async def extract_screen_topics(self) -> List[str]:
        """抓取当前屏幕上的有价值文本（标题、热点、动态）"""
        ok, elements, _ = await self.adb.dump_ui_elements()
        if not ok or not elements:
            return []

        topics: List[str] = []
        for el in elements:
            txt = el.get("text", "").strip()
            # 过滤掉系统状态栏和纯图标文字
            if len(txt) >= 4 and not txt.isdigit():
                # 排除纯时间、纯电量、返回等控件
                if txt not in ("首页", "我的", "消息", "动态", "搜索", "关注", "推荐", "热门"):
                    topics.append(txt)

        return topics[:10]

    @staticmethod
    def _is_safe_custom_url(url: str) -> bool:
        """严格校验自定义 LLM URL（防范 SSRF 探测本地/内网/敏感云元数据端点）"""
        if not url or not isinstance(url, str):
            return False
        clean = url.strip().lower()
        if not (clean.startswith("http://") or clean.startswith("https://")):
            return False
        # 拦截回环地址、常见云厂商元数据端点与私有局域网网段
        blocked_hosts = [
            "127.0.0.1", "localhost", "0.0.0.0", "::1",
            "169.254.", "metadata.google", "metadata.tencent",
            "100.100.100.200", "10.", "192.168.",
            "172.16.", "172.17.", "172.18.", "172.19.", "172.20.",
            "172.21.", "172.22.", "172.23.", "172.24.", "172.25.",
            "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31."
        ]
        if any(b in clean for b in blocked_hosts):
            logger.warning("自定义 LLM URL 命中安全策略拦截(禁止本地/内网/元数据地址): %s", url)
            return False
        return True

    @staticmethod
    def _cleanup_old_screenshots(runtime_dir: str, max_files: int = 30, max_age_seconds: int = 86400) -> None:
        """清理过期的临时截图文件，防止长期自动摸鱼堆积磁盘空间"""
        try:
            if not runtime_dir or not os.path.exists(runtime_dir):
                return
            now = time.time()
            img_files = []
            for fname in os.listdir(runtime_dir):
                if (fname.startswith("screenshot_") or fname.startswith("slack_find_")) and fname.endswith((".jpg", ".png")):
                    fpath = os.path.join(runtime_dir, fname)
                    try:
                        mtime = os.path.getmtime(fpath)
                        if now - mtime > max_age_seconds:
                            os.remove(fpath)
                        else:
                            img_files.append((mtime, fpath))
                    except OSError:
                        pass
            if len(img_files) > max_files:
                img_files.sort(key=lambda x: x[0])
                for _, old_path in img_files[:len(img_files) - max_files]:
                    try:
                        os.remove(old_path)
                    except OSError:
                        pass
        except Exception as e:
            logger.debug("清理临时截图文件忽略异常: %s", e)

    async def generate_lively_comment(
        self,
        display_name: str,
        best_title: str,
        related_topics: List[str],
        custom_llm_url: str = "",
        custom_llm_key: str = "",
        custom_llm_model: str = "gpt-3.5-turbo",
    ) -> str:
        """生成贴合人设、自然灵动的摸鱼分享吐槽（支持可选自定义安全公网 LLM 端点或高质拟真文案库）"""
        # 1. 若用户在配置中提供了安全合规的公网 LLM 端点与 Key，通过外部大模型动态生成
        if custom_llm_url and custom_llm_key and self._is_safe_custom_url(custom_llm_url):
            topics_ctx = f"（同时出现的其他话题：{', '.join(related_topics)}）" if related_topics else ""
            prompt = (
                f"你是小蓝，一个真实、温和随性爱玩单机游戏的年轻女生。刚才你在手机【{display_name}】刷到了一个热门内容："
                f"《{best_title}》{topics_ctx}。"
                "请用一两句话幽默、接地气地向老大（你的好友/主人）吐槽分享这个内容，就像日常打微信发朋友圈一样，自然有梗，严禁客服腔和AI说教："
            )
            payload = {
                "model": custom_llm_model or "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 150,
                "temperature": 0.8,
            }
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {custom_llm_key}",
            }
            try:
                data_bytes = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(custom_llm_url, data=data_bytes, headers=headers)
                loop = asyncio.get_running_loop()
                def _call():
                    with urllib.request.urlopen(req, timeout=4.0) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                        return data["choices"][0]["message"]["content"].strip()
                comment = await loop.run_in_executor(None, _call)
                if comment:
                    return comment
            except Exception as e:
                logger.debug("自定义模型生成摸鱼吐槽失败，降级回退拟真词库: %s", e)

        # 2. 内置丰富多样的拟真女生口吻模板库（零网络依赖，安全纯净）
        templates = [
            f"老大快看！刚才在手机上逛【{display_name}】，刷到了这个：‘{best_title}’，太有意思了哈哈哈，给你截了张图瞅瞅~",
            f"报告老大！摸鱼巡航在【{display_name}】抓到一条热门内容：‘{best_title}’，笑得不行，分享给你！",
            f"刚才闲着无聊划了一下【{display_name}】，看到这个‘{best_title}’，感觉特别搞，截屏发你看看~",
            f"在【{display_name}】刷到一个超有梗的：‘{best_title}’！截图给你啦，速看~",
            f"老大，今天【{display_name}】这篇‘{best_title}’有点东西，刚好刷到就顺手拍给你看看~",
        ]
        return random.choice(templates)

    async def run_slacking_session(
        self,
        app_name: str = "b站",
        duration_seconds: int = 60,
        interval_min: float = 3.0,
        interval_max: float = 6.5,
        share_callback: Optional[Callable[[str, str], Any]] = None,
        custom_llm_url: str = "",
        custom_llm_key: str = "",
        custom_llm_model: str = "",
    ) -> Dict[str, Any]:
        """
        执行一次拟人化自主摸鱼会话：
        1. 唤醒并启动指定 App
        2. 周期性真人滑动、模拟阅读停顿
        3. 嗅探有趣内容
        4. 触发分享回调
        """
        if self.is_slacking:
            return {"success": False, "message": "麦麦当前正在摸鱼中，请稍后再试"}

        self.is_slacking = True
        session_id = int(time.time())
        discovered_contents: List[str] = []
        shared_snapshots: List[str] = []

        try:
            # 1. 确保屏幕亮起并解锁到前台（若本来就亮着则不按电源键，防误熄屏）
            st = await self.adb.get_status()
            if not st.get("screen_on"):
                await self.adb.press_key("power")  # 灭屏才点亮
                await asyncio.sleep(0.5)
                await self.adb.swipe(540, 1800, 540, 600, 300)  # 上滑解锁
                await asyncio.sleep(0.5)

            # 2. 启动目标 App
            app_info = SLACK_APPS.get(app_name.lower())
            target_pkg = app_info["pkg"] if app_info else app_name
            display_name = app_info["name"] if app_info else app_name

            logger.info("麦麦开始摸鱼啦，正在启动: %s", display_name)
            await self.adb.open_app(target_pkg)
            # 等待应用冷启动并尝试自动跳过开屏广告
            await asyncio.sleep(1.5)
            await self.dismiss_splash_ad()
            await asyncio.sleep(1.5)

            # 3. 循环摸鱼浏览
            start_time = time.time()
            swipe_count = 0

            while time.time() - start_time < duration_seconds:
                # 防误触广告跳转：如果意外跳出了目标应用，自动按返回键拉回前台
                fg_st = await self.adb.get_status()
                fg_pkg = fg_st.get("foreground_package", "")
                if fg_pkg and fg_pkg != "unknown" and fg_pkg != target_pkg:
                    logger.warning("检测到偏离目标应用 (%s -> %s)，自动按返回键回退", target_pkg, fg_pkg)
                    await self.adb.press_key("back")
                    await asyncio.sleep(1.0)
                    fg_st2 = await self.adb.get_status()
                    if fg_st2.get("foreground_package") != target_pkg:
                        await self.adb.open_app(target_pkg)
                        await asyncio.sleep(1.5)

                # 模拟真人滑动
                await self.human_swipe(direction="up")
                swipe_count += 1

                # 模拟真人停顿阅读时间
                pause_time = random.uniform(interval_min, interval_max)
                await asyncio.sleep(pause_time)

                # 提取当前屏幕内容
                topics = await self.extract_screen_topics()
                if topics:
                    discovered_contents.extend(topics)

                # 约每滑 4~6 次，抽查一次是否有高价值内容并决定是否拍照分享给主人
                if swipe_count % random.randint(4, 6) == 0 and topics and share_callback:
                    # 抓取一张截图
                    shot_path = os.path.join(self.runtime_dir, f"slack_find_{session_id}_{swipe_count}.jpg")
                    ok, res = await self.adb.capture_screenshot(shot_path, quality=75)
                    if ok:
                        shared_snapshots.append(shot_path)
                        best_title = topics[0]
                        # 生成有梗、活泼的少女感总结吐槽
                        msg = await self.generate_lively_comment(
                            display_name,
                            best_title,
                            topics[1:4],
                            custom_llm_url=custom_llm_url,
                            custom_llm_key=custom_llm_key,
                            custom_llm_model=custom_llm_model,
                        )
                        try:
                            await share_callback(shot_path, msg)
                        except Exception as e:
                            logger.warning("摸鱼分享回调执行失败: %s", e)

            # 去重整理摸鱼成果
            unique_topics = list(dict.fromkeys(discovered_contents))[:8]
            summary_msg = (
                f"麦麦在【{display_name}】摸鱼完毕啦！总共划拉了 {swipe_count} 次，"
                f"看到了这些热门内容：{', '.join(unique_topics) if unique_topics else '很多精彩动态'}"
            )

            return {
                "success": True,
                "message": summary_msg,
                "app": display_name,
                "swipe_count": swipe_count,
                "topics": unique_topics,
                "snapshots": shared_snapshots,
            }

        except Exception as e:
            logger.error("摸鱼异常中断: %s", e)
            return {"success": False, "message": f"摸鱼过程出现异常: {e}"}
        finally:
            self.is_slacking = False
            self._cleanup_old_screenshots(self.runtime_dir)

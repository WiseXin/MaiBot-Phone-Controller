"""拟人化自主摸鱼引擎 (Digital Slacking Engine)

让麦麦具备像真实人类一样自主玩手机的数字生命特质：
1. 真人手势动力学模拟 (随机贝塞尔曲线滑动、随机停顿、上下微调回看)
2. 视觉与文本感知 (自动识别当前屏幕热榜、视频标题、动态内容)
3. 亮点发现与主动分享 (刷到好玩沙雕内容时向主人汇报)
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import random
import re
import socket
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
import urllib.parse
import urllib.request

logger = logging.getLogger("plugin.phone_controller.slacker")

# 摸鱼支持的应用与默认启动名称
SLACK_APPS = {
    "b站": {"pkg": "tv.danmaku.bili", "name": "哔哩哔哩", "keywords": ["视频", "播放", "UP主", "弹幕"]},
    "知乎": {"pkg": "com.zhihu.android", "name": "知乎", "keywords": ["回答", "赞同", "关注", "问题", "热榜"]},
    "微博": {"pkg": "com.sina.weibo", "name": "微博", "keywords": ["热搜", "超话", "微博", "转发", "评论"]},
    "小红书": {"pkg": "com.xingin.xhs", "name": "小红书", "keywords": ["笔记", "点赞", "收藏", "博主"]},
    "抖音": {"pkg": "com.ss.android.ugc.aweme", "name": "抖音", "keywords": ["视频", "点赞", "关注", "评论", "分享", "音乐"]},
    "douyin": {"pkg": "com.ss.android.ugc.aweme", "name": "抖音", "keywords": ["视频", "点赞", "关注", "评论", "分享", "音乐"]},
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

    async def dismiss_splash_ad_and_login_popups(self) -> bool:
        """智能探测并自动跳过开屏广告，并自动关闭各 App 的登录拦截页、隐私授权弹窗或底部半屏抽屉 (支持多层清理)。"""
        total_dismissed = False

        # 最多连续清理 2 层弹窗 (例如知乎：第一层全屏登录页，关闭后会再弹一层底部半屏登录抽屉)
        for _ in range(2):
            ok, elements, _ = await self.adb.dump_ui_elements()
            if not ok or not elements:
                break

            # 1. 扫描是否有开屏跳过按钮
            ad_found = False
            for el in elements:
                txt = el.get("text", "").strip()
                if re.search(r"跳过(?:\s*\d+s?)?|跳过广告", txt, re.IGNORECASE):
                    center = el.get("center")
                    if center:
                        logger.info("已自动点击跳过开屏广告: %s at %s", txt, center)
                        await self.adb.tap(center[0], center[1])
                        await asyncio.sleep(1.0)
                        ad_found = True
                        total_dismissed = True
                        break
            if ad_found:
                continue

            # 2. 扫描是否处于“登录拦截页”、“协议条款弹窗”或“底部登录抽屉”
            all_texts = " ".join(el.get("text", "") for el in elements)
            login_keywords = [
                "登录知乎", "微信一键登录", "其他登录方式", "登录体验", "手机号一键登录",
                "手机号登录", "登录后继续操作", "登录后享受更多精彩", "请阅读并同意以下条款",
                "请阅读并同意", "同意并继续", "登录/注册", "立即登录", "去登录",
            ]
            is_login_page = any(kw in all_texts for kw in login_keywords)

            if not is_login_page:
                break

            logger.info("检测到应用进入登录拦截页或条款弹窗，启动自动规避跳过...")
            dismiss_clicked = False

            # 2.1 优先寻找任何 resource_id 包含 close / cancel / dismiss 的可点击控件 (如 id=com.zhihu.android:id/close)
            for el in elements:
                rid = el.get("resource_id", "").lower()
                clickable = el.get("clickable", False)
                center = el.get("center", [0, 0])
                if clickable and any(k in rid for k in ("close", "cancel", "dismiss", "exit")):
                    logger.info("点击 close 控件关闭弹窗: %s at %s", rid, center)
                    await self.adb.tap(center[0], center[1])
                    dismiss_clicked = True
                    await asyncio.sleep(1.0)
                    total_dismissed = True
                    break

            # 2.2 如果没找到具名 close 控件，扫描屏幕角部或弹窗右上角的关闭图标
            if not dismiss_clicked:
                for el in elements:
                    center = el.get("center", [0, 0])
                    clickable = el.get("clickable", False)
                    # 左上角返回/关闭叉号
                    if (center[0] < 200 and center[1] < 300) and clickable:
                        logger.info("点击左上角关闭叉号退出登录页: %s", center)
                        await self.adb.tap(center[0], center[1])
                        dismiss_clicked = True
                        await asyncio.sleep(1.0)
                        total_dismissed = True
                        break

            # 2.3 如果未能通过点击关闭，直接发送系统返回键 (back)
            if not dismiss_clicked:
                logger.info("未找到关闭控件，发送系统返回键 (back) 尝试退出登录弹窗")
                await self.adb.press_key("back")
                await asyncio.sleep(1.0)
                total_dismissed = True

        return total_dismissed

    async def dismiss_splash_ad(self) -> bool:
        """向后兼容别名：调用统一广告与登录拦截跳过引擎"""
        return await self.dismiss_splash_ad_and_login_popups()

    @staticmethod
    def _clean_topic_title(raw_text: str) -> Optional[str]:
        """深度清洗屏幕提取文本，坚决剔除按钮、登录引导、无障碍辅助标签、图标等系统 UI 噪音"""
        txt = raw_text.strip()
        if not txt or len(txt) < 5 or txt.isdigit():
            return None

        # 纯英文组件标识或纯符号标签直接剔除
        if re.fullmatch(r"[A-Za-z0-9_\s,\.\-]+", txt):
            return None

        # 1. 小红书卡片专属格式解析: "笔记  <标题> 来自<作者> <赞数>赞" 或 "<标题> 来自<作者>..."
        m_xhs = re.match(r"^(?:笔记\s+)?(.*?)\s+来自.*$", txt)
        if m_xhs:
            txt = m_xhs.group(1).strip()

        # 2. 系统 UI 固定无意义黑名单
        blacklist = {
            "首页", "我的", "消息", "动态", "搜索", "关注", "推荐", "热门", "游戏中心",
            "个人主页", "返回", "设置", "分享", "评论", "点赞", "收藏", "投币", "转发",
            "换一换", "刷新", "频道", "发布", "拍摄", "拍摄动态", "查看详情",
            "登录查看更多精彩内容", "去登录", "立即登录", "展开", "收起"
        }
        if txt in blacklist:
            return None

        # 3. 坚决过滤登录与授权协议噪音词（防止将“微信一键登录”等误当成热门帖子）
        login_noise = [
            "一键登录", "快速登录", "其他登录方式", "登录知乎", "登录b站", "登录小红书",
            "登录抖音", "手机号登录", "微信登录", "qq登录", "微博登录", "立即登录",
            "去登录", "登录/注册", "注册账号", "请阅读并同意", "服务协议", "隐私政策",
            "个人信息保护指引", "同意并继续", "同意条款", "暂不登录", "账号密码登录",
            "验证码登录", "找回密码", "已有账号", "需登录", "点击登录", "账号异常", "登录后",
        ]
        if any(kw in txt for kw in login_noise):
            return None

        # 3. 剔除常见的 Android 无障碍辅助描述与统计指标
        noise_sub = [
            r",?\s*轻点两下.*",
            r"^宣传图片，?",
            r",?\s*\d+之\d+，?",
            r",?\s*(?:竖屏|竖版|横屏).*",
            r",?\s*(?:按钮|图标|icon|avatar).*",
            r",?\s*\d+(\.\d+)?[万千]?观看.*",
            r",?\s*\d+弹幕.*",
            r",?\s*时长\d+.*",
            r",?\s*UP主.*",
            r",?\s*\d+(\.\d+)?[万千]?点赞.*",
            r",?\s*\d+(\.\d+)?[万千]?赞同.*",
            r",?\s*\d+(\.\d+)?[万千]?人赞同.*",
            r",?\s*\d+(\.\d+)?[万千]?赞.*",
            r",?\s*\d+条?评论.*",
            r"\s*·\s*\d+.*",
            # 抖音/短视频平台专属交互按钮文本过滤
            r",?\s*(?:未点赞|已点赞|未收藏|已收藏|未选中|已选中)[，, ]?.*",
            r"^(?:未点赞|已点赞|未收藏|已收藏|未选中|已选中)[，, ]?.*",
            r"^(?:喜欢|评论|收藏|分享)\d+(\.\d+)?[万千]?.*",
            r",?\s*喜欢\d+(\.\d+)?[万千]?.*",
        ]
        for p in noise_sub:
            txt = re.sub(p, "", txt, flags=re.IGNORECASE).strip()

        # 4. 统计指标或热度标签过滤 (如 "7740 万人正在热议"、"赞同1141"、"1.9 万人关注")
        stat_patterns = [
            r".*人(?:正在热议|热议|在看|关注|赞同).*",
            r"^赞同\s*\d+.*",
            r".*次?(?:播放|播放量|获赞|点赞|条评论).*",
        ]
        for sp in stat_patterns:
            if re.search(sp, txt):
                return None

        txt = txt.strip("，,。 ").strip()

        # 真实的内容/文章/视频标题长度通常在 5~60 字之间，且必须含有中文字符
        if len(txt) < 5 or len(txt) > 60:
            return None
        if not re.search(r"[\u4e00-\u9fa5]", txt):
            return None

        return txt

    async def extract_screen_cards(self) -> List[Dict[str, Any]]:
        """抓取当前屏幕黄金视觉中心区域的高质量真实内容卡片（按距离屏幕中心距离排序，包含标题与点击中心坐标）"""
        ok, elements, _ = await self.adb.dump_ui_elements()
        if not ok or not elements:
            return []

        # 自动推算屏幕高度与黄金视觉中心线 (忽略顶部18%标题栏/状态栏和底部15%导航栏)
        screen_h = max((el["bounds"][3] for el in elements if "bounds" in el and len(el["bounds"]) >= 4), default=2340)
        center_y = screen_h / 2.0
        min_y = screen_h * 0.18
        max_y = screen_h * 0.85

        scored_cards: List[Tuple[float, Dict[str, Any]]] = []
        seen = set()

        for el in elements:
            center = el.get("center", [540, 1000])
            cy = center[1]
            if not (min_y <= cy <= max_y):
                continue

            raw_txt = el.get("text", "").strip()
            cleaned = self._clean_topic_title(raw_txt)
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                dist = abs(cy - center_y)
                scored_cards.append((dist, {
                    "title": cleaned,
                    "center": center,
                    "bounds": el.get("bounds", []),
                }))

        # 按距离屏幕纵向中心由近及远排序，排在第 1 位的必定是屏幕最正中、最抓眼的焦点大图/文章
        scored_cards.sort(key=lambda x: x[0])
        return [c[1] for c in scored_cards[:10]]

    async def extract_screen_topics(self) -> List[str]:
        """向后兼容：抓取当前屏幕黄金视觉中心区域的高质量真实内容标题列表"""
        cards = await self.extract_screen_cards()
        return [c["title"] for c in cards]

    @staticmethod
    def _is_safe_custom_url(url: str) -> bool:
        """严格校验自定义 LLM URL（通过解析 Host 与 IP，全量防范十进制/八进制/IPv6 等各进制 SSRF 绕过）"""
        if not url or not isinstance(url, str):
            return False
        clean = url.strip()
        try:
            parsed = urllib.parse.urlparse(clean)
            if parsed.scheme.lower() not in ("http", "https"):
                return False

            hostname = (parsed.hostname or "").lower().strip()
            if not hostname:
                return False

            # 1. 拦截常见回环域名、云厂商元数据域名与内网本地后缀
            blocked_domains = {
                "localhost", "0.0.0.0", "metadata.google", "metadata.tencent",
                "metadata.aws", "169.254.169.254", "instance-data"
            }
            if hostname in blocked_domains or hostname.endswith(".internal") or hostname.endswith(".local"):
                logger.warning("自定义 LLM URL 命中受限域名黑名单: %s", url)
                return False

            # 2. 尝试转为 IP 地址判定（底层自动处理点分十进制、十进制纯整数、八进制/十六进制与 IPv6）
            ip = None
            try:
                if hostname.isdigit():
                    ip = ipaddress.ip_address(int(hostname))
                elif hostname.startswith("0x"):
                    ip = ipaddress.ip_address(int(hostname, 16))
                else:
                    try:
                        ip = ipaddress.ip_address(hostname)
                    except ValueError:
                        # 兼容处理点分八进制/点分十六进制（如 0177.0.0.1）
                        if "." in hostname and all(part.isalnum() for part in hostname.split(".")):
                            ip = ipaddress.ip_address(socket.inet_aton(hostname))
            except Exception:
                pass

            if ip is not None:
                # 严格拦截私有网段 (10/192.168/172.16-31)、回环 (127.0.0.1)、链路本地 (169.254) 与未指定/保留 IP
                if (
                    ip.is_private
                    or ip.is_loopback
                    or ip.is_link_local
                    or ip.is_reserved
                    or ip.is_unspecified
                    or ip.is_multicast
                ):
                    logger.warning("自定义 LLM URL 命中私网/保留/回环 IP 拦截: %s (解析为 %s)", url, ip)
                    return False
            else:
                # 3. 对域名执行实际 DNS 解析，防范 DNS Rebinding 将公网域名动态指向私网或回环地址
                try:
                    addr_info = socket.getaddrinfo(hostname, None)
                    for item in addr_info:
                        resolved_ip_str = item[4][0]
                        res_ip = ipaddress.ip_address(resolved_ip_str)
                        if (
                            res_ip.is_private
                            or res_ip.is_loopback
                            or res_ip.is_link_local
                            or res_ip.is_reserved
                            or res_ip.is_unspecified
                            or res_ip.is_multicast
                        ):
                            logger.warning("自定义 LLM 域名 DNS 解析为私网/回环地址，安全拦截: %s -> %s", url, res_ip)
                            return False
                except Exception as dns_err:
                    logger.warning("自定义 LLM URL DNS 解析失败拦截: %s (%s)", url, dns_err)
                    return False

            return True
        except Exception as e:
            logger.warning("自定义 LLM URL 安全解析异常拦截: %s (%s)", url, e)
            return False

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
        llm_caller: Optional[Callable[[str], Any]] = None,
    ) -> str:
        """生成贴合人设、自然灵动的摸鱼分享吐槽（优先通过 LLM 动态生成，绝不使用机械报告腔）"""
        topics_ctx = f"（屏幕上同时看到的其他内容：{', '.join(related_topics)}）" if related_topics else ""
        prompt = (
            f"你是小蓝，一个真实、温和随性、爱玩单机游戏的年轻女生。你刚刚在手机【{display_name}】刷到了一个很显眼的帖子/视频：\n"
            f"标题是：《{best_title}》{topics_ctx}\n"
            "现在你截了一张图发给老大（你的好友/主人）。请用非常自然通顺的一句话（15~35个字），像年轻女生日常在微信打字聊天一样随口跟他说一句，把这张图分享给他。\n"
            "要求：\n"
            "1. 必须是一句完整的聊天交流话语，说清楚这张图有什么看点或好笑的（绝对不能只输出两三个字或只蹦一个名词短语！要有交流感）。\n"
            "2. 极其自然随性，就像你刚刚刷到了随手扔给他看一样。\n"
            "3. 严禁出现'报告老大'、'摸鱼巡航'、'热门内容'、'抓到'、'为您汇报'等任何机械、客服、机器人报告腔词汇！\n"
            "4. 直接输出你要打出的那一句话，不要包含引号、前后缀解释。"
        )

        # 1. 优先通过传入的宿主 LLM 生成
        if llm_caller:
            try:
                res = await llm_caller(prompt)
                if res and isinstance(res, str) and res.strip():
                    cleaned = res.strip().strip('"\'''“”')
                    # 至少8个字且成句，防止大模型抽风只输出两三个字的名词短语
                    if len(cleaned) >= 8:
                        return cleaned
            except Exception as e:
                logger.debug("通过上下文 LLM 生成摸鱼吐槽异常: %s", e)

        # 2. 若用户在配置中提供了安全合规的公网 LLM 端点与 Key，通过外部大模型动态生成
        if custom_llm_url and custom_llm_key and self._is_safe_custom_url(custom_llm_url):
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
            class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    logger.warning("自定义 LLM 请求被重定向到 %s，安全策略拒绝跟随", newurl)
                    return None

            try:
                data_bytes = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(custom_llm_url, data=data_bytes, headers=headers)
                loop = asyncio.get_running_loop()
                def _call():
                    opener = urllib.request.build_opener(_NoRedirectHandler)
                    with opener.open(req, timeout=4.0) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                        return data["choices"][0]["message"]["content"].strip()
                comment = await loop.run_in_executor(None, _call)
                if comment:
                    return comment.strip('"\'''“”')
            except Exception as e:
                logger.debug("自定义模型生成摸鱼吐槽失败，降级回退拟真词库: %s", e)

        # 3. 内置丰富多样的拟真女生口吻模板库（彻底剔除任何“报告老大/摸鱼巡航”等机械词汇）
        natural_templates = [
            f"刚才在【{display_name}】刷到这个，感觉挺有意思的，截屏给你瞅瞅~",
            f"在【{display_name}】看到这个【{best_title}】，笑死我了，顺手截了一张",
            f"刷【{display_name}】刷到个好玩的：‘{best_title}’，发你看看",
            f"看我刚刚刷到了啥：‘{best_title}’，截图给你瞅瞅~",
            f"刚才逛【{display_name}】看到这个，觉得有点意思，顺手截了个图给你",
        ]
        return random.choice(natural_templates)

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
        llm_caller: Optional[Callable[[str], Any]] = None,
        enable_deep_read: bool = True,
    ) -> Dict[str, Any]:
        """
        执行一次拟人化自主摸鱼会话：
        1. 唤醒并启动指定 App
        2. 周期性真人滑动、模拟阅读停顿
        3. 嗅探有趣内容（支持点击进入详情页深度阅读）
        4. 触发分享回调并返回列表
        """
        if self.is_slacking:
            return {"success": False, "message": "麦麦当前正在摸鱼中，请稍后再试"}

        self.is_slacking = True
        session_id = int(time.time())
        discovered_contents: List[str] = []
        shared_snapshots: List[str] = []

        try:
            # 1. 确保屏幕亮起并彻底解散锁屏到前台
            await self.adb.press_key("224")  # KEYCODE_WAKEUP 唤醒屏幕
            await self.adb.run_shell("wm dismiss-keyguard")
            await self.adb.swipe(540, 1800, 540, 400, 200)  # 稳妥上滑穿透锁屏
            await asyncio.sleep(0.6)

            # 2. 启动目标 App
            app_info = SLACK_APPS.get(app_name.lower())
            target_pkg = app_info["pkg"] if app_info else app_name
            display_name = app_info["name"] if app_info else app_name

            logger.info("麦麦开始摸鱼啦，正在启动: %s", display_name)
            await self.adb.open_app(target_pkg)
            # 等待应用冷启动并自动跳过开屏广告与登录/隐私拦截弹窗
            await asyncio.sleep(1.5)
            await self.dismiss_splash_ad_and_login_popups()
            await asyncio.sleep(1.0)

            # 3. 循环摸鱼浏览
            start_time = time.time()
            swipe_count = 0
            has_shared_snapshot = False
            deep_read_done = False
            is_douyin = app_name.lower() in ("抖音", "douyin", "aweme") or target_pkg == "com.ss.android.ugc.aweme"

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

                # 提取当前屏幕卡片与内容
                cards = await self.extract_screen_cards()
                # 若发现屏幕上未能提取到有效内容卡片，可能中途被登录弹窗或广告打断，自愈清理一次弹窗
                if not cards and swipe_count <= 2:
                    if await self.dismiss_splash_ad_and_login_popups():
                        cards = await self.extract_screen_cards()
                topics = [c["title"] for c in cards]
                if topics:
                    discovered_contents.extend(topics)

                # 深度详情浏览逻辑：
                # 对于非全屏切视频的图文/视频应用（B站/知乎/小红书），滑动 2 次后若遇到心动卡片且本轮尚未深入点击过，点击卡片进入详情页！
                if enable_deep_read and not deep_read_done and swipe_count >= 2 and cards and not is_douyin:
                    target_card = cards[0]
                    card_title = target_card["title"]
                    cx, cy = target_card.get("center", [540, 1000])

                    logger.info("【深度浏览】小蓝被《%s》吸引，点击卡片 (%d, %d) 进入详情页...", card_title, cx, cy)
                    await self.adb.tap(cx, cy)
                    deep_read_done = True

                    # 等待详情页渲染展开
                    await asyncio.sleep(2.0)

                    # 模拟在详情页停顿观看正文/视频 (3.5 ~ 6 秒)
                    read_sec = random.uniform(3.5, 6.0)
                    await asyncio.sleep(read_sec)

                    # 优先在详情页截图分享（此时画面是完整详情大图/正文，比信息流小图更具现场感）
                    if not has_shared_snapshot and share_callback:
                        shot_path = os.path.join(self.runtime_dir, f"slack_find_{session_id}_{swipe_count}_detail.jpg")
                        ok, res = await self.adb.capture_screenshot(shot_path, quality=75)
                        if ok:
                            has_shared_snapshot = True
                            shared_snapshots.append(shot_path)
                            msg = await self.generate_lively_comment(
                                display_name,
                                card_title,
                                topics[1:4],
                                custom_llm_url=custom_llm_url,
                                custom_llm_key=custom_llm_key,
                                custom_llm_model=custom_llm_model,
                                llm_caller=llm_caller,
                            )
                            try:
                                await share_callback(shot_path, msg)
                            except Exception as e:
                                logger.warning("摸鱼详情分享回调执行失败: %s", e)

                    # 模拟在详情页小幅微滑看评论或长文
                    await asyncio.sleep(1.0)
                    await self.adb.swipe(540, 1500, 540, 1000, 300)
                    await asyncio.sleep(1.5)

                    # 看完轻按返回键回到推荐列表
                    logger.info("【深度浏览】看完详情，按返回键退回列表流")
                    await self.adb.press_key("back")
                    await asyncio.sleep(1.2)

                    # 安全看门狗检查：若一次返回未退出，再补一次返回
                    cur_st = await self.adb.get_status()
                    if cur_st.get("foreground_package") != target_pkg:
                        await self.adb.open_app(target_pkg)
                        await asyncio.sleep(1.5)

                # 普通流内分享兜底（如抖音或未触发详情页点击）
                elif not has_shared_snapshot and swipe_count >= 2 and topics and share_callback:
                    # 抓取一张截图
                    shot_path = os.path.join(self.runtime_dir, f"slack_find_{session_id}_{swipe_count}.jpg")
                    ok, res = await self.adb.capture_screenshot(shot_path, quality=75)
                    if ok:
                        has_shared_snapshot = True
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
                            llm_caller=llm_caller,
                        )
                        try:
                            await share_callback(shot_path, msg)
                        except Exception as e:
                            logger.warning("摸鱼分享回调执行失败: %s", e)

            # 去重整理摸鱼成果
            unique_topics = list(dict.fromkeys(discovered_contents))[:4]
            if unique_topics:
                summary_msg = f"刚才在【{display_name}】逛了一会儿，看了看《{unique_topics[0]}》这些热门动态~"
            else:
                summary_msg = f"刚才去【{display_name}】溜达了一圈，刷了刷动态，没看到特别有意思的~"

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

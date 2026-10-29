"""phone_controller 插件主入口

麦麦安卓手机控制核心组件库：
1. 核心设备状态与无线连接 (phone_status, phone_connect, phone_pair)
2. 视觉感知与 UI 分析 (phone_screenshot, phone_dump)
3. 基础交互动作 (phone_tap_text, phone_tap, phone_swipe, phone_text, phone_key, phone_open_app, phone_macro)
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import random
import time
from typing import Any, Dict, List, Optional, Tuple

from maibot_sdk import MaiBotPlugin, Tool
from maibot_sdk.types import ToolParameterInfo, ToolParamType

from .adb_engine import AdbEngine
from .config import PhoneControllerConfig
from .slacker import SlackerEngine

logger = logging.getLogger("plugin.phone_controller")


class PhoneControllerPlugin(MaiBotPlugin):
    """手机管家核心插件实现类"""

    config_model = PhoneControllerConfig

    def __init__(self):
        super().__init__()
        self.adb: Optional[AdbEngine] = None
        self.slacker: Optional[SlackerEngine] = None
        self._auto_slack_task: Optional[asyncio.Task] = None
        self._last_owner_stream_id: str = ""

    async def on_load(self) -> None:
        """插件加载初始化"""
        cfg: PhoneControllerConfig = self.config
        logger.info("正在加载手机管家插件: v%s", cfg.plugin.version)

        # 初始化 ADB 控制引擎与自主摸鱼引擎
        self.adb = AdbEngine(
            adb_path=cfg.device.adb_path,
            device_serial=cfg.device.device_serial,
        )
        self.slacker = SlackerEngine(self.adb, runtime_dir=self._get_runtime_dir())

        # 若配置了默认无线连接 IP 和端口，尝试自动静默连接
        if cfg.device.default_host and not cfg.device.device_serial:
            logger.info("尝试自动连接受控手机: %s:%s", cfg.device.default_host, cfg.device.default_port)
            asyncio.create_task(self.adb.connect(cfg.device.default_host, cfg.device.default_port))

        # 启动闲时自动摸鱼巡航调度器 (若开启)
        self._start_auto_slacker()

        logger.info("手机管家插件加载完成")

    async def on_unload(self) -> None:
        """插件卸载清理"""
        self._stop_auto_slacker()
        logger.info("手机管家插件已卸载")

    async def on_config_update(self, scope: str, config_data: dict, version: str) -> None:
        """热更新配置"""
        if scope == "self":
            cfg: PhoneControllerConfig = self.config
            if self.adb:
                self.adb.adb_path = cfg.device.adb_path
                self.adb.set_device(cfg.device.device_serial)
            if self.slacker:
                self.slacker.runtime_dir = self._get_runtime_dir()
            # 重启摸鱼调度器以应用最新作息与间隔配置
            self._start_auto_slacker()
            logger.info("手机管家配置热更新成功 (v%s)", version)

    # -------------------------------------------------------------------------
    # 闲时自动摸鱼巡航调度器 (数字生命模式)
    # -------------------------------------------------------------------------

    def _start_auto_slacker(self) -> None:
        """启动或重载自动摸鱼调度任务"""
        self._stop_auto_slacker()
        try:
            cfg: PhoneControllerConfig = self.config
            if cfg.slack_off.enabled and cfg.slack_off.auto_slacking:
                logger.info("【数字生命】已激活闲时自主摸鱼巡航服务，作息窗口: %s", cfg.slack_off.active_time_range)
                self._auto_slack_task = asyncio.create_task(self._auto_slacking_loop())
        except Exception as e:
            logger.warning("启动自动摸鱼调度器异常: %s", e)

    def _stop_auto_slacker(self) -> None:
        """停止自动摸鱼调度任务"""
        if self._auto_slack_task and not self._auto_slack_task.done():
            self._auto_slack_task.cancel()
            self._auto_slack_task = None

    def _is_in_active_hours(self, range_str: str) -> bool:
        """根据北京时间 (UTC+8) 判断当前是否在设定的玩手机时间段内"""
        try:
            # 严格基于北京时间 (UTC+8) 计算
            beijing_now = datetime.now(timezone(timedelta(hours=8)))
            now_min = beijing_now.hour * 60 + beijing_now.minute

            parts = range_str.strip().split("-")
            if len(parts) != 2:
                return True

            s_h, s_m = map(int, parts[0].strip().split(":"))
            e_h, e_m = map(int, parts[1].strip().split(":"))
            start_min = s_h * 60 + s_m
            end_min = e_h * 60 + e_m

            if start_min <= end_min:
                return start_min <= now_min <= end_min
            else:
                # 跨夜时段
                return now_min >= start_min or now_min <= end_min
        except Exception as e:
            logger.warning("解析活跃时间范围异常: %s", e)
            return True

    async def _auto_slacking_loop(self) -> None:
        """闲时自主摸鱼巡航主循环"""
        logger.info("闲时自主摸鱼巡航协程已启动")

        while True:
            try:
                cfg: PhoneControllerConfig = self.config
                if not cfg.slack_off.enabled or not cfg.slack_off.auto_slacking:
                    break

                # 安全门禁：未配置主人账号时保持休眠，绝不对公网或未知群推送
                if not cfg.device.owner_qq.strip():
                    logger.debug("未配置主人账号，自动摸鱼巡航保持休眠")
                    await asyncio.sleep(1800)
                    continue

                # 1. 计算配置要求的随机摸鱼间隔 (秒)
                min_sec = max(1800, int(cfg.slack_off.interval_hours_min * 3600))
                max_sec = max(min_sec, int(cfg.slack_off.interval_hours_max * 3600))
                target_interval = random.randint(min_sec, max_sec)

                # 2. 检查距离上一次摸鱼过去了多久 (持久化校准，彻底防止重启与配置重载后频繁摸鱼抢跑)
                last_slack_ts = self._load_last_slack_time()
                now = time.time()
                if last_slack_ts > 0:
                    elapsed = now - last_slack_ts
                    if elapsed < target_interval:
                        remaining_sleep = target_interval - elapsed
                        logger.info(
                            "【数字生命】距离上次摸鱼仅过去 %.1f 分钟，距下一次摸鱼仍需休眠 %.1f 小时，保持静默休眠...",
                            elapsed / 60.0,
                            remaining_sleep / 3600.0,
                        )
                        await asyncio.sleep(remaining_sleep)
                        continue
                else:
                    # 全新初次启动且无历史记录：先进行 600~1200 秒的开机静默缓冲
                    logger.info("【数字生命】检测到无历史摸鱼记录，执行初次启动静默缓冲...")
                    await asyncio.sleep(random.randint(600, 1200))

                # 3. 检查作息时间与手机状态
                if self._is_in_active_hours(cfg.slack_off.active_time_range):
                    status = await self.adb.get_status()
                    if status.get("connected"):
                        apps = [x.strip() for x in cfg.slack_off.preferred_apps.split(",") if x.strip()]
                        target_app = random.choice(apps) if apps else "b站"
                        logger.info("【数字生命】麦麦闲来无事，自主拿起手机去刷【%s】啦！", target_app)

                        # 解析主要通知目标与备用通知目标 (支持 QQ 号、机器人 QQ 号、Discord ID)
                        owner_accounts = [
                            p.strip()
                            for p in cfg.device.owner_qq.replace("，", ",").split(",")
                            if p.strip()
                        ]
                        primary_target = cfg.slack_off.notify_stream_id.strip()
                        if not primary_target and owner_accounts:
                            primary_target = owner_accounts[0]

                        primary_streams = await self._resolve_streams_for_target(primary_target, owner_accounts) if primary_target else []
                        if not primary_streams and self._last_owner_stream_id:
                            primary_streams = [self._last_owner_stream_id]

                        fallback_target = getattr(cfg.slack_off, "fallback_stream_id", "").strip()
                        fallback_streams = await self._resolve_streams_for_target(fallback_target, owner_accounts) if fallback_target else []

                        async def _send_with_fallback(text: Optional[str] = None, img_b64: Optional[str] = None) -> bool:
                            if not primary_streams and not fallback_streams:
                                logger.debug("未配置摸鱼通知账号且无活跃私聊记录，静默跳过分享")
                                return False

                            # 1. 优先使用主要通道发送
                            if primary_streams:
                                for s in primary_streams:
                                    try:
                                        success = True
                                        if text:
                                            res = await self.ctx.send.text(text, s)
                                            if isinstance(res, bool) and not res:
                                                success = False
                                        if success and img_b64:
                                            res = await self.ctx.send.image(img_b64, s)
                                            if isinstance(res, bool) and not res:
                                                success = False
                                        if success:
                                            logger.info("摸鱼成果已通过主通道成功发送到会话: %s", s)
                                            return True
                                        logger.warning("主通道会话 %s 发送未成功，尝试主通道下一可用链路...", s)
                                    except Exception as err:
                                        logger.warning("主通道会话 %s 抛出异常: %s", s, err)
                            else:
                                logger.warning("主要通知目标 [%s] 未能解析到有效私聊会话流，请确认账号是否正确或已开启私聊", primary_target)

                            # 2. 只有当主会话通道所有链路均不通时，才采用备用通道！
                            if fallback_streams:
                                logger.warning("⚠️ 主会话通道不通或发送失败，采用备用通道容灾发送...")
                                for s in fallback_streams:
                                    try:
                                        success = True
                                        if text:
                                            res = await self.ctx.send.text(text, s)
                                            if isinstance(res, bool) and not res:
                                                success = False
                                        if success and img_b64:
                                            res = await self.ctx.send.image(img_b64, s)
                                            if isinstance(res, bool) and not res:
                                                success = False
                                        if success:
                                            logger.info("摸鱼成果已通过备用通道成功发送到会话: %s", s)
                                            return True
                                        logger.warning("备用通道会话 %s 发送未成功...", s)
                                    except Exception as err:
                                        logger.warning("备用通道会话 %s 抛出异常: %s", s, err)
                            else:
                                logger.warning("主会话通道发送失败，且未配置有效备用通道")

                            return False

                        async def _auto_share(img_path: str, caption: str):
                            if cfg.slack_off.share_interesting_finds:
                                try:
                                    with open(img_path, "rb") as f:
                                        img_b64 = base64.b64encode(f.read()).decode("utf-8")
                                    await _send_with_fallback(text=caption, img_b64=img_b64)
                                except Exception as err:
                                    logger.warning("摸鱼主动出站消息发送失败: %s", err)

                        async def _llm_comment(prompt: str) -> str:
                            try:
                                res = await self.ctx.llm.generate(
                                    prompt=prompt,
                                    task_name="replyer",
                                    temperature=0.85,
                                    max_tokens=800,
                                )
                                if isinstance(res, dict) and res.get("response"):
                                    return str(res["response"]).strip()
                            except Exception as e:
                                logger.debug("调用宿主 LLM 生成摸鱼配文失败: %s", e)
                            return ""

                        # 执行自主摸鱼
                        res = await self.slacker.run_slacking_session(
                            app_name=target_app,
                            duration_seconds=cfg.slack_off.session_duration_seconds,
                            interval_min=cfg.slack_off.swipe_interval_min,
                            interval_max=cfg.slack_off.swipe_interval_max,
                            share_callback=_auto_share,
                            custom_llm_url=cfg.slack_off.custom_llm_url,
                            custom_llm_key=cfg.slack_off.custom_llm_key,
                            custom_llm_model=cfg.slack_off.custom_llm_model,
                            llm_caller=_llm_comment,
                        )

                        # 若开启了结算播报，且本轮未发送过截图分享，会话结束时向主人发送一条简短打卡总结
                        notify_summary_enabled = getattr(cfg.slack_off, "notify_summary", True)
                        if res and res.get("success") and not res.get("snapshots") and notify_summary_enabled:
                            summary_text = res.get("message")
                            if summary_text:
                                await _send_with_fallback(text=summary_text)

                        # 摸鱼完毕自动灭屏锁屏
                        if cfg.slack_off.lock_screen_after_slack:
                            await asyncio.sleep(1.0)
                            await self.adb.press_key("power")

                        # 记录并持久化本次摸鱼完成时间戳 (防服务重启后过早再次摸鱼)
                        self._save_last_slack_time(time.time())
                    else:
                        logger.debug("受控手机未连接，跳过本次自动摸鱼")
                else:
                    logger.debug("当前处于免打扰时段，麦麦正在安睡，不去玩手机")

                # 本轮周期结束，计算并休眠下一个完整随机周期
                next_sleep = random.randint(min_sec, max_sec)
                logger.info("本轮摸鱼巡航结束，进入深度休眠，下次巡航约在 %.1f 小时后", next_sleep / 3600.0)
                await asyncio.sleep(next_sleep)

            except asyncio.CancelledError:
                logger.info("自动摸鱼调度任务已正常停止")
                break
            except Exception as e:
                logger.error("自动摸鱼循环异常: %s", e)
                await asyncio.sleep(600)

    async def _resolve_streams_for_target(self, target_id: str, owner_accounts: Optional[List[str]] = None) -> List[str]:
        """根据配置的 ID 解析该目标对应的私聊会话流列表。

        目标 ID 可以是：
        1. 用户的 QQ 号（主人的 QQ）
        2. 机器人的专属 QQ 号（例如官方机器人号或小号机器人号）
        3. 用户的 Discord ID
        （兼容底层 32 位十六进制会话 ID）
        """
        tid = str(target_id or "").strip()
        if not tid:
            return []

        # 兼容性防御：如果极端情况下直接填写了 32 位十六进制会话 ID
        if len(tid) == 32 and not tid.isdigit():
            try:
                int(tid, 16)
                return [tid]
            except ValueError:
                pass

        owners = owner_accounts or []

        matched_streams: List[str] = []
        for plat in ("qq", "discord"):
            try:
                res = await self.ctx.chat.get_private_streams(platform=plat)
                raw_streams = []
                if isinstance(res, list):
                    raw_streams = res
                elif isinstance(res, dict) and "streams" in res:
                    raw_streams = res.get("streams") or []

                # 后建立的活跃会话排在前面优先尝试
                for s in reversed(raw_streams):
                    if not isinstance(s, dict):
                        continue
                    u_id = str(s.get("user_id") or "").strip()
                    bot_acc = str(s.get("account_id") or "").strip()
                    sid = str(s.get("session_id") or s.get("stream_id") or "").strip()

                    if not sid or sid in matched_streams:
                        continue

                    # 格式 1 & 3：target_id 是用户自身账号 (如 QQ 号或 Discord 用户 ID)
                    if u_id == tid:
                        matched_streams.append(sid)
                    # 格式 2：target_id 是机器人账号 (如机器人的专属 QQ 号)，且私聊对象为主人
                    elif bot_acc == tid and (not owners or u_id in owners):
                        matched_streams.append(sid)
            except Exception as e:
                logger.debug("获取平台 %s 私聊流异常: %s", plat, e)

        # 兼容性增强：若用户填入的是 QQ 开放平台分配的官方机器人展示号 (通常为 400/401 开头，如 4010000000)，
        # 腾讯底层网关会将 Bot 转换为内部长整数 UID，此时寻找与主人绑定的官方机器人私聊
        if not matched_streams and (tid.startswith("40") or tid.startswith("401")):
            try:
                res = await self.ctx.chat.get_private_streams(platform="qq")
                raw_streams = res if isinstance(res, list) else (res.get("streams") if isinstance(res, dict) else [])
                for s in (raw_streams or []):
                    if not isinstance(s, dict):
                        continue
                    u_id = str(s.get("user_id") or "").strip()
                    bot_acc = str(s.get("account_id") or "").strip()
                    sid = str(s.get("session_id") or s.get("stream_id") or "").strip()
                    # 匹配主人且 Bot 账号为官方长 UID (>10位)
                    if sid and (not owners or u_id in owners) and len(bot_acc) > 10:
                        if sid not in matched_streams:
                            matched_streams.append(sid)
            except Exception as e:
                logger.debug("尝试对齐 QQ 官方机器人长 UID 会话异常: %s", e)

        # 兜底查找
        if not matched_streams:
            for plat in ("qq", "discord"):
                try:
                    res = await self.ctx.chat.get_stream_by_user_id(user_id=tid, platform=plat)
                    s_id = None
                    if isinstance(res, dict):
                        s_id = res.get("stream_id") or res.get("session_id")
                    elif res is not None:
                        s_id = getattr(res, "stream_id", None) or getattr(res, "session_id", None)
                    if s_id and str(s_id) not in matched_streams:
                        matched_streams.append(str(s_id))
                except Exception as e:
                    logger.debug("通过 get_stream_by_user_id 查询 %s 异常: %s", tid, e)

        return matched_streams

    # -------------------------------------------------------------------------
    # 安全防御辅助
    # -------------------------------------------------------------------------

    def _extract_user_id(self, kwargs: Dict[str, Any]) -> str:
        """多级健壮提取调用者用户 ID (优先宿主不可伪造的 message 结构体，安全防御)"""
        # 1. 【安全第一】优先从宿主保证注入的底层 message 消息体解析（不可被大模型入参伪造）
        msg = kwargs.get("message")
        if isinstance(msg, dict):
            # 常见嵌套容器与 candidate keys (兼容 QQ官方Bot, OneBot, NapCat, Discord, Telegram 等)
            candidate_containers = [
                msg.get("user_info"),
                msg.get("sender"),
                msg.get("author"),
                msg.get("from_user"),
                msg.get("data"),
                msg,
            ]
            candidate_keys = ["user_id", "id", "sender_id", "author_id", "userId", "open_id"]
            for container in candidate_containers:
                if isinstance(container, dict):
                    for k in candidate_keys:
                        val = str(container.get(k) or "").strip()
                        if val and val != "None":
                            return val

        elif msg is not None:
            # 对象形式属性多级探测
            for attr in ("user_info", "sender", "author", "from_user", "data"):
                sub = getattr(msg, attr, None)
                if sub is not None:
                    for k in ("user_id", "id", "sender_id", "author_id", "userId", "open_id"):
                        val = str(getattr(sub, k, "") or "").strip()
                        if val and val != "None":
                            return val
            for k in ("user_id", "id", "sender_id", "author_id", "userId"):
                val = str(getattr(msg, k, "") or "").strip()
                if val and val != "None":
                    return val

        # 2. 仅在无 message 消息体时（例如单元测试或非消息驱动直接调用），回退到顶层注入字段
        for top_key in ("user_id", "sender_id", "author_id", "from_user_id"):
            val = str(kwargs.get(top_key) or "").strip()
            if val and val != "None":
                return val

        logger.warning(
            "【手机管家鉴权】未能从工具上下文中解析出调用者 ID，请求将被安全拦截。kwargs keys: %s, message keys: %s",
            list(kwargs.keys()),
            list(msg.keys()) if isinstance(msg, dict) else (dir(msg) if msg else "无"),
        )
        return ""

    def _check_owner_auth(self, *args, **kwargs) -> Tuple[bool, str]:
        """检查调用者是否为主人，防止他人误触或滥用"""
        passed_uid = ""
        stream_id = ""
        merged_kwargs = dict(kwargs)
        if len(args) >= 1:
            if isinstance(args[0], dict):
                merged_kwargs.update(args[0])
            else:
                passed_uid = str(args[0] or "").strip()
        if len(args) >= 2:
            stream_id = str(args[1] or "").strip()

        if not stream_id:
            stream_id = str(merged_kwargs.get("stream_id") or "").strip()

        # 健壮提取调用者 ID：优先显式参数，兜底多级消息体结构提取
        caller_user_id = passed_uid or self._extract_user_id(merged_kwargs)

        try:
            cfg: PhoneControllerConfig = self.config
            raw_owner = str(cfg.device.owner_qq).strip() if cfg else ""
        except Exception:
            raw_owner = ""

        # 【核心安全防线】未配置主人或仅填入分隔符时，默认拒绝一切控制指令，防止在群聊中被任意调用泄露手机隐私
        if not raw_owner:
            return False, (
                "【安全拦截】手机管家插件尚未配置主人账号（device.owner_qq）。"
                "为防止群聊成员恶意操控你的手机或泄露隐私，默认拒绝所有指令。"
                "请管理员先在插件配置中填入主人 QQ 号或 Discord 用户 ID 后再使用。"
            )

        # 支持英文逗号与中文逗号分隔的多主人配置
        owners = [x.strip() for x in raw_owner.replace("，", ",").split(",") if x.strip()]
        if not owners:
            return False, (
                "【安全拦截】手机管家插件尚未配置有效的主人账号（device.owner_qq 为空或仅包含分隔符）。"
                "为防止群聊成员恶意操控你的手机或泄露隐私，默认拒绝所有指令。"
                "请管理员先在插件配置中填入主人 QQ 号或 Discord 用户 ID 后再使用。"
            )

        # 严格白名单匹配：调用者 ID 必须明确在主人列表中，绝不放行空列表或未知用户 (fail-closed)
        if caller_user_id and caller_user_id in owners:
            # 仅在非群聊或明确是主人私聊流时记录为兜底摸鱼通知流，绝不对公聊群推送
            is_group = bool(
                merged_kwargs.get("group_id")
                or "group" in stream_id.lower()
                or "guild" in stream_id.lower()
                or "channel" in stream_id.lower()
            )
            if stream_id and not is_group:
                self._last_owner_stream_id = stream_id
            return True, ""

        return False, f"权限拦截：手机控制功能仅允许主人（ID: {raw_owner}）操作。"

    def _get_runtime_dir(self) -> str:
        """获取安全的运行时临时文件目录"""
        try:
            return self.ctx.paths.runtime_dir
        except Exception:
            p = "/tmp/phone_controller"
            os.makedirs(p, exist_ok=True)
            return p

    @staticmethod
    def _cleanup_old_screenshots(runtime_dir: str, max_files: int = 30, max_age_seconds: int = 86400) -> None:
        """清理过期的临时截图文件，防止长期自动摸鱼堆积磁盘空间"""
        try:
            if not os.path.exists(runtime_dir):
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

            # 若保留文件数仍超过上限，删除最旧的文件
            if len(img_files) > max_files:
                img_files.sort(key=lambda x: x[0])
                for _, old_path in img_files[:len(img_files) - max_files]:
                    try:
                        os.remove(old_path)
                    except OSError:
                        pass
        except Exception as e:
            logger.debug("清理临时截图文件忽略异常: %s", e)

    def _get_state_file_path(self) -> Path:
        """获取插件持久化运行时状态文件路径 (健壮支持绝对路径)"""
        candidates = []
        try:
            d = Path(self.ctx.paths.data_dir)
            candidates.append(Path("/opt/maibot/instance") / d)
            candidates.append(d if d.is_absolute() else Path.cwd() / d)
        except Exception:
            pass

        candidates.extend([
            Path("/opt/maibot/instance/data/plugins/WiseXin.phone-controller"),
            Path.cwd() / "data" / "plugins" / "WiseXin.phone-controller",
        ])

        # 优先寻找已经存在真实状态文件的路径
        for c in candidates:
            p = c / "runtime_state.json"
            if p.exists():
                return p

        # 若均不存在，在首个可写候选目录下创建并返回
        for c in candidates:
            try:
                c.mkdir(parents=True, exist_ok=True)
                return c / "runtime_state.json"
            except Exception:
                continue

        fallback = Path.cwd() / "runtime_state.json"
        return fallback

    def _load_last_slack_time(self) -> float:
        """读取上一次摸鱼完成的时间戳 (防重启后过早摸鱼)"""
        try:
            p = self._get_state_file_path()
            logger.info("【状态加载】检查摸鱼历史记录文件: %s (存在=%s)", p, p.exists())
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    val = float(data.get("last_slack_timestamp", 0.0))
                    logger.info("【状态加载】成功读取上次摸鱼时间: %s (ts=%.1f)", data.get("last_slack_datetime"), val)
                    return val
        except Exception as e:
            logger.warning("读取上次摸鱼时间戳异常: %s", e)
        return 0.0

    def _save_last_slack_time(self, ts: float) -> None:
        """持久化保存上一次摸鱼完成的时间戳"""
        try:
            p = self._get_state_file_path()
            with open(p, "w", encoding="utf-8") as f:
                json.dump({
                    "last_slack_timestamp": ts,
                    "last_slack_datetime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.debug("保存上次摸鱼时间戳异常: %s", e)

    def _resolve_target(self, target: str, port: Optional[int] = None) -> Tuple[str, int, str]:
        """解析设备别名（如'小米'、'vivo'）或 IP:端口"""
        target_clean = target.strip().lower()
        
        # 用户配置别名
        merged_aliases: Dict[str, str] = {}
        try:
            cfg: PhoneControllerConfig = self.config
            if cfg and cfg.device.aliases:
                if isinstance(cfg.device.aliases, dict):
                    merged_aliases.update(cfg.device.aliases)
                elif isinstance(cfg.device.aliases, str):
                    for item in cfg.device.aliases.split(","):
                        if "=" in item:
                            k_part, v_part = item.split("=", 1)
                            merged_aliases[k_part.strip()] = v_part.strip()
        except Exception:
            pass

        # 1. 尝试匹配别名 (完全匹配或包含匹配)
        matched_alias = ""
        matched_addr = ""
        for alias_key, addr in merged_aliases.items():
            k = alias_key.lower().strip()
            if target_clean == k or k in target_clean or target_clean in k:
                matched_alias = alias_key
                matched_addr = addr.strip()
                break

        final_addr = matched_addr if matched_addr else target.strip()
        
        # 2. 解析 host 与 port
        if ":" in final_addr:
            h, p_str = final_addr.split(":", 1)
            p = int(p_str) if p_str.isdigit() else (port or 5555)
            return h.strip(), p, matched_alias
        
        return final_addr, port or 5555, matched_alias

    # -------------------------------------------------------------------------
    # 1. 核心设备与连接工具
    # -------------------------------------------------------------------------

    @Tool(
        "phone_status",
        description="查看受控手机的连接状态、电量、亮灭屏状态及当前前台正在运行的应用包名。",
        parameters=[],
    )
    async def handle_phone_status(self, **kwargs) -> Dict[str, Any]:
        auth_ok, msg = self._check_owner_auth(kwargs)
        if not auth_ok:
            return {"success": False, "message": msg}

        status = await self.adb.get_status()
        return {"success": True, "data": status}

    @Tool(
        "phone_devices",
        description="查看当前所有可用的手机设备别名（如'小米'、'vivo'）以及当前已连接的目标设备。",
        parameters=[],
    )
    async def handle_phone_devices(self, **kwargs) -> Dict[str, Any]:
        auth_ok, msg = self._check_owner_auth(kwargs)
        if not auth_ok:
            return {"success": False, "message": msg}

        cfg: PhoneControllerConfig = self.config
        aliases: Dict[str, str] = {}
        if cfg and cfg.device.aliases:
            if isinstance(cfg.device.aliases, dict):
                aliases.update(cfg.device.aliases)
            elif isinstance(cfg.device.aliases, str):
                for item in cfg.device.aliases.split(","):
                    if "=" in item:
                        k_part, v_part = item.split("=", 1)
                        aliases[k_part.strip()] = v_part.strip()

        devs = await self.adb.list_devices()
        return {
            "success": True,
            "current_active_device": self.adb.device_serial or "未指定(自动使用默认)",
            "preset_aliases": aliases,
            "online_adb_devices": devs,
        }

    @Tool(
        "phone_connect",
        description="连接或切换受控手机。支持直接传入设备别名（如'手机A'、'备用机'）或具体 IP/端口（如 192.168.1.100:5555 或 100.x.x.x:5555）。",
        parameters=[
            ToolParameterInfo(
                name="target",
                param_type=ToolParamType.STRING,
                description="设备别名（如'手机A'、'备用机'）或 IP 地址（如 192.168.1.100）或 IP:端口",
                required=True,
            ),
            ToolParameterInfo(
                name="port",
                param_type=ToolParamType.INTEGER,
                description="可选，无线调试端口号（若 target 已含端口或为预设别名，可不填）",
                required=False,
            ),
        ],
    )
    async def handle_phone_connect(self, target: str, port: Optional[int] = None, **kwargs) -> Dict[str, Any]:
        auth_ok, msg = self._check_owner_auth(kwargs)
        if not auth_ok:
            return {"success": False, "message": msg}

        host, final_port, alias_name = self._resolve_target(target, port)
        ok, out = await self.adb.connect(host, final_port)
        
        prefix = f"【{alias_name}】" if alias_name else ""
        if ok:
            return {
                "success": True,
                "message": f"成功连接至{prefix}设备 ({host}:{final_port})",
                "target": f"{host}:{final_port}",
                "alias": alias_name,
            }
        return {
            "success": False,
            "message": f"连接{prefix}设备 ({host}:{final_port}) 失败: {out}",
        }

    @Tool(
        "phone_pair",
        description="配对受控手机无线调试（首次使用或换新手机时）。需传入手机开发者选项中的 IP、配对端口及 6 位配对码。",
        parameters=[
            ToolParameterInfo(name="host", param_type=ToolParamType.STRING, description="配对 IP 地址", required=True),
            ToolParameterInfo(name="port", param_type=ToolParamType.INTEGER, description="配对页面显示的端口号", required=True),
            ToolParameterInfo(name="code", param_type=ToolParamType.STRING, description="6 位配对码", required=True),
        ],
    )
    async def handle_phone_pair(self, host: str, port: int, code: str, **kwargs) -> Dict[str, Any]:
        auth_ok, msg = self._check_owner_auth(kwargs)
        if not auth_ok:
            return {"success": False, "message": msg}

        ok, out = await self.adb.pair(host, port, code)
        return {"success": ok, "message": out}

    # -------------------------------------------------------------------------
    # 2. 视觉看屏与 UI 解析
    # -------------------------------------------------------------------------

    @Tool(
        "phone_screenshot",
        description="截取手机当前画面。截图会自动通过麦麦发到当前会话窗口供你和主人直观查看屏幕内容。",
        parameters=[
            ToolParameterInfo(
                name="send_to_chat",
                param_type=ToolParamType.BOOLEAN,
                description="是否将截图直接发送到当前聊天窗口中，默认 True",
                required=False,
            ),
        ],
    )
    async def handle_phone_screenshot(self, send_to_chat: bool = True, **kwargs) -> Dict[str, Any]:
        auth_ok, msg = self._check_owner_auth(kwargs)
        if not auth_ok:
            return {"success": False, "message": msg}

        filename = f"screenshot_{int(time.time())}.jpg"
        save_path = os.path.join(self._get_runtime_dir(), filename)
        cfg: PhoneControllerConfig = self.config

        ok, res = await self.adb.capture_screenshot(save_path, quality=cfg.device.screenshot_quality)
        if not ok:
            return {"success": False, "message": f"截图失败: {res}"}

        # 自动发送到当前聊天流（转换为合规 Base64 字符串出站）
        stream_id = kwargs.get("stream_id")
        if send_to_chat and stream_id and cfg.device.auto_send_screenshot:
            try:
                with open(save_path, "rb") as f:
                    img_b64 = base64.b64encode(f.read()).decode("utf-8")
                await self.ctx.send.image(img_b64, stream_id)
            except Exception as e:
                logger.warning("截图发送至聊天失败: %s", e)

        # 顺手清理过期截图，避免长期运行占满磁盘
        self._cleanup_old_screenshots(self._get_runtime_dir())

        return {"success": True, "message": "截图成功", "image_path": save_path}

    @Tool(
        "phone_dump",
        description="导出当前屏幕 UI 布局树，获取所有可见文字、按钮及它们的屏幕中心点击坐标 (x, y)。",
        parameters=[],
    )
    async def handle_phone_dump(self, **kwargs) -> Dict[str, Any]:
        auth_ok, msg = self._check_owner_auth(kwargs)
        if not auth_ok:
            return {"success": False, "message": msg}

        ok, elements, err = await self.adb.dump_ui_elements()
        if not ok:
            return {"success": False, "message": err}

        # 只返回前 30 个有效元素避免 token 膨胀
        summary = elements[:30]
        return {
            "success": True,
            "total_elements": len(elements),
            "elements_sample": summary,
        }

    # -------------------------------------------------------------------------
    # 3. 基础交互操作与智能点击
    # -------------------------------------------------------------------------

    @Tool(
        "phone_tap_text",
        description="【最推荐的点击方式】根据界面上显示的文字或按钮描述智能寻找元素并自动点击，比盲猜坐标更精准可靠。",
        parameters=[
            ToolParameterInfo(
                name="text",
                param_type=ToolParamType.STRING,
                description="想要点击的界面文字或按钮标签（如'允许'、'确认'、'签到'、'发送'）",
                required=True,
            ),
        ],
    )
    async def handle_phone_tap_text(self, text: str, **kwargs) -> Dict[str, Any]:
        auth_ok, msg = self._check_owner_auth(kwargs)
        if not auth_ok:
            return {"success": False, "message": msg}

        ok, res = await self.adb.tap_text(text)
        return {"success": ok, "message": res}

    @Tool(
        "phone_tap",
        description="模拟点击屏幕精确像素坐标 (x, y)。",
        parameters=[
            ToolParameterInfo(name="x", param_type=ToolParamType.INTEGER, description="X 轴像素坐标", required=True),
            ToolParameterInfo(name="y", param_type=ToolParamType.INTEGER, description="Y 轴像素坐标", required=True),
        ],
    )
    async def handle_phone_tap(self, x: int, y: int, **kwargs) -> Dict[str, Any]:
        auth_ok, msg = self._check_owner_auth(kwargs)
        if not auth_ok:
            return {"success": False, "message": msg}

        ok, res = await self.adb.tap(x, y)
        return {"success": ok, "message": res}

    @Tool(
        "phone_swipe",
        description="滑动手机屏幕。支持方向枚举（up向上翻页/down向下/left向左/right向右），也支持精确坐标滑动。",
        parameters=[
            ToolParameterInfo(
                name="direction",
                param_type=ToolParamType.STRING,
                description="滑动方向：'up' (向上翻页), 'down' (向下滑), 'left' (向左滑), 'right' (向右滑)",
                required=False,
            ),
            ToolParameterInfo(name="x1", param_type=ToolParamType.INTEGER, description="起点 X 坐标", required=False),
            ToolParameterInfo(name="y1", param_type=ToolParamType.INTEGER, description="起点 Y 坐标", required=False),
            ToolParameterInfo(name="x2", param_type=ToolParamType.INTEGER, description="终点 X 坐标", required=False),
            ToolParameterInfo(name="y2", param_type=ToolParamType.INTEGER, description="终点 Y 坐标", required=False),
        ],
    )
    async def handle_phone_swipe(
        self,
        direction: Optional[str] = "up",
        x1: Optional[int] = None,
        y1: Optional[int] = None,
        x2: Optional[int] = None,
        y2: Optional[int] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        auth_ok, msg = self._check_owner_auth(kwargs)
        if not auth_ok:
            return {"success": False, "message": msg}

        if x1 is not None and y1 is not None and x2 is not None and y2 is not None:
            ok, res = await self.adb.swipe(x1, y1, x2, y2)
        elif direction:
            ok, res = await self.adb.swipe_direction(direction)
        else:
            return {"success": False, "message": "请提供滑动方向或完整的起止坐标"}

        return {"success": ok, "message": res}

    @Tool(
        "phone_text",
        description="向手机当前光标所在的输入框打字。支持中文（通过 ADBKeyboard 输入法无缝输入）。",
        parameters=[
            ToolParameterInfo(name="text", param_type=ToolParamType.STRING, description="需要输入的文本或中文字符串", required=True),
        ],
    )
    async def handle_phone_text(self, text: str, **kwargs) -> Dict[str, Any]:
        auth_ok, msg = self._check_owner_auth(kwargs)
        if not auth_ok:
            return {"success": False, "message": msg}

        ok, res = await self.adb.input_text(text)
        return {"success": ok, "message": res}

    @Tool(
        "phone_key",
        description="按下系统物理或虚拟按键：'back'(返回), 'home'(主屏幕), 'enter'(回车), 'power'(电源键), 'recent'(多任务)。",
        parameters=[
            ToolParameterInfo(
                name="key",
                param_type=ToolParamType.STRING,
                description="按键名称：back, home, enter, power, recent, volume_up, volume_down",
                required=True,
            ),
        ],
    )
    async def handle_phone_key(self, key: str, **kwargs) -> Dict[str, Any]:
        auth_ok, msg = self._check_owner_auth(kwargs)
        if not auth_ok:
            return {"success": False, "message": msg}

        ok, res = await self.adb.press_key(key)
        return {"success": ok, "message": res}

    @Tool(
        "phone_open_app",
        description="启动手机上的应用程序。支持中文名（'网易云'、'微信'、'B站'、'知乎'、'微博'、'抖音'、'设置'）或安卓包名。",
        parameters=[
            ToolParameterInfo(name="app", param_type=ToolParamType.STRING, description="应用名称或包名", required=True),
        ],
    )
    async def handle_phone_open_app(self, app: str, **kwargs) -> Dict[str, Any]:
        auth_ok, msg = self._check_owner_auth(kwargs)
        if not auth_ok:
            return {"success": False, "message": msg}

        ok, res = await self.adb.open_app(app)
        return {"success": ok, "message": res}

    @Tool(
        "phone_macro",
        description="连招宏执行器：按顺序一次性执行一整套动作（点击、滑动、输入文字、按键、延时），减少轮次开销。",
        parameters=[
            ToolParameterInfo(
                name="actions_json",
                param_type=ToolParamType.STRING,
                description=(
                    "动作列表 JSON 字符串，例如：\n"
                    '[{"type":"tap_text","text":"签到"},{"type":"sleep","ms":1000},{"type":"key","key":"back"}]'
                ),
                required=True,
            ),
            ToolParameterInfo(
                name="repeat",
                param_type=ToolParamType.INTEGER,
                description="整套动作重复执行次数 (默认 1 次)",
                required=False,
            ),
        ],
    )
    async def handle_phone_macro(self, actions_json: str, repeat: int = 1, **kwargs) -> Dict[str, Any]:
        auth_ok, msg = self._check_owner_auth(kwargs)
        if not auth_ok:
            return {"success": False, "message": msg}

        try:
            actions = json.loads(actions_json)
            if not isinstance(actions, list):
                return {"success": False, "message": "actions_json 必须是动作对象列表"}
        except Exception as e:
            return {"success": False, "message": f"JSON 解析失败: {e}"}

        try:
            ok, logs = await self.adb.execute_macro(actions, repeat=repeat)
            return {"success": ok, "logs": logs}
        except Exception as e:
            logger.error("执行宏连招异常未捕获: %s", e)
            return {"success": False, "message": f"宏连招执行异常: {e}"}

    # -------------------------------------------------------------------------
    # 4. 拟人化自主摸鱼 (数字生命模式)
    # -------------------------------------------------------------------------

    @Tool(
        "phone_slack_off",
        description="【数字生命/自主摸鱼】让麦麦在受控手机上自主摸鱼刷内容（支持 B站/知乎/微博/小红书/网易云），模拟真人手势滑动与停顿阅读，刷到好玩内容时主动给主人发截图吐槽分享。",
        parameters=[
            ToolParameterInfo(
                name="app",
                param_type=ToolParamType.STRING,
                description="想要摸鱼的应用，例如：'b站'、'知乎'、'微博'、'小红书'、'网易云'（默认'b站'）",
                required=False,
            ),
            ToolParameterInfo(
                name="duration_seconds",
                param_type=ToolParamType.INTEGER,
                description="本次摸鱼持续时长（秒），默认 60 秒，最长 300 秒",
                required=False,
            ),
            ToolParameterInfo(
                name="share_to_chat",
                param_type=ToolParamType.BOOLEAN,
                description="摸鱼时刷到好玩的内容是否自动发送截图和吐槽到当前聊天窗口（默认 True）",
                required=False,
            ),
        ],
    )
    async def handle_phone_slack_off(
        self,
        app: str = "b站",
        duration_seconds: int = 25,
        share_to_chat: bool = True,
        **kwargs,
    ) -> Dict[str, Any]:
        auth_ok, msg = self._check_owner_auth(kwargs)
        if not auth_ok:
            return {"success": False, "message": msg}

        cfg: PhoneControllerConfig = self.config
        if not cfg.slack_off.enabled:
            return {"success": False, "message": "自主摸鱼功能已在插件配置中关闭"}

        # 对话交互场景下摸鱼时长上限设为 35 秒，确保总耗时在 Host RPC 60s 超时内
        duration = max(10, min(duration_seconds, 35))
        stream_id = kwargs.get("stream_id")

        async def _on_share(image_path: str, caption: str):
            if share_to_chat and stream_id and cfg.slack_off.share_interesting_finds:
                try:
                    await self.ctx.send.text(caption, stream_id)
                    with open(image_path, "rb") as f:
                        img_b64 = base64.b64encode(f.read()).decode("utf-8")
                    await self.ctx.send.image(img_b64, stream_id)
                except Exception as e:
                    logger.warning("摸鱼分享发送失败: %s", e)

        async def _llm_comment(prompt: str) -> str:
            try:
                res = await self.ctx.llm.generate(
                    prompt=prompt,
                    task_name="replyer",
                    temperature=0.85,
                    max_tokens=800,
                )
                if isinstance(res, dict) and res.get("response"):
                    return str(res["response"]).strip()
            except Exception as e:
                logger.debug("调用宿主 LLM 生成摸鱼配文失败: %s", e)
            return ""

        res = await self.slacker.run_slacking_session(
            app_name=app,
            duration_seconds=duration,
            interval_min=cfg.slack_off.swipe_interval_min,
            interval_max=cfg.slack_off.swipe_interval_max,
            share_callback=_on_share if share_to_chat else None,
            custom_llm_url=cfg.slack_off.custom_llm_url,
            custom_llm_key=cfg.slack_off.custom_llm_key,
            custom_llm_model=cfg.slack_off.custom_llm_model,
            llm_caller=_llm_comment,
        )
        return res


def create_plugin() -> MaiBotPlugin:
    """插件工厂入口函数"""
    return PhoneControllerPlugin()

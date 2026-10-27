"""phone_controller 插件主入口

让麦麦具备控制受控安卓手机的全功能组件库：
1. 核心设备状态与无线连接 (phone_status, phone_connect, phone_pair)
2. 视觉感知与 UI 分析 (phone_screenshot, phone_dump)
3. 交互动作 (phone_tap_text, phone_tap, phone_swipe, phone_text, phone_key, phone_open_app, phone_macro)
4. 动态录屏与抽帧 (phone_record_screen)
5. 网易云音乐联动 (music_lyrics, music_search, music_control, music_room_say)
6. QQ 空间互动 (qzone_post_feed, qzone_like_feed, qzone_get_feeds)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from maibot_sdk import MaiBotPlugin, Tool
from maibot_sdk.types import ToolParameterInfo, ToolParamType

from .adb_engine import AdbEngine
from .config import PhoneControllerConfig
from .music import MusicClient
from .qzone import QzoneClient
from .recorder import ScreenRecorder

logger = logging.getLogger("plugin.phone_controller")


class PhoneControllerPlugin(MaiBotPlugin):
    """手机管家插件实现类"""

    config_model = PhoneControllerConfig

    def __init__(self):
        super().__init__()
        self.adb: Optional[AdbEngine] = None
        self.recorder: Optional[ScreenRecorder] = None
        self.music: Optional[MusicClient] = None
        self.qzone: Optional[QzoneClient] = None

    async def on_load(self) -> None:
        """插件加载初始化"""
        cfg: PhoneControllerConfig = self.config
        logger.info("正在加载手机管家插件: v%s", cfg.plugin.version)

        # 1. 初始化底层引擎
        self.adb = AdbEngine(
            adb_path=cfg.device.adb_path,
            device_serial=cfg.device.device_serial,
        )
        self.recorder = ScreenRecorder(adb=self.adb)
        self.music = MusicClient(adb=self.adb, package_name=cfg.music.package_name)
        self.qzone = QzoneClient(
            base_url=cfg.qzone.napcat_http_url,
            token=cfg.qzone.napcat_access_token,
        )

        # 2. 若配置了默认无线连接 IP 和端口，尝试自动静默连接
        if cfg.device.default_host and not cfg.device.device_serial:
            logger.info("尝试自动连接受控手机: %s:%s", cfg.device.default_host, cfg.device.default_port)
            asyncio.create_task(self.adb.connect(cfg.device.default_host, cfg.device.default_port))

        logger.info("手机管家插件加载完成")

    async def on_unload(self) -> None:
        """插件卸载清理"""
        logger.info("手机管家插件已卸载")

    async def on_config_update(self, scope: str, config_data: dict, version: str) -> None:
        """热更新配置"""
        if scope == "self":
            cfg: PhoneControllerConfig = self.config
            if self.adb:
                self.adb.adb_path = cfg.device.adb_path
                self.adb.set_device(cfg.device.device_serial)
            if self.music:
                self.music.package_name = cfg.music.package_name
            if self.qzone:
                self.qzone.base_url = cfg.qzone.napcat_http_url
                self.qzone.token = cfg.qzone.napcat_access_token
            logger.info("手机管家配置热更新成功 (v%s)", version)

    # -------------------------------------------------------------------------
    # 安全防御辅助
    # -------------------------------------------------------------------------

    def _check_owner_auth(self, user_id: Any) -> Tuple[bool, str]:
        """检查调用者是否为主人 QQ，防止群友误触或滥用"""
        cfg: PhoneControllerConfig = self.config
        owner = str(cfg.device.owner_qq).strip()
        if not owner:
            return True, ""  # 未配置主人则不限制
        if str(user_id).strip() != owner:
            return False, f"权限拦截：手机控制功能仅允许主人（QQ: {owner}）操作。"
        return True, ""

    def _get_runtime_dir(self) -> str:
        """获取安全的运行时临时文件目录"""
        try:
            return self.ctx.paths.runtime_dir
        except Exception:
            p = "/tmp/phone_controller"
            os.makedirs(p, exist_ok=True)
            return p

    # -------------------------------------------------------------------------
    # 1. 核心设备与连接工具
    # -------------------------------------------------------------------------

    @Tool(
        "phone_status",
        description="查看受控手机的连接状态、电量、亮灭屏状态及当前前台正在运行的应用包名。",
        parameters=[],
    )
    async def handle_phone_status(self, **kwargs) -> Dict[str, Any]:
        auth_ok, msg = self._check_owner_auth(kwargs.get("user_id"))
        if not auth_ok:
            return {"success": False, "message": msg}

        status = await self.adb.get_status()
        return {"success": True, "data": status}

    @Tool(
        "phone_connect",
        description="连接受控手机的无线调试端口 (IP:端口)。在手机重启或无线调试端口改变后使用此工具重连。",
        parameters=[
            ToolParameterInfo(
                name="host",
                param_type=ToolParamType.STRING,
                description="手机的 IP 地址（如 Tailscale 100.x.x.x 或局域网 IP）",
                required=True,
            ),
            ToolParameterInfo(
                name="port",
                param_type=ToolParamType.INTEGER,
                description="无线调试端口号",
                required=False,
            ),
        ],
    )
    async def handle_phone_connect(self, host: str, port: int = 5555, **kwargs) -> Dict[str, Any]:
        auth_ok, msg = self._check_owner_auth(kwargs.get("user_id"))
        if not auth_ok:
            return {"success": False, "message": msg}

        ok, out = await self.adb.connect(host, port)
        return {"success": ok, "message": out}

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
        auth_ok, msg = self._check_owner_auth(kwargs.get("user_id"))
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
        auth_ok, msg = self._check_owner_auth(kwargs.get("user_id"))
        if not auth_ok:
            return {"success": False, "message": msg}

        filename = f"screenshot_{int(time.time())}.jpg"
        save_path = os.path.join(self._get_runtime_dir(), filename)
        cfg: PhoneControllerConfig = self.config

        ok, res = await self.adb.capture_screenshot(save_path, quality=cfg.device.screenshot_quality)
        if not ok:
            return {"success": False, "message": f"截图失败: {res}"}

        # 自动发送到当前聊天流
        stream_id = kwargs.get("stream_id")
        if send_to_chat and stream_id and cfg.device.auto_send_screenshot:
            try:
                await self.ctx.send.image(save_path, stream_id)
            except Exception as e:
                logger.warning("截图发送至聊天失败: %s", e)

        return {"success": True, "message": "截图成功", "image_path": save_path}

    @Tool(
        "phone_dump",
        description="导出当前屏幕 UI 布局树，获取所有可见文字、按钮及它们的屏幕中心点击坐标 (x, y)。",
        parameters=[],
    )
    async def handle_phone_dump(self, **kwargs) -> Dict[str, Any]:
        auth_ok, msg = self._check_owner_auth(kwargs.get("user_id"))
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
    # 3. 基础操作与智能点击
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
        auth_ok, msg = self._check_owner_auth(kwargs.get("user_id"))
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
        auth_ok, msg = self._check_owner_auth(kwargs.get("user_id"))
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
        auth_ok, msg = self._check_owner_auth(kwargs.get("user_id"))
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
        auth_ok, msg = self._check_owner_auth(kwargs.get("user_id"))
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
        auth_ok, msg = self._check_owner_auth(kwargs.get("user_id"))
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
        auth_ok, msg = self._check_owner_auth(kwargs.get("user_id"))
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
        auth_ok, msg = self._check_owner_auth(kwargs.get("user_id"))
        if not auth_ok:
            return {"success": False, "message": msg}

        try:
            actions = json.loads(actions_json)
            if not isinstance(actions, list):
                return {"success": False, "message": "actions_json 必须是动作对象列表"}
        except Exception as e:
            return {"success": False, "message": f"JSON 解析失败: {e}"}

        ok, logs = await self.adb.execute_macro(actions, repeat=repeat)
        return {"success": ok, "logs": logs}

    # -------------------------------------------------------------------------
    # 4. 录屏感知与抽帧
    # -------------------------------------------------------------------------

    @Tool(
        "phone_record_screen",
        description="录制手机屏幕指定秒数的动态操作，并自动抽帧成多张关键帧图片发送到当前会话供查看。",
        parameters=[
            ToolParameterInfo(
                name="seconds",
                param_type=ToolParamType.INTEGER,
                description="录屏秒数 (3~15 秒，默认 5 秒)",
                required=False,
            ),
            ToolParameterInfo(
                name="frames",
                param_type=ToolParamType.INTEGER,
                description="抽取的关键帧数量 (2~6 张，默认 4 张)",
                required=False,
            ),
        ],
    )
    async def handle_phone_record_screen(self, seconds: int = 5, frames: int = 4, **kwargs) -> Dict[str, Any]:
        auth_ok, msg = self._check_owner_auth(kwargs.get("user_id"))
        if not auth_ok:
            return {"success": False, "message": msg}

        cfg: PhoneControllerConfig = self.config
        if not cfg.screen_record.enabled:
            return {"success": False, "message": "录屏功能已被管理员禁用"}

        out_dir = os.path.join(self._get_runtime_dir(), f"rec_{int(time.time())}")
        ok, frame_paths, err = await self.recorder.record_and_extract_frames(
            duration_seconds=seconds,
            frame_count=frames,
            output_dir=out_dir,
        )

        if not ok:
            return {"success": False, "message": err}

        # 自动发送关键帧到聊天
        stream_id = kwargs.get("stream_id")
        if stream_id and cfg.screen_record.auto_send_frames:
            for p in frame_paths:
                try:
                    await self.ctx.send.image(p, stream_id)
                    await asyncio.sleep(0.3)
                except Exception as e:
                    logger.warning("关键帧发送失败: %s", e)

        return {
            "success": True,
            "message": f"录屏完成，已提取 {len(frame_paths)} 张关键帧",
            "frame_paths": frame_paths,
        }

    # -------------------------------------------------------------------------
    # 5. 网易云音乐联动
    # -------------------------------------------------------------------------

    @Tool(
        "music_lyrics",
        description="查询指定歌曲的歌词内容（支持歌名直接查询）。",
        parameters=[
            ToolParameterInfo(name="song_name", param_type=ToolParamType.STRING, description="歌曲名或搜索词", required=True),
        ],
    )
    async def handle_music_lyrics(self, song_name: str, **kwargs) -> Dict[str, Any]:
        ok, songs, err = await self.music.search_song(song_name, limit=1)
        if not ok or not songs:
            return {"success": False, "message": f"未搜索到歌曲 '{song_name}': {err}"}

        song_id = songs[0]["id"]
        title = f"{songs[0]['name']} - {songs[0]['artist']}"
        ok, lyrics, err = await self.music.get_lyrics(song_id)
        if not ok:
            return {"success": False, "message": err}

        return {"success": True, "song": title, "lyrics": lyrics[:1500]}

    @Tool(
        "music_control",
        description="控制手机网易云音乐播放：'play_pause'(播放/暂停), 'next'(下一首), 'prev'(上一首)。",
        parameters=[
            ToolParameterInfo(
                name="action",
                param_type=ToolParamType.STRING,
                description="动作类型: 'play_pause' (播放/暂停), 'next' (下一首), 'prev' (上一首)",
                required=True,
            ),
        ],
    )
    async def handle_music_control(self, action: str, **kwargs) -> Dict[str, Any]:
        auth_ok, msg = self._check_owner_auth(kwargs.get("user_id"))
        if not auth_ok:
            return {"success": False, "message": msg}

        ok, res = await self.music.control_playback(action)
        return {"success": ok, "message": res}

    @Tool(
        "music_room_say",
        description="在手机网易云音乐「一起听」聊天室发言交流。",
        parameters=[
            ToolParameterInfo(name="text", param_type=ToolParamType.STRING, description="在聊天室发送的文本内容", required=True),
        ],
    )
    async def handle_music_room_say(self, text: str, **kwargs) -> Dict[str, Any]:
        auth_ok, msg = self._check_owner_auth(kwargs.get("user_id"))
        if not auth_ok:
            return {"success": False, "message": msg}

        ok, res = await self.music.room_say(text)
        return {"success": ok, "message": res}

    # -------------------------------------------------------------------------
    # 6. QQ 空间互动
    # -------------------------------------------------------------------------

    @Tool(
        "qzone_post_feed",
        description="在 QQ 空间发布一条新说说（由受控或中继账号发布）。",
        parameters=[
            ToolParameterInfo(name="content", param_type=ToolParamType.STRING, description="说说的文本内容", required=True),
        ],
    )
    async def handle_qzone_post_feed(self, content: str, **kwargs) -> Dict[str, Any]:
        auth_ok, msg = self._check_owner_auth(kwargs.get("user_id"))
        if not auth_ok:
            return {"success": False, "message": msg}

        cfg: PhoneControllerConfig = self.config
        if not cfg.qzone.enabled:
            return {"success": False, "message": "QQ空间功能未启用"}

        ok, res = await self.qzone.publish_feed(content, max_daily=cfg.qzone.daily_post_limit)
        return {"success": ok, "message": res}

    @Tool(
        "qzone_like_feed",
        description="为指定的 QQ 空间说说点赞。",
        parameters=[
            ToolParameterInfo(name="feed_id", param_type=ToolParamType.STRING, description="说说的 ID (tid)", required=False),
            ToolParameterInfo(name="user_id", param_type=ToolParamType.STRING, description="被点赞用户 QQ 号", required=False),
        ],
    )
    async def handle_qzone_like_feed(self, feed_id: str = "", user_id: str = "", **kwargs) -> Dict[str, Any]:
        auth_ok, msg = self._check_owner_auth(kwargs.get("user_id"))
        if not auth_ok:
            return {"success": False, "message": msg}

        cfg: PhoneControllerConfig = self.config
        if not cfg.qzone.enabled:
            return {"success": False, "message": "QQ空间功能未启用"}

        ok, res = await self.qzone.like_feed(feed_id=feed_id, user_id=user_id)
        return {"success": ok, "message": res}

    @Tool(
        "qzone_get_feeds",
        description="获取好友 QQ 空间的最新动态列表。",
        parameters=[
            ToolParameterInfo(name="count", param_type=ToolParamType.INTEGER, description="获取条数 (默认 5 条)", required=False),
        ],
    )
    async def handle_qzone_get_feeds(self, count: int = 5, **kwargs) -> Dict[str, Any]:
        auth_ok, msg = self._check_owner_auth(kwargs.get("user_id"))
        if not auth_ok:
            return {"success": False, "message": msg}

        cfg: PhoneControllerConfig = self.config
        if not cfg.qzone.enabled:
            return {"success": False, "message": "QQ空间功能未启用"}

        ok, feeds, err = await self.qzone.get_feeds(count=count)
        if not ok:
            return {"success": False, "message": err}
        return {"success": True, "feeds": feeds[:count]}


def create_plugin() -> MaiBotPlugin:
    """插件工厂入口函数"""
    return PhoneControllerPlugin()

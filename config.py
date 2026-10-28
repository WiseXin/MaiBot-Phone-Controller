"""phone_controller 插件配置模型 (符合 MaiBot SDK 2.x 规范)"""

from __future__ import annotations

from maibot_sdk import Field, PluginConfigBase


class PluginSection(PluginConfigBase):
    """插件核心基础信息"""

    __ui_label__ = "基础配置"
    __ui_icon__ = "package"
    __ui_order__ = 0

    name: str = Field(default="phone_controller", description="插件名称")
    version: str = Field(default="1.1.0", description="插件版本")
    config_version: str = Field(default="1.1.0", description="配置版本(Runner 校验)")
    enabled: bool = Field(default=True, description="是否启用手机控制插件")


class DeviceSection(PluginConfigBase):
    """受控手机 ADB 与连接配置"""

    __ui_label__ = "受控设备"
    __ui_icon__ = "smartphone"
    __ui_order__ = 1

    adb_path: str = Field(
        default="adb",
        description="宿主机 ADB 执行文件路径。默认'adb'会自动探测环境变量及常见系统路径",
    )
    device_serial: str = Field(
        default="",
        description="指定控制的设备序列号或 IP:端口。留空表示自动使用当前连接的唯一设备",
    )
    default_host: str = Field(
        default="",
        description="受控手机无线调试 IP（如 127.0.0.1、局域网 IP 或 Tailscale 100.x.x.x）。配置后麦麦启动时自动尝试连接",
    )
    default_port: int = Field(default=5555, description="受控手机无线调试端口，默认 5555")
    owner_qq: str = Field(
        default="",
        description="【核心安全项·必填】允许控制手机的主人账号 ID（支持 QQ 号与 Discord 用户 ID，多主人用英文逗号分隔）。默认留空将安全拦截所有控制命令，防止群聊成员误触或隐私泄露",
    )
    auto_send_screenshot: bool = Field(
        default=True,
        description="截图后是否自动发送到当前会话窗口供查看",
    )
    screenshot_quality: int = Field(
        default=75,
        description="截图压缩画质 (1-100)，降低网络开销与存储占用",
    )
    aliases: str = Field(
        default="",
        description="设备别名映射表（逗号分隔，例如：'我的手机=192.168.1.100:5555'）",
    )


class SlackOffSection(PluginConfigBase):
    """拟人化自主摸鱼配置 (数字生命模式)"""

    __ui_label__ = "自主摸鱼 (数字生命)"
    __ui_icon__ = "coffee"
    __ui_order__ = 2

    enabled: bool = Field(default=True, description="是否启用自主摸鱼能力")
    auto_slacking: bool = Field(
        default=False,
        description="是否启用闲时自动定时摸鱼巡航（开启前请务必先在 device.owner_qq 配置主人账号）",
    )
    interval_hours_min: float = Field(
        default=2.0,
        description="自动摸鱼最小间隔小时数（例如 2.0 表示至少间隔 2 小时）",
    )
    interval_hours_max: float = Field(
        default=4.0,
        description="自动摸鱼最大间隔小时数（例如 4.0 表示最多间隔 4 小时）",
    )
    session_duration_seconds: int = Field(
        default=60,
        description="单次自动摸鱼持续秒数（默认 60 秒）",
    )
    active_time_range: str = Field(
        default="09:00-23:00",
        description="允许自动摸鱼的时间段（24小时制 HH:MM-HH:MM，深夜时段自动免打扰静默睡眠）",
    )
    lock_screen_after_slack: bool = Field(
        default=True,
        description="摸鱼完毕后是否自动按电源键锁屏灭屏，节省手机电量",
    )
    preferred_apps: str = Field(
        default="b站,知乎,小红书,抖音",
        description="麦麦摸鱼爱逛的应用名称（逗号分隔）",
    )
    share_interesting_finds: bool = Field(
        default=True,
        description="摸鱼刷到有趣内容时，是否自动抓取截图分享给主人",
    )
    swipe_interval_min: float = Field(
        default=3.0,
        description="模拟真人阅读的最短停留秒数",
    )
    swipe_interval_max: float = Field(
        default=7.0,
        description="模拟真人阅读的最长停留秒数",
    )
    notify_stream_id: str = Field(
        default="",
        description="自动摸鱼时主通知会话 stream_id（留空自动使用主人最近私聊窗口）",
    )
    fallback_stream_id: str = Field(
        default="",
        description="备用通知会话 stream_id（当主通知窗口发送失败时自动降级尝试）",
    )
    custom_llm_url: str = Field(
        default="",
        description="可选：自定义 AI 总结吐槽 API 端点（OpenAI 兼容接口，留空使用内置拟真文案库）",
    )
    custom_llm_key: str = Field(
        default="",
        description="可选：自定义 AI 总结吐槽 API 密钥",
    )
    custom_llm_model: str = Field(
        default="gpt-3.5-turbo",
        description="可选：自定义 AI 总结吐槽模型名称",
    )


class PhoneControllerConfig(PluginConfigBase):
    """phone_controller 顶层配置模型"""

    plugin: PluginSection = Field(default_factory=PluginSection)
    device: DeviceSection = Field(default_factory=DeviceSection)
    slack_off: SlackOffSection = Field(default_factory=SlackOffSection)

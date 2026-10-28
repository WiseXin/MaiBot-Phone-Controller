"""phone_controller 插件配置模型 (符合 MaiBot SDK 2.x 规范)

支持在 WebUI 中通过 json_schema_extra 渲染中文标签 (label)、输入框提示 (placeholder) 与大白话描述 (hint)。
"""

from __future__ import annotations

from typing import ClassVar
from maibot_sdk import Field, PluginConfigBase


class PluginSection(PluginConfigBase):
    """插件核心基础信息"""

    __ui_label__: ClassVar[str] = "基础配置"
    __ui_icon__: ClassVar[str] = "package"
    __ui_order__: ClassVar[int] = 0

    name: str = Field(
        default="phone_controller",
        description="插件名称",
        json_schema_extra={
            "label": "插件标识",
            "hint": "插件内部唯一标识名称",
        },
    )
    version: str = Field(
        default="1.1.0",
        description="插件版本",
        json_schema_extra={
            "label": "插件版本",
            "hint": "当前插件代码版本",
        },
    )
    config_version: str = Field(
        default="1.1.0",
        description="配置版本(Runner 校验)",
        json_schema_extra={
            "label": "配置结构版本",
            "hint": "用于版本迁移与兼容性校验",
        },
    )
    enabled: bool = Field(
        default=True,
        description="是否启用手机控制插件",
        json_schema_extra={
            "label": "启用手机管家",
            "hint": "是否开启本手机控制插件的总开关",
        },
    )


class DeviceSection(PluginConfigBase):
    """受控手机 ADB 与连接配置"""

    __ui_label__: ClassVar[str] = "受控设备"
    __ui_icon__: ClassVar[str] = "smartphone"
    __ui_order__: ClassVar[int] = 1

    adb_path: str = Field(
        default="adb",
        description="宿主机 ADB 执行文件路径。默认'adb'会自动探测环境变量及常见系统路径",
        json_schema_extra={
            "label": "宿主机 ADB 路径",
            "hint": "宿主机 ADB 命令行路径。默认 'adb' 即可，系统会自动探测环境变量",
            "placeholder": "adb",
        },
    )
    device_serial: str = Field(
        default="",
        description="指定控制的设备序列号或 IP:端口。留空表示自动使用当前连接的唯一设备",
        json_schema_extra={
            "label": "指定设备 Serial",
            "hint": "指定控制的手机序列号或 IP:端口。留空表示自动使用当前连接的唯一在线设备",
            "placeholder": "留空自动使用唯一在线设备",
        },
    )
    default_host: str = Field(
        default="",
        description="受控手机无线调试 IP（如 127.0.0.1、局域网 IP 或 Tailscale 100.x.x.x）。配置后麦麦启动时自动尝试连接",
        json_schema_extra={
            "label": "自动连接主机 IP",
            "hint": "受控手机无线调试 IP（支持 Tailscale 专网 100.x.x.x、局域网 IP 或留空）",
            "placeholder": "例如 100.82.29.119 或 192.168.1.100",
        },
    )
    default_port: int = Field(
        default=5555,
        description="受控手机无线调试端口，默认 5555",
        json_schema_extra={
            "label": "无线调试端口",
            "hint": "Android 原生无线调试端口号，默认 5555",
            "placeholder": "5555",
        },
    )
    owner_qq: str = Field(
        default="",
        description="【核心安全项·必填】允许控制手机的主人账号 ID（支持 QQ 号与 Discord 用户 ID，多主人用英文逗号分隔）。默认留空将安全拦截所有控制命令，防止群聊成员误触或隐私泄露",
        json_schema_extra={
            "label": "【核心安全项】主人账号 ID",
            "hint": "⚠️必填项：允许控制手机的主人账号（QQ 号或 Discord 用户数字 ID，多个用英文逗号隔开），留空默认拦截所有操作以保安全！",
            "placeholder": "例如 489618891, 1563093479125688342",
        },
    )
    auto_send_screenshot: bool = Field(
        default=True,
        description="截图后是否自动发送到当前会话窗口供查看",
        json_schema_extra={
            "label": "截屏自动发往聊天",
            "hint": "在聊天中让麦麦看屏幕后，是否自动将截屏图片发送到当前会话窗口",
        },
    )
    screenshot_quality: int = Field(
        default=75,
        description="截图压缩画质 (1-100)，降低网络开销与存储占用",
        json_schema_extra={
            "label": "截图压缩画质 (1-100)",
            "hint": "截图压缩画质 (范围 1~100)，默认 75 兼顾高清画面与低网络带宽消耗",
            "placeholder": "75",
        },
    )
    aliases: str = Field(
        default="",
        description="设备别名映射表（逗号分隔，例如：'我的手机=192.168.1.100:5555'）",
        json_schema_extra={
            "label": "设备别名映射表",
            "hint": "多机党神器：给手机起好记的名字，在聊天中直接对麦麦说大白话即可换机（如“麦麦，连接备用机”）",
            "placeholder": "备用机=192.168.1.100:5555,小米=100.64.0.1:5555",
        },
    )


class SlackOffSection(PluginConfigBase):
    """拟人化自主摸鱼配置 (数字生命模式)"""

    __ui_label__: ClassVar[str] = "自主摸鱼 (数字生命)"
    __ui_icon__: ClassVar[str] = "coffee"
    __ui_order__: ClassVar[int] = 2

    enabled: bool = Field(
        default=True,
        description="是否启用自主摸鱼能力",
        json_schema_extra={
            "label": "启用自主摸鱼能力",
            "hint": "是否开启手机摸鱼功能（开启后支持在聊天中叫麦麦去刷手机，如“麦麦，去刷刷B站”）",
        },
    )
    auto_slacking: bool = Field(
        default=False,
        description="是否启用闲时自动定时摸鱼巡航（开启前请务必先在 device.owner_qq 配置主人账号）",
        json_schema_extra={
            "label": "定时自动摸鱼巡航 (数字生命模式)",
            "hint": "开启后麦麦会在白天闲暇时间自主唤醒手机浏览，刷到好玩内容发截图找你吐槽（建议先配好主人账号）",
        },
    )
    interval_hours_min: float = Field(
        default=2.0,
        description="自动摸鱼最小间隔小时数（例如 2.0 表示至少间隔 2 小时）",
        json_schema_extra={
            "label": "摸鱼最小随机间隔 (小时)",
            "hint": "两次自动摸鱼之间的最短休息时间，例如 2.0 表示至少间隔 2 小时",
            "placeholder": "2.0",
        },
    )
    interval_hours_max: float = Field(
        default=4.0,
        description="自动摸鱼最大间隔小时数（例如 4.0 表示最多间隔 4 小时）",
        json_schema_extra={
            "label": "摸鱼最大随机间隔 (小时)",
            "hint": "两次自动摸鱼之间的最长休息时间，例如 4.0 表示最多间隔 4 小时",
            "placeholder": "4.0",
        },
    )
    session_duration_seconds: int = Field(
        default=60,
        description="单次自动摸鱼持续秒数（默认 60 秒）",
        json_schema_extra={
            "label": "单次摸鱼浏览时长 (秒)",
            "hint": "每次玩手机的持续秒数（建议 30~60 秒，防长时间锁屏卡死）",
            "placeholder": "60",
        },
    )
    active_time_range: str = Field(
        default="09:00-23:00",
        description="允许自动摸鱼的时间段（24小时制 HH:MM-HH:MM，深夜时段自动免打扰静默睡眠）",
        json_schema_extra={
            "label": "摸鱼作息时间窗口",
            "hint": "24 小时制 HH:MM-HH:MM，深夜时段麦麦会自动进入免打扰睡眠静默状态，绝不触碰手机",
            "placeholder": "09:00-23:00",
        },
    )
    lock_screen_after_slack: bool = Field(
        default=True,
        description="摸鱼完毕后是否自动按电源键锁屏灭屏，节省手机电量",
        json_schema_extra={
            "label": "摸鱼完毕自动锁屏待机",
            "hint": "摸鱼结束后自动按电源键灭屏休眠待命，极度节省手机电量",
        },
    )
    preferred_apps: str = Field(
        default="b站,知乎,小红书,抖音",
        description="麦麦摸鱼爱逛的应用池（支持：b站, 知乎, 小红书, 抖音，用逗号分隔）",
        json_schema_extra={
            "label": "爱逛的应用池",
            "hint": "麦麦摸鱼爱逛的应用名称（完整支持：b站, 知乎, 小红书, 抖音，用英文逗号分隔）",
            "placeholder": "b站,知乎,小红书,抖音",
        },
    )
    share_interesting_finds: bool = Field(
        default=True,
        description="摸鱼刷到有趣内容时，是否自动抓取截图分享给主人",
        json_schema_extra={
            "label": "精彩内容主动分享",
            "hint": "刷到有趣爆款内容时，是否自动抓取高清截图主动私聊发给主人吐槽",
        },
    )
    notify_summary: bool = Field(
        default=False,
        description="摸鱼结束时是否发送打卡结算简报（默认 false：仅抓到精彩截图时才向主人发送，其余时间静默摸鱼免打扰）",
        json_schema_extra={
            "label": "摸鱼打卡结算播报",
            "hint": "摸鱼结束时是否发送打卡结算简报（默认 false：极简防打扰模式，仅抓到精彩大图才发送；设为 true 则每次锁屏前都发简述打卡）",
        },
    )
    swipe_interval_min: float = Field(
        default=3.0,
        description="模拟真人阅读的最短停留秒数",
        json_schema_extra={
            "label": "模拟阅读最短停留 (秒)",
            "hint": "模拟真人滑动一下屏幕后的最短阅读停留秒数",
            "placeholder": "3.0",
        },
    )
    swipe_interval_max: float = Field(
        default=7.0,
        description="模拟真人阅读的最长停留秒数",
        json_schema_extra={
            "label": "模拟阅读最长停留 (秒)",
            "hint": "模拟真人滑动一下屏幕后的最长阅读停留秒数",
            "placeholder": "7.0",
        },
    )
    notify_stream_id: str = Field(
        default="",
        description="摸鱼主动分享目标（留空最推荐：自动定位主人私聊窗口并支持多通道主备降级；亦可直接填主人 QQ 号或机器人号）",
        json_schema_extra={
            "label": "摸鱼主通知通道",
            "hint": "留空最推荐：系统全自动反查最近活跃的主人私聊通道，多机器人时自动实现主备降级！亦可直接填写主人 QQ 号或机器人号",
            "placeholder": "留空自动推导，或填写QQ号/机器人号",
        },
    )
    fallback_stream_id: str = Field(
        default="",
        description="备用通知目标（可选，当主通道发送失败时自动降级；留空若存在多机器人通道会自动选路作为备用）",
        json_schema_extra={
            "label": "备用降级通知通道",
            "hint": "可选：当主通道发送失败或网络波动时自动降级尝试；留空自动将另一机器人通道设为备用",
            "placeholder": "留空自动将另一通道设为备用",
        },
    )
    custom_llm_url: str = Field(
        default="",
        description="可选：自定义 AI 总结吐槽 API 端点（OpenAI 兼容接口，留空使用内置拟真文案库）",
        json_schema_extra={
            "label": "自定义大模型 API 端点 (可选)",
            "hint": "可选高级项：第三方 OpenAI 兼容接口，留空默认使用麦麦内置大模型驱动灵动吐槽，无需配置！",
            "placeholder": "留空使用麦麦内置大模型",
        },
    )
    custom_llm_key: str = Field(
        default="",
        description="可选：自定义 AI 总结吐槽 API 密钥",
        json_schema_extra={
            "label": "自定义大模型 API 密钥 (可选)",
            "hint": "可选：第三方大模型的 API Key",
            "placeholder": "sk-...",
        },
    )
    custom_llm_model: str = Field(
        default="gpt-3.5-turbo",
        description="可选：自定义 AI 总结吐槽模型名称",
        json_schema_extra={
            "label": "自定义大模型名称 (可选)",
            "hint": "可选：第三方大模型模型名，如 gpt-3.5-turbo",
            "placeholder": "gpt-3.5-turbo",
        },
    )


class PhoneControllerConfig(PluginConfigBase):
    """phone_controller 顶层配置模型"""

    plugin: PluginSection = Field(default_factory=PluginSection)
    device: DeviceSection = Field(default_factory=DeviceSection)
    slack_off: SlackOffSection = Field(default_factory=SlackOffSection)

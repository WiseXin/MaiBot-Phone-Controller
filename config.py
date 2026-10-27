"""phone_controller 插件配置模型 (符合 MaiBot SDK 2.x 规范)"""

from __future__ import annotations

from typing import List
from maibot_sdk import Field, PluginConfigBase


class PluginSection(PluginConfigBase):
    """插件核心基础信息"""

    __ui_label__ = "基础配置"
    __ui_icon__ = "package"
    __ui_order__ = 0

    name: str = Field(default="phone_controller", description="插件名称")
    version: str = Field(default="1.0.0", description="插件版本")
    config_version: str = Field(default="1.0.0", description="配置版本(Runner 校验)")
    enabled: bool = Field(default=True, description="是否启用手机控制插件")


class DeviceSection(PluginConfigBase):
    """受控手机 ADB 与安全配置"""

    __ui_label__ = "受控设备"
    __ui_icon__ = "smartphone"
    __ui_order__ = 1

    adb_path: str = Field(default="/usr/bin/adb", description="宿主机 ADB 可执行文件路径")
    device_serial: str = Field(
        default="",
        description="指定控制的设备 Serial 或 IP:端口。留空表示自动使用当前连接的唯一设备",
    )
    default_host: str = Field(
        default="",
        description="受控手机无线调试 IP（例如 Tailscale 100.x.x.x 或局域网 IP）",
    )
    default_port: int = Field(default=5555, description="受控手机无线调试默认端口")
    owner_qq: str = Field(
        default="489618891",
        description="允许控制手机的主人 QQ 号。留空则不限制调用者",
    )
    auto_send_screenshot: bool = Field(
        default=True,
        description="截图后是否自动通过麦麦发到当前会话窗口供查看",
    )
    screenshot_quality: int = Field(
        default=75,
        description="截图压缩画质 (1-100)，降低图片体积与网络开销",
    )


class ScreenRecordSection(PluginConfigBase):
    """录屏感知配置"""

    __ui_label__ = "录屏感知"
    __ui_icon__ = "video"
    __ui_order__ = 2

    enabled: bool = Field(default=True, description="是否启用手机录屏与抽帧能力")
    default_duration: int = Field(default=5, description="默认录屏时长(秒)")
    max_duration: int = Field(default=30, description="单次最大录屏时长(秒)")
    default_frames: int = Field(default=6, description="录屏完成后抽取的关键帧数量")
    auto_send_frames: bool = Field(
        default=True,
        description="抽帧完成后是否自动把关键帧图片发送到当前会话",
    )


class MusicSection(PluginConfigBase):
    """网易云音乐控制配置"""

    __ui_label__ = "音乐控制"
    __ui_icon__ = "music"
    __ui_order__ = 3

    enabled: bool = Field(default=True, description="是否启用网易云音乐控制与歌词查询能力")
    package_name: str = Field(
        default="com.netease.cloudmusic",
        description="手机上网易云音乐 App 的安卓包名",
    )


class QzoneSection(PluginConfigBase):
    """QQ空间互动配置（基于 OneBot HTTP API）"""

    __ui_label__ = "QQ空间联动"
    __ui_icon__ = "heart"
    __ui_order__ = 4

    enabled: bool = Field(default=True, description="是否启用 QQ 空间互动（点赞/说说/动态）能力")
    napcat_http_url: str = Field(
        default="http://100.115.30.64:3000",
        description="NapCat HTTP API 地址（用于发送说说和点赞）",
    )
    napcat_access_token: str = Field(
        default="ac9aadf68d0937ed06bbfee5ee4f4bb6a0dab7bf698cc83a",
        description="NapCat 访问 Token",
    )
    daily_post_limit: int = Field(default=8, description="每日发说说最大条数，防止刷屏")
    daily_comment_limit: int = Field(default=10, description="每日评论最大条数")


class PhoneControllerConfig(PluginConfigBase):
    """phone_controller 顶层配置模型"""

    plugin: PluginSection = Field(default_factory=PluginSection)
    device: DeviceSection = Field(default_factory=DeviceSection)
    screen_record: ScreenRecordSection = Field(default_factory=ScreenRecordSection)
    music: MusicSection = Field(default_factory=MusicSection)
    qzone: QzoneSection = Field(default_factory=QzoneSection)

"""phone_controller 插件配置模型 (符合 MaiBot SDK 2.x 规范)"""

from __future__ import annotations

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


class PhoneControllerConfig(PluginConfigBase):
    """phone_controller 顶层配置模型"""

    plugin: PluginSection = Field(default_factory=PluginSection)
    device: DeviceSection = Field(default_factory=DeviceSection)

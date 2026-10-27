"""ADB 核心控制引擎与设备交互驱动。

提供：
1. 设备连接与状态管理 (connect, pair, status, devices)
2. 视觉看屏 (screencap 内存直读压缩, uiautomator XML 解析节点与文字坐标)
3. 交互操作 (tap, tap_text, swipe, press_key, open_app)
4. 中文输入 (ADBKeyboard 广播协议 + 原生 input 回退)
5. 连招宏引擎 (Macro 串行执行)
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import re
import shutil
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple
from PIL import Image

logger = logging.getLogger("plugin.phone_controller.adb")

# 常用包名别名表
APP_PACKAGE_MAP: Dict[str, str] = {
    "网易云音乐": "com.netease.cloudmusic",
    "网易云": "com.netease.cloudmusic",
    "微信": "com.tencent.mm",
    "qq": "com.tencent.mobileqq",
    "手q": "com.tencent.mobileqq",
    "知乎": "com.zhihu.android",
    "b站": "tv.danmaku.bili",
    "bilibili": "tv.danmaku.bili",
    "哔哩哔哩": "tv.danmaku.bili",
    "微博": "com.sina.weibo",
    "抖音": "com.ss.android.ugc.aweme",
    "快手": "com.smile.gifmaker",
    "淘宝": "com.taobao.taobao",
    "京东": "com.jingdong.app.mall",
    "设置": "com.android.settings",
    "相机": "com.android.camera",
    "相册": "com.miui.gallery",
    "浏览器": "com.android.browser",
    "时钟": "com.android.deskclock",
}

# 常用系统按键映射
KEY_MAP: Dict[str, int] = {
    "home": 3,
    "back": 4,
    "menu": 82,
    "enter": 66,
    "power": 26,
    "recent": 187,
    "volume_up": 24,
    "volume_down": 25,
    "mute": 164,
    "delete": 67,
    "space": 62,
}


class AdbEngine:
    """异步 ADB 命令执行与交互控制引擎"""

    def __init__(self, adb_path: str = "adb", device_serial: str = ""):
        self.adb_path = self._resolve_adb_path(adb_path)
        self.device_serial = device_serial.strip()

    @staticmethod
    def _resolve_adb_path(configured_path: str) -> str:
        """智能寻找可执行的 ADB 二进制路径，支持各平台开箱即用"""
        if configured_path and os.path.isabs(configured_path) and os.path.exists(configured_path):
            return configured_path
        
        # 优先在系统 PATH 查找
        found = shutil.which(configured_path) or shutil.which("adb")
        if found:
            return found

        # 常见 Linux / macOS / Windows 默认安装路径探测
        candidates = [
            "/usr/bin/adb",
            "/usr/local/bin/adb",
            "/opt/homebrew/bin/adb",
            r"C:\platform-tools\adb.exe",
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
        return configured_path or "adb"

    def set_device(self, serial: str) -> None:
        """动态设置当前操作的设备序列号/IP:端口"""
        self.device_serial = serial.strip()

    def _build_adb_cmd(self, args: List[str]) -> List[str]:
        cmd = [self.adb_path]
        if self.device_serial:
            cmd.extend(["-s", self.device_serial])
        cmd.extend(args)
        return cmd

    async def run_cmd(self, args: List[str], timeout: float = 20.0) -> Tuple[bool, str]:
        """运行 ADB 基础命令并捕获文本输出"""
        full_cmd = self._build_adb_cmd(args)
        try:
            proc = await asyncio.create_subprocess_exec(
                *full_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            out_str = stdout.decode("utf-8", errors="replace").strip()
            err_str = stderr.decode("utf-8", errors="replace").strip()

            if proc.returncode == 0:
                return True, out_str
            else:
                combined_err = f"{out_str}\n{err_str}".strip()
                logger.warning("ADB 执行失败 %s: code=%s, err=%s", full_cmd, proc.returncode, combined_err)
                return False, combined_err
        except asyncio.TimeoutError:
            logger.error("ADB 执行超时 %s (%ss)", full_cmd, timeout)
            return False, f"执行超时 ({timeout}s)"
        except Exception as e:
            logger.error("ADB 异常 %s: %s", full_cmd, e)
            return False, str(e)

    async def run_shell(self, shell_cmd: str, timeout: float = 20.0) -> Tuple[bool, str]:
        """执行 adb shell 命令"""
        return await self.run_cmd(["shell", shell_cmd], timeout=timeout)

    # -------------------------------------------------------------------------
    # 1. 设备与连接管理
    # -------------------------------------------------------------------------

    async def connect(self, host: str, port: int = 5555) -> Tuple[bool, str]:
        """连接无线调试设备"""
        target = f"{host.strip()}:{port}"
        # 连接命令不需要指定 -s
        proc = await asyncio.create_subprocess_exec(
            self.adb_path, "connect", target,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        out = (stdout.decode() + "\n" + stderr.decode()).strip()
        if "connected to" in out.lower():
            self.device_serial = target
            return True, f"成功连接至 {target}"
        return False, f"连接失败: {out}"

    async def pair(self, host: str, port: int, code: str) -> Tuple[bool, str]:
        """首次配对无线调试"""
        target = f"{host.strip()}:{port}"
        proc = await asyncio.create_subprocess_exec(
            self.adb_path, "pair", target, str(code).strip(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        out = (stdout.decode() + "\n" + stderr.decode()).strip()
        if "successfully paired" in out.lower():
            return True, f"配对成功: {target}"
        return False, f"配对失败: {out}"

    async def list_devices(self) -> List[Dict[str, str]]:
        """获取当前已识别设备列表"""
        proc = await asyncio.create_subprocess_exec(
            self.adb_path, "devices", "-l",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        lines = stdout.decode().strip().splitlines()
        devices = []
        for line in lines[1:]:
            parts = line.split()
            if len(parts) >= 2:
                devices.append({
                    "serial": parts[0],
                    "state": parts[1],
                    "details": " ".join(parts[2:]),
                })
        return devices

    async def get_status(self) -> Dict[str, Any]:
        """获取设备详细状态（电量、屏幕、前台 App）"""
        status: Dict[str, Any] = {"connected": False}
        devs = await self.list_devices()
        status["devices_count"] = len(devs)
        status["all_devices"] = devs

        # 检查当前设备
        ok, battery_out = await self.run_shell("dumpsys battery", timeout=5.0)
        if not ok:
            status["error"] = "设备未响应或未连接"
            return status

        status["connected"] = True

        # 解析电量
        level_match = re.search(r"level:\s*(\d+)", battery_out)
        status["battery_level"] = int(level_match.group(1)) if level_match else None
        status["charging"] = "status: 2" in battery_out or "AC powered: true" in battery_out or "USB powered: true" in battery_out

        # 解析屏幕亮灭
        _, power_out = await self.run_shell("dumpsys power | grep 'mHoldingDisplay'", timeout=5.0)
        status["screen_on"] = "true" in power_out.lower()

        # 解析当前前台应用
        _, focus_out = await self.run_shell("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'", timeout=5.0)
        pkg_match = re.search(r"u0\s+([^/\s]+)/", focus_out) or re.search(r"ActivityRecord{[^}]+u0\s+([^/\s]+)/", focus_out)
        status["foreground_package"] = pkg_match.group(1) if pkg_match else "unknown"

        return status

    # -------------------------------------------------------------------------
    # 2. 视觉看屏与 UI 结构解析
    # -------------------------------------------------------------------------

    async def capture_screenshot(self, output_path: str, quality: int = 75) -> Tuple[bool, str]:
        """
        截取手机当前画面并保存到本地 output_path。
        采用管道直接抓取 PNG 字节，并在内存中用 PIL 压缩转为 JPEG，速度极快且节省磁盘。
        """
        cmd = self._build_adb_cmd(["exec-out", "screencap", "-p"])
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            raw_data, stderr = await proc.communicate()
            if proc.returncode != 0 or not raw_data:
                return False, f"screencap 失败: {stderr.decode(errors='replace')}"

            # 转换为 JPG 压缩保存
            image = Image.open(io.BytesIO(raw_data))
            if image.mode in ("RGBA", "P"):
                image = image.convert("RGB")
            
            # 确保父目录存在
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            image.save(output_path, format="JPEG", quality=quality, optimize=True)
            return True, output_path
        except Exception as e:
            logger.error("截图处理异常: %s", e)
            return False, str(e)

    async def dump_ui_elements(self) -> Tuple[bool, List[Dict[str, Any]], str]:
        """
        导出当前屏幕可交互 UI 节点树，提取文字、类名及中心点击坐标。
        """
        # 将 dump 写入手机临时路径并拉取
        remote_xml = "/sdcard/_window_dump.xml"
        ok, out = await self.run_shell(f"uiautomator dump {remote_xml}", timeout=10.0)
        if not ok or "dumped to" not in out:
            # 尝试回退方式
            return False, [], f"uiautomator dump 失败: {out}"

        ok, xml_content = await self.run_shell(f"cat {remote_xml}", timeout=10.0)
        await self.run_shell(f"rm {remote_xml}", timeout=3.0)

        if not ok or not xml_content.startswith("<?xml"):
            return False, [], "获取 UI XML 失败或内容为空"

        try:
            root = ET.fromstring(xml_content)
            elements: List[Dict[str, Any]] = []

            for node in root.iter("node"):
                text = node.attrib.get("text", "").strip()
                desc = node.attrib.get("content-desc", "").strip()
                label = text or desc
                clickable = node.attrib.get("clickable") == "true"
                bounds_str = node.attrib.get("bounds", "")

                # 解析 bounds: [x1,y1][x2,y2]
                match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds_str)
                if match:
                    x1, y1, x2, y2 = map(int, match.groups())
                    cx = (x1 + x2) // 2
                    cy = (y1 + y2) // 2
                    width = x2 - x1
                    height = y2 - y1

                    if (label or clickable) and width > 5 and height > 5:
                        elements.append({
                            "text": label,
                            "type": node.attrib.get("class", "").split(".")[-1],
                            "center": [cx, cy],
                            "bounds": [x1, y1, x2, y2],
                            "clickable": clickable,
                        })

            return True, elements, ""
        except Exception as e:
            return False, [], f"XML 解析失败: {e}"

    async def find_element_by_text(self, target_text: str) -> Optional[Tuple[int, int]]:
        """在当前界面寻找匹配文字的中心坐标"""
        ok, elements, _ = await self.dump_ui_elements()
        if not ok:
            return None

        target = target_text.strip().lower()

        # 1. 优先完全一致匹配
        for el in elements:
            if el["text"].lower() == target:
                return el["center"][0], el["center"][1]

        # 2. 包含匹配
        for el in elements:
            if target in el["text"].lower():
                return el["center"][0], el["center"][1]

        return None

    # -------------------------------------------------------------------------
    # 3. 基础交互动作
    # -------------------------------------------------------------------------

    async def tap(self, x: int, y: int) -> Tuple[bool, str]:
        """模拟点击坐标 (x, y)"""
        ok, err = await self.run_shell(f"input tap {x} {y}")
        return ok, f"点击 ({x}, {y})" if ok else err

    async def tap_text(self, text: str) -> Tuple[bool, str]:
        """智能按界面上的文字寻找元素并点击"""
        coords = await self.find_element_by_text(text)
        if not coords:
            return False, f"未在当前屏幕找到文字包含 '{text}' 的可交互元素"
        x, y = coords
        ok, err = await self.tap(x, y)
        if ok:
            return True, f"成功点击元素 '{text}' ({x}, {y})"
        return False, err

    async def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 300,
    ) -> Tuple[bool, str]:
        """滑动屏幕"""
        ok, err = await self.run_shell(f"input swipe {x1} {y1} {x2} {y2} {duration_ms}")
        return ok, f"从 ({x1},{y1}) 滑动到 ({x2},{y2})" if ok else err

    async def swipe_direction(self, direction: str, distance_ratio: float = 0.5) -> Tuple[bool, str]:
        """按方向滑动（up/down/left/right，默认为上滑浏览下一个页面）"""
        # 默认取标准屏幕参考中点 (540, 1200)
        cx, cy = 540, 1200
        delta = int(800 * distance_ratio)
        direction = direction.lower().strip()

        if direction in ("up", "向上"):
            return await self.swipe(cx, cy + delta // 2, cx, cy - delta // 2, 350)
        elif direction in ("down", "向下"):
            return await self.swipe(cx, cy - delta // 2, cx, cy + delta // 2, 350)
        elif direction in ("left", "向左"):
            return await self.swipe(cx + delta // 2, cy, cx - delta // 2, cy, 350)
        elif direction in ("right", "向右"):
            return await self.swipe(cx - delta // 2, cy, cx + delta // 2, cy, 350)
        else:
            return False, f"不支持的滑动方向: {direction}"

    async def press_key(self, key_name: str) -> Tuple[bool, str]:
        """按下系统按键（back/home/enter/power 等）"""
        key_lower = key_name.lower().strip()
        code = KEY_MAP.get(key_lower)
        if code is None:
            if key_lower.isdigit():
                code = int(key_lower)
            else:
                return False, f"未知的按键名: {key_name} (可选: {list(KEY_MAP.keys())})"

        ok, err = await self.run_shell(f"input keyevent {code}")
        return ok, f"按下按键: {key_name} (code={code})" if ok else err

    async def input_text(self, text: str) -> Tuple[bool, str]:
        """
        向当前焦点输入框输入文本。
        一律采用 ADBKeyboard Base64 广播协议传输，彻底避免 shell 注入和特殊字符转义错误。
        """
        b64_str = base64.b64encode(text.encode("utf-8")).decode("utf-8")
        ok, out = await self.run_shell(f"am broadcast -a ADB_INPUT_B64 --es msg {b64_str}")
        if ok and ("result=0" in out or "Broadcast completed" in out):
            return True, f"已输入文本: {text}"

        # 若未启用 ADBKeyboard，安全过滤后回退到原生 input text
        safe_chars = re.sub(r"[^a-zA-Z0-9_ -]", "", text)
        if safe_chars:
            safe_text = safe_chars.replace(" ", "%s")
            ok2, err2 = await self.run_shell(f"input text {safe_text}")
            if ok2:
                return True, f"已通过基础输入法输入: {safe_chars} (建议手机端启用 ADBKeyboard 支持全字符输入)"

        return False, f"输入失败，手机端请安装并启用 ADBKeyboard 输入法: {out}"

    async def open_app(self, app_name_or_pkg: str) -> Tuple[bool, str]:
        """通过常用名或包名启动 App"""
        target = app_name_or_pkg.strip().lower()
        pkg = APP_PACKAGE_MAP.get(target, app_name_or_pkg.strip())

        # 严格包名校验，杜绝 shell 注入风险
        if not re.match(r"^[a-zA-Z0-9_.]+$", pkg):
            return False, f"非法包名或应用标识: {app_name_or_pkg}"

        # 优先使用 monkey 工具快速调起包名启动入口
        ok, out = await self.run_shell(f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1")
        if ok and "No activities found" not in out:
            return True, f"成功启动应用: {app_name_or_pkg} ({pkg})"

        # 兜底方式：在 Python 侧解析真实入口，避免 shell 嵌套注入
        ok_res, out_res = await self.run_shell(f"cmd package resolve-activity --brief {pkg}")
        if ok_res and "/" in out_res:
            activity = out_res.strip().splitlines()[-1].strip()
            if re.match(r"^[a-zA-Z0-9_./$]+$", activity):
                ok_start, out_start = await self.run_shell(f"am start -n {activity}")
                if ok_start and "Error" not in out_start:
                    return True, f"已拉起应用: {app_name_or_pkg} ({activity})"

        return False, f"无法启动应用 {app_name_or_pkg}: 未找到有效启动入口"

    # -------------------------------------------------------------------------
    # 4. 连招宏执行引擎 (Macro)
    # -------------------------------------------------------------------------

    async def execute_macro(self, actions: List[Dict[str, Any]], repeat: int = 1) -> Tuple[bool, List[str]]:
        """
        一次性连续执行一组动作。
        支持动作类型:
        - {"type": "tap", "x": 100, "y": 200}
        - {"type": "tap_text", "text": "签到"}
        - {"type": "swipe", "direction": "up"} 或 {"type": "swipe", "x1": 500, "y1": 1500, "x2": 500, "y2": 500}
        - {"type": "text", "text": "你好"}
        - {"type": "key", "key": "back"}
        - {"type": "sleep", "ms": 500}
        """
        logs: List[str] = []
        repeat = max(1, min(repeat, 20))  # 安全限制最多循环 20 次

        for r in range(repeat):
            for i, act in enumerate(actions):
                act_type = act.get("type", "").lower()
                if act_type == "tap":
                    ok, msg = await self.tap(int(act["x"]), int(act["y"]))
                elif act_type == "tap_text":
                    ok, msg = await self.tap_text(str(act["text"]))
                elif act_type == "swipe":
                    if "direction" in act:
                        ok, msg = await self.swipe_direction(str(act["direction"]))
                    else:
                        ok, msg = await self.swipe(
                            int(act["x1"]), int(act["y1"]), int(act["x2"]), int(act["y2"]), int(act.get("ms", 300))
                        )
                elif act_type == "text":
                    ok, msg = await self.input_text(str(act["text"]))
                elif act_type == "key":
                    ok, msg = await self.press_key(str(act["key"]))
                elif act_type == "sleep":
                    ms = int(act.get("ms", 500))
                    await asyncio.sleep(min(ms, 5000) / 1000.0)
                    ok, msg = True, f"等待 {ms}ms"
                else:
                    ok, msg = False, f"未知的宏动作类型: {act_type}"

                logs.append(f"[R{r+1}-Step{i+1}] {msg}")
                # 默认动作间微小延迟 300ms
                await asyncio.sleep(0.3)

        return True, logs

"""手机录屏与视频抽帧模块 (ADB screenrecord + FFmpeg)

实现：
1. 手机端调用 screenrecord 进行静默录屏
2. 将录制视频高速拉取至本地 runtime 目录
3. 调用本地 ffmpeg 提取等间距关键帧图片，供视觉理解或发送至聊天
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from typing import List, Tuple
from .adb_engine import AdbEngine

logger = logging.getLogger("plugin.phone_controller.recorder")


class ScreenRecorder:
    """录屏与视频抽帧处理器"""

    def __init__(self, adb: AdbEngine, ffmpeg_path: str = "ffmpeg"):
        self.adb = adb
        self.ffmpeg_path = ffmpeg_path

    async def record_and_extract_frames(
        self,
        duration_seconds: int = 5,
        frame_count: int = 4,
        output_dir: str = "/tmp/phone_record",
    ) -> Tuple[bool, List[str], str]:
        """
        录制手机屏幕指定秒数，并提取指定数量的关键帧图片。

        :param duration_seconds: 录屏秒数 (2~30)
        :param frame_count: 抽取的关键帧数量 (1~12)
        :param output_dir: 本地输出目录
        :return: (成功与否, 关键帧图片绝对路径列表, 错误或状态信息)
        """
        # 0. 环境预检
        if not shutil.which(self.ffmpeg_path):
            return (
                False,
                [],
                f"系统未检测到 ffmpeg 工具 ('{self.ffmpeg_path}')，请在服务器安装 ffmpeg (如 apt install ffmpeg) 后再使用录屏抽帧功能",
            )

        duration = max(2, min(duration_seconds, 30))
        frame_count = max(1, min(frame_count, 12))
        os.makedirs(output_dir, exist_ok=True)

        remote_mp4 = "/sdcard/_screen_rec_tmp.mp4"
        local_mp4 = os.path.join(output_dir, "rec.mp4")

        # 1. 触发手机录屏 (screenrecord 会在 time-limit 秒后自动停止)
        logger.info("开始录屏 %s 秒: %s", duration, remote_mp4)
        ok, out = await self.adb.run_shell(
            f"screenrecord --time-limit {duration} --bit-rate 4000000 {remote_mp4}",
            timeout=duration + 10.0,
        )

        # 2. 拉取视频文件到本地
        pull_cmd = ["pull", remote_mp4, local_mp4]
        pull_ok, pull_out = await self.adb.run_cmd(pull_cmd, timeout=30.0)
        # 清理手机端临时文件
        await self.adb.run_shell(f"rm -f {remote_mp4}", timeout=5.0)

        if not pull_ok or not os.path.exists(local_mp4) or os.path.getsize(local_mp4) == 0:
            return False, [], f"录屏文件拉取失败: {pull_out}"

        # 3. 计算抽帧 fps 并调用 ffmpeg 抽取关键帧
        fps = frame_count / float(duration)
        frame_pattern = os.path.join(output_dir, "frame_%02d.jpg")

        ffmpeg_cmd = [
            self.ffmpeg_path,
            "-y",
            "-hide_banner",
            "-loglevel", "error",
            "-i", local_mp4,
            "-vf", f"fps={fps:.4f},scale='min(720,iw)':-2",
            "-frames:v", str(frame_count),
            frame_pattern,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *ffmpeg_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
            if proc.returncode != 0:
                return False, [], f"ffmpeg 抽帧失败: {stderr.decode(errors='replace')}"

            # 收集提取的关键帧图片
            frames: List[str] = []
            for f in sorted(os.listdir(output_dir)):
                if f.startswith("frame_") and f.endswith(".jpg"):
                    frames.append(os.path.join(output_dir, f))

            # 抽帧完成后清理本地 mp4，避免长期占用磁盘空间
            try:
                if os.path.exists(local_mp4):
                    os.remove(local_mp4)
            except OSError:
                pass

            if not frames:
                return False, [], "抽帧未生成任何图片"

            return True, frames, f"成功录制 {duration} 秒并抽取 {len(frames)} 张关键帧图片"
        except Exception as e:
            return False, [], f"视频抽帧处理异常: {e}"

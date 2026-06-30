#!/usr/bin/env python3
"""
Agnes Video MCP Server
通过 MCP 协议调用 Agnes Video V2.0 模型生成视频（异步任务）。
API: POST https://apihub.agnes-ai.com/v1/videos (创建)
     GET https://apihub.agnes-ai.com/agnesapi?video_id=xxx (获取结果)
"""

import os
import time
import asyncio
from pathlib import Path
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# ──────── 配置 ────────
AGNES_API_KEY = os.environ.get("AGNES_API_KEY", "")
CREATE_URL = "https://apihub.agnes-ai.com/v1/videos"
RESULT_URL = "https://apihub.agnes-ai.com/agnesapi"
DEFAULT_MODEL = "agnes-video-v2.0"
OUTPUT_DIR = Path("generated-videos")
POLL_INTERVAL = 10  # 轮询间隔（秒）
MAX_WAIT = 600  # 最大等待时间（秒）

_client: httpx.AsyncClient | None = None

app = Server("agnes-video")


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0))
    return _client


# ──────── 核心 API ────────
async def create_video_task(
    api_key: str,
    prompt: str,
    image_url: str = "",
    image_urls: list[str] | None = None,
    mode: str = "",
    width: int = 1152,
    height: int = 768,
    num_frames: int = 121,
    frame_rate: int = 24,
    negative_prompt: str = "",
    seed: int | None = None,
) -> dict:
    body: dict[str, Any] = {
        "model": DEFAULT_MODEL,
        "prompt": prompt,
        "width": width,
        "height": height,
        "num_frames": num_frames,
        "frame_rate": frame_rate,
    }

    if image_url and not image_urls:
        body["image"] = image_url
    elif image_urls:
        body["extra_body"] = {"image": image_urls}
        if mode:
            body["extra_body"]["mode"] = mode

    if mode and not image_urls:
        body["mode"] = mode

    if negative_prompt:
        body["negative_prompt"] = negative_prompt
    if seed is not None:
        body["seed"] = seed

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    client = get_client()
    try:
        resp = await client.post(CREATE_URL, headers=headers, json=body)
    except httpx.TimeoutException:
        raise RuntimeError("创建视频任务超时（连接或响应超时），请稍后重试")
    except httpx.RequestError as e:
        raise RuntimeError(f"创建视频任务网络错误: {e}")

    if resp.status_code == 429:
        raise RuntimeError(f"视频生成速率限制（每分钟1次）。请等待一分钟后重试。详细信息: {resp.text}")
    if resp.status_code != 200:
        raise RuntimeError(f"创建任务失败 (HTTP {resp.status_code}): {resp.text}")
    return resp.json()


async def get_video_result(api_key: str, video_id: str) -> dict:
    headers = {"Authorization": f"Bearer {api_key}"}
    client = get_client()
    resp = await client.get(f"{RESULT_URL}?video_id={video_id}", headers=headers)
    if resp.status_code != 200:
        raise RuntimeError(f"查询视频失败 (HTTP {resp.status_code}): {resp.text}")
    return resp.json()


async def download_video(url: str, filepath: Path) -> Path:
    client = get_client()
    resp = await client.get(url)
    if resp.status_code != 200:
        raise RuntimeError(f"下载视频失败 (HTTP {resp.status_code})")
    filepath.write_bytes(resp.content)
    return filepath


async def poll_until_done(api_key: str, video_id: str) -> dict:
    elapsed = 0
    last_progress = -1
    while elapsed < MAX_WAIT:
        result = await get_video_result(api_key, video_id)
        status = result.get("status", "unknown")
        progress = result.get("progress", 0)

        if progress != last_progress:
            last_progress = progress

        if status == "completed":
            return result
        if status == "failed":
            error = result.get("error", {})
            raise RuntimeError(f"视频生成失败: {error}")

        await asyncio.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

    raise TimeoutError(f"视频生成超时 (已等待 {MAX_WAIT} 秒)")


# ──────── MCP 工具 ────────
@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="generate_video",
            description=(
                "使用 Agnes Video V2.0 模型生成视频（异步任务，自动轮询等待完成）。"
                "支持文生视频、图生视频、多图视频和关键帧动画。"
                "返回下载到本地的视频文件路径。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "视频内容的文本描述。推荐结构: [主体] + [动作] + [场景] + [镜头运动] + [光线] + [风格]",
                    },
                    "image_url": {
                        "type": "string",
                        "description": "图生视频模式下的输入图片 URL（公开可访问）。",
                    },
                    "image_urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "多图视频/关键帧模式的输入图片 URL 数组。提供此参数即进入多图模式。",
                    },
                    "mode": {
                        "type": "string",
                        "description": "生成模式。多图+关键帧过渡用 'keyframes'，普通图生视频用 'ti2vid'。",
                    },
                    "width": {
                        "type": "integer",
                        "description": "视频宽度，默认 1152。支持标准分辨率映射 (480p/720p/1080p)。",
                        "default": 1152,
                    },
                    "height": {
                        "type": "integer",
                        "description": "视频高度，默认 768。",
                        "default": 768,
                    },
                    "num_frames": {
                        "type": "integer",
                        "description": "视频帧数，必须 ≤441 且遵循 8n+1 规则。默认 121（约5秒@24fps）。",
                        "default": 121,
                    },
                    "frame_rate": {
                        "type": "integer",
                        "description": "帧率 (1-60)，默认 24。",
                        "default": 24,
                    },
                    "negative_prompt": {
                        "type": "string",
                        "description": "反向提示词，描述需要避免的内容。",
                    },
                    "seed": {
                        "type": "integer",
                        "description": "随机种子，用于可复现结果。",
                    },
                    "api_key": {
                        "type": "string",
                        "description": "Agnes API Key。如不传入则使用环境变量 AGNES_API_KEY。",
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "视频输出目录路径，默认 generated-videos/",
                    },
                },
                "required": ["prompt"],
            },
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name != "generate_video":
        raise ValueError(f"未知工具: {name}")

    prompt = arguments["prompt"]
    api_key = arguments.get("api_key", "") or AGNES_API_KEY
    if not api_key:
        return [TextContent(type="text", text="❌ 未提供 API Key。请设置 AGNES_API_KEY 环境变量或通过 api_key 参数传入。")]

    image_url = arguments.get("image_url", "")
    image_urls = arguments.get("image_urls")
    mode = arguments.get("mode", "")
    width = arguments.get("width", 1152)
    height = arguments.get("height", 768)
    num_frames = arguments.get("num_frames", 121)
    frame_rate = arguments.get("frame_rate", 24)
    negative_prompt = arguments.get("negative_prompt", "")
    seed = arguments.get("seed")
    output_dir = arguments.get("output_dir", "")

    global OUTPUT_DIR
    if output_dir:
        OUTPUT_DIR = Path(output_dir)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        # 1. 创建任务
        task = await create_video_task(
            api_key=api_key,
            prompt=prompt,
            image_url=image_url,
            image_urls=image_urls,
            mode=mode,
            width=width,
            height=height,
            num_frames=num_frames,
            frame_rate=frame_rate,
            negative_prompt=negative_prompt,
            seed=seed,
        )
        video_id = task["video_id"]
        seconds = task.get("seconds", "?")
        size = task.get("size", "?")

        # 2. 轮询直到完成
        result = await poll_until_done(api_key, video_id)
        video_url = result.get("remixed_from_video_id")

        if not video_url:
            return [TextContent(type="text", text="❌ 视频生成完成但未获取到下载链接。")]

        # 3. 下载视频
        safe_name = "".join(c if c.isalnum() or c in (" ", "-", "_") else "_" for c in prompt[:30]).strip()
        filename = f"{safe_name}_{int(time.time())}.mp4"
        filepath = OUTPUT_DIR / filename
        await download_video(video_url, filepath)

        mode_label = "多图/关键帧" if image_urls else ("图生视频" if image_url else "文生视频")
        return [
            TextContent(
                type="text",
                text=(
                    f"🎬 {mode_label}完成！\n"
                    f"📁 保存路径: {filepath}\n"
                    f"⏱ 视频时长: {seconds} 秒\n"
                    f"📐 分辨率: {size}\n"
                    f"🎞 帧数: {num_frames} frames @ {frame_rate} fps\n"
                    f"🤖 模型: {DEFAULT_MODEL}"
                ),
            )
        ]

    except httpx.TimeoutException:
        return [TextContent(type="text", text="❌ 请求超时。Agnes 视频 API 响应较慢，请稍后重试。")]
    except RuntimeError as e:
        return [TextContent(type="text", text=f"❌ {e}")]
    except Exception as e:
        return [TextContent(type="text", text=f"❌ 未知错误: {type(e).__name__}: {e}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())

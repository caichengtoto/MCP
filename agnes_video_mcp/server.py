#!/usr/bin/env python3
"""
Agnes Video MCP Server (Async Split Design)
拆分异步流程为两个工具，避免 MCP 客户端超时：
  create_video — 创建任务，立即返回 video_id
  check_video  — 查询状态，完成时下载视频
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

AGNES_API_KEY = os.environ.get("AGNES_API_KEY", "")
CREATE_URL = "https://apihub.agnes-ai.com/v1/videos"
RESULT_URL = "https://apihub.agnes-ai.com/agnesapi"
DEFAULT_MODEL = "agnes-video-v2.0"
OUTPUT_DIR = Path("generated-videos")

_client: httpx.AsyncClient | None = None

app = Server("agnes-video")


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0))
    return _client


async def _build_body(arguments: dict) -> dict:
    body: dict[str, Any] = {
        "model": DEFAULT_MODEL,
        "prompt": arguments["prompt"],
        "width": arguments.get("width", 1152),
        "height": arguments.get("height", 768),
        "num_frames": arguments.get("num_frames", 121),
        "frame_rate": arguments.get("frame_rate", 24),
    }
    image_url = arguments.get("image_url", "")
    image_urls = arguments.get("image_urls")
    if image_url and not image_urls:
        body["image"] = image_url
    elif image_urls:
        body["extra_body"] = {"image": image_urls}
        if arguments.get("mode"):
            body["extra_body"]["mode"] = arguments["mode"]
    if arguments.get("mode") and not image_urls:
        body["mode"] = arguments["mode"]
    if arguments.get("negative_prompt"):
        body["negative_prompt"] = arguments["negative_prompt"]
    if arguments.get("seed") is not None:
        body["seed"] = arguments["seed"]
    return body


async def _call_api(api_key: str, body: dict) -> dict:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    client = get_client()
    try:
        resp = await client.post(CREATE_URL, headers=headers, json=body)
    except httpx.TimeoutException:
        raise RuntimeError("创建视频任务超时，请稍后重试")
    except httpx.RequestError as e:
        raise RuntimeError(f"网络错误: {e}")
    if resp.status_code == 429:
        raise RuntimeError("速率限制（每分钟1次），请等待一分钟后重试")
    if resp.status_code != 200:
        raise RuntimeError(f"API 错误 (HTTP {resp.status_code}): {resp.text}")
    return resp.json()


# ──────── 工具列表 ────────
@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="create_video",
            description="创建 Agnes 视频生成任务，立即返回 video_id。拿到 ID 后用 check_video 查询进度。",
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "视频英文描述"},
                    "image_url": {"type": "string", "description": "图生视频的图片 URL"},
                    "image_urls": {"type": "array", "items": {"type": "string"}, "description": "多图模式 URL 数组"},
                    "mode": {"type": "string", "description": "keyframes / ti2vid"},
                    "width": {"type": "integer", "default": 1152},
                    "height": {"type": "integer", "default": 768},
                    "num_frames": {"type": "integer", "default": 121, "description": "≤441, 8n+1"},
                    "frame_rate": {"type": "integer", "default": 24},
                    "negative_prompt": {"type": "string"},
                    "seed": {"type": "integer"},
                    "api_key": {"type": "string"},
                },
                "required": ["prompt"],
            },
        ),
        Tool(
            name="check_video",
            description="查询视频任务状态。如果已完成则自动下载并返回本地路径。需要每 10-15 秒轮询一次。",
            inputSchema={
                "type": "object",
                "properties": {
                    "video_id": {"type": "string", "description": "create_video 返回的 video_id"},
                    "api_key": {"type": "string"},
                    "output_dir": {"type": "string"},
                },
                "required": ["video_id"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    api_key = arguments.get("api_key", "") or AGNES_API_KEY
    if not api_key:
        return [TextContent(type="text", text="❌ 未提供 API Key")]

    try:
        if name == "create_video":
            body = await _build_body(arguments)
            task = await _call_api(api_key, body)
            video_id = task["video_id"]
            seconds = task.get("seconds", "?")
            size = task.get("size", "?")
            status = task.get("status", "?")
            return [
                TextContent(
                    type="text",
                    text=(
                        f"✅ 视频任务已创建\n"
                        f"🎬 video_id: {video_id}\n"
                        f"📊 状态: {status}\n"
                        f"⏱ 预计时长: {seconds} 秒\n"
                        f"📐 分辨率: {size}\n"
                        f"\n⏳ 请等待 30-60 秒后用 check_video 查询进度。"
                    ),
                )
            ]

        elif name == "check_video":
            video_id = arguments["video_id"]
            output_dir = arguments.get("output_dir", "")
            global OUTPUT_DIR
            if output_dir:
                OUTPUT_DIR = Path(output_dir)
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

            headers = {"Authorization": f"Bearer {api_key}"}
            client = get_client()
            resp = await client.get(f"{RESULT_URL}?video_id={video_id}", headers=headers)
            if resp.status_code != 200:
                return [TextContent(type="text", text=f"❌ 查询失败 (HTTP {resp.status_code}): {resp.text}")]
            result = resp.json()
            status = result.get("status", "unknown")
            progress = result.get("progress", 0)

            if status == "completed":
                video_url = result.get("remixed_from_video_id")
                if not video_url:
                    return [TextContent(type="text", text="❌ 任务完成但无下载链接")]
                dl_resp = await client.get(video_url)
                if dl_resp.status_code != 200:
                    return [TextContent(type="text", text=f"❌ 下载失败 (HTTP {dl_resp.status_code})")]
                filename = f"video_{video_id[:12]}_{int(time.time())}.mp4"
                filepath = OUTPUT_DIR / filename
                filepath.write_bytes(dl_resp.content)
                return [
                    TextContent(
                        type="text",
                        text=(
                            f"🎬 视频生成完成！\n"
                            f"📁 路径: {filepath}\n"
                            f"⏱ 时长: {result.get('seconds', '?')} 秒\n"
                            f"📐 分辨率: {result.get('size', '?')}"
                        ),
                    )
                ]
            elif status == "failed":
                return [TextContent(type="text", text=f"❌ 任务失败: {result.get('error', {})}")]
            else:
                return [
                    TextContent(
                        type="text",
                        text=f"⏳ 状态: {status} | 进度: {progress}% | video_id: {video_id}\n请 10-15 秒后再查询。",
                    )
                ]

        else:
            return [TextContent(type="text", text=f"❌ 未知工具: {name}")]

    except RuntimeError as e:
        return [TextContent(type="text", text=f"❌ {e}")]
    except Exception as e:
        return [TextContent(type="text", text=f"❌ 错误: {type(e).__name__}: {e}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())

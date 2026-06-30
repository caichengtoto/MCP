#!/usr/bin/env python3
"""
Agnes Image MCP Server
通过 MCP 协议调用 Agnes Image API 生成图片。
模型: agnes-image-2.1-flash
API: POST https://apihub.agnes-ai.com/v1/images/generations
"""

import os
import json
import asyncio
from pathlib import Path
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent


# ──────── 配置 ────────
AGNES_API_KEY = os.environ.get("AGNES_API_KEY", "")
AGNES_BASE_URL = "https://apihub.agnes-ai.com/v1/images/generations"
DEFAULT_MODEL = "agnes-image-2.1-flash"
DEFAULT_SIZE = "1024x1024"
OUTPUT_DIR = Path(os.environ.get("AGNES_OUTPUT_DIR", "generated-images"))

# HTTP 客户端（连接池复用）
_client: httpx.AsyncClient | None = None

app = Server("agnes-image")


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(300.0))
    return _client


# ──────── 核心 API 调用 ────────
async def call_agnes_api(
    prompt: str,
    size: str = DEFAULT_SIZE,
    model: str = DEFAULT_MODEL,
    api_key: str = "",
    image_urls: list[str] | None = None,
    return_base64: bool = False,
) -> dict[str, Any]:
    """调用 Agnes Image API 生成图片"""
    if not api_key and not AGNES_API_KEY:
        raise ValueError("未提供 API Key，请设置 AGNES_API_KEY 环境变量或通过参数传入")

    key = api_key or AGNES_API_KEY

    body: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "size": size,
    }

    if image_urls:
        # 图生图模式 — 图片必须放在 extra_body.image 中
        body["extra_body"] = {
            "image": image_urls,
            "response_format": "b64_json" if return_base64 else "url",
        }
    elif return_base64:
        # 文生图 Base64 输出 — 用 return_base64 参数
        body["return_base64"] = True
    else:
        # 文生图 URL 输出 — response_format 放在 extra_body
        body["extra_body"] = {"response_format": "url"}

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    client = get_client()
    response = await client.post(AGNES_BASE_URL, headers=headers, json=body)

    if response.status_code != 200:
        error_detail = response.text
        raise RuntimeError(
            f"Agnes API 返回错误 (HTTP {response.status_code}): {error_detail}"
        )

    return response.json()


# ──────── 结果保存 ────────
async def save_image(result: dict[str, Any], prompt: str) -> str:
    """将 API 返回的图片保存到本地文件"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    data = result.get("data", [])
    if not data:
        raise ValueError("API 返回数据为空，没有生成图片")

    item = data[0]
    url = item.get("url")
    b64_json = item.get("b64_json")

    # 用 prompt 前 30 个字符做文件名
    safe_name = "".join(c if c.isalnum() or c in (" ", "-", "_") else "_" for c in prompt[:30]).strip()
    if not safe_name:
        safe_name = "generated"

    # 去重：加上时间戳
    import time
    timestamp = int(time.time())
    filename = f"{safe_name}_{timestamp}.png"
    filepath = OUTPUT_DIR / filename

    if url:
        # 从 URL 下载图片
        client = get_client()
        img_resp = await client.get(url)
        if img_resp.status_code != 200:
            raise RuntimeError(f"下载图片失败 (HTTP {img_resp.status_code})")
        filepath.write_bytes(img_resp.content)

    elif b64_json:
        import base64
        filepath.write_bytes(base64.b64decode(b64_json))

    else:
        raise ValueError("API 返回既无 url 也无 b64_json")

    return str(filepath.absolute())


# ──────── MCP 工具定义 ────────
@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="generate_image",
            description=(
                "使用 Agnes Image 2.1 Flash 模型生成图片。"
                "支持文生图（Text-to-Image）和图生图（Image-to-Image）。"
                "每次生成一张图片，返回保存到本地的文件路径。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": (
                            "图片生成的文本提示词。"
                            "文生图推荐结构: [主体] + [场景/环境] + [风格] + [光照] + [构图] + [质量要求]。"
                            "图生图推荐结构: [改变要求] + [新风格/场景] + [需添加或移除的元素] + [需保留的元素]。"
                        ),
                    },
                    "size": {
                        "type": "string",
                        "description": "输出图片尺寸，例如 1024x1024、1024x768、768x1024。默认 1024x1024。",
                        "default": DEFAULT_SIZE,
                    },
                    "model": {
                        "type": "string",
                        "description": "模型名称，默认 agnes-image-2.1-flash",
                        "default": DEFAULT_MODEL,
                    },
                    "api_key": {
                        "type": "string",
                        "description": "Agnes API Key。如不传入，则使用环境变量 AGNES_API_KEY。",
                    },
                    "image_url": {
                        "type": "string",
                        "description": "图生图模式下输入图片的 URL（公开可访问），提供此参数即进入图生图模式。",
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "图片输出目录路径，默认 generated-images/",
                    },
                },
                "required": ["prompt"],
            },
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name != "generate_image":
        raise ValueError(f"未知工具: {name}")

    prompt = arguments["prompt"]
    size = arguments.get("size", DEFAULT_SIZE)
    model = arguments.get("model", DEFAULT_MODEL)
    api_key = arguments.get("api_key", "")
    image_url = arguments.get("image_url", "")
    output_dir = arguments.get("output_dir", "")

    # 设置输出目录
    global OUTPUT_DIR
    if output_dir:
        OUTPUT_DIR = Path(output_dir)

    try:
        # 判断是否为图生图模式
        is_img2img = bool(image_url)
        mode_label = "图生图" if is_img2img else "文生图"

        # 调用 API
        result = await call_agnes_api(
            prompt=prompt,
            size=size,
            model=model,
            api_key=api_key,
            image_urls=[image_url] if is_img2img else None,
        )

        # 保存图片
        filepath = await save_image(result, prompt)

        # 提取响应信息
        data = result.get("data", [{}])[0]
        revised = data.get("revised_prompt")

        info_parts = [
            f"🎨 {mode_label}完成！",
            f"📁 保存路径: {filepath}",
            f"📐 尺寸: {size}",
            f"🤖 模型: {model}",
        ]
        if revised:
            info_parts.append(f"📝 修订提示词: {revised}")

        return [TextContent(type="text", text="\n".join(info_parts))]

    except Exception as e:
        return [TextContent(type="text", text=f"❌ 生成失败: {e}")]


# ──────── 入口 ────────
async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())

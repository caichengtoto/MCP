#!/usr/bin/env python3
"""测试 Agnes Image API 直接调用"""
import asyncio
import json
from pathlib import Path

import httpx

import os
API_KEY = os.environ.get("AGNES_API_KEY", "")
if not API_KEY:
    raise RuntimeError("请设置 AGNES_API_KEY 环境变量")
URL = "https://apihub.agnes-ai.com/v1/images/generations"
OUTPUT_DIR = Path("C:/Users/CC/WorkBuddy/2026-06-05-22-37-37/generated-images")

PROMPT = "A simple and cute anime girl character design, minimalist style, clean lines, soft pastel colors, big round eyes, gentle smile, long flowing hair, school uniform, white background, full body character sheet, flat illustration style, high quality"

async def main():
    body = {
        "model": "agnes-image-2.1-flash",
        "prompt": PROMPT,
        "size": "1024x1024",
        "extra_body": {"response_format": "url"}
    }
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=300.0) as client:
        print("正在调用 Agnes Image API...")
        resp = await client.post(URL, headers=headers, json=body)
        print(f"状态码: {resp.status_code}")
        print(f"响应: {resp.text[:500]}")

        if resp.status_code != 200:
            raise RuntimeError(f"API 调用失败: {resp.text}")

        result = resp.json()
        img_url = result["data"][0]["url"]
        print(f"图片 URL: {img_url}")

        img_resp = await client.get(img_url)
        if img_resp.status_code != 200:
            raise RuntimeError(f"图片下载失败: {img_resp.status_code}")

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        filepath = OUTPUT_DIR / "agnes_image_test.png"
        filepath.write_bytes(img_resp.content)
        print(f"图片已保存: {filepath}")


if __name__ == "__main__":
    asyncio.run(main())

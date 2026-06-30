#!/usr/bin/env python3
"""通过 stdio 协议测试 Agnes Image MCP Server"""
import asyncio
import json
import os
import subprocess
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    server_params = StdioServerParameters(
        command="C:\\Users\\CC\\.workbuddy\\mcp-servers\\agnes-image-mcp\\venv\\Scripts\\python.exe",
        args=["C:\\Users\\CC\\.workbuddy\\mcp-servers\\agnes-image-mcp\\server.py"],
        env={"AGNES_API_KEY": os.environ.get("AGNES_API_KEY", "")},
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print(f"可用工具: {[t.name for t in tools.tools]}")

            result = await session.call_tool(
                "generate_image",
                {
                    "prompt": "A simple and cute anime girl character, minimalist style, soft pastel colors, big round eyes, white background, character design",
                    "size": "1024x1024",
                },
            )
            print("MCP 工具调用结果:")
            for content in result.content:
                print(content.text)


if __name__ == "__main__":
    asyncio.run(main())

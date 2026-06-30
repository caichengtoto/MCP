# Agnes Image MCP Server

通过 MCP 协议调用 [Agnes AI](https://agnes-ai.com) 的图像生成模型，在 WorkBuddy 等支持 MCP 的客户端中直接生成图片。

## 功能

- ✅ 文生图（Text-to-Image）
- ✅ 图生图（Image-to-Image）
- ✅ 自动下载并保存图片到本地
- ✅ 支持自定义尺寸和模型参数

## 默认模型

- `agnes-image-2.1-flash`

## 安装

### 1. 克隆仓库

```bash
git clone https://github.com/caichengtoto/MCP.git
cd MCP
```

### 2. 创建虚拟环境

```bash
python -m venv venv
```

### 3. 安装依赖

```bash
venv\Scripts\pip install mcp httpx
```

### 4. 配置环境变量

```bash
set AGNES_API_KEY=your_api_key_here
```

## 在 WorkBuddy 中使用

在 `~/.workbuddy/mcp.json` 中添加：

```json
{
  "mcpServers": {
    "agnes-image": {
      "command": "C:\\Users\\CC\\.workbuddy\\mcp-servers\\agnes_image_mcp\\venv\\Scripts\\python.exe",
      "args": ["C:\\Users\\CC\\.workbuddy\\mcp-servers\\agnes_image_mcp\\server.py"],
      "env": {
        "AGNES_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

然后在 WorkBuddy 连接器管理页中信任 `agnes-image` 即可。

## 工具参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `prompt` | 是 | 图片生成描述（建议英文） |
| `size` | 否 | 默认 `1024x1024` |
| `model` | 否 | 默认 `agnes-image-2.1-flash` |
| `image_url` | 否 | 图生图模式输入图片 URL |
| `output_dir` | 否 | 输出目录，默认 `generated-images/` |

## 项目结构

```
.
├── server.py      # MCP Server 主程序
├── test_api.py    # API 直接调用测试
├── test_mcp.py    # MCP stdio 协议测试
└── .gitignore
```

## 许可证

MIT

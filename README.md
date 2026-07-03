# 📺 bilibili-up-digest

B站UP主视频智能摘要工具 —— 输入UP主名字，自动抓取其所有投稿视频，AI智能概括内容并给出观看建议。

## 为什么需要这个工具？

B站很多视频10-30分钟，看完才知道值不值。这个工具帮你：

1. **快速扫描** UP主的所有投稿
2. **了解核心内容** —— 不用点开视频就知道讲了什么  
3. **判断是否值得看** —— 按「强烈推荐 → 可跳过」四级评级

## 功能

- 🔍 输入UP主名字，自动搜索并确认身份
- 📥 批量获取UP主全部投稿视频（标题、简介、播放量、时长等）
- 🤖 AI智能概括每个视频：主题、内容摘要、亮点、受众、推荐度
- 📊 按推荐度排序输出，一眼看出哪些值得看
- 📁 同时输出 Markdown + JSON 双格式报告
- 🚫 支持无AI模式（纯规则推断，也能用）

## 快速开始

```bash
# 1. 克隆
git clone https://github.com/YYYcjj/bilibili-up-digest.git
cd bilibili-up-digest

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置LLM API
cp .env.example .env
# 编辑 .env，填入你的 API Key

# 4. 运行
python digest.py --up "影视飓风"
```

## 使用示例

```bash
# 基础用法：AI概括影视飓风所有视频
python digest.py --up "影视飓风"

# 只抓前3页（150个视频）
python digest.py --up "影视飓风" --pages 3

# 不用AI，快速规则概括
python digest.py --up "影视飓风" --no-ai

# 指定模型
python digest.py --up "影视飓风" --model deepseek-chat

# 按播放量排序
python digest.py --up "影视飓风" --sort-by views

# 直接指定UID（跳过搜索）
python digest.py --up "影视飓风" --mid 946974

# JSON格式输出
python digest.py --up "影视飓风" --output json
```

## 输出报告示例

```
📺 影视飓风 | 共 156 个视频

## ⭐ 强烈推荐
### [科技] 我用AI做了一个能自动剪辑的视频工具
> 📅 2025-12-03 | ⏱ 18:32 | 👁 2,345,678 | 👍 123,456
> 介绍了用大模型+传统CV结合的自动剪辑工具开发过程，从需求分析
> 到技术选型再到落地实现，干货极多。核心观点：AI不会替代剪辑师，
> 但会淘汰不会用AI的剪辑师。
>   • 完整的工具开发流程拆解
>   • AI与传统CV的混合架构设计
>   • 剪辑行业AI化趋势判断
> 🎯 创作者/开发者 | 📌 AI+创作，信息密度极高
> 🔗 https://www.bilibili.com/video/BV1xx411c7mD
```

## LLM API 配置

支持所有 OpenAI 兼容接口：

| 服务 | LLM_API_BASE | LLM_MODEL |
|------|-------------|-----------|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| Moonshot | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-turbo` |
| SiliconFlow | `https://api.siliconflow.cn/v1` | `Qwen/Qwen2.5-7B-Instruct` |

编辑 `.env` 文件填入对应信息即可。

## 推荐度说明

| 评级 | 含义 | 判断标准 |
|------|------|---------|
| ⭐ 强烈推荐 | 必看 | 干货极多、内容独特、信息密度高 |
| 👍 推荐 | 值得看 | 内容有价值，相关知识增量明显 |
| 💡 可选 | 可看可不看 | 内容尚可但信息密度一般 |
| ⏭️ 可跳过 | 不用看 | 水视频、广告、内容重复 |

## 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--up` / `-u` | UP主名字（必填） | - |
| `--mid` | 直接指定UID，跳过搜索 | - |
| `--pages` / `-p` | 最大抓取页数（每页50个） | 20 |
| `--no-ai` | 不使用AI，仅规则推断 | false |
| `--model` | 指定LLM模型 | 读取.env |
| `--output` / `-o` | 输出格式 markdown/json/text | markdown |
| `--sort-by` | 排序 recommendation/date/views | recommendation |

## 项目结构

```
bilibili-up-digest/
├── bilibili.py       # B站API封装（搜索、视频列表、WBI签名）
├── summarizer.py     # AI概括模块（LLM调用 + 规则降级）
├── digest.py         # 主入口（编排流程）
├── requirements.txt  # Python依赖
├── .env.example      # 环境变量模板
└── output/           # 输出报告目录
```

## 技术说明

- **B站API**: 使用公开接口 + WBI签名，无需登录
- **速率控制**: 请求间自动间隔，避免触发反爬
- **降级策略**: AI不可用时自动切换规则概括
- **无依赖浏览器**: 纯HTTP请求，轻量快速

## 参考项目

- [bilibili-summary](https://github.com/ET06731/bilibili-summary) - B站视频AI摘要
- [bilibili-API-collect](https://github.com/SocialSisterYi/bilibili-API-collect) - B站API文档收集（已停更）

## License

MIT

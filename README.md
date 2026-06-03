# Earnings Season Workflow

财报季自动化：把券商研报 PDF 自动转成**投资社区中文简报 + 英文海报 + 中文海报**，合并推送到飞书群。

## 模块

| 文件 | 职责 |
|------|------|
| `fetch_prices.py` | Tiger 实时行情 → `market_data.json` |
| `preprocess_pdfs.py` | PDF 文本提取（PDF 损坏时按需） |
| `run_workflow.py` | 调 Claude 生成中文 brief |
| `generate_posters.py` | 生成英文/中文海报、合成水印、推送飞书 |
| `push_feishu.py` | 飞书 token / 卡片构建 / 图片上传 |

## 快速开始

```bash
# 1. 配置环境变量（见 EARNINGS_SEASON.md）
export ANTHROPIC_AUTH_TOKEN=...   # 或 ANTHROPIC_API_KEY
export FEISHU_APP_SECRET=...
export FEISHU_WEBHOOK=...

# 2. 研报 PDF 放入 研报input/，拉取行情
python3 fetch_prices.py APP NVDA COST ...

# 3. 生成 brief
python3 run_workflow.py

# 4. 生成海报并推送
python3 generate_posters.py --push
```

详细使用手册见 [EARNINGS_SEASON.md](EARNINGS_SEASON.md)，工具拆解见 [workflow_tools.md](workflow_tools.md)，AI 工作规则见 [CLAUDE.md](CLAUDE.md)。

## 说明

- 所有密钥通过环境变量注入，仓库内不含任何真实凭证。
- `研报input/`、`海报/`、`output/` 为数据与产物目录，已在 `.gitignore` 中排除。

# CLAUDE.md — Earnings Season Workflow

财报季：把券商研报自动转成**投资社区中文简报 + 英文海报 + 中文海报**，合并推送到飞书群。

> 详细使用手册见 [EARNINGS_SEASON.md](EARNINGS_SEASON.md)；工具/步骤拆解见 [workflow_tools.md](workflow_tools.md)；历史决策与故障复盘见 [memory.md](memory.md)。本文件只列给 AI 的工作规则,不重复手册细节。

## 模块职责

| 文件 | 职责 |
|------|------|
| `fetch_prices.py` | Tiger 实时行情 → `market_data.json` |
| `preprocess_pdfs.py` | PDF 文本提取 → `研报input/.cache/`(仅当 PDF 损坏时按需) |
| `run_workflow.py` | 调 Claude 生成中文 brief → `output/{date}_briefs.md` |
| `generate_posters.py` | 生成英文+中文海报、合成水印、推送飞书 |
| `push_feishu.py` | 飞书 token / 卡片构建 / 图片上传 |

## 标准流程(每个交易日)

1. 研报 PDF 放入 `研报input/`(文件名随意,可中文)
2. `python3 fetch_prices.py APP NVDA COST ...` —— **必须手动指定 ticker**
3. `python3 run_workflow.py` —— 生成 brief 到 `output/`
4. `source ~/.zshrc && python3 generate_posters.py --push` —— 生成海报并推送

## 强制规则(不要违反)

- **必须手动指定 ticker**:中文文件名无法可靠推断 ticker,自动解析会导致价格错误(见 memory.md 的 FUTU $168 事故)。绝不依赖文件名猜 ticker 去拉价格。
- **英文海报必须全英文**:生成后自动检测 CJK 字符,含中文则重试。不要放行带中文的 `_en.html`。
- **brief 文字 + 海报合并为一条飞书消息**,不拆成多条发送。
- 推送前确认 `FEISHU_APP_SECRET`、`ANTHROPIC_API_KEY`(或 `ANTHROPIC_AUTH_TOKEN`)已加载。
- PDF 被 Claude API 拒绝("PDF not valid")时:先 `python3 preprocess_pdfs.py`(需 `brew install poppler`),脚本会自动 fallback 读 `.cache/` 文本。
- **合集型(多标的)研报**:会议综述/行业横评类(覆盖多个标的)在 `collections.json` 里声明(`match` 文件名子串 + `source`/`title`/`tickers`),`run_workflow.py` 会按声明的 ticker 逐个出小节并附各自行情;**仍需先手动 fetch_prices 拉这些 ticker**。判定规则:brief 含 **≥3 个 `$名称(TICKER)$`** 即被 `generate_posters.py` 自动渲染为模块化合集海报。不要把这类报告硬塞单公司模板(会乱认 ticker + 注入旧价)。
- **专有名词用官方正式名,禁止音译**:公司中文名、产品/项目/计划名必须用官方名,绝不写拼音或臆造。当前 API 网关**不支持联网搜索**(`web_search`/WebSearch 均被拒,仅 WebFetch 可抓 URL),所以名称由 `name_glossary.json` 词典强制校正;遇到无法确认的新名称,先 WebFetch 官方资料,仍不确定则**询问用户**确认后入库。

## 写作风格

中文 brief 与海报文案遵循用户全局写作规范(美股分析文章风格);不要自创格式。

## 维护约定

每次改动脚本逻辑或修复 bug 后,**在 [memory.md](memory.md) 追加记录**(背景 / 根因 / 解决方案),保持可复盘。

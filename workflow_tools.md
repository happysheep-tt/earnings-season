# Earnings Season — Workflow Steps & Tools

> 描述投资社区财报季 AI workflow 的完整步骤和每步所需工具，供 AI 组配置评测环境参考。

---

## 项目概述

每个交易日（财报季期间），workflow 将券商研报自动转化为投资社区中文财报简报、英文海报和中文海报，并推送到飞书群。整个流程分为 3 个主步骤，每步由独立脚本负责。

---

## Step 0（按需）：PDF 文本预提取

**触发条件**：研报 PDF 内部结构损坏，Claude API 拒绝处理时使用。

**操作**：用 `pdftotext` 将 PDF 提取为纯文本，缓存到 `研报input/.cache/`。

**工具**：
| 工具 | 类型 | 用途 |
|------|------|------|
| `pdftotext` (poppler) | CLI / subprocess | 提取损坏 PDF 的文本内容 |
| 文件系统 write | 本地 I/O | 写入 `.cache/{filename}.txt` |

---

## Step 1：获取实时行情

**脚本**：`fetch_prices.py`

**操作**：拉取指定 ticker 的实时收盘价和盘后数据，写入 `market_data.json`。

**工具**：
| 工具 | 类型 | 用途 |
|------|------|------|
| Tiger Open API — `QuoteClient.get_quote_real_time` | HTTP / Python SDK (`tigeropen`) | 获取实时收盘价、涨跌幅、前收价 |
| Tiger Open API — `QuoteClient.get_quote_overnight` | HTTP / Python SDK (`tigeropen`) | 获取盘前/盘后延伸行情 |
| 文件系统 write | 本地 I/O | 写入 `market_data.json` |

**function calling**：无（脚本直接调用 Tiger SDK，不经过 LLM）

---

## Step 2：生成财报简报

**脚本**：`run_workflow.py`

**操作**：读取 `研报input/` 下的研报文件（PDF 或 MD），逐份生成中文财报简报，汇总保存到 `output/{date}_briefs.md`。

**工具**：
| 工具 | 类型 | 用途 |
|------|------|------|
| 文件系统 read | 本地 I/O | 读取 PDF / MD 研报文件 |
| 文件系统 read | 本地 I/O | 读取 `market_data.json` 获取实时价格 |
| Anthropic Claude API — `messages.create` (document input) | HTTP / Python SDK (`anthropic`) | 将 PDF base64 传入 Claude，生成中文 brief |
| 文件系统 read（fallback） | 本地 I/O | 读取 `.cache/` 文本缓存（PDF API 失败时） |
| 文件系统 write | 本地 I/O | 写入 `output/{date}_briefs.md` |

**function calling**：
- Claude API 调用使用 **document input**（PDF 作为 base64 内容块传入）
- 实时价格通过 `price_ctx` 注入 system prompt，Claude 无需自己调用行情 API

---

## Step 3：生成英文 + 中文海报，推送飞书

**脚本**：`generate_posters.py --push`

**操作**：读取 briefs，每条生成两张海报——全英文（`_en.html`）和中文（`_zh.html`），各自渲染为 PNG，与 brief 文字合并为一条飞书卡片消息（英文海报 + 中文海报 + brief 文字）推送到群。

**工具**：
| 工具 | 类型 | 用途 |
|------|------|------|
| 文件系统 read | 本地 I/O | 读取 `output/{date}_briefs.md` |
| Anthropic Claude API — `messages.create` (POSTER_SYSTEM) | HTTP / Python SDK (`anthropic`) | 从中文 brief 生成**全英文** HTML 海报（`_en.html`） |
| Anthropic Claude API — `messages.create` (POSTER_SYSTEM_ZH) | HTTP / Python SDK (`anthropic`) | 从中文 brief 生成**中文** HTML 海报（`_zh.html`） |
| Playwright | Python 库 | 将两张 HTML 分别渲染为 PNG 图片 |
| Pillow (PIL) | Python 库 | 合成水印 |
| 文件系统 write | 本地 I/O | 写入 `海报/poster_{ticker}_{date}_en.html` 和 `_zh.html` |
| Feishu API — `POST /auth/v3/tenant_access_token/internal` | HTTP | 获取短期 tenant access token |
| Feishu API — `POST /im/v1/images` | HTTP | 上传英文 + 中文 PNG 各一张，各返回 image_key |
| Feishu Webhook — `POST {WEBHOOK_URL}` | HTTP（HMAC-SHA256 签名） | 推送 brief 文字 + 两张海报图片合并为一条卡片消息 |

**function calling**：
- 两次 Claude API 调用均为纯文本生成（brief text in → HTML out）
- Feishu 推送通过脚本直接发 HTTP 请求，不经过 LLM

**验证逻辑**（脚本内部）：
- 英文海报生成后检测 CJK 字符，含中文自动重试，最多 3 次（中文海报不做此检测）
- `validate_brief()` 在推送前检查 brief 格式（4项）：大标题格式、价格 emoji、数据新鲜度、价格偏差

---

## 完整工具清单

| 工具 | 分类 | Step | 是否经过 LLM |
|------|------|------|------------|
| Tiger Open API (`get_quote_real_time`) | 外部 API | 1 | 否 |
| Tiger Open API (`get_quote_overnight`) | 外部 API | 1 | 否 |
| Anthropic Claude API (document input) | LLM API | 2 | 是 |
| Anthropic Claude API (英文海报生成, POSTER_SYSTEM) | LLM API | 3 | 是 |
| Anthropic Claude API (中文海报生成, POSTER_SYSTEM_ZH) | LLM API | 3 | 是 |
| Feishu API (tenant_access_token) | 外部 API | 3 | 否 |
| Feishu API (image upload) | 外部 API | 3 | 否 |
| Feishu Webhook (card push) | 外部 API | 3 | 否 |
| Playwright | 本地工具 | 3 | 否 |
| pdftotext (poppler) | 本地工具 | 0 | 否 |
| 文件系统 read/write | 本地 I/O | 全部 | 否 |

---

## 环境依赖

```bash
# Python 包
pip install anthropic tigeropen httpx playwright pillow

# 系统工具
brew install poppler        # pdftotext（Step 0，按需）
playwright install chromium # HTML → PNG 渲染（Step 3）
```

**环境变量**（`~/.zshrc`）：
```bash
export ANTHROPIC_AUTH_TOKEN=...
export ANTHROPIC_BASE_URL=...          # 如使用代理
export FEISHU_APP_SECRET=...           # 飞书应用凭证
export FEISHU_SIGN_KEY=...             # Webhook 签名密钥
export TIGER_CONFIG_PATH=...           # Tiger OpenAPI 配置文件路径
```

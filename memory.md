# Earnings Season — Project Memory

每次修改都记录在这里。目的：追踪决策原因、复盘故障、让 Claude 在下次会话能快速恢复上下文。

---

## 2026-05-08

### 架构重构：从单文件拆分为四模块

**背景**：`run_workflow.py` 承载了数据拉取、PDF 处理、brief 生成、海报生成、飞书推送五项职责，调试困难，出错时难以定位。

**拆分结果：**

| 文件 | 职责 |
|------|------|
| `fetch_prices.py` | Tiger 实时行情 → `market_data.json` |
| `preprocess_pdfs.py` | PDF 文本提取 → `研报input/.cache/` |
| `push_feishu.py` | 飞书 webhook 推送（签名、卡片构建、图片上传） |
| `run_workflow.py` | Claude brief + 海报生成，调用上述模块 |

**原则**：`run_workflow.py` 只关心 Claude API 调用和生成逻辑；数据获取和推送完全解耦。

---

### Bug Fix：FUTU 价格错误（核心教训）

**问题**：FUTU 的 brief 引用了 $168（UBS 研报中的报告日价格），而当天实际收盘价是 $144.89（-13.8%）。

**根本原因（循环依赖）**：
1. `extract_ticker("富途控股：Q126预览.pdf")` → 返回 `富途控股：Q12`（中文文件名，提取失败）
2. `fetch_tiger_quote("富途控股：Q12")` → 空字符串（无此 ticker）
3. brief 在没有价格上下文的情况下生成 → Claude 直接使用研报里的 $168
4. brief 生成完成后 ticker 才被正确解析为 `FUTU`，但为时已晚

**解决方案（两段式注入）**：
- Step 1（生成前）：用文件名猜测的 ticker 尝试拉取价格，作为 hint 传给 Claude
- Step 2（生成后）：从 brief 里提取到正确 ticker → 查 `market_data.json` → 调用 `inject_price_into_brief()` 强制替换价格行

**`inject_price_into_brief()` 逻辑**：
- 找到 `$公司名(TICKER)$` 那一行
- 剥离所有现有价格数据（emoji、`Closed $`、`US$`、`报告日收盘价`）
- 在行末附加 Tiger 实时价格字符串

**根本解决**：`fetch_prices.py` 要求用户在运行前**手动指定 ticker**，彻底绕开中文文件名解析问题。

---

### Bug Fix：MCD PDF 被 Claude API 拒绝

**问题**：`麦当劳：1Q26最终评估.pdf` 报错 `"The PDF specified was not valid"`，brief 生成失败。

**调查**：
- PDF header 有效（`%PDF-1.3`）
- `pdfplumber` / `pdfminer` 均报错：`'NoneType' object has no attribute 'objid'`（内部对象树损坏）
- `pdftotext -enc Latin1` 可以成功提取文本（poppler 对损坏 PDF 容错性更强）

**解决方案**：
1. 新建 `preprocess_pdfs.py`：用 `pdftotext -enc Latin1` 提取文本，存入 `研报input/.cache/`
2. `generate_brief()` 里增加 try/except：Claude PDF API 失败时自动 fallback 到文本 cache
3. 解码方式：`subprocess.stdout.decode("latin-1", errors="replace")`（不能用默认 UTF-8）

**注意**：需要安装 poppler：`brew install poppler`

---

### 新增：Brief 格式变更

**旧格式**（第一行）：
```
超微电脑：营收大幅低于指引，但毛利率意外超预期，空头回补推涨25%
```

**新格式**（第一行 = 大标题，第三行 = 中文叙述标题）：
```
Super Micro Computer (SMCI)  (花旗 买入 / Buy，目标价 $50，前目标价 $40 — 上调 +25%)

超微电脑：营收大幅低于指引，但毛利率意外超预期，空头回补推涨25%
```

**原因**：飞书卡片标题用大标题（公司英文名 + 投行/评级/PT），正文第一行才是中文叙述标题。信息密度更高，读者一眼看到投研来源。

**飞书卡片 header 取法**：`_feishu_card` / `push_feishu.build_card` 直接用 brief 第 0 行作为卡片标题。

---

### 新增：Pre-push 验证 Hook

**位置**：`run_workflow.py` → `validate_before_push()`

**4 项检查**：

| # | 检查内容 | 失败动作 |
|---|---------|---------|
| ① | Brief 格式：有 header `(TICKER)`、`$Company(TICKER)$`、必要章节、免责声明 | 警告 / strict 阻断 |
| ② | 价格 emoji 存在（📈/📉/🚀）| 警告 |
| ③ | `market_data.json` 新鲜度 ≤ 4 小时 | 警告 |
| ④ | brief 中价格 vs Tiger 缓存偏差 ≤ 5% | 警告 |

**默认行为**：打印警告，不阻断推送（判断权留给人）。
**`--strict` 模式**：任何检查失败都阻断推送。

```bash
python3 run_workflow.py --feishu          # 警告模式（默认）
python3 run_workflow.py --feishu --strict # 严格模式，验证失败不推送
```

---

### 飞书集成细节（备忘）

- **Webhook 签名**：HMAC-SHA256，字段 `timestamp` + `sign` 放在 request body JSON 里（不是 header）
- **签名字符串格式**：`f"{timestamp}\n{sign_key}"` encode UTF-8，digest 后 base64
- **图片上传**：需要 `FEISHU_APP_SECRET` 换取 tenant access token，再 POST 到 `/im/v1/images`
- **消息类型**：`msg_type: interactive`，brief + 图片合并为一条卡片消息
- **已知限制**：webhook 消息无法通过 API 撤回（无 message_id），只能在飞书 app 里手动长按撤回

---

### 价格显示格式（标准）

Tiger 实时价格统一用以下中文格式注入 brief：

```
📈 收涨 $498.87 (+6.4%，前收 $468.83) | After-Hrs 盘后: $492.80 (-1.22%)
📉 收跌 $144.89 (-13.8%，前收 $168.00) | After-Hrs 盘后: $151.41 (+4.50%)
🚀 大涨 $XXX.XX (+X.X%，前收 $XXX.XX)   ← 涨幅 ≥5% 用火箭
```

盘前/盘后时间戳 Tiger API 有时返回空，格式降级为不带 `[HH:MM EDT]`。

---

## 2026-05-09

### 架构重构：brief 与海报完全解耦，合并为单条飞书消息

**背景**：海报混入中文（ASML、DDOG、NET），根因是 `run_workflow.py` 把中文 brief 传给 Claude 生成海报。同时推送逻辑分散在两个脚本，导致 brief 和海报各发一条消息。

**最终三步架构**：

| 步骤 | 脚本 | 职责 | 飞书 |
|------|------|------|------|
| Step 1 | `fetch_prices.py` | Tiger 行情 → `market_data.json` | — |
| Step 2 | `run_workflow.py` | brief 生成 → `output/{date}_briefs.md` | 不推送 |
| Step 3 | `generate_posters.py --push` | 英文海报生成 + 验证 → **合并卡片推送** | brief 文字 + 海报图片，一条消息 |

**`run_workflow.py` 变更**：
- 删除全部海报代码（`POSTER_CSS`、`POSTER_SYSTEM`、`generate_poster()`）
- 删除 `--feishu`、`--no-poster`、`--no-brief`、`--force` 参数
- 删除 `validate_before_push()` 函数
- 只负责生成 brief 并保存到文件

**`generate_posters.py`（新脚本，唯一的推送入口）**：
- 读 `output/{date}_briefs.md`，逐 brief 生成英文海报
- System prompt 强制英文：生成后检测 CJK 字符，含中文则自动重试（最多 3 次）
- `validate_brief()` 在每次 push 前运行 ①–④ 检查
- `--push` 调用 `feishu_push(brief, ticker, poster_html)` → **一条消息 = brief 文字 + 海报图片**
- `--strict` 验证失败时阻断推送
- 启动时检查 `FEISHU_APP_SECRET`，未设置直接报错退出

**强制规则**：
- 海报必须全英文
- brief 和海报必须合并为一条飞书消息，不允许分开发送
- 不发图片 = 不合格

---

### Bug Fix：飞书频率限制（code 11232）

**问题**：批量推送多条消息时，飞书 webhook 返回 code 11232（frequency limited），部分消息发送失败。

**修改**：`push_feishu.feishu_push()` 和 `generate_posters._do_push()` 均加入退避重试：
- 检测到 11232 时等待 3–7 秒（随机抖动），最多重试 3 次

---

## 2026-05-29

### Bug Fix：价格新鲜度门限误丢隔夜收盘价

**问题**：`run_workflow._is_price_fresh()` 拿行情显示串里的 `[数据截至 MM/DD]` 标记与本地 today 比较，不一致就跳过价格注入。美股隔夜休市，最新数据本就带"昨天"的 EDT 日期，于是被误判为过期 → brief 退回用研报历史价（即 FUTU $168 事故的同类）。

**修改**：`_is_price_fresh()` 直接返回 True。行情新鲜度只由 `market_data.json` 文件 mtime（`preflight_check`）把关，不再与本地日期比较。**始终使用刚抓取的最新数据**。

### 新增：名称校正词典 name_glossary.json

**背景**：模型常把公司官方中文名/项目名音译或臆造（如 Marvell→「马威科技」、PDD 项目→拼音）。本想用 Anthropic 服务端 `web_search` 工具核实，但**当前 API 网关（LiteLLM 代理）不支持 `web_search` 工具类型**，WebSearch 同样被网关拒绝（仅 WebFetch 抓 URL 可用）。

**方案**：`name_glossary.json`（`{"replacements": {错误写法: 官方名}}`）由操作者核实后维护，`run_workflow` 与 `generate_posters` 生成后做强制字符串替换。已确认：Marvell→**迈威尔科技**、PDD 项目→**新拼姆**。新名称抓不到时询问用户确认后入库。

### 其他

- `_get_price_display()`：增加去交易所后缀回查（`KC.O`→`KC`），修复带 `.O/.N` 后缀时缓存查价 miss。
- brief `max_tokens` 1100→2400，修复长简报（尤其多投行合并）被截断。
- Marvell 两篇研报合并为一篇：提取文本合成单个 `.md` 输入，走「多家投行合并简报」格式。

---

## 2026-06-03

### Bug Fix：盘前/盘后涨幅抓不到（HPE 盘前 +30% 漏显示）

**问题**：`fetch_prices.fetch_one()` 用 `get_stock_briefs()`（未传 `include_hour_trading`）取常规价，延伸行情走 `get_quote_overnight()`，但后者在盘前时段常返回空 → HPE 财报盘前暴涨 +30% 没显示出来。

**修改**：改为 `get_stock_briefs([sym], include_hour_trading=True)`，优先读返回行里的 `hour_trading_latest_price / hour_trading_change_rate / hour_trading_tag / hour_trading_latest_time` 构建盘前/盘后串；`get_quote_overnight` 降级为兜底。

### 新增：合集型（多标的）研报规则

**背景**：会议综述/行业横评类研报（如 Jefferies AI 大会回顾）覆盖多个标的，硬塞单公司模板会乱认一个 ticker + 注入旧价（同「奥铃」误标）。目标：读者用最少时间获取每个标的的大行研判。

**实现（配置驱动）**：
- `collections.json`：声明 `match`（文件名子串）/`source`/`title`/`tickers`。
- `run_workflow.py`：`match_collection()` 命中后用 `generate_collection_brief()` 生成多标的简报——每个声明 ticker 一个小节，`$公司名(TICKER)$` 行末附各自 Tiger 实时价。仍需先手动 `fetch_prices` 拉这些 ticker。
- `generate_posters.py`：`is_collection()` 判定 brief 含 ≥3 个 `$名称(TICKER)$` → 走模块化合集海报模板（`POSTER_SYSTEM_COLLECTION` / `_ZH`，主题头 + 标的卡片网格）；合集型推送时文字卡片不 trim，保留全部标的。

---

## Ticker 备忘

| 公司 | Ticker | 备注 |
|------|--------|------|
| Block（原 Square） | **XYZ** | 不是 SQ，已确认 |
| 三星电子 | 005930.KS | 韩国市场，Tiger 可能无实时报价 |
| Marvell | MRVL | 官方中文名「迈威尔科技」（词典已收录） |
| 云顶新加坡 | GENS.SI | 新加坡市场，Tiger 无实时价，收盘价需手动提供 |

---

## 待观察 / 已知问题

- `get_quote_overnight` 有时不返回延伸行情时间戳（`ext_time` 为空），影响显示但不影响功能
- 策略类研报（如「美国股票观点」）无具体 ticker，海报文件名会包含中文，属正常现象
- 每次新 session 开始前需要 `source ~/.zshrc` 确保 `FEISHU_APP_SECRET` 等环境变量已加载
- **【待优化】合集海报画质不够清晰**（2026-06-03 Jefferies 合集卡片）。合集海报信息密度高，`push_feishu._html_to_png` 用 Playwright 默认 1x 截图，缩放后偏糊。下次优化：截图设 `device_scale_factor=2`（或更高 DPI）再合成水印。
- **API 网关不支持 `web_search` 工具**（LiteLLM 代理），脚本与 WebSearch 都无法联网搜索；仅 WebFetch 抓指定 URL 可用。名称核实改走 `name_glossary.json` + 询问用户。

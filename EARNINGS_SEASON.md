# Earnings Season Workflow — 使用手册

## 文件职责一览

| 文件 | 层级 | 职责 | 能否单独运行 |
|------|------|------|-------------|
| `fetch_prices.py` | 数据层① | Tiger 实时行情 → `market_data.json` | ✅ 是 |
| `preprocess_pdfs.py` | 数据层② | PDF 文本提取 → `研报input/.cache/` | ✅ 是（按需） |
| `push_feishu.py` | 推送层 | 飞书 webhook + 海报上传 | ✅ 可测试 |
| `run_workflow.py` | 生成层 | Claude brief + 海报，调用推送 | ✅ 主流程 |
| `generate_posters.py` | 海报层 | 独立海报生成（**强制全英文**），支持重试验证 | ✅ 是 |

---

## 每日标准流程

### 准备

把当天研报 PDF 放入 `研报input/`，文件名随意（中文可以）。

---

### Step 1 — 获取实时行情

```bash
python3 fetch_prices.py APP U COST FUTU NVDA MCD
```

HK 股票用 `--hk` 参数：
```bash
python3 fetch_prices.py APP NVDA --hk 01810 09988
```

确认数据已写入：
```bash
python3 fetch_prices.py --show
```

> **为什么要手动指定 Ticker？**
> 研报文件名是中文，脚本无法从「富途控股：Q126预览.pdf」可靠地推断出 `FUTU`。
> 手动指定是确保价格准确的唯一方法。

---

### Step 2 — 生成 brief，保存到文件

```bash
python3 run_workflow.py
```

生成所有 brief，保存到 `output/{date}_briefs.md`。不推送飞书，推送由 Step 3 统一完成。

---

### Step 3 — 生成英文海报，推送合并卡片

```bash
python3 generate_posters.py --push
```

> ⚠️ 运行前确认 `FEISHU_APP_SECRET` 已加载：
> ```bash
> source ~/.zshrc
> ```

每条飞书消息 = brief 文字 + 海报图片，**合并为一条**，不分开发送。

**参数：**

| 参数 | 作用 |
|------|------|
| `--push` | 生成后推送合并卡片到飞书群 |
| `--strict` | brief 验证失败时阻断推送 |
| `--force` | 强制重新生成已存在的海报 |
| `--ticker DDOG ASML` | 只处理指定 ticker |
| `--date 2026-05-09` | 指定日期（默认今天） |

**强制规则**：海报全英文；brief + 海报必须合并为一条消息。生成后自动检测 CJK 字符，含中文则重试。

---

### 输出文件

```
output/
  2026-05-08_briefs.md     ← 所有 brief 合集（Markdown）

海报/
  poster_app_2026-05-08.html
  poster_futu_2026-05-08.html
  ...

market_data.json           ← 实时行情缓存（fetch_prices.py 生成）
```

---

## 异常处理

### PDF 被 Claude API 拒绝（"PDF not valid"）

某些 PDF 内部结构损坏，Claude API 会直接拒绝。

**解决方案：预提取文本**
```bash
# Step 1: 提取所有 PDF 文本到 .cache/（需要 poppler）
python3 preprocess_pdfs.py

# 如果 poppler 未安装：
brew install poppler

# Step 2: 正常运行（run_workflow.py 会自动读取 cache）
python3 run_workflow.py --feishu
```

查看缓存状态：
```bash
python3 preprocess_pdfs.py --show
```

重新提取（覆盖缓存）：
```bash
python3 preprocess_pdfs.py --force
```

---

### 价格数据不对（brief 里用了研报历史价格）

根本原因：`fetch_prices.py` 没有在生成前运行，或 Ticker 没有包含在内。

**检查步骤：**
```bash
# 1. 查看当前缓存
python3 fetch_prices.py --show

# 2. 重新拉取漏掉的 Ticker
python3 fetch_prices.py FUTU

# 3. 重新运行生成（已有海报会跳过，只重新生成 brief）
python3 run_workflow.py --feishu --no-poster
```

---

### 飞书推送失败

```bash
# 测试 webhook 连通性
python3 push_feishu.py --test
```

常见原因：
- `FEISHU_APP_SECRET` 未设置 → `generate_posters.py --push` 启动前会直接报错拦截；先 `source ~/.zshrc`
- 签名错误 → 检查 `FEISHU_SIGN_KEY` 是否正确
- 频率限制（code 11232）→ `push_feishu.py` 已内置退避重试，通常自动恢复

---

## 环境变量（~/.zshrc）

```bash
export ANTHROPIC_AUTH_TOKEN=your_token
export ANTHROPIC_BASE_URL=your_base_url
export FEISHU_APP_SECRET=your_feishu_app_secret
export TIGER_CONFIG_PATH=/path/to/tiger_openapi_config.properties
```

修改后生效：`source ~/.zshrc`

---

## 完整目录结构

```
earnings season/
├── 研报input/                    ← 放研报 PDF / MD（输入）
│   └── .cache/                  ← PDF 文本缓存（preprocess_pdfs.py 生成，自动创建）
├── output/                      ← 生成的 brief 合集 MD
├── 海报/                        ← 生成的海报 HTML
│
├── fetch_prices.py              ← Step 1: Tiger 行情 → market_data.json
├── run_workflow.py              ← Step 2: brief 生成 + 飞书文字卡片推送
├── generate_posters.py          ← Step 3: 英文海报生成 + 飞书图片推送
├── preprocess_pdfs.py           ← 按需: PDF 文本预提取（被 run_workflow.py 自动调用）
├── push_feishu.py               ← 工具库: 飞书 webhook（被上述脚本调用，不单独运行）
│
├── market_data.json             ← 实时行情缓存（fetch_prices.py 生成）
└── EARNINGS_SEASON.md           ← 本文件
```

---

## 快速参考卡

```
准备
  source ~/.zshrc                                        加载环境变量（每次新 session）

每日操作（3 步）
──────────────────────────────────────────────────────────
1. python3 fetch_prices.py APP U COST FUTU NVDA [--hk 01810]
2. python3 run_workflow.py                              生成 brief，保存到 output/
3. python3 generate_posters.py --push                  生成英文海报 + 推合并卡片（brief+图片）
   （如有 PDF 报错，Step 2 前先运行 python3 preprocess_pdfs.py）
──────────────────────────────────────────────────────────

调试工具
  python3 fetch_prices.py --show              查看行情缓存
  python3 preprocess_pdfs.py --show           查看 PDF 文本缓存
  python3 push_feishu.py --test               测试飞书连通性
  python3 generate_posters.py --ticker X --force --push   重新生成指定海报
```

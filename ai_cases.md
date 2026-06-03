# Earnings Season — AI Workflow Cases

> 面向 AI 组评测使用。每个 case 对应投资社区财报季 workflow 中的一个真实 AI 调用场景。
> 所有示例均基于实际运行过的 prompt 和输出。

---

## Case 1：从研报 PDF 生成中文财报简报

```json
{
  "id": "es_001",
  "type": "文档理解 + 结构化写作",
  "input": [
    {
      "role": "user",
      "content": "根据这份研报 PDF，帮我生成一篇投资社区风格的财报简报。",
      "attachments": [
        {
          "type": "document",
          "filename": "应用材料：FQ2业绩回顾 - 年度盛会，全员集结.pdf"
        }
      ]
    }
  ],
  "expected": {
    "应覆盖": [
      "第一行大标题格式：英文公司全名 (TICKER)  (投行 中文/英文评级，目标价 $PT，前目标价 — 涨跌幅)",
      "第三行中文叙述标题：公司中文名：[核心故事一句话]",
      "$公司中文名(TICKER)$ 行 + 从 Tiger MCP 获取的实时价格（不使用研报内历史价格）",
      "被市场低估的信号（叙述段落，有洞察而非堆砌数据）",
      "核心财务数据：营收/毛利率/EPS 实际 vs 预期 + 超预期%",
      "业务分部（半导体设备/AGS/China 占比等）",
      "Q3 指引数据",
      "分析师观点",
      "末行免责声明：*仅供社区讨论，不构成投资建议。*"
    ],
    "格式约束": [
      "价格必须来自 Tiger MCP 实时数据，严禁引用研报内历史价格",
      "金融术语保留英文（YoY/QoQ/bps/EPS/PT）",
      "涨跌 emoji：📈收涨 / 📉收跌 / 🚀大涨（≥5%）"
    ]
  },
  "note": {
    "能力类型": "PDF 文档理解 + 行情 API 调用 + 格式化写作",
    "tool_calling": [
      "read_file / document input — 读取 PDF 研报内容",
      "get_realtime_quote(symbols=['AMAT'], sec_type='STK') — agent 需从 PDF 中识别 ticker，主动调用 Tiger MCP 获取实时价格注入 brief"
    ],
    "考察重点": "agent 是否主动调用行情 API；是否区分研报历史价 vs 实时价并使用正确来源"
  }
}
```

**真实输出节选（参考）：**

```
Applied Materials (AMAT)  (Bernstein 跑赢大市 / Outperform，目标价 $525，前目标价 $425 — 上调 +23.5%)

应用材料：FQ2营收/EPS双超预期，FQ3指引爆表，半导体设备超级周期加速兑现

$应用材料(AMAT)$ 财报公布后走势强劲，市场对超预期业绩及炸裂指引反应积极。收盘价 $440.56（研报披露日数据） 📉 收跌 $431.20 (-2.8%，前收 $443.62) [数据截至 05/13 03:12 EDT] | After-Hrs 盘后: $434.63 (+0.80%)
```

---

## Case 2：价格数据合规性验证

```json
{
  "id": "es_002",
  "type": "数据核查 + 行情 API 调用",
  "input": [
    {
      "role": "user",
      "content": "帮我检查这篇财报简报的价格数据是否准确，如有问题请指出并给出修正格式。\n\nBrief 中价格行：\n$富途控股(FUTU)$ Q126财报公布，业绩低于预期，盘后下跌。收盘价 $168.00（研报披露日数据）"
    }
  ],
  "expected": {
    "应覆盖": [
      "agent 主动调用 Tiger MCP 获取 FUTU 当日实际收盘价",
      "识别 brief 使用了研报历史价 $168.00，与实时收盘价存在显著偏差",
      "给出正确替换格式，使用 Tiger 实时数据，包含涨跌 emoji 和盘后数据"
    ],
    "应提及来源": true
  },
  "note": {
    "能力类型": "主动行情查询 + 数字核查 + 格式修正",
    "function_calling": [
      "get_realtime_quote(symbols=['FUTU'], sec_type='STK') — agent 需主动识别 ticker 并调用 Tiger MCP，不能仅凭 prompt 中的 $168 做判断"
    ],
    "背景": "对应真实事故：FUTU 研报记载 $168（报告日历史价），实际当日收跌 -13.8% 至 $144.89，brief 误用历史价导致错误信息发出",
    "考察重点": "agent 是否主动调用行情 API 而非直接接受 prompt 中的价格数字"
  }
}
```

---

## Case 3：从多份研报合并生成单个 Brief

```json
{
  "id": "es_003",
  "type": "多文档综合 + 结构化写作",
  "input": [
    {
      "role": "user",
      "content": "以下是英伟达 NVDA 的两份研报摘要，请合并生成一篇财报简报。
    }
  ],
  "expected": {
    "应覆盖": [
      "大标题中列出两家投行（Wells Fargo · Citi）及各自目标价",
      "综合两份研报核心数据：营收超预期（正面）+ 毛利率低于预期（负面）均需体现",
      "中国出货受限风险在叙述段落中提及",
      "价格行使用 agent 从 Tiger MCP 获取的实时数据；涨幅 ≥5% 用 🚀，否则用 📈/📉",
      "分析师观点区块分别列出两家机构评级和目标价"
    ]
  },
  "note": {
    "能力类型": "多源信息综合 + 行情 API 调用 + 格式化写作",
      "get_realtime_quote(symbols=['NVDA'], sec_type='STK') — agent 需主动识别 ticker 并调用 Tiger MCP 获取当日价格"
    ],
    "考察重点": "多来源合并不遗漏矛盾信息（超预期营收 vs 低于预期毛利率）；agent 自主调用行情 API"
  }
}
```


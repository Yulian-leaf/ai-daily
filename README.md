# AI4S-Daily

> 面向 **AI for Science** 的每日科研资讯站：每天自动抓取 arXiv / GitHub / 实验室博客 / 期刊 / Hacker News，用大模型打分筛选并写成结构化中文摘要，渲染成日报；再基于日报汇总出周报、双周报告和可分享海报，全部托管在 GitHub Pages。

**线上站点**：<https://yulian-leaf.github.io/ai-daily/>

零后端、零服务器、零运维：一台 GitHub Actions runner + 一个 `data` 分支 + 一个 SQLite 文件，就是全部基础设施。

---

## 目录

- [它产出什么](#它产出什么)
- [工作流程](#工作流程)
- [快速开始（全程在 GitHub 网页操作）](#快速开始全程在-github-网页操作)
- [模型预设与成本](#模型预设与成本)
- [配置说明](#配置说明)
- [定制提示词](#定制提示词)
- [本地开发](#本地开发)
- [架构](#架构)
- [常见问题](#常见问题)

---

## 它产出什么

一次流水线跑完，会生成四个互相可跳转的静态页面：

| 产物 | 内容 |
| --- | --- |
| `index.html` | **日报**。页头是「今日新增 / 归档」计数和「周报 / 海报」入口；正文有「⭐ 我的收藏 / 今日新增 / 归档」三个分栏、「子领域」筛选条，每张卡片显示评分、来源、主题标签和四段式摘要（创新点 / 技术方案 / 关键数据 / 为什么值得关注）。 |
| `weekly.html` | **周报**。按北京时间自然周（周一~周日）汇总已上墙的日报条目，产出标题、一句话金句、综述正文、按子领域分组的本期亮点、趋势观察、下周展望，并保留历史周报归档。 |
| `biweekly.html` | **双周报告**。覆盖两个自然周，额外要求做跨周趋势对比。与周报共用同一张表、同一套渲染，只换提示词和窗口。 |
| `poster.html` | **海报**。把最新一期报告渲染成 1080px 宽的竖版长图，含渐变头图、金句、8 个子领域各 1 条 + 公共池 2 条的亮点（带评分）、子领域分布条形图，适合群聊 / 朋友圈分享。 |

> 海报是定尺寸的静态 HTML，用浏览器打开就能截图成竖版长图（开发期用无头浏览器截图得到 `poster.png`）。截图不是流水线步骤，`poster.png` 也不进 git。

## 工作流程

```
config/sources.yaml ─┐
config/preferences.yaml ─┤
                         ▼
   fetch      16 个信息源并发抓取 ──► URL 级去重 ──► items 表（SQLite）
                         ▼
   summarize  ① scorer（便宜模型）：每条打分 0-10 + 主题标签 + 子领域归类
              ② summarizer（强模型）：只给「分数达标 + 未总结」的候选里
                 分数最高的 top_n 条写结构化摘要 ──► summaries 表
                         ▼
   render     渲染 index.html，并把本批次标记为「今天冒头」──► 今日新增栏
                         ▼
   weekly     把「已上墙」的日报条目汇总成周报 / 双周报告 ──► weekly_reports 表
                         ▼
   poster     把最新一期报告渲染成海报
                         ▼
              四个 HTML ──► data 分支根目录 ──► GitHub Pages
```

两个关键设计：

- **两级模型分工**。打分要跑全量候选（几十到上百条），总结只跑个位数条目。所以打分用便宜模型、总结用强模型，成本大头落在不得不跑的那一步。
- **`surfaced_at` 决定「今日 vs 归档」**。每次 `render` 会把还没标记过的摘要打上时间戳，因此**同一天第二次 `render` 今日栏就是空的**（去重语义，不是 bug）。想强制重新上墙，把对应行的 `surfaced_at` 置空再 render。
- **每日额度封顶**。`summarize` 会统计当天已新写的摘要数，最多补到 `top_n` 条。所以定时任务一天重跑三次也不会多花钱、不会重复上墙。

## 快速开始（全程在 GitHub 网页操作）

不需要本地 Python 环境。

**1. Fork 仓库**到自己的账号下。

**2. 配一个 LLM 的 API key**。`Settings` → `Secrets and variables` → `Actions` → `New repository secret`。

只需要其中一家的 key，Secret 名字必须完全一致：

| Provider | Secret 名 | 模型字符串示例 |
| --- | --- | --- |
| DeepSeek | `DEEPSEEK_API_KEY` | `deepseek/deepseek-chat` |
| Anthropic | `ANTHROPIC_API_KEY` | `anthropic/claude-haiku-4-5`、`anthropic/claude-sonnet-4-6` |
| OpenAI | `OPENAI_API_KEY` | `openai/gpt-4o-mini`、`openai/gpt-4o` |
| Gemini | `GEMINI_API_KEY` | `gemini/gemini-2.5-flash` |
| Groq | `GROQ_API_KEY` | Llama / Mixtral 系列 |
| Moonshot | `MOONSHOT_API_KEY` | `moonshot/moonshot-v1-128k` |

没配的那几个留空即可（workflow 已经把全部变量透传，空字符串不会报错）。这些 Secret 只存在你自己的 fork 里。

**3. 让 `config/preferences.yaml` 的 `models` 对上你刚配的 key**。点铅笔图标在线编辑即可：

```yaml
models:
  scorer:     deepseek/deepseek-chat   # 按你配了 key 的那家改
  summarizer: deepseek/deepseek-chat
```

**这一步不能跳过**：默认值是 Anthropic 的模型，如果你的 key 是别家的，第一次跑就会因为缺 key 直接失败。顺手可以改 `keywords`（决定打分偏好）、`score_threshold` 和 `top_n`（决定每天上墙几条）。

**4. 启用 Actions**。Fork 出来的仓库 Actions 默认是禁用的：进 `Actions` 标签页，点 "I understand my workflows, go ahead and enable them"。

**5. 手动跑一次 `daily`**。`Actions` → 左侧选 `daily` → `Run workflow` → `Run workflow`。第一次大约 2~4 分钟，日志最后应该有 `rendered=N output=site`。

**6. 打开 Pages**。`Settings` → `Pages` → `Build and deployment` → `Source` 选 `Deploy from a branch` → `Branch` 选 `data`，**folder 选 `/(root)`** → `Save`。

> ⚠️ 必须选 **`/(root)`**，不能选 `/docs`。流水线是把 `site/` 整个拷到 `data` 分支**根目录**发布的。选错 folder 会 404。

**7. 等一分钟**访问 `https://<你的用户名>.github.io/<仓库名>/`。之后 `daily` 每天 UTC 23:00（北京 07:00）自动跑，跑完把新数据 commit 到 `data` 分支，Pages 自动更新。

## 模型预设与成本

挑一套填进 `preferences.yaml` 的 `models` 即可。月成本按「每天 1 次、约 75 条候选打分、10 条总结」粗估，仅供参考。

| 预设 | scorer | summarizer | 需要的 Secret | 月成本（约） |
| --- | --- | --- | --- | --- |
| 省钱党 | `deepseek/deepseek-chat` | `deepseek/deepseek-chat` | `DEEPSEEK_API_KEY` | < $1 |
| 平衡党（原默认） | `anthropic/claude-haiku-4-5` | `anthropic/claude-sonnet-4-6` | `ANTHROPIC_API_KEY` | $3 ~ $5 |
| 品质党 | `anthropic/claude-sonnet-4-6` | `anthropic/claude-opus-4-7` | `ANTHROPIC_API_KEY` | $20 ~ $40 |
| 中文混搭 | `deepseek/deepseek-chat` | `anthropic/claude-sonnet-4-6` | 两个都要 | $2 ~ $4 |
| OpenAI 入门 | `openai/gpt-4o-mini` | `openai/gpt-4o` | `OPENAI_API_KEY` | ~ $1 |

选型经验：`scorer` 和 `summarizer` 不必同一家；评分阶段的 token 用量是总结阶段的 5~10 倍，所以「便宜模型评分 + 强模型总结」是性价比最高的一档。中文摘要质量对模型风格敏感，Claude Sonnet 系列的中文输出比较稳定。

LiteLLM 认得的所有 provider 都能用，格式统一是 `<provider>/<model>`，完整列表见 [LiteLLM 文档](https://docs.litellm.ai/docs/providers)。

**每次运行的实测成本会打在日志里**，按阶段拆分：

```
summarize done: scored=75 passed=32 backlog=0 purged=0 already=0 summarized=10 cost=$0.0264 (scorer=$0.0053 + summarizer=$0.0211)
```

这个数字来自 LiteLLM 的 `response_cost`。如果显示 `cost=$0`，说明该模型还不在 LiteLLM 内置价格表里，可以尝试升级 `litellm`。

## 配置说明

### `config/sources.yaml` —— 信息源

默认启用 16 个源：4 个 arXiv 分类组、4 个 GitHub Topic、7 个 RSS（DeepMind / Google Research / MS Research / NVIDIA / Nature / Science / 量子位）、1 个 Hacker News 查询。

| `type` | 必填 | 可选 | 说明 |
| --- | --- | --- | --- |
| `rss` | `name`, `url` | —— | 任意标准 RSS / Atom feed。 |
| `arxiv` | `name`, `categories` | `max_results`（默认 50） | `categories` 是 arXiv 分类码数组，如 `[q-bio.BM, q-bio.QM]`。 |
| `github` | `name`, `topic` | `min_stars`（默认 0） | 抓该 Topic 下最近有推送的仓库，按 star 过滤。 |
| `hackernews` | `name`, `query` | `min_points`（默认 100） | 走 HN Algolia 接口。`query` 只支持空格分隔的关键词，**不支持 `OR` 和括号**。 |

任何一个源挂掉都只会记一条 error 日志并返回空列表，不影响其他源和整条流水线。

### `config/preferences.yaml` —— 抓什么、怎么筛

```yaml
keywords: [protein structure prediction, molecular dynamics, drug discovery, ...]
subfields:                                  # 子领域分类，scorer 会把每条归到其中一个
  - {key: protein, label: 蛋白质/结构}
  - {key: drug,    label: 药物发现}
fetch_window_hours: 168                     # 抓取窗口（小时），168 = 7 天
models:
  scorer:     deepseek/deepseek-chat
  summarizer: deepseek/deepseek-chat
score_threshold: 6                          # 评分 >= 该值才进入总结阶段（0-10）
top_n: 10                                   # 每日最多总结 / 上墙条数（1-100）
```

- `keywords` 越具体越好，它是 scorer 打分的主要风向标，同时也决定了什么内容能通过阈值。
- `subfields` 的 `key` 必须是 scorer 能输出的值；模型给出越界或非法的 key 时，程序会记一条 warning 并回退成「未归类」，不会崩。
- `fetch_window_hours` 调小到 36 会漏掉低频更新的博客；调大到 720（30 天上限）也不会造成重复，因为有 URL 级去重。
- `score_threshold` 调高总结更精，但可能凑不满 `top_n`；调低更全但更杂。
- `top_n` 是硬上限，直接决定每天 summarizer 阶段的 LLM 调用次数，也就是主要成本。

## 定制提示词

`prompts/` 下四个纯文本模板，改它们比改代码更直接：

| 文件 | 作用 |
| --- | --- |
| `score.txt` | 打分的 system + user prompt。想让模型更看重论文还是工程落地，改这里。 |
| `summarize.txt` | 单条摘要模板，决定四个字段（创新点 / 技术方案 / 关键数据 / 为什么值得关注）的语气和详细程度。 |
| `weekly.txt` | 周报模板。 |
| `biweekly.txt` | 双周报告模板，比周报多了跨周趋势对比的要求。 |

模板里用 `{keywords}`、`{title}`、`{content}`、`{items}`、`{range}` 这类占位符，由 `src/prompts.py` 填充；写 JSON 示例时出现的花括号是安全的（渲染器只替换已知占位符，不会碰其他花括号）。

周报模板有两处**防幻觉约束**是踩坑后加的，改的时候别删：亮点里的链接必须原样照抄输入、标题的时间范围必须用注入值而不是自己推算。

## 本地开发

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS / Linux: source .venv/bin/activate

pip install -r requirements-dev.txt   # 含测试依赖；只跑不改用 requirements.txt
cp .env.example .env                  # 填入至少一个 provider 的 key
```

### CLI 一览

所有子命令都支持 `--sources` / `--preferences` / `--db`，默认值分别是 `config/sources.yaml` / `config/preferences.yaml` / `data/ai_daily.db`。

```bash
# 1. 抓取 + 去重入库
python -m src.main fetch
#   fetch summary: fetched=132 deduped=87 stored=87

# 2. 打分 + 总结（每日额度封顶）
python -m src.main summarize
#   summarize done: scored=75 passed=32 backlog=0 purged=0 already=0 summarized=10 cost=$0.0264 (...)

# 3. 渲染日报
python -m src.main render --output-dir site --within-days 30

# 4. 生成周报 / 双周报告（窗口内已上墙条目不足 3 条时跳过）
python -m src.main weekly --period weekly
python -m src.main weekly --period biweekly

# 5. 把最新一期报告渲染成海报
python -m src.main poster --period weekly
```

`render` 的 `--output-dir` 默认 `site`、`--within-days` 默认 `30`；`weekly` / `poster` 的 `--output-dir` 也是 `site`。GitHub Actions 用的就是这套默认值，跑完再把 `site/` 拷到 `data` 分支根目录。

注意 `fetch` / `summarize` / `render` 是**有状态**的：`render` 会写 `surfaced_at`，所以本地反复 `render` 时今日栏会越来越空，这是预期行为。

### 跑测试

```bash
pytest    # 105 个用例，覆盖配置、四类抓取器、LLM 重试、去重、存储迁移、渲染、周报/海报
```

测试全部走 `tmp_path` 独立数据库和 httpx mock，不发真实网络请求、不调真实模型。

## 架构

```
config/sources.yaml ─┐
config/preferences.yaml ─┤
                         ▼
      ┌──────────────────────────────────────────┐
      │ fetch_all：按源并发，单源失败不影响其他    │
      │ rss / arxiv / github / hackernews        │
      └───────────────────┬──────────────────────┘
                          ▼
                 URL 去重（批内 + 库内）
                          ▼
      items 表 ──► scorer（便宜）──► summaries 表 ──► summarizer（强，top_n 封顶）
                                                        │
                          ┌─────────────────────────────┘
                          ▼
      Jinja2 渲染 ──► index.html / weekly.html / biweekly.html / poster.html
                          ▼
                 data 分支根目录 ──► GitHub Pages
```

### 数据层

就是一个 SQLite 文件，三张表：

- **`items`**：抓取结果（`url` 主键去重、标题、正文、来源、发布时间、首次见到时间）。
- **`summaries`**：评分 + 结构化摘要（分数、标签、子领域、四段摘要、两个模型名与各自成本、`surfaced_at`）。
- **`weekly_reports`**：周报 / 双周报告，唯一键是 `(period, week_start)`，所以同一期重复生成是覆盖而不是堆积。

`init()` 里带着四段**幂等迁移**（补 `surfaced_at` / `field` / `summarized_at` / `slogan` 列），老数据库直接启动就能升级，不需要手动改表，也不会丢数据。

### 发布机制

`daily` workflow 每次跑的时序：

1. checkout `main`（拿代码、config、prompts）；
2. 把 `data` 分支 fetch 到 `data-branch/`（不存在就用 orphan 分支创建），把 `data/` 拷回工作目录 —— 这是 SQLite 能累积历史的关键；
3. 跑 `fetch` → `summarize` → `render`；
4. 生成 `weekly` / `biweekly` / `poster`。这三步都设了 `continue-on-error`：周报要额外调一次 LLM，失败时只跳过本次的周报和海报（旧的仍留在 `data` 分支），不会拖垮当天日报的发布；
5. **发布前校验** `site/` 里 `index.html`、`weekly.html`、`poster.html` 是否齐全 —— 缺了就报错退出。因为日报页头的「周报 / 海报」是同目录相对链接，缺文件就会点出 404，所以这一步是有意设为致命的；
6. 把 `data/` 和 `site/` 内容拷回 `data-branch`，`touch .nojekyll`，commit & push 到 `data` 分支。

整个流程**只写 `data` 分支，从不改 `main`**：`main` 只有你手动 push 代码时才会变，机器生成的内容全在 `data`。

## 常见问题

**`Missing API key env vars: X`**
`preferences.yaml` 里指定的模型所属 provider 没配 key。要么去 Secrets 加 `X`，要么把 `models` 改成你已经配了 key 的那家。

**Pages 打开是 404 或者是 README**
Pages 的 `Source` 必须配成 `Deploy from a branch` → branch `data` → **folder `/(root)`**。选成 `main` 会渲染 README，选成 `data /docs` 会 404（页面在分支根目录，不在 `docs/` 里）。

**「今日新增」是空的**
预期行为。同一天第二次 `render` 不会再展示已 surface 过的内容。要强制重上墙，去 SQLite 把对应 `summaries.surfaced_at` 置为 `NULL` 再 render。

**周报没生成**
窗口内（本周一至今）达标且已上墙的条目少于 3 条时会跳过。另外留意上一步 `Generate weekly / biweekly report pages` 的日志 —— 它失败时不会让整个 job 变红（`continue-on-error`），但会留下 error 输出。

**`source X returned 0 items`**
多半是该源 URL 失效了。手动访问那个 URL 看是不是 404 / 改版，换新地址或注释掉该条。

**arxiv 429 / 超时**
代码内置一次退避重试（30s → 60s）并在请求之间做节流。持续失败说明 runner 的 IP 被限流，等一小时再跑，或临时注释掉某个 arxiv 源。

**GitHub API 限流**
匿名配额很小。workflow 已把 `secrets.GITHUB_TOKEN` 透传给程序；本地开发要在 `.env` 里自己填一个 PAT。

**`cost=0`**
LiteLLM 内置价格表里暂时没有这个模型，不影响运行。可尝试升级 `litellm`。

**想换成本地模型（Ollama / vLLM）**
LiteLLM 支持：把 `models.scorer` 改成 `ollama/llama3:8b` 之类，并设置 `OLLAMA_API_BASE`。GitHub 免费 runner 跑不动本地模型，只适合自托管 runner。

## 文档

仓库里还有几份开发过程文档，答辩 / 复习时比 README 更细：

| 路径 | 内容 |
| --- | --- |
| `docs/stages/00~04-*.md` | 五个阶段的实施记录：目标、改动、验证数据、踩坑。 |
| `docs/创新点.md`、`docs/创新点-来源说明.md` | 逐条技术亮点及其来源。 |
| `docs/考核复习.md` | 考核 / 答辩复习提纲。 |
| `docs/周汇报.md`、`docs/周汇报-第二周.md` | 周汇报正文。 |

> 这些文档里出现的 `--output-dir docs` 是早期版本的写法。当前发布目录是 `data` 分支根目录（见上文「发布机制」），代码里的默认值和 CI 用的都是 `site`。

## 隐私与安全

- **Fork 默认是公开的**：`config/*.yaml` 里的关键词与模型选择、`data` 分支里的 SQLite 和 HTML，所有人都能看到。想藏起来就把 fork 设为 private（注意 GitHub Pages 在 private 仓库上的免费政策，以官方当前说明为准）。
- **不要把邮箱、Webhook URL 之类写进 `config/*.yaml`**，那些会一起 commit。敏感配置一律走 Secrets。
- `.env` 已在 `.gitignore` 里，本地放心填 key。
- `site/` 和 `data/` 也在 `.gitignore` 里 —— 它们是产物，只通过 `data` 分支发布，不进 `main`。

## 致谢

基于 [BerriAI/litellm](https://github.com/BerriAI/litellm) 做多 provider 路由，网页模板用 [Jinja2](https://jinja.palletsprojects.com/)，抓取用 [httpx](https://www.python-httpx.org/) 与 [feedparser](https://feedparser.readthedocs.io/)。

## License

MIT，详见 [LICENSE](LICENSE)。

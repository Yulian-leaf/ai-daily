# tests/ 测试目录说明

> 本目录是 ai-daily 的 pytest 测试套件，共 **90 个测试**（截至 Phase 1）。
> 每个测试文件对应 `src/` 里的一个模块，用「文件名 ≈ 被测模块」的方式组织。
>
> 运行方式：
> ```bash
> python -m pytest -q          # 全部
> python -m pytest tests/test_dedup.py   # 单个文件
> python -m pytest tests/ -k "field"     # 按关键字筛选
> ```

---

## 总览表

| 文件 | 对应模块 | 数量 | 说明 |
| --- | --- | --- | --- |
| `test_config.py` | `src/config.py` | 5 | 配置加载基础（sources 校验、默认值、真实配置可加载） |
| `test_config_stage2.py` | `src/config.py` | 7 | 模型/阈值解析 + **subfields 解析（Phase 1 新增 3 个）** |
| `test_dedup.py` | `src/dedup.py` | 3 | URL 去重 |
| `test_fetchers/test_arxiv.py` | `fetchers/arxiv.py` | 3 | arXiv 抓取、超时重试 |
| `test_fetchers/test_github.py` | `fetchers/github.py` | 1 | GitHub Topic 抓取过滤 |
| `test_fetchers/test_hackernews.py` | `fetchers/hackernews.py` | 1 | HN 抓取过滤 |
| `test_fetchers/test_orchestrator.py` | `fetchers/__init__.py` | 3 | 多源编排：聚合 + 单源失败隔离 |
| `test_fetchers/test_rss.py` | `fetchers/rss.py` | 3 | RSS 抓取、时间窗口过滤 |
| `test_llm.py` | `src/llm.py` | 10 | JSON 解析容错、API key 校验 |
| `test_logging_setup.py` | `src/logging_setup.py` | 2 | 日志初始化 |
| `test_main.py` | `src/main.py` | 2 | `run_fetch` 去重入库 |
| `test_main_render.py` | `src/main.py` | 1 | `run_render_cmd` 写 HTML |
| `test_main_summarize.py` | `src/main.py` | 1 | `run_summarize_cmd` 调流水线 |
| `test_models.py` | `src/models.py` | 3 | 数据类（Item/Score/Summary/Analysis） |
| `test_notifier_labels.py` | `notifier/labels.py` | 8 | 来源 → 友好名+分类（**Phase 1 改 AI4S 源 + 新增 1 个**） |
| `test_notifier_web.py` | `notifier/web.py` | 6 | HTML 渲染：今日/归档分栏、来源徽章（**Phase 1 改 1 个**） |
| `test_prompts.py` | `src/prompts.py` | 5 | 提示词加载与占位符渲染 |
| `test_storage.py` | `src/storage.py` | 5 | items 表：建表、去重、幂等写入 |
| `test_storage_dedup.py` | `src/storage.py` | 7 | `surfaced_at` 今日/归档语义、迁移 |
| `test_storage_stage2.py` | `src/storage.py` | 9 | 评分/总结读写、**field 列（Phase 1 新增 2 个）** |
| `test_summarizer.py` | `src/summarizer.py` | 5 | 评分+总结流水线、**field 解析（Phase 1 新增 2 个）** |

---

## 分模块详解

### 配置 `src/config.py`

**`test_config.py`（5）**
- `test_load_default_config` / `test_load_config_defaults_fetch_window`：不传配置时用默认值。
- `test_load_config_missing_source_field_raises`：source 缺 `name`/`type` 报 `ConfigError`。
- `test_load_config_rejects_bool_fetch_window`：`fetch_window_hours` 传布尔值要报错（防误写）。
- `test_real_default_config_loads`：**仓库里真实的 `config/*.yaml` 能正常加载**（冒烟测试）。

**`test_config_stage2.py`（7）**
- 前 4 个：`models.scorer/summarizer`、`score_threshold`、`top_n` 的解析与校验（缺 summarizer 报错、models 缺省为 None、阈值越界报错）。
- **Phase 1 新增 3 个（subfields）**：
  - `test_parses_subfields`：`subfields` 列表正确解析成 `[{key,label}, ...]`。
  - `test_subfields_absent_defaults_to_empty`：不配 subfields 时默认 `[]`。
  - `test_subfields_reject_bad_entry`：subfield 缺 `label` 等非法项报 `ConfigError`。

### 去重 `src/dedup.py`

**`test_dedup.py`（3）**
- `test_dedup_by_url_removes_already_seen`：已在库里（seen）的 URL 被过滤。
- `test_dedup_by_url_dedups_within_batch`：同一次抓取里重复的 URL 被去重。
- `test_dedup_by_url_empty_input`：空输入返回空。

### 抓取器 `src/fetchers/`

**`test_fetchers/test_arxiv.py`（3）** — `fetch_arxiv`
- 返回最近论文；超时自动重试一次；404 不重试。

**`test_fetchers/test_github.py`（1）** — `fetch_github`
- 按 `pushed_at` 时间窗口 + `min_stars` 过滤仓库。

**`test_fetchers/test_hackernews.py`（1）** — `fetch_hackernews`
- 按 `min_points` 过滤 HN 帖子。

**`test_fetchers/test_orchestrator.py`（3）** — `fetch_all`
- `test_fetch_all_aggregates_results`：多源结果正确合并。
- `test_fetch_all_isolates_failing_fetcher`：某个源抛异常时**不影响其它源**（核心设计）。
- `test_fetch_all_skips_unknown_source_type`：未知 type 打 WARNING 并跳过。

**`test_fetchers/test_rss.py`（3）** — `fetch_rss`
- 返回窗口内条目；过滤过旧条目；HTTP 错误抛出。

> 抓取器测试都用 `httpx_mock` / 预置 fixture（如 `rss_feed_xml`、`arxiv_response_xml`）模拟网络，**不真正联网**。

### LLM `src/llm.py`

**`test_llm.py`（10）**
- `test_parse_json_loose_*`（4 个）：容错解析——去掉 markdown 代码块围栏、修复尾逗号、乱输入报错。
- `test_complete_json_*`（3 个）：干净响应解析、坏 JSON 重试一次后成功、重试一次后放弃。
- `test_check_api_keys_*`（3 个）：按 provider 反查环境变量，缺 key 报错、混合 provider 校验。

### 日志 `src/logging_setup.py`

**`test_logging_setup.py`（2）**
- 返回 logger；重复调用幂等（不重复加 handler）。

### 主流程 CLI `src/main.py`

**`test_main.py`（2）** — `run_fetch`
- `test_run_fetch_dedup_and_store`：抓取→去重→入库，返回统计数。
- `test_run_fetch_skips_already_seen`：已见过的 URL 被跳过。

**`test_main_render.py`（1）** — `run_render_cmd`
- 渲染后写出 `index.html`。

**`test_main_summarize.py`（1）** — `run_summarize_cmd`
- 加载配置并调用 `run_summarize` 流水线（mock LLM）。

### 数据模型 `src/models.py`

**`test_models.py`（3）**
- `Item` 最小构造、带 `raw` 载荷构造、按值相等比较。

### 来源标签 `src/notifier/labels.py`

**`test_notifier_labels.py`（8）**
- `test_known_lab_source`：**Phase 1 改** `rss:openai-blog`→`rss:deepmind-blog`（lab）。
- `test_known_journal_source`：**Phase 1 新增** `rss:nature` → Nature / paper。
- `test_known_github_trending`：**Phase 1 改** `github-trending-protein` → `GitHub · protein`。
- `test_known_arxiv`：**Phase 1 改** `arxiv-qbio` → `arXiv · 生命`。
- `test_known_hn`：Hacker News → community。
- `test_unknown_rss_falls_back_to_name_and_other` / `test_unknown_github_falls_back_to_github_category` / `test_completely_unstructured_source`：未知来源按前缀兜底。

### 渲染 `src/notifier/web.py`

**`test_notifier_web.py`（6）**
- `test_render_site_first_run_puts_summaries_in_today_band`：首次渲染，摘要进「今日新增」栏。
- `test_render_site_keeps_today_same_day_moves_to_archive_next_day`：同日二次渲染仍在今日，跨天后移到归档。
- `test_render_site_empty_db_writes_empty_states`：空库渲染空状态文案。
- `test_render_site_source_badge_uses_friendly_label_and_category`：**Phase 1 改** `openai-blog`→`deepmind-blog`（验证来源徽章用友好名+分类）。
- `test_render_site_archive_groups_by_surfaced_date`：归档按 surfaced 日期分组、倒序。
- `test_render_site_includes_favorites_machinery`：包含收藏（本地 localStorage）机制。

### 提示词 `src/prompts.py`

**`test_prompts.py`（5）**
- `load_prompt` 找到文件 / 文件缺失报错。
- `render` 填充占位符、保留 JSON 示例里的 `{{ }}` 字面花括号、缺 key 报错。

### 存储 `src/storage.py`

**`test_storage.py`（5）** — items 表
- `init` 建 schema；`seen_urls` 初始为空；`record_items` 入库 + 重复 URL 幂等 + 保留首次 `first_seen`。

**`test_storage_dedup.py`（7）** — `surfaced_at` 今日/归档语义
- `get_today_summaries` 返回今日上墙或未上墙的、跳过只有 score 没 summary 的。
- `mark_surfaced` 打上墙时间戳、幂等、空列表；当天仍在今日，跨天才进归档。
- `get_archive_summaries` 按 `within_days` 窗口过滤（只含之前几天上墙的）。
- 旧库（无 `surfaced_at` 列）迁移并回填。

**`test_storage_stage2.py`（9）** — 评分/总结读写
- items 表持久化完整内容；`seen_urls` 过滤；score+summary 回环；未评分条目过滤；外键约束报错；旧 `seen_urls` 表清理。
- **Phase 1 新增 2 个（field）**：
  - `test_save_score_persists_field`：`Score.field` 写库后可读回。
  - `test_init_migrates_adds_field_column`：旧库（无 `field` 列）迁移后读回空字符串、不崩。

### 评分+总结 `src/summarizer.py`

**`test_summarizer.py`（5）**
- `test_run_summarize_scores_all_and_summarizes_top_n`：全量打分 + 只总结过阈值的 top_n（mock LLM）。
- `test_run_summarize_skips_item_on_score_error`：单条打分失败不中断整体。
- `test_run_summarize_with_no_items_is_noop`：无条目时零调用。
- **Phase 1 新增 2 个（field 解析）**：
  - `test_run_summarize_parses_field`：scorer 返回合法 `field` 时正确写入。
  - `test_run_summarize_field_out_of_range_falls_back`：返回越界 field 时回退为 `""`。

---

## 测试策略小结

1. **网络全 mock**：抓取器用 `httpx_mock`，LLM 用 `AsyncMock` 打桩，测试不依赖外网、不花钱、可重复。
2. **临时目录**：涉及 SQLite/文件都用 pytest 的 `tmp_path`，互不污染。
3. **按阶段演进**：文件名带 `stage2` / `dedup` 等后缀，对应项目开发的不同阶段（Stage 1 抓取、Stage 2 评分总结、Stage 3 去重展示）；Phase 1 新增的 subfields/field 测试也落在对应文件里。

## Phase 1 改动标记（AI4S）

- **新增 8 个测试**：`test_config_stage2.py` +3（subfields 解析）、`test_notifier_labels.py` +1（期刊源）、`test_storage_stage2.py` +2（field 存储/迁移）、`test_summarizer.py` +2（field 解析）。
- **修改 5 个断言**：`test_notifier_labels.py`（3 处来源改 AI4S）、`test_notifier_web.py`（来源徽章改 DeepMind）。
- 总量从 Phase 0 的 82 → Phase 1 的 90。

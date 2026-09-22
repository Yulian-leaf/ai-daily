
## Plan: AI4S-Daily 推送站（基于 ai-daily 改造）


### 已确认的决策
- 本地克隆开发 + 新建 GitHub 仓库部署；LLM 用 **DeepSeek**（`deepseek/deepseek-chat`）
- 周报节奏：**周一 + 周四**；前端保持**纯静态单文件 HTML + Jinja2**（零构建）
- 8 个子领域：蛋白质/结构、药物发现、分子模拟、材料科学、气候地球、AI4Math/PDE、科学基础模型、生物信息

### 关键架构事实（调研所得）
- CLI 三命令 `fetch → summarize → render`；SQLite 两张表 `items` + `summaries`（`surfaced_at` 区分今日新增/归档）
- fetchers 注册表在 `src/fetchers/__init__.py`（rss/arxiv/github/hackernews）；LLM 走 LiteLLM（`src/llm.py::_PROVIDER_ENV` 已含 deepseek）
- 渲染 `src/notifier/web.py::render_site`；标签 `labels.py::label_for`；提示词 `prompts/score.txt` + https://github.com/feng-nengyu/ai-daily/tree/main/prompts/summarize.txt#L19-L23
- 部署：`daily.yml` cron → checkout main + orphan `data` 分支 → 跑流水线输出 `docs/` → 回写 data 分支 → Pages 服务 `/docs`

### 分阶段步骤
- **Phase 0 基线跑通**：克隆、venv、DeepSeek key、三命令 demo、`pytest` 72 测试基线、写 `docs/stages/00-基线.md`
- **Phase 1 AI4S 主线**：重写 `config/sources.yaml`（arXiv 科学分类/GitHub topic/科学 RSS）与 https://github.com/feng-nengyu/ai-daily/tree/main/config/preferences.yaml（关键词+模型+subfields）；扩展 `src/config.py`；改 `prompts/score.txt` 输出 `field`（8 选 1）；改 `src/models.py`、`storage.py`（加 field 列+迁移）、`summarizer.py`、`labels.py`；补测试
- **Phase 2 子领域筛选**：`templates/index.html.j2` 加 8 个子领域 chips 筛选（data-field + 内联 JS）；`web.py` 传 subfields/field_labels；补测试
- **Phase 3 周报 + 日报/周报切换**：新增 `prompts/weekly.txt`、`src/weekly.py`、`templates/weekly.html.j2`；`storage.py` 加 `weekly_reports` 表（UNIQUE(period, week_start) 幂等 upsert）；`main.py` 加 `weekly` 子命令（`--period weekly|biweekly`）；前端加「日报/周报」切换导航；补 `test_weekly.py`。**详细设计见 `docs/stages/03-周报.md`**（数据模型 / 生成流程 / 提示词 / 渲染 / 调度 / 与 3.5 衔接）
- **Phase 3.5 双周分析报告 + 海报设计（本周新增，亮点）**：
  - **双周分析报告**：在周报基础上，每两周生成一份深度综述——跨周趋势（领域热度变化）、Top 工作对比、新方向浮现，由 LLM 汇总两周数据生成综述正文；
  - **海报化设计**（把报告变成「一张可分享的海报」）：顶部标题+周期+生成时间 → 中部 Top 亮点（标题+一句话摘要+子领域色块）→ 底部数据统计（抓取数/总结数/子领域分布）+ 站点链接；
  - **技术路线（保持纯静态、零新依赖）**：① Jinja2 渲染独立海报版 HTML（定尺寸布局，浏览器打开即截图）；② 生成 SVG 矢量海报（纯文本、可无损转 PNG）；③ 推荐——复用现有渲染 + 无头浏览器截图产出 `poster.png` 供直接下载分享；
  - **亮点/思考**：把「数据日报」升级为「可传播的内容产品」——一张图讲清一周科研热点，适合分享朋友圈/群聊/公众号，是项目从「工具」走向「产品」的一步。
- **Phase 4 部署**：`daily.yml`（每日）+ 新增 `weekly.yml`（周一/四）双 workflow；建仓库、Secrets、Actions 权限、Pages（data→/docs）；线上验证
- **Phase 5 收尾**：更新 `README.md`、`docs/stages/` 索引与逐文件代码讲解（考核）

### Relevant files（核心改动）
`config/sources.yaml`、`config/preferences.yaml`、`prompts/{score,summarize,weekly,report}.txt`、`src/{config,models,storage,summarizer,weekly,report,main}.py`、`src/notifier/{web,labels}.py`、`templates/{index,weekly,poster}.html.j2`、`.github/workflows/{daily,weekly,biweekly}.yml`、`tests/*`、`docs/stages/*`

### Verification
每阶段：`pytest` 全绿 + 本地命令跑通 + commit + `docs/stages` 记录；Phase 4 验证 Actions 手动运行、`data` 分支产出 `docs/index.html` + `docs/weekly.html`、线上 Pages 可访问且切换/筛选正常；Phase 3.5 验证双周报告 + 海报（`poster.png`）生成成功、内容与数据一致。

### Further Considerations
- 周报生成额外 DeepSeek token 成本极低（< ¥0.1/次）；arXiv 若 429 可按上游 FAQ 临时注释对应源。
- 子领域由 scorer LLM 输出 `field` 入库，另可加静态来源兜底映射。

计划已存入会话文件，可随时基于它推进。你看是否需要调整任何阶段或细节？
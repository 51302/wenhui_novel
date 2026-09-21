# 文辉小说 Skill 体系说明与效果评估

> 本文档说明后端 `backend/skills/` 下各模块 Skill 的作用、运行时如何被选择注入、以及前后端如何选择使用；并给出一份**推理式效果评估**（未做真实生成实验，仅基于规则与链路推演）。

## 一、整体架构

Skill 是"提示词层"的可插拔写作规则，运行时按作品/章节上下文自动选择，合并去重后注入章节生成 Prompt。

```
作品(genre + writing_style_id) + 章节(概要 + skill_ids + 反AI开关)
        │
        ▼
   SkillSelector（选择）
        │  基础层 → 题材层 → 能力层 → 风格层 → 质量层
        ▼
   SkillMerger（合并去重 + 版本/hash + 长度上限）
        │
        ▼
   build_prompt 注入 → LangGraph 章节生成
```

核心代码：
- 加载：`backend/app/skills/loader.py`（扫描 `**/SKILL.md`，跳过带 `.git` 的 vendored 参考仓库）
- 选择：`backend/app/skills/selector.py`
- 合并：`backend/app/skills/merger.py`
- 注入：`backend/app/service/chapter_gen_graph.py` 的 `node_build_prompt` / `node_load_existing`

## 二、Skill 模块与作用

### 1. 基础层（base）— `theme_skills/novel-general`
每章必注入的通用地基。核心是**故事引擎门禁**：写正文前先过七问（可记忆场景 / POV 欲望 / 阻力 / 被迫选择 / 即时代价 / 不可逆变化 / 追读钩子），并用"无效章节负面清单"拦截"只介绍设定 / 盘点 / 埋伏笔 / 让主角意识到某事"这类空转章节。附通用写作守则（禁设计文档语言、禁作者层泄漏、POV 权限、对白节奏、力量尺度匹配）。

### 2. 题材层（genre）— 16 个
玄幻 / 都市情感 / 悬疑 / 末世 / 科幻 / 武侠 / 历史权谋 / 轻小说 / 军事 / 体育 / 灵异 / 现实 / 奇幻 / 动漫 / 游戏 / 无限流。

每个题材统一六段内联分层模板：
- 读者承诺 + 一句可证伪检查
- 开书先定（6 项，缺一先问）
- 前三章承诺链
- 本章场景写法（按需选 1-2 种，每种带量化计数 + 失败模式改法）
- 成文软区间（软参考，非合格线）
- 交付自检 checkbox + 量化反套路红线

### 3. 能力层（capability）— 7 个
辅助题材、可叠加的机制/设定层：
- `novel-world-settings` 世界设定：设定服务人物，禁开篇堆百科
- `novel-cheat-system` 金手指系统：外挂提供机会而非替代决策
- `novel-romance-settings` 情感关系：关系靠事件推进而非心动独白
- `novel-writing-styles` 文风控制：先有故事引擎再谈文风
- `novel-xuanhuan-subgenres` / `novel-urban-subgenres`：题材细化
- `novel-schools` 流派结构：凡人流/苟道流/无敌流等推进模式

### 4. 风格层（style）— `writer_skills/` 20 个作家
辰东 / 我吃西红柿 / 墨香铜臭 / 烽火戏诸侯 / 蝴蝶蓝 / 八月长安 / 耳根 / 尾鱼 / 净无痕 / 蔡骏 / 关心则乱 / 叶非夜 / 忘语 / 柳岸花又明 / 三九音域 / 狐尾的笔 / 丁墨 / 天瑞说符 / 圣骑士的传说 / 卧牛真人。

每个是一份 `writer-<id>` Skill，`author_style_id` 保留旧 ID 兼容前端。决定"怎么表达"，与题材层正交叠加。

### 5. 质量层（quality）— `detection_skills/novel-anti-ai`
中文网文反 AI 味质量控制，口径与项目现有三道防线对齐：
- `prompts.yaml`（HARD_RED_LINES / UNIVERSAL_ANTI_AI_GUIDE / HUMAN_VOICE_MANDATE / SELF_CHECK_LIST）
- `conf/ai_feature_rules.json`（66 条特征规则，阈值真相源）
- `service/text_cleaner.py`（程序化清洗）

本 Skill 只补代码改不动的**结构/语义**问题（故事引擎空转、说明书设定、五感堆砌、微动作流水线、目光扫描、剧本式对话、工整收尾、缺人味毛边），并给 0-100 AI 味评分与"先结构后密度"去味顺序。**默认每章注入**，可在章节生成时关闭。

## 三、选择与优先级规则

`SkillSelector` 的选择顺序与去重：
1. 恒定注入 `novel-general`（base）
2. 质量层 `novel-anti-ai`（`include_quality=True` 时，默认）
3. 显式指定：章节 `skill_ids` + 作品 `writing_style_id` + 章节 `author_style`（旧 `chendong` 会映射到 `writer-chendong`）
4. 题材关键词命中（genre/概要/设定/角色文本）→ 题材层 + 相关能力层
5. Skill 元数据 `triggers` 命中

合并后排序：`(非base, priority, id)`，即 base 最前、quality(priority=95) 最后（近因效应，紧贴写作指令）。`SkillMerger` 逐行去重共同规则，超 8000 字符按行截断，并记录每个 Skill 的 version 与 content_hash。

## 四、前后端如何使用

### 作品创建 / 编辑（决定后续所有章节的默认写法）
- 位置：创作中心 → 新建作品 / 编辑作品
- 可选：**题材**（标签多选，写入 `genre`）、**写作风格（作家）**（单选，写入 `novel.writing_style_id`）
- 效果：该作品后续每次章节生成，未单独指定时**自动继承**作品的题材与作家风格

### 章节生成（可临时覆盖 + 反AI开关）
- 可临时多选作家风格、章节模板（覆盖作品默认）
- **反AI检测去味**开关：默认勾选。勾选 → 注入 `novel-anti-ai` 质量层；取消 → 本章跳过质量层
- 对应参数：`use_anti_ai`（默认 `true`）

### 参数贯通链路
```
前端 Creation.vue
  作品：writing_style_id, genre
  章节：skill_ids / author_style, use_anti_ai
        │
  POST /api/novels/create|update      → novel.writing_style_id
  POST /api/chapters/generate|regenerate → task_data
        │
  ChapterService.generate_with_ai / regenerate_with_ai
        │
  run_chapter_gen(state: use_anti_ai, skill_ids, author_style…)
        │
  node_build_prompt:
    explicit = skill_ids + author_style + novel.writing_style_id(继承)
    SkillSelector.select(..., include_quality=use_anti_ai)
```

## 五、推理式效果评估（未做真实生成，基于规则与链路推演）

### 评估方法
对三个典型场景，推演"选中哪些 Skill、注入了什么约束、大概率改善什么、潜在风险是什么"。

### 场景 A：玄幻 + 作家"辰东" + 反AI开
选中：`novel-general → novel-xuanhuan → writer-chendong → novel-anti-ai`
- **预期改善**：故事引擎门禁挡掉"纯升级流水账"；玄幻层的"获得—代价—下一阈值"量化计数压制无代价升级；辰东风格补强开篇钩子与悬念递进；反AI层压制破折号/明喻堆砌/微动作流水线。
- **协同**：题材(写什么) × 风格(怎么表达) × 质量(不像AI) 三者正交，冲突面小。
- **风险**：注入总量约 5–6K 字符，叠加原有 system prompt 后偏长，弱模型可能对靠后的红线遵守率下降（已靠 priority 把质量层放最后缓解）。

### 场景 B：都市情感 + 无作家 + 反AI开
选中：`novel-general → novel-urban-romance → novel-urban-subgenres → novel-anti-ai`
- **预期改善**：情感层的"关系靠事件推进、潜台词对白"抑制"心动独白 + 旁白宣布相爱"；反套路红线"直接表白为 0"针对性强；反AI层抑制总结式煽情收尾。
- **风险**：未选作家风格时表达层较弱，文风个性依赖模型默认，可能偏平。可引导用户在作品级选一个作家风格兜底。

### 场景 C：悬疑 + 反AI关
选中：`novel-general → novel-mystery`（不含质量层）
- **预期**：悬疑层的"公平线索投放、揭示时才追加决定性事实=0"仍生效；但反AI结构/语义检查缺席，AI 腔风险回升。
- **结论**：反AI关适合"先出结构正确的草稿，再单独跑去味"的工作流；常规创作建议保持默认开。

### 横向推理结论
| 维度 | 评估 | 依据 |
|---|---|---|
| 结构完整性 | 显著提升 | base 故事引擎门禁 + 题材前三章承诺链，从"有没有戏"层面把关 |
| 题材贴合度 | 提升 | 16 题材各有量化场景写法与反套路红线，不再是泛化三段 |
| 反AI味 | 提升且不重复 | 质量层与 text_cleaner/prompt 铁律分工明确，只补结构/语义 |
| 风格可控 | 提升 | 作品级继承 + 章节级覆盖，20 作家可选 |
| 可维护性 | 提升 | 结构化 frontmatter + 版本 + content_hash + 单元测试 |
| 主要风险 | 注入长度 | 多层叠加后 Prompt 偏长，建议监控实际 token 与弱模型遵守率 |

### 已通过的确定性验证（非生成质量，是链路正确性）
- Skill 加载 45 个、配置校验 0 错、无重复 id
- 作品作家继承：`explicit='chendong'` → 命中 `writer-chendong`
- 反AI开关：`include_quality=False` → 不含 `novel-anti-ai`；默认 True → 含且排末尾
- 单元测试 3 项通过（loader / selector / merger）

## 六、后续可选增强
1. 生成后落一个"AI 味评分"日志节点（复用 `novel-anti-ai` 的评分框架 + `ai_feature_rules.json`），超阈值触发一次定向去味重写。
2. 前端在作品卡片显示已选作家风格标签。
3. 监控实际注入 token，必要时对能力层做"按概要命中才注入"的进一步收敛。

# ============================================================================
# 小说创作与记忆管理统一Prompt总成 —— 提示词内容已迁移至 conf/prompts.yaml
#
# 本文件仅保留组装/查询逻辑，提示词原文与模板数据均从配置文件加载：
# - 修改提示词 → 编辑 backend/app/conf/prompts.yaml，保存后热加载生效，无需改代码/重启。
# - 记忆体维度、作家风格、章节模板、性格映射等结构化数据同样来自配置。
# - 所有模板使用 {placeholder} 占位符，调用时通过 .format(**kwargs) 填充。
# ============================================================================

from app.prompts.prompt_loader import get_config
from app.utils.logger import system_logger

# ============================================================================
# 记忆体维度统一配置 — 所有模块引用此定义，只改一处（来源：prompts.yaml）
# ============================================================================

MEMORY_DIMENSION_DEFS = [tuple(d) for d in (get_config("MEMORY_DIMENSION_DEFS") or [])]


def get_memory_category_names() -> list:
    return [d[0] for d in MEMORY_DIMENSION_DEFS]


def get_frontend_to_dimension_map() -> dict:
    return {d[1]: d[0] for d in MEMORY_DIMENSION_DEFS}


def get_ai_label_to_dimension_map() -> dict:
    return {d[2]: d[0] for d in MEMORY_DIMENSION_DEFS}


def get_dimension_dedup_map() -> dict:
    return {d[0]: d[3] for d in MEMORY_DIMENSION_DEFS}


def match_ai_label_to_dimension(label: str) -> str:
    label = label.strip()
    ai_map = get_ai_label_to_dimension_map()
    if label in ai_map:
        return ai_map[label]
    for dim_key, _, ai_label, _ in MEMORY_DIMENSION_DEFS:
        if dim_key in label or label in dim_key:
            return dim_key
        if ai_label and (ai_label in label or label in ai_label):
            return dim_key
    for dim_key, _, _, _ in MEMORY_DIMENSION_DEFS:
        for kw in dim_key:
            if kw in label:
                return dim_key
    return None


# ============================================================================
# 第一部分：生成模块 —— 用于根据大纲创作章节（来源：prompts.yaml）
# ============================================================================

GENERATE_SYSTEM_PROMPT = get_config("GENERATE_SYSTEM_PROMPT", "")
CHARACTER_NAMING_GUIDE = get_config("CHARACTER_NAMING_GUIDE", "")
GENERATE_CREATIVE_DIRECTION = get_config("GENERATE_CREATIVE_DIRECTION", "")

# 开写前铁律（最高优先级，置顶注入——模型对 system prompt 开头指令遵守率最高，
# 与 HUMAN_VOICE_MANDATE 第七条口径一致但更短更硬，专治模型忽视长段规则）
HARD_RED_LINES = get_config("HARD_RED_LINES", "")

# ============================================================================
# 第二部分：情感描写指南 —— 136种情绪维度全覆盖（来源：prompts.yaml）
# ============================================================================

HUMAN_EMOTION_GUIDE = get_config("HUMAN_EMOTION_GUIDE", "")

# ============================================================================
# 第三部分：战斗描写指南 —— 提升战斗场景的质感与冲击力（来源：prompts.yaml）
# ============================================================================

COMBAT_WRITING_GUIDE = get_config("COMBAT_WRITING_GUIDE", "")

# 静态场景铁律（对话/解释/展示/夜谈类章节的防AI专项）
STATIC_SCENE_GUIDE = get_config("STATIC_SCENE_GUIDE", "")

# 全类型通用反AI铁律（不分题材/场景，每章必注入，与检测器口径一致）
UNIVERSAL_ANTI_AI_GUIDE = get_config("UNIVERSAL_ANTI_AI_GUIDE", "")

# 人味强制生成令（人设锚定+白名单句法+正例仿写；与禁止式清单互补，每章必注入）
HUMAN_VOICE_MANDATE = get_config("HUMAN_VOICE_MANDATE", "")

# ============================================================================
# 第四部分：网感风格指南 —— 让文字更接地气、更有梗（来源：prompts.yaml）
# ============================================================================

VULGAR_DIALOGUE_GUIDE = get_config("VULGAR_DIALOGUE_GUIDE", "")

# ============================================================================
# 第五部分：角色认知边界 —— 角色知道的 ≠ 作者知道的（来源：prompts.yaml）
# ============================================================================

COGNITION_BOUNDARY_GUIDE = get_config("COGNITION_BOUNDARY_GUIDE", "")

# ============================================================================
# 第六部分：提示词工程层 —— 约束分层 + 冲突裁决 + 写作流程（来源：prompts.yaml）
# ============================================================================

GENERATION_FRAMEWORK = get_config("GENERATION_FRAMEWORK", "")
SELF_CHECK_LIST = get_config("SELF_CHECK_LIST", "")

# ============================================================================
# 生成模块 System Prompt 组装 —— 恒定核心 + 按需场景指南
#
# 结构说明（兼顾前缀缓存与按需注入）：
# - 恒定核心：身份/总框架/具名/情感/认知 每章必用，放在最前且顺序恒定，
#   作为请求前缀稳定命中 DeepSeek 前缀缓存。
# - 按需指南：战斗/静态场景/网感 是"场景特异"指南，仅当章节概要（或题材）
#   命中对应特征时才追加在核心之后；不命中则不注入，省 token 且更贴合章节。
#   由于追加位置在核心之后，核心前缀仍可命中缓存。
# 正文生成（_call_generation_api）与 AI 续写共用；SELF_CHECK_LIST 与字数提醒
# 保留在 user 末尾以维持近因效应（缓存只认前缀，不受尾部影响）。
# ============================================================================

GENERATE_CORE_SYSTEM_PROMPT = (
    HARD_RED_LINES  # 置顶：开写前铁律（最高优先级，模型对开头指令遵守率最高）
    + "\n\n" + GENERATE_SYSTEM_PROMPT
    + "\n\n" + GENERATION_FRAMEWORK
    + "\n\n" + CHARACTER_NAMING_GUIDE
    + "\n\n" + HUMAN_EMOTION_GUIDE
    + "\n\n" + COGNITION_BOUNDARY_GUIDE
    + "\n\n" + HUMAN_VOICE_MANDATE
    + "\n\n" + UNIVERSAL_ANTI_AI_GUIDE
)

# ============================================================================
# 按需场景指南推荐 —— 根据章节概要关键词（+题材）决定注入哪些指南
# ============================================================================

# 战斗场景触发词：概要出现任一 → 注入 COMBAT_WRITING_GUIDE
COMBAT_TRIGGER_KEYWORDS = (
    "战斗", "厮杀", "打斗", "对决", "比武", "斗法", "围攻", "偷袭", "突袭",
    "追杀", "逃杀", "碾压", "反杀", "击杀", "激战", "血战", "大战", "决战",
    "生死战", "突围", "破阵", "进攻", "反击", "交手", "过招", "冲突", "对峙",
)

# 静态场景触发词：概要出现任一 → 注入 STATIC_SCENE_GUIDE
# （对话/谈判/夜谈/展示/教学等"静态说明文重灾区"章节）
STATIC_SCENE_TRIGGER_KEYWORDS = (
    "对话", "谈判", "商谈", "夜谈", "密谋", "商议", "交易", "拜师", "回忆",
    "祭拜", "审讯", "审问", "答疑", "讲解", "展示", "参观", "游览", "夜聊",
    "闲聊", "诉苦", "和解", "结盟", "会面", "探视", "饭局", "酒局",
    # 汇报/受命/辞别类（拜见师父、领任务、道别等静态对话场景，AI 易写成规整说明文）
    "拜见", "请安", "问安", "领命", "受命", "复命", "辞别", "拜别", "道别",
    "告别", "叮嘱", "交代", "嘱咐", "禀报", "汇报", "请示", "召见", "接见",
    "会客", "赐", "任务", "告之", "告知",
)

# 网感触发词：概要出现任一 → 注入 VULGAR_DIALOGUE_GUIDE
VULGAR_TRIGGER_KEYWORDS = (
    "弹幕", "直播", "系统提示", "评论区", "吐槽", "玩梗", "段子", "嘴贱",
    "对骂", "骂战", "叫骂", "破口大骂", "市井", "街头", "赌场", "酒馆",
    "嘲讽", "挑衅", "怼", "粉丝", "水友", "打赏",
)

# 网感题材提示：题材命中任一 → 网感指南常驻（现代/系统/穿越类用梗多）
VULGAR_GENRE_HINTS = (
    "都市", "现代", "系统", "穿越", "直播", "末世", "娱乐", "校园", "职场",
    "网游", "搞笑", "轻松",
)


def _has_any(text: str, keywords) -> list:
    """返回 text 中命中的关键词列表（空文本/空词表 → 空列表）"""
    if not text:
        return []
    return [k for k in keywords if k in text]


def recommend_scene_guides(summary: str = "", genre: str = "") -> list:
    """根据章节概要（+题材）推荐按需场景指南，返回指南文本列表（顺序恒定）

    - 静态场景 → STATIC_SCENE_GUIDE（原顺序最先）
    - 战斗场景 → COMBAT_WRITING_GUIDE
    - 网感（概要命中 或 题材为网感题材）→ VULGAR_DIALOGUE_GUIDE
    保持追加顺序恒定，让核心前缀之后的缓存尾部尽量一致。
    """
    guides = []
    if _has_any(summary or "", STATIC_SCENE_TRIGGER_KEYWORDS):
        guides.append(STATIC_SCENE_GUIDE)
    if _has_any(summary or "", COMBAT_TRIGGER_KEYWORDS):
        guides.append(COMBAT_WRITING_GUIDE)
    if _has_any(summary or "", VULGAR_TRIGGER_KEYWORDS) or _has_any(genre or "", VULGAR_GENRE_HINTS):
        guides.append(VULGAR_DIALOGUE_GUIDE)
    return guides


def build_generate_system_prompt(summary: str = "", genre: str = "") -> str:
    """组装生成/续写 system prompt：恒定核心 + 按需场景指南

    :param summary: 本章概要（按关键词推荐场景指南）
    :param genre:   作品题材标签（网感题材常驻网感指南）
    """
    parts = [GENERATE_CORE_SYSTEM_PROMPT]
    guides = recommend_scene_guides(summary, genre)
    parts.extend(guides)
    result = "\n\n".join(p for p in parts if p)
    if guides:
        system_logger.info(
            f"[按需提示词] 命中指南: {', '.join(g.replace('【','').splitlines()[0][:20] for g in guides)}"
        )
    return result

# ============================================================================
# 第七部分：提取模块 —— 用于从章节中提取结构化记忆（来源：prompts.yaml）
# ============================================================================

MEMORY_EXTRACT_PROMPT = get_config("MEMORY_EXTRACT_PROMPT", "")
MEMORY_INCREMENTAL_PROMPT = get_config("MEMORY_INCREMENTAL_PROMPT", "")
LIGHT_EXTRACT_PROMPT = get_config("LIGHT_EXTRACT_PROMPT", "")
FULL_EXTRACT_PROMPT = get_config("FULL_EXTRACT_PROMPT", "")
AGGREGATE_MEMORY_PROMPT = get_config("AGGREGATE_MEMORY_PROMPT", "")

# 提取接口 system prompt（供 AI 提取/增量提取/重建等场景使用，来源：prompts.yaml）
EXTRACT_SYSTEM_PROMPT = get_config("EXTRACT_SYSTEM_PROMPT", "")
EXTRACT_FULL_SYSTEM_PROMPT = get_config("EXTRACT_FULL_SYSTEM_PROMPT", "")
EXTRACT_FULL_STRICT_SYSTEM_PROMPT = get_config("EXTRACT_FULL_STRICT_SYSTEM_PROMPT", "")
EXTRACT_INCREMENTAL_SYSTEM_PROMPT = get_config("EXTRACT_INCREMENTAL_SYSTEM_PROMPT", "")

# ============================================================================
# 第八部分：作家风格库 —— 章节级写作技法模板（供章节设定下拉框选择）
# ============================================================================

AUTHOR_STYLES = get_config("AUTHOR_STYLES") or []


def get_author_style_guide(style_id: str) -> str:
    """根据作家风格ID获取对应的技法指南，未匹配时返回空字符串"""
    if not style_id:
        return ""
    for s in AUTHOR_STYLES:
        if s.get("id") == style_id:
            return s.get("guide", "")
    return ""


def get_author_style_list():
    """返回作家风格列表（供前端下拉框）"""
    return AUTHOR_STYLES

# ============================================================================
# 第九部分：章节级别写作模板库（按功能分类：场景 / 情绪走向 / 字数结构 / 语言风格）
# ============================================================================

CHAPTER_TEMPLATES = get_config("CHAPTER_TEMPLATES") or []


def get_chapter_template_guide(template_id: str) -> str:
    """根据模板ID获取对应的技法指南，未匹配时返回空字符串"""
    if not template_id:
        return ""
    for t in CHAPTER_TEMPLATES:
        if t.get("id") == template_id:
            return t.get("guide", "")
    return ""


def get_chapter_template_list():
    """返回章节模板列表（供前端下拉框）"""
    return CHAPTER_TEMPLATES

# ============================================================================
# 第十部分：人物性格 → 默认章节模板 映射（来源：prompts.yaml）
# 生成章节时若未手动选择章节模板，则读取作品主角（characters 第一个角色）的
# personality，关键词匹配以下映射，自动适配对应的章节模板
# ============================================================================

PERSONALITY_TEMPLATE_MAP = [tuple(p) for p in (get_config("PERSONALITY_TEMPLATE_MAP") or [])]


def resolve_personality_template(personality: str) -> str:
    """根据角色性格文本（自由输入）关键词匹配默认章节模板ID；无匹配返回空字符串"""
    if not personality:
        return ""
    for keyword, template_id in PERSONALITY_TEMPLATE_MAP:
        if keyword in personality:
            return template_id
    return ""


# ============================================================================
# 第十一部分：章节概要规划（为作品批量生成后续 N 章概要）—— 来源：prompts.yaml
# ============================================================================

OUTLINE_SYSTEM_PROMPT = get_config("OUTLINE_SYSTEM_PROMPT", "")
OUTLINE_USER_PROMPT_TEMPLATE = get_config("OUTLINE_USER_PROMPT_TEMPLATE", "")

# ============================================================================
# 第十二部分：AI 续写模块 —— 疯批专属规则 + 续写主 Prompt（来源：prompts.yaml）
# ============================================================================

CONTINUE_CHAOT_RULES = get_config("CONTINUE_CHAOT_RULES", "")
CONTINUE_PROMPT = get_config("CONTINUE_PROMPT", "")

"""生成后程序化清洗：用纯代码规则去除 AI 检测标记的统计特征

背景：AI 检测工具主要看 perplexity（困惑度）与 burstiness（突发性）两个统计特征。
- 困惑度低（句句可预测、模板化）→ 判 AI
- 突发性低（句子长度均匀、节奏齐整）→ 判 AI
prompt 规则（让模型自己改）效果有限，本模块在生成后对文本做程序化改写，
直接压掉高频 AI 特征，不经过模型（免费、零延迟）。

处理规则（每条超过密度阈值才触发，阈值见下方常量）：
1. dash    破折号"——"压减（AI 最爱用；保留极少量，其余换逗号/句号）
2. colon   冒号"："压减（超频解释句；非引语冒号换逗号）
3. ellipsis 省略号"……"压减（超出部分换句号；后跟断句符时直接删除）
4. exclaim 感叹号"！"压减（阈值放宽，叙述中超出才处理）
5. not_is  "不是X，是Y"解释句式压缩（全文最多保留1处，其余删前留后）
6. not_is_dot "不是X。是Y。"句号版压缩（两连保留1处；三连"不是X。不是Y。是Z。"出现即压）
7. triple  三连顿号排比拆散（X、Y、Z → X、Y，还有Z）
8. simile  明喻词换形（仿佛/如同/宛如/犹如/好似 → 像，降书面感）
9. like     "像"字比喻密度压减（全文最多5个；句尾补丁比喻换"跟X似的"口语形）
10. abrupt   高频副词压减（忽然/突然/猛地等；同词300字内最多1个 + 全文每500字1个）
11. conj    句首连接词压减（于是/因此/然后/接着/随即/继而，全文最多保留1个）
12. guide   "那种…像/仿佛"引导句式清除（"那种"二字删除，降模板感）
13. subject 冗余主语删除（连续两句同主语 → 后句删主语，制造无主语句/碎片句）
14. buffer   缓冲垫短段消除（"沉默。""空气安静了。"独立成段是 AI 过渡软着陆 → 并入下一段开头，硬切）
15. longlist 顿号4+连拆散（屋顶、木梁、裂缝、苔藓 扫描式列举 → 第3项后断开）
16. shorttail 连续短句合并（"慌乱。一闪而过。""药味还在。胸口还在疼。"短句排比 → 前句句号改逗号）
17. paragraph 段落长度均匀 → 拆最长段（打破段落均匀强迫症）
18. burst   均匀长句拆短（连续3句长度相近 → 中间句逗号改句号，提升突发性）
19. repeat   完全重复短句压减（"烛火又跳了一下。"出现4次 → 只留第1次，其余删除）
20. word     标签词重复压减（同一环境词"烛火"超4次 → 换同义变体火苗/烛焰/灯焰，降词频）
21. para_head 段首主语重复压减（连续2段"他……他……"同主语 → 第2段删主语，制造碎片句）
22. emotion 情绪标签词独立段删除（"慌乱。""震惊。"裸情绪词独立成段 = 直接贴情绪标签，整段删除，删后自然衔接）
23. dup_para 段落级大段雷同删除（相邻/跨段连续≥16字相同且占较短段≥40% → 删后出现段，防七猫"复制粘贴式重复"驳回）

两阶段清洗（关键：AI 特征大量藏在对话台词里，单一"先保护引号再清洗"会漏掉）：
- 阶段一（全文级，含对话）：dash / not_is / not_is_dot / triple / longlist / simile / like / abrupt / guide
  —— 先于占位保护执行，台词里的标点与句式特征同样压
- 阶段二（引号保护后，句法/段落级）：colon / ellipsis / exclaim / conj / subject / shorttail / buffer / emotion / paragraph / burst / dup_para / repeat / word / para_head
  —— 引号内整体占位保护，句子结构与段落节奏规则只作用于叙述

安全边界：
- 全部规则只动标点、高频词与固定句式，不删剧情、不增内容
- 开关：config.yaml ai.text_clean.enabled（默认开启）
"""
import re

from app.utils.logger import system_logger

# ==================== 密度阈值（每 N 字允许保留的数量） ====================
DASH_KEEP_PER_CHARS = 5000       # 破折号：每5000字允许1个（实际=几乎全删，prompt要求0个）
DASH_KEEP_ABS = 0                # 破折号：全文绝对保留上限=0（prompt要求0个，不管文本多短）
COLON_KEEP_PER_CHARS = 400       # 冒号：每400字允许2个
COLON_KEEP_COUNT = 2
ELLIPSIS_KEEP_PER_CHARS = 600    # 省略号：每600字允许1个
EXCLAIM_KEEP_PER_CHARS = 150     # 感叹号：人类网文本身多，阈值放宽
NOT_IS_KEEP_MAX = 0              # "不是X，是Y"：全文最多0处（检测器红牌项，彻底消除）
TRIPLE_KEEP_PER_CHARS = 800      # 三连排比：每800字允许1个
SIMILE_KEEP_PER_CHARS = 250      # 明喻词：每250字允许1个
LIKE_KEEP_MAX = 3                # "像"字比喻：全文不超过3个（检测器红牌项）
ABRUPT_KEEP_PER_CHARS = 500      # 忽然/突然/猛地等：每500字允许1个
ABRUPT_WINDOW = 300               # 同词局部密度：相同副词300字内最多1个（"忽然"92字内3次→删超出的）
CONJ_KEEP_MAX = 1                # 句首连接词（于是/因此/然后/接着）：全文最多1个
GUIDE_KEEP_MAX = 1               # "那种…像/仿佛"引导句式：全文最多1处
SUBJECT_REMOVE_MAX = 3           # 冗余主语删除（制造无主语句）：全文最多3处
PARA_HEAD_MAX = 2                # 段首主语重复删除：全文最多2处
BUFFER_MAX_LEN = 14              # 缓冲垫短段最大长度（字符）
SHORTTAIL_MAX = 6                # 连续短句合并：全文最多6处
REPEAT_SENT_MAX_LEN = 14         # 完全重复短句最长14字（超过视为普通句）
REPEAT_TRIGGER = 2               # 完全相同短句出现≥2次即触发压减
REPEAT_KEEP = 1                  # 保留第1次，其余删除
WORD_KEEP_MAX = 4                # 环境词变体替换：同一词全文最多出现4次
PARAGRAPH_EVEN_MIN = 40          # 段落均匀判定下限（字符）
PARAGRAPH_EVEN_MAX = 160         # 段落均匀判定上限（字符）
PARAGRAPH_EVEN_DELTA = 35        # 段落长度最大差（字符）
DUP_NGRAM_LEN = 16             # 段落级大段雷同：连续16字相同视为重复块
DUP_PARA_MIN_RATIO = 0.4       # 重复块占较短段落比例≥40%才删
DUP_PARA_MAX = 5               # 段落级重复删除：全文最多5段
# ---- 新增规则阈值 ----
PUNCT_BUG_MAX = 3              # 标点连用修复（"。，""，。"）：全文最多修3处（避免误伤引号边界）
COMMA_TRIPLE_KEEP_MAX = 1      # 逗号版三连形容词：全文保留1处，其余拆散
DOUBLE_SIMILE_KEEP_MAX = 0     # 双重比喻标记（"像是X似的"）：全文0处（冗余双标记=AI特征）
FRAME_SIMILE_KEEP_MAX = 1      # 双框比喻尾（"仿佛X一般"）：全文保留1处
ADJ_INDEP_MAX = 3              # 形容词独立段（"粗重的。"）：全文并入3处
SHORT_ACTION_BURST_MIN = 3     # 短动作连排（"碎了。塌了。散了。"）：≥3连触发合并
SHORT_ACTION_BURST_MAX = 2     # 短动作连排合并：全文最多2处
SHORT_PARA_DENSITY_MAX = 0.15  # 短句独立段密度（≤12字独立段占比>15%=AI节奏模板）
HALF_EXPLAIN_MAX = 1           # "某种X""说不清的X"半解释：全文最多1处（超出交LLM改写）
FORMAL_CONJ_MAX = 1            # 书面连词（不仅/既又/与其不如）：全文最多1处
IDION_QUAD_DENSITY_MAX = 3     # 单段四字格≥3个触发（成语堆砌=AI书面感）
NEG_HAVE3_MAX = 0              # "没有X，没有Y，只有Z"三连否定：全文0处（交LLM改写）
# ---- 句子残缺/悬空检测（AI 输出最显眼的断句bug） ----
SENTENCE_BROKEN_MAX = 1        # 句子残缺（"X的、。""X、。"顿号/逗号后直接句号）：全文≤1处
SENTENCE_FUSED_MAX = 1         # 句子粘连（两句无标点直接连，"涌出来不是渗"）：全文≤1处
ADJ_CHAIN_DASH_MAX = 1         # 顿号形容词链悬空（"X的、Y的、"结尾）：全文≤1处
SHORT_PARA_RUN_MAX = 2         # 连续短句独立段排比（≥3连触发，全文最多2处）
# ---- _NOT_IS_RE 修复：X 最小长度从 2 改 1，覆盖"不是渗，是涌" ----

# ==================== 正则 ====================
# 引号保护：中文引号（成对/行尾未闭合）+ 半角引号（不跨行，防止未闭合引号吞噬正文）
_QUOTE_RE = re.compile(r'“[^”\n]*”|“[^”\n]*$|"[^"\n]*"')
# 断句符（含换行边界）
_SENT_END_RE = re.compile(r'[^。！？；!?;\n]*[。！？；!?;]')
# "不是X，是Y" 解释句式（逗号版；X 最短1字覆盖"不是渗，是涌"）
_NOT_IS_RE = re.compile(r'不是([^，。；！？]{1,24})[，,](?:而是|却是|就是|是)([^，。；！？]{1,40})')
# "不是X。是Y。" 句号短句版（两连：不是三年五年。是三百年。；不跨段落）
_NOT_IS_DOT2_RE = re.compile(r'不是([^。，；！？\n]{1,10})[。！](?:而是|就是|是)([^。，；！？\n]{1,20})[。！]')
# "不是X。不是Y。是Z。" 短句排比版（三连：不是白色。不是红色。是金色。；允许跨单行，匹配区间含 \n\n 段落边界时跳过）
_NOT_IS_DOT3_RE = re.compile(r'不是([^。，；！？\n]{1,10})[。！]\s*不是([^。，；！？\n]{1,10})[。！]\s*(?:而是|就是|是)([^。，；！？\n]{1,20})[。！]')
# "不是X，不是Y，是Z。" 逗号版三连否定排比（不是霉，不是灰，是更淡的什么）
_NOT_IS_COMMA3_RE = re.compile(r'不是([^，。；！？\n]{1,10})[，,]\s*不是([^，。；！？\n]{1,10})[，,]\s*(?:而是|就是|是)([^，。；！？\n]{1,30})')
# 三连顿号排比（如 震惊、愤怒、不解）
_TRIPLE_RE = re.compile(r'([\u4e00-\u9fff]{2,4})、([\u4e00-\u9fff]{2,4})、([\u4e00-\u9fff]{2,4})(?=[，。；！？])')
# "像X，像Y，像Z" 三连排比（AI 高频：像潮水，像棉絮，像没有尽头的白）
_LIKE_TRIPLE_RE = re.compile(r'像([^，。；！？]{1,10})，像([^，。；！？]{1,10})，像([^，。；！？]{1,10})(?=[。，；！？])')
# 书面感明喻词（优先替换，越靠前越书卷气）
_SIMILE_WORDS = ("仿佛", "如同", "宛如", "犹如", "好似", "宛似")
# 引语冒号前缀（说：/道：等保留）
_SPEECH_TAIL_RE = re.compile(r'[说说道问喊叫念应叹答]$')
# 高频转折/突发副词（超出即删除，靠动词/语境承接）
_ABRUPT_WORDS = ("忽然", "突然", "骤然", "猛地", "倏地", "陡然", "冷不防")
# 句首连接词（超出即删除；检测器红牌项）
_CONJ_WORDS = ("于是", "因此", "然后", "接着", "随即", "继而")
# "那种…像/仿佛"引导句式（检测器红牌项）
_GUIDE_RE = re.compile(r'那种(?=像是|像|仿佛|如同|好像)')
# "像"字（排除"好像"及复合词内的像）
_LIKE_ISOLATED_RE = re.compile(r'(?<!好)像(?<!想)(?<!雕)(?<!画)(?<!图)(?<!影)(?<!模)(?<!照)')
# 句尾补丁比喻（，像X。/ 像是X。→ 跟X似的）
_LIKE_PATCH_RE = re.compile(r'(?<!好)像(?:是)?([^，。；！？\s]{1,12})(?=[，。；！？])')
# 代词/人名 + 动作白名单（删除冗余主语时校验，避免病句）
_SUBJECT_WORDS = ("陈妄", "他", "她", "它")
# 段首主语表（段落开头词重复检测：连续2段同主语开头 → 第2段删主语）
_PARA_SUBJECTS = ("独臂女人", "陈妄", "解尘", "木棉", "她", "他")
# 环境词变体替换表（标签词重复红牌：同一环境词高频 → 从第 WORD_KEEP_MAX+1 次起换同义变体）
_WORD_VARIANTS = (("烛火", ("火苗", "烛焰", "灯焰")),)
# 情绪标签词独立段（检测器红牌"直接贴情绪标签"：裸情绪词独立成段，AI 完成写作任务不留给读者推演）
_EMOTION_LABEL_RE = re.compile(
    r'(?m)^[ \t]*(?:慌乱|震惊|愤怒|恐惧|害怕|激动|感动|惊慌|惊惧|不安|疑惑|迷茫|绝望|'
    r'兴奋|悲哀|喜悦|委屈|慌张|惊愕|惶恐|尴尬|紧张|骇然|愕然|惊怒|心悸|心慌)[。．！]?[ \t]*$')
_SUBJECT_ACTION_RE = re.compile(
    r'(陈妄|他|她|它)(看见|看到|听到|闻到|感觉|觉得|想起|想到|抬头|低头|转身|回头|伸手|抬手|攥|握|站起|站起身|走|跑|笑|哭|叹|皱|眯|盯|看|望|深吸|吐|张开|闭上|翻|抽|拽|撑|挪|退|跪|坐)')
# 缓冲垫词表（AI 节奏切换软着陆高频词）
_BUFFER_WORDS = ("沉默", "安静", "寂静", "静默", "无言", "愣住", "顿住", "顿了一下",
                 "停了半拍", "停了一拍", "半晌", "片刻", "一瞬", "缓了缓",
                 "回过神来", "哑然", "噤声", "鸦雀无声", "空气凝滞", "静了一瞬",
                 "静了一息", "沉默了一会儿", "沉默了片刻", "顿了顿")
# 连续短句（≤7字内容 + 句号）；lookbehind 确保短句从行首/断句符后开始，
# 避免从长句中间截取（"陈妄盯着她的手势。"→ 误匹配"妄盯着她的手势。"）
_SHORT_SENT_RE = re.compile(r'(?<![^。！？；!?;\n])[^。！？；!?;\n]{1,7}。')
# 顿号4+连（扫描式列举：A、B、C、D → A、B、C，还有D）
_LONGLIST_RE = re.compile(
    r'([\u4e00-\u9fff]{1,4}、[\u4e00-\u9fff]{1,4}、)([\u4e00-\u9fff]{1,4})(、)([\u4e00-\u9fff]{1,4}(?:、[\u4e00-\u9fff]{1,4})*)(?=[，。；！？])')
# ---- 新增清洗正则（阶段一/阶段二） ----
# 标点连用（"。，""，。""。。""！。"）：终止标点后紧跟其他终止/逗号标点 → 保留首个
_PUNCT_BUG_RE = re.compile(r'[。！？；]([，。！？；])')
# 逗号版三连形容词（"粗重，沉闷，一下一下的"=AI 节奏排比；与顿号版 _TRIPLE_RE 互补）
_COMMA_TRIPLE_RE = re.compile(
    r'([\u4e00-\u9fff]{2,4})，([\u4e00-\u9fff]{2,4})，([\u4e00-\u9fff]{2,6})(?=[，。；！？])')
# 双重比喻标记（"像是X似的"=双标记冗余 → "像X"）
_DOUBLE_SIMILE_RE = re.compile(r'像是([^，。；！？\n\s]{1,20})似的')
# 双框比喻尾（"仿佛X一般"/"如同X一般"/"宛如X般" → 去"一般/般"）
_FRAME_SIMILE_RE = re.compile(r'(仿佛|如同|宛如|犹如|好似)([^，。；！？\n]{1,20})一般')
# 形容词独立段（"粗重的。""干涩的。"独立成段=AI 标签式节奏；排除代词"我的/你的/他的"）
_ADJ_INDEP_RE = re.compile(
    r'(?m)^[ \t]*[\u4e00-\u9fff]{1,4}的[。．！]?[ \t]*$')
# 短动作连排（"碎了。塌了。散了。"动词+了+句号连续≥3 → 前两改逗号）
_SHORT_ACTION_BURST_RE = re.compile(r'((?:[\u4e00-\u9fff]{1,3}了[。！]){3,})')
# 句首连接词补充（在原 _CONJ_WORDS 基础上扩展）
_CONJ_EXTRA_WORDS = ("随后", "旋即", "不多时", "紧接着")
# ---- 句子残缺/悬空检测正则 ----
# 顿号/逗号后直接跟句号（"尖细的、。""湿漉漉的、。"=句子残缺，AI 输出 bug）
# 排除引号内对话，匹配"顿号或逗号 + 可选空白 + 句号/感叹号"
_SENTENCE_BROKEN_RE = re.compile(r'[、，][\s]*[。．！]')
# 句子粘连（两句无标点直接连："涌出来不是渗"=动词+不是，缺逗号）
# 匹配"动词/形容词 + 不是X" 且前文非标点（缺分隔符）
_SENTENCE_FUSED_RE = re.compile(r'(?<![，。；！？、\n])([^\s，。；！？、\n]{2,8})不是([^\s，。；！？、\n]{1,8})')
# 顿号形容词链悬空（"X的、Y的、"以顿号结尾，无后续内容=残缺）
_ADJ_CHAIN_DASH_RE = re.compile(r'([\u4e00-\u9fff]{1,6}的、[\u4e00-\u9fff]{1,6}的、)(?=[，。；！？\n]|$)')
# "X得。" / "X得，"残缺句（"声音干得。""干瘪得，""清晰得，"=形容词+得+标点，AI 输出残缺）
# 匹配"汉字+得+句号/感叹号/逗号"，lookbehind 紧贴"得"前，排除"觉得""记得""获得"
# 正常用法"跑得快，"不匹配（"得"后面是"快"不是标点）
_DE_BROKEN_RE = re.compile(r'([\u4e00-\u9fff])(?<![觉记获])得[。．！，,]')
# 单字残缺句（"又。""嗯。"独立成句=残缺或无意义短句）
# 匹配段首单字+句号（排除"好。""是。""对。"等正常应答词）
_SINGLE_CHAR_BROKEN_RE = re.compile(r'(?m)(?:^|\n)[ \t]*([\u4e00-\u9fff])[。．！][ \t]*(?:\n|$)')
# 名词+代词粘连（"心跳他开口了""嘴唇动了动又"=两句无标点粘连）
# 匹配"名词+他/她/它+动词"，缺逗号分隔
_NOUN_PRONOUN_FUSED_RE = re.compile(
    r'([^\s，。；！？、\n]{2,6})(他|她|它)(开口|闭眼|低头|抬头|转身|回头|看见|听见|感觉|知道|想|说|问|笑|哭|叹|皱|盯|看|望|站|坐|走|跑|停|动)')



def _is_clean_enabled() -> bool:
    """是否启用程序化清洗（config.yaml ai.text_clean.enabled，默认开启）"""
    try:
        from app.config import get as cfg
        return bool(cfg("ai.text_clean.enabled", True))
    except Exception:
        return True


# ==================== 引号占位保护 ====================

def _protect_quotes(text: str):
    """把引号内内容替换为 \x00N\x00 占位符，返回 (保护后文本, [(占位符, 原文), ...])"""
    placeholders = []

    def repl(m):
        ph = f"\x00{len(placeholders)}\x00"
        placeholders.append((ph, m.group(0)))
        return ph

    return _QUOTE_RE.sub(repl, text), placeholders


def _restore_quotes(text: str, placeholders) -> str:
    for ph, original in placeholders:
        text = text.replace(ph, original)
    return text


# ==================== 规则实现（均在超过阈值后触发） ====================

def _fix_dash(text: str, stats: dict) -> str:
    """破折号"——"压减：全文绝对保留 DASH_KEEP_ABS 个（默认0），其余按上下文替换为句号/逗号，段首删除"""
    if "——" not in text:
        return text
    limit = DASH_KEEP_ABS
    if text.count("——") <= limit:
        return text
    kept = 0
    replaced = 0
    out = []
    last_ch = ""
    i = 0
    n = len(text)
    while i < n:
        if text.startswith("——", i):
            if kept < limit:
                kept += 1
                out.append("——")
                last_ch = "—"
            elif not "".join(out).strip():
                pass  # 段首/句首破折号：直接删除（无内容可承接）
            elif last_ch in "。！？；!?;":
                out.append("。")  # 前文已是完整句 → 句号
                last_ch = "。"
            else:
                out.append("，")  # 常规：逗号承接（"不是X——是Y"→"不是X，是Y"）
                last_ch = "，"
            replaced += 1
            i += 2
            continue
        out.append(text[i])
        last_ch = text[i]
        i += 1
    if replaced:
        stats["dash"] = stats.get("dash", 0) + replaced
    return "".join(out)


def _fix_colon(text: str, stats: dict) -> str:
    """冒号"："压减：引语冒号（说：/道：）永远保留，普通冒号压到配额内"""
    if "：" not in text:
        return text
    quota = max(COLON_KEEP_COUNT, (len(text) // COLON_KEEP_PER_CHARS) * COLON_KEEP_COUNT)
    if text.count("：") <= quota:
        return text
    replaced = 0
    out = []
    last_ch = ""
    for ch in text:
        if ch == "：":
            if quota > 0:
                quota -= 1
                out.append(ch)
            elif last_ch and _SPEECH_TAIL_RE.search(last_ch):
                out.append(ch)  # 引语冒号超配额也保留
            else:
                out.append("，")
                replaced += 1
            last_ch = out[-1]
            continue
        out.append(ch)
        last_ch = ch
    if replaced:
        stats["colon"] = stats.get("colon", 0) + replaced
    return "".join(out)


def _fix_ellipsis(text: str, stats: dict) -> str:
    """省略号"……"压减：超出部分换句号；后跟断句符时直接删除"""
    if "……" not in text:
        return text
    quota = max(1, len(text) // ELLIPSIS_KEEP_PER_CHARS)
    if text.count("……") <= quota:
        return text
    replaced = 0
    out = []
    i = 0
    n = len(text)
    while i < n:
        if text.startswith("……", i):
            if quota > 0:
                quota -= 1
                out.append("……")
                i += 2
                continue
            if i + 2 < n and text[i + 2] in "。！？；!?;":
                pass  # 后跟断句符：省略号删除，避免"。。"重叠
            else:
                out.append("。")
                replaced += 1
            i += 2
            continue
        out.append(text[i])
        i += 1
    if replaced:
        stats["ellipsis"] = stats.get("ellipsis", 0) + replaced
    return "".join(out)


def _fix_exclaim(text: str, stats: dict) -> str:
    """感叹号"！"压减：叙述中超配额换句号（对话已被占位保护）"""
    quota = max(1, len(text) // EXCLAIM_KEEP_PER_CHARS)
    if text.count("！") <= quota:
        return text
    replaced = 0
    out = []
    for ch in text:
        if ch == "！":
            if quota > 0:
                quota -= 1
                out.append(ch)
            else:
                out.append("。")
                replaced += 1
        else:
            out.append(ch)
    if replaced:
        stats["exclaim"] = stats.get("exclaim", 0) + replaced
    return "".join(out)


def _fix_not_is(text: str, stats: dict) -> str:
    """"不是X，是Y"解释句式压减：全文最多保留1处（检测器红牌项），其余压缩为"是Y"（删否定补丁）"""
    matches = list(_NOT_IS_RE.finditer(text))
    if not matches:
        return text
    quota = NOT_IS_KEEP_MAX
    if len(matches) <= quota:
        return text
    replaced = 0
    out = []
    last = 0
    for idx, m in enumerate(matches):
        out.append(text[last:m.start()])
        if idx < quota:
            out.append(m.group(0))
        else:
            y = m.group(2)
            # 避免 "是是Y"；Y 以"是/而"开头时直接使用
            prefix = "" if y.startswith(("是", "而", "就")) else "是"
            out.append(prefix + y)
            replaced += 1
        last = m.end()
    out.append(text[last:])
    if replaced:
        stats["not_is"] = stats.get("not_is", 0) + replaced
    return "".join(out)


def _fix_not_is_dot(text: str, stats: dict) -> str:
    """句号版"不是X"压减（检测器红牌项，AI 爱用短句排比做强调）：
    - 句号三连"不是X。不是Y。是Z。"（含跨行）→ 出现即压缩为"是Z。"
    - 逗号三连"不是X，不是Y，是Z" → 出现即压缩为"是Z"
    - 两连"不是X。是Y。" → 全文最多保留 NOT_IS_KEEP_MAX 处
    压缩均删否定补丁留肯定句，语义保留。"""
    replaced = 0
    # --- 逗号版三连：出现即压缩（不是霉，不是灰，是更淡的什么 → 是更淡的什么）---
    m3c = list(_NOT_IS_COMMA3_RE.finditer(text))
    if m3c:
        out = []
        last = 0
        for m in m3c:
            out.append(text[last:m.start()])
            z = m.group(3)
            prefix = "" if z.startswith(("是", "而", "就")) else "是"
            out.append(prefix + z)
            replaced += 1
            last = m.end()
        out.append(text[last:])
        text = "".join(out)
    # --- 句号版三连：出现即压缩 ---
    m3 = list(_NOT_IS_DOT3_RE.finditer(text))
    if m3:
        out = []
        last = 0
        for m in m3:
            out.append(text[last:m.start()])
            z = m.group(3)
            prefix = "" if z.startswith(("是", "而", "就")) else "是"
            out.append(prefix + z + "。")
            replaced += 1
            last = m.end()
        out.append(text[last:])
        text = "".join(out)
    # --- 两连版：超过配额才压缩 ---
    m2 = list(_NOT_IS_DOT2_RE.finditer(text))
    if not m2 or len(m2) <= NOT_IS_KEEP_MAX:
        return text
    quota = NOT_IS_KEEP_MAX
    out = []
    last = 0
    for idx, m in enumerate(m2):
        out.append(text[last:m.start()])
        if idx < quota:
            out.append(m.group(0))
        else:
            y = m.group(2)
            prefix = "" if y.startswith(("是", "而", "就")) else "是"
            out.append(prefix + y + "。")
            replaced += 1
        last = m.end()
    out.append(text[last:])
    if replaced:
        stats["not_is_dot"] = stats.get("not_is_dot", 0) + replaced
    return "".join(out)


def _fix_triple(text: str, stats: dict) -> str:
    """三连排比拆散：
    - 顿号三连（X、Y、Z → X、Y，还有Z）
    - "像"字三连（像X，像Y，像Z → 像X和Y，还有Z，降"像"字密度）
    超过配额才处理（保留前 N 个不动）"""
    quota = max(1, len(text) // TRIPLE_KEEP_PER_CHARS)
    replaced = 0
    # --- 顿号三连 ---
    matches = list(_TRIPLE_RE.finditer(text))
    if matches and len(matches) > quota:
        out = []
        last = 0
        for idx, m in enumerate(matches):
            out.append(text[last:m.start()])
            if idx < quota:
                out.append(m.group(0))
            else:
                out.append(f"{m.group(1)}、{m.group(2)}，还有{m.group(3)}")
                replaced += 1
            last = m.end()
        out.append(text[last:])
        text = "".join(out)
    # --- "像"字三连（强 AI 特征：出现即拆，不保留配额） ---
    lm = list(_LIKE_TRIPLE_RE.finditer(text))
    if lm:
        out = []
        last = 0
        for m in lm:
            out.append(text[last:m.start()])
            out.append(f"像{m.group(1)}和{m.group(2)}，还有{m.group(3)}")
            replaced += 1
            last = m.end()
        out.append(text[last:])
        text = "".join(out)
    if replaced:
        stats["triple"] = stats.get("triple", 0) + replaced
    return text


def _fix_simile(text: str, stats: dict) -> str:
    """明喻词换形：超配额时把书面明喻词（仿佛/如同/宛如/犹如/好似）换成“像”"""
    total = sum(text.count(w) for w in _SIMILE_WORDS)
    quota = max(1, len(text) // SIMILE_KEEP_PER_CHARS)
    if total <= quota:
        return text
    need = total - quota
    replaced = 0
    for w in _SIMILE_WORDS:
        if need <= 0:
            break
        cnt = text.count(w)
        if cnt == 0:
            continue
        take = min(cnt, need)
        text = text.replace(w, "像", take)
        replaced += take
        need -= take
    if replaced:
        stats["simile"] = stats.get("simile", 0) + replaced
    return text


def _fix_like_density(text: str, stats: dict) -> str:
    """"像"字比喻密度压减：全文最多 LIKE_KEEP_MAX 个（检测器红牌项），
    超出的句尾补丁比喻（，像X。/ 像是X。）直接删除比喻部分（保留主干句），
    不再换成"跟X似的"（"跟X似的"本身也是AI检测红牌项）"""
    count = len(_LIKE_ISOLATED_RE.findall(text))
    if count <= LIKE_KEEP_MAX:
        return text
    need = count - LIKE_KEEP_MAX
    replaced = [0]

    def repl(m):
        if replaced[0] >= need:
            return m.group(0)
        replaced[0] += 1
        # 直接删除比喻部分，保留主干（前面的逗号也一起删）
        return ""

    new_text = _LIKE_PATCH_RE.sub(repl, text)
    # 清理删除后可能产生的多余逗号（"，。"→"。"）
    new_text = re.sub(r'，。', '。', new_text)
    new_text = re.sub(r'，，', '，', new_text)
    if replaced[0]:
        stats["like"] = replaced[0]
    return new_text


def _fix_abrupt_adverbs(text: str, stats: dict) -> str:
    """高频副词压减：忽然/突然/骤然/猛地/倏地/陡然
    - 同词局部密度：相同副词 ABRUPT_WINDOW 字内最多保留1个（"忽然"92字内3次→删超出的）
    - 全文配额兜底：每 ABRUPT_KEEP_PER_CHARS 字允许1个
    超出直接删除（靠动词与语境承接，删除后读感更"人"）"""
    hits = []
    for w in _ABRUPT_WORDS:
        start = 0
        while True:
            pos = text.find(w, start)
            if pos == -1:
                break
            hits.append((pos, w))
            start = pos + len(w)
    if not hits:
        return text
    hits.sort()
    # 1) 同词窗口密度
    remove_set = set()
    by_word = {}
    for pos, w in hits:
        by_word.setdefault(w, []).append(pos)
    for poss in by_word.values():
        last_keep = None
        for p in poss:
            if last_keep is None or p - last_keep >= ABRUPT_WINDOW:
                last_keep = p
            else:
                remove_set.add(p)
    # 2) 全文配额兜底
    quota = max(1, len(text) // ABRUPT_KEEP_PER_CHARS)
    kept = 0
    for pos, w in hits:
        if pos in remove_set:
            continue
        if kept < quota:
            kept += 1
        else:
            remove_set.add(pos)
    if not remove_set:
        return text
    # 3) 重建文本（删除的副词连后跟逗号一起删）
    out = []
    last = 0
    for pos, w in hits:
        if pos not in remove_set:
            continue
        out.append(text[last:pos])
        nxt = pos + len(w)
        if nxt < len(text) and text[nxt] == "，":
            last = nxt + 1
        else:
            last = nxt
    out.append(text[last:])
    stats["abrupt"] = stats.get("abrupt", 0) + len(remove_set)
    return "".join(out)


def _fix_conjunctions(text: str, stats: dict) -> str:
    """句首连接词压减：于是/因此/然后/接着/随即/继而/随后/旋即/不多时/紧接着 全文最多保留1个，
    超出部分删除（句首位置的连接词删除后语义损失最小，制造"硬跳转"）"""
    all_conj = _CONJ_WORDS + _CONJ_EXTRA_WORDS
    hits = []
    for w in all_conj:
        start = 0
        while True:
            pos = text.find(w, start)
            if pos == -1:
                break
            # 仅句首位置：前文（去空白）为空或以断句符结尾
            prev = text[:pos].rstrip(" \t\n")
            if not prev or prev[-1] in "。！？；!?;":
                hits.append((pos, w))
            start = pos + len(w)
    if not hits:
        return text
    hits.sort()
    if len(hits) <= CONJ_KEEP_MAX:
        return text
    kept = 0
    removed = 0
    out = []
    last = 0
    for pos, w in hits:
        out.append(text[last:pos])
        if kept < CONJ_KEEP_MAX:
            kept += 1
            out.append(w)
            last = pos + len(w)
        else:
            nxt = pos + len(w)
            if nxt < len(text) and text[nxt] == "，":
                last = nxt + 1
            else:
                last = nxt
            removed += 1
    out.append(text[last:])
    if removed:
        stats["conj"] = stats.get("conj", 0) + removed
    return "".join(out)


def _fix_simile_guides(text: str, stats: dict) -> str:
    """"那种…像/仿佛"引导句式清除：全文最多保留1处，其余删除"那种"二字
    （"那种像是要杀人的眼神" → "像是要杀人的眼神"，降模板感）"""
    matches = list(_GUIDE_RE.finditer(text))
    if not matches:
        return text
    if len(matches) <= GUIDE_KEEP_MAX:
        return text
    removed = 0
    out = []
    last = 0
    for idx, m in enumerate(matches):
        out.append(text[last:m.start()])
        if idx < GUIDE_KEEP_MAX:
            out.append(m.group(0))
        else:
            removed += 1  # 删除"那种"二字
        last = m.end()
    out.append(text[last:])
    if removed:
        stats["guide"] = stats.get("guide", 0) + removed
    return "".join(out)


def _fix_punct_bug(text: str, stats: dict) -> str:
    """标点连用修复："。，""，。""。。""！。" → 保留首个终止标点
    （AI 输出偶发的标点叠加，"是空的。，底下" → "是空的。底下"）
    限制 PUNCT_BUG_MAX 处，避免误伤引号边界。"""
    matches = list(_PUNCT_BUG_RE.finditer(text))
    if not matches:
        return text
    fixed = 0
    out = []
    last = 0
    for m in matches:
        if fixed >= PUNCT_BUG_MAX:
            break
        out.append(text[last:m.start()])
        out.append(text[m.start()])  # 保留首个标点
        last = m.end()
        fixed += 1
    out.append(text[last:])
    if fixed:
        stats["punct_bug"] = stats.get("punct_bug", 0) + fixed
    return "".join(out)


def _fix_comma_triple(text: str, stats: dict) -> str:
    """逗号版三连形容词拆散："粗重，沉闷，一下一下的" → "粗重沉闷，一下一下的"
    （AI 节奏排比；与顿号版 _TRIPLE_RE 互补，逗号版更隐蔽）
    全文保留 COMMA_TRIPLE_KEEP_MAX 处，其余把第一逗号删除（合并前两项）。"""
    matches = list(_COMMA_TRIPLE_RE.finditer(text))
    if not matches:
        return text
    removed = 0
    out = []
    last = 0
    for idx, m in enumerate(matches):
        out.append(text[last:m.start()])
        if idx < COMMA_TRIPLE_KEEP_MAX:
            out.append(m.group(0))
        else:
            # 合并前两项：A，B，C → AB，C
            out.append(m.group(1) + m.group(2) + "，" + m.group(3))
            removed += 1
        last = m.end()
    out.append(text[last:])
    if removed:
        stats["comma_triple"] = stats.get("comma_triple", 0) + removed
    return "".join(out)


def _fix_double_simile(text: str, stats: dict) -> str:
    """双重比喻标记去重："像是X似的" → "像X"
    （"像是"已表比喻，"似的"是冗余双标记，AI 高频特征）
    全文绝对清除（DOUBLE_SIMILE_KEEP_MAX=0）。"""
    if not _DOUBLE_SIMILE_RE.search(text):
        return text
    replaced = _DOUBLE_SIMILE_RE.subn(lambda m: "像" + m.group(1), text)[0]
    cnt = len(_DOUBLE_SIMILE_RE.findall(text))
    if cnt:
        stats["double_simile"] = stats.get("double_simile", 0) + cnt
    return replaced


def _fix_frame_simile(text: str, stats: dict) -> str:
    """双框比喻尾删除："仿佛X一般"/"如同X一般" → "仿佛X"/"如同X"
    （"一般"是冗余尾框，书卷气过重=AI 特征）
    全文保留 FRAME_SIMILE_KEEP_MAX 处。"""
    matches = list(_FRAME_SIMILE_RE.finditer(text))
    if not matches:
        return text
    removed = 0
    out = []
    last = 0
    for idx, m in enumerate(matches):
        out.append(text[last:m.start()])
        if idx < FRAME_SIMILE_KEEP_MAX:
            out.append(m.group(0))
        else:
            out.append(m.group(1) + m.group(2))
            removed += 1
        last = m.end()
    out.append(text[last:])
    if removed:
        stats["frame_simile"] = stats.get("frame_simile", 0) + removed
    return "".join(out)


def _fix_sentence_broken(text: str, stats: dict) -> str:
    """句子残缺修复："X的、。""X、。"（顿号/逗号后直接句号）→ 删除悬空的顿号/逗号
    （AI 输出 bug："尖细的、。"→"尖细的。"；"湿漉漉的、。"→"湿漉漉的。"）
    全文最多修 SENTENCE_BROKEN_MAX 处（避免误伤引号边界）。"""
    matches = list(_SENTENCE_BROKEN_RE.finditer(text))
    if not matches:
        return text
    fixed = 0
    out = []
    last = 0
    for m in matches:
        if fixed >= SENTENCE_BROKEN_MAX:
            break
        # 删除悬空的顿号/逗号（m.start() 是顿号/逗号位置）
        out.append(text[last:m.start()])
        out.append(text[m.end() - 1])  # 保留句号
        last = m.end()
        fixed += 1
    out.append(text[last:])
    if fixed:
        stats["sentence_broken"] = stats.get("sentence_broken", 0) + fixed
    return "".join(out)


def _fix_adj_chain_dash(text: str, stats: dict) -> str:
    """顿号形容词链悬空修复："X的、Y的、"（以顿号结尾无后续）→ 删除尾部顿号
    （AI 输出 bug："那种没来由的、尖细的、"→"那种没来由的、尖细的"）
    全文最多修 ADJ_CHAIN_DASH_MAX 处。"""
    matches = list(_ADJ_CHAIN_DASH_RE.finditer(text))
    if not matches:
        return text
    fixed = 0
    out = []
    last = 0
    for m in matches:
        if fixed >= ADJ_CHAIN_DASH_MAX:
            break
        out.append(text[last:m.end() - 1])  # 保留到第二个"的"，删尾部顿号
        last = m.end()
        fixed += 1
    out.append(text[last:])
    if fixed:
        stats["adj_chain_dash"] = stats.get("adj_chain_dash", 0) + fixed
    return "".join(out)


def _strip_redundant_subject_in_line(line: str, budget: list) -> str:
    """单行内：连续两句以同一主语开头 → 删除后句主语（制造无主语句/碎片句）。
    budget 为剩余可删除次数（跨行共享）"""
    sents = list(_SENT_END_RE.finditer(line))
    if len(sents) < 2 or budget[0] <= 0:
        return line
    changes = []
    for i in range(1, len(sents)):
        prev_s = sents[i - 1].group(0)
        cur_s = sents[i].group(0)
        m_cur = _SUBJECT_ACTION_RE.match(cur_s)
        if not m_cur:
            continue
        subj = m_cur.group(1)
        if prev_s.lstrip().startswith(subj):
            changes.append(sents[i].start() + m_cur.start())
            budget[0] -= 1
            if budget[0] <= 0:
                break
    if not changes:
        return line
    chars = list(line)
    for pos in sorted(changes, reverse=True):
        del chars[pos:pos + len(_SUBJECT_ACTION_RE.match(line[pos:]).group(1))]
    return "".join(chars)


def _fix_redundant_subject(text: str, stats: dict) -> str:
    """冗余主语删除：连续两句同主语 → 后句删主语（"他抬起头。他看见……" → "他抬起头。看见……"），
    制造无主语句，打破"连续3句主谓宾完整"的 AI 基础句式模板。全文最多 SUBJECT_REMOVE_MAX 处"""
    budget = [SUBJECT_REMOVE_MAX]
    lines = text.split("\n")
    out = []
    changed = 0
    for line in lines:
        if budget[0] <= 0:
            out.append(line)
            continue
        new_line = _strip_redundant_subject_in_line(line, budget)
        if new_line != line:
            changed += 1
        out.append(new_line)
    if changed:
        stats["subject"] = stats.get("subject", 0) + changed
        return "\n".join(out)
    return text


def _fix_buffer_paragraphs(text: str, stats: dict) -> str:
    """缓冲垫短段消除：AI 在节奏切换时用"沉默。""空气安静了。"独立成段做软着陆。
    检测夹在中间、≤14字、含缓冲词、以句号结尾的短段：
    - 下一段非对话 → 并入下一段开头（硬切）
    - 下一段是对话 → 回退并入前一段末尾（保留语义，去掉独立成段）"""
    paras = text.split("\n\n")
    if len(paras) < 3:
        return text
    merged = 0
    out = []
    i = 0
    n = len(paras)
    while i < n:
        seg = paras[i]
        stripped = seg.strip()
        if (0 < i < n - 1 and "\x00" not in seg
                and len(stripped) <= BUFFER_MAX_LEN
                and any(w in stripped for w in _BUFFER_WORDS)
                and stripped.endswith(("。", "……"))):
            nxt = paras[i + 1]
            nxt_head = nxt.lstrip()[:1]
            if nxt_head not in ("”", "“", "\x00"):
                # 下一段可承接 → 并入下一段开头
                paras[i + 1] = stripped + nxt
                merged += 1
                i += 1
                continue
            # 下一段是对话 → 并入前一段末尾（前段结尾需是普通标点）
            if out:
                prev_tail = out[-1].rstrip()
                if prev_tail and prev_tail[-1] not in ("”", "“", "\x00"):
                    out[-1] = prev_tail + stripped
                    merged += 1
                    i += 1
                    continue
        out.append(seg)
        i += 1
    if merged:
        stats["buffer"] = stats.get("buffer", 0) + merged
        return "\n\n".join(out)
    return text


def _fix_longlist(text: str, stats: dict) -> str:
    """顿号4+连拆散：AI 扫描式列举（屋顶、木梁、裂缝、苔藓）→ 第3项后断开"""
    matches = list(_LONGLIST_RE.finditer(text))
    if not matches:
        return text
    replaced = 0
    out = []
    last = 0
    for m in matches:
        out.append(text[last:m.start()])
        out.append(m.group(1) + m.group(2) + "，还有" + m.group(4))
        replaced += 1
        last = m.end()
    out.append(text[last:])
    if replaced:
        stats["longlist"] = stats.get("longlist", 0) + replaced
    return "".join(out)


def _merge_short_sents_in_line(line: str, budget: int) -> tuple:
    """行内连续短句合并：相邻两个 ≤7字 句号短句（不含对话）→ 前句句号改逗号。
    每行最多合并1处；优先合并"中间短句对"（两端短句保留，制造短-中-中节奏）"""
    if budget <= 0:
        return line, 0
    matches = list(_SHORT_SENT_RE.finditer(line))
    if len(matches) < 2:
        return line, 0
    # 收集相邻短句对（m1 的句号紧接 m2 开头，且都不含对话占位）
    pairs = []
    for i in range(len(matches) - 1):
        m1, m2 = matches[i], matches[i + 1]
        if m1.end() != m2.start():
            continue
        if "\x00" in m1.group(0) or "\x00" in m2.group(0):
            continue
        # 跳过"不是X。是Y。"句号版：合并会造出新的"不是X，是Y"，绕过 not_is 配额
        if m1.group(0).startswith("不是") and m2.group(0).lstrip("嗯啊哦").startswith(("而是", "就是", "是")):
            continue
        pairs.append((m1, m2))
    if not pairs:
        return line, 0
    # 优先合并"中间短句对"（两端短句保留），只有一对时合并它
    target = pairs[1] if len(pairs) > 1 else pairs[0]
    m1, m2 = target
    chars = list(line)
    pos = m1.end() - 1
    if chars[pos] == "。":
        chars[pos] = "，"
        return "".join(chars), 1
    return line, 0


def _fix_short_sentence_tail(text: str, stats: dict) -> str:
    """连续短句合并：AI 心理标签（"慌乱。一闪而过。"）与工整短句收尾
    （"药味还在。胸口还在疼。"）的短句排比 → 前句句号改逗号，打断等长节奏。
    全文最多 SHORTTAIL_MAX 处"""
    budget = SHORTTAIL_MAX
    lines = text.split("\n")
    out = []
    changed = 0
    for line in lines:
        if budget <= 0:
            out.append(line)
            continue
        new_line, used = _merge_short_sents_in_line(line, budget)
        if used:
            budget -= used
            changed += used
        out.append(new_line)
    if changed:
        stats["shorttail"] = stats.get("shorttail", 0) + changed
        return "\n".join(out)
    return text


def _fix_emotion_label(text: str, stats: dict) -> str:
    """情绪标签词独立段删除：检测器红牌"直接贴情绪标签"
    （"慌乱。""震惊。"裸情绪词独立成段 = AI 在完成写作任务，不留给读者推演；
    手册原例："慌乱。一闪而过。"）。
    只删整段只有一个情绪词的裸段（带主语/修饰语的不动），删后前后段自然衔接。"""
    lines = text.split("\n")
    out = []
    removed = 0
    for line in lines:
        if _EMOTION_LABEL_RE.match(line):
            removed += 1
            continue
        out.append(line)
    if not removed:
        return text
    # 清理删除后产生的连续空行
    res = []
    prev_empty = False
    for line in out:
        empty = not line.strip()
        if empty and prev_empty:
            continue
        res.append(line)
        prev_empty = empty
    stats["emotion"] = stats.get("emotion", 0) + removed
    return "\n".join(res)


def _fix_even_paragraphs(text: str, stats: dict) -> str:
    """段落均匀拆段：所有段落长度都在 [PARAGRAPH_EVEN_MIN, PARAGRAPH_EVEN_MAX] 且
    长度差 ≤ DELTA（AI 段落均匀强迫症）→ 拆最长段，在安全逗号处断成两段"""
    paras = text.split("\n\n")
    if len(paras) < 3:
        return text
    lens = [len(p) for p in paras]
    valid = [x for x in lens if x > 0]
    if len(valid) < 3:
        return text
    if max(valid) > PARAGRAPH_EVEN_MAX or min(valid) < PARAGRAPH_EVEN_MIN:
        return text
    if max(valid) - min(valid) > PARAGRAPH_EVEN_DELTA:
        return text
    idx = lens.index(max(lens))
    seg = paras[idx]
    commas = [pos for pos, ch in enumerate(seg) if ch == "，"]
    cut = None
    for pos in commas:
        # 拆点前后各留至少15字（约半行），避免碎段
        if 15 <= pos and len(seg) - pos - 1 >= 15:
            nxt = seg[pos + 1:pos + 3].strip()
            if nxt and nxt[0] not in "的地得和与及而且并":
                cut = pos
                break
    if cut is None:
        return text
    paras[idx] = seg[:cut] + "。\n\n" + seg[cut + 1:]
    stats["paragraph"] = stats.get("paragraph", 0) + 1
    return "\n\n".join(paras)


def _break_even_in_line(line: str) -> str:
    """单行内：连续3句长度相近（过于均匀）→ 中间句在逗号处拆句，提升突发性"""
    sents = list(_SENT_END_RE.finditer(line))
    if len(sents) < 3:
        return line
    lens = [m.end() - m.start() for m in sents]
    changes = []
    i = 0
    while i + 2 < len(sents):
        a, b, c = lens[i], lens[i + 1], lens[i + 2]
        if (18 <= a <= 60 and 18 <= b <= 60 and 18 <= c <= 60
                and max(a, b, c) - min(a, b, c) <= 12):
            mid = sents[i + 1]
            seg = line[mid.start():mid.end()]
            pos = seg.find("，")
            # 拆后两边都不要太短，避免碎句
            if 8 <= pos and len(seg) - pos - 1 >= 8:
                changes.append(mid.start() + pos)
                i += 3  # 跳过已处理窗口，避免连环拆
                continue
        i += 1
    if not changes:
        return line
    chars = list(line)
    for p in changes:
        chars[p] = "。"
    return "".join(chars)


def _fix_even_sentences(text: str, stats: dict) -> str:
    """均匀长句拆短（burstiness 核心）：逐行处理，跨行不误判"""
    lines = text.split("\n")
    changed = 0
    out = []
    for line in lines:
        new_line = _break_even_in_line(line)
        if new_line != line:
            changed += 1
        out.append(new_line)
    if changed:
        stats["burst"] = stats.get("burst", 0) + changed
        return "\n".join(out)
    return text


def _fix_repeated_sentences(text: str, stats: dict) -> str:
    """完全重复短句压减：AI 反复用同一环境短句做节奏垫（"烛火又跳了一下。"出现4次、
    "和之前一样。"重复），检测器统计到整句完全重复即红牌。
    处理：3~14字、句号结尾、完全相同 ≥2 次 → 只保留第1次，其余删除（靠上下文承接）。
    仅处理叙述（对话已被占位保护）；删除后清理连续空行。"""
    pat = re.compile(r'[^。！？；\n]{3,%d}。' % REPEAT_SENT_MAX_LEN)
    matches = list(pat.finditer(text))
    if len(matches) < 2:
        return text
    groups = {}
    for m in matches:
        s = m.group(0)
        if "\x00" in s:
            continue  # 跳过含对话占位符的句子
        groups.setdefault(s, []).append((m.start(), m.end()))
    removals = []
    removed = 0
    for s, ms in groups.items():
        if len(ms) < REPEAT_TRIGGER:
            continue
        for start, end in ms[REPEAT_KEEP:]:
            removals.append((start, end))
            removed += 1
    if not removed:
        return text
    removals.sort(reverse=True)
    for start, end in removals:
        text = text[:start] + text[end:]
    text = re.sub(r'\n{3,}', '\n\n', text)  # 清理空段
    stats["repeat"] = stats.get("repeat", 0) + removed
    return text


def _fix_duplicate_paragraphs(text: str, stats: dict) -> str:
    """段落级大段雷同删除（第23条）：相邻或跨段出现连续≥16字相同（复制粘贴/大段复述），
    且重复部分占较短段≥40% → 删掉后出现的段落（保留首次出现）。
    七猫等平台检测"相邻或跨段出现大段雷同、复述或复制粘贴式重复"即此问题。
    仅处理叙述段（对话已被占位保护，含占位符的段跳过）。"""
    paras = text.split("\n\n")
    if len(paras) < 2:
        return text
    n = DUP_NGRAM_LEN

    def _grams(s: str) -> set:
        s = s.strip()
        if "\x00" in s or len(s) < n:
            return set()
        return {s[i:i + n] for i in range(len(s) - n + 1)}

    para_grams = [_grams(p) for p in paras]
    keep = [True] * len(paras)
    removed = 0
    budget = DUP_PARA_MAX
    seen = {}  # gram -> 首次出现的段落idx
    for i, pg in enumerate(para_grams):
        if not pg:
            continue
        dup_prev = -1
        for g in pg:
            prev = seen.get(g)
            if prev is not None and keep[prev] and prev != i:
                shared = pg & para_grams[prev]
                if shared:
                    shorter = min(len(paras[i].strip()), len(paras[prev].strip()))
                    if shorter > 0 and len(shared) * n / shorter >= DUP_PARA_MIN_RATIO:
                        dup_prev = prev
                        break
        if dup_prev >= 0:
            keep[i] = False
            removed += 1
            budget -= 1
            if budget <= 0:
                break
        else:
            for g in pg:
                seen.setdefault(g, i)
    if removed:
        out = [p for p, k in zip(paras, keep) if k]
        stats["dup_para"] = stats.get("dup_para", 0) + removed
        return "\n\n".join(out)
    return text


def _fix_word_variants(text: str, stats: dict) -> str:
    """标签词重复压减（第7类红牌）：同一环境词全文高频（"烛火"13次），
    超过 WORD_KEEP_MAX 次后替换为同义变体（火苗/烛焰/灯焰交替）。
    仅作用于叙述（对话已被占位保护）。"""
    changed = 0
    for word, variants in _WORD_VARIANTS:
        positions = [m.start() for m in re.finditer(re.escape(word), text)]
        if len(positions) <= WORD_KEEP_MAX:
            continue
        chars = list(text)
        vi = 0
        for i, pos in enumerate(positions):
            if i < WORD_KEEP_MAX:
                continue
            v = variants[vi % len(variants)]
            chars[pos:pos + len(word)] = v
            vi += 1
            changed += 1
        text = "".join(chars)
    if changed:
        stats["word"] = stats.get("word", 0) + changed
    return text


def _fix_para_head_subject(text: str, stats: dict) -> str:
    """段首主语重复压减（第5类红牌："他……他……他……"连续同开头）：
    连续 ≥2 段以同一主语开头 → 第2段起删段首主语，制造无主语句（碎片句）。
    对话段（占位符开头）跳过；删后剩余需以动词/标点开头且不太短。"""
    paras = text.split("\n\n")
    if len(paras) < 2:
        return text
    removed = 0
    budget = PARA_HEAD_MAX
    prev_subj = None
    out = []
    for seg in paras:
        head = seg.lstrip()
        if budget > 0 and head and head[0] not in ("\x00", "“", "「", "」"):
            subj = None
            for s in _PARA_SUBJECTS:
                if head.startswith(s):
                    subj = s
                    break
            if subj is not None and subj == prev_subj:
                rest = head[len(subj):]
                if len(rest.strip()) >= 4 and not rest.startswith(("的", "地", "得")):
                    seg = seg.replace(subj, "", 1)
                    removed += 1
                    budget -= 1
                    prev_subj = None
                else:
                    prev_subj = subj
            else:
                prev_subj = subj
        else:
            prev_subj = None
        out.append(seg)
    if removed:
        stats["para_head"] = stats.get("para_head", 0) + removed
        return "\n\n".join(out)
    return text


def _fix_adj_independent(text: str, stats: dict) -> str:
    """形容词独立段并入下段："粗重的。""干涩的。"独立成段 → 并入下一段开头
    （AI 标签式节奏模板；与 _fix_emotion_label 互补，但此处处理非情绪的形容词）
    全文最多并入 ADJ_INDEP_MAX 处，避免过度改写段落结构。"""
    if not _ADJ_INDEP_RE.search(text):
        return text
    paras = text.split("\n\n")
    if len(paras) < 2:
        return text
    merged = 0
    out = []
    i = 0
    while i < len(paras):
        seg = paras[i]
        # 当前段是形容词独立段，且未超配额，且有下一段可并入
        if (merged < ADJ_INDEP_MAX
                and _ADJ_INDEP_RE.match(seg.strip())
                and i + 1 < len(paras)
                and paras[i + 1].strip()):
            # 去掉独立段的句号，并入下一段开头
            adj = seg.strip().rstrip("。．！").rstrip()
            out.append(adj + "，" + paras[i + 1].lstrip())
            merged += 1
            i += 2  # 跳过下一段（已并入）
        else:
            out.append(seg)
            i += 1
    if merged:
        stats["adj_indep"] = stats.get("adj_indep", 0) + merged
        return "\n\n".join(out)
    return text


def _fix_short_action_burst(text: str, stats: dict) -> str:
    """短动作连排合并："碎了。塌了。散了。"（动词+了+句号连续≥3）→ "碎了，塌了，散了。"
    （AI 节奏模板：连续短动作独立成句制造紧凑感，人类会用逗号一气呵成）
    全文最多处理 SHORT_ACTION_BURST_MAX 处。"""
    matches = list(_SHORT_ACTION_BURST_RE.finditer(text))
    if not matches:
        return text
    fixed = 0
    out = []
    last = 0
    for m in matches:
        if fixed >= SHORT_ACTION_BURST_MAX:
            break
        out.append(text[last:m.start()])
        chunk = m.group(1)
        # 把内部的句号换成逗号，末尾句号保留
        inner = chunk[:-1].replace("。", "，").replace("！", "，")
        out.append(inner + chunk[-1])
        last = m.end()
        fixed += 1
    out.append(text[last:])
    if fixed:
        stats["short_action_burst"] = stats.get("short_action_burst", 0) + fixed
    return "".join(out)


# ==================== 入口 ====================

def clean_generated_text(text: str) -> tuple:
    """程序化清洗入口

    :param text: 模型生成的章节正文
    :return: (清洗后文本, 统计dict)；统计为空表示未启用/无需清洗
    """
    if not text or not text.strip():
        return text, {}
    if not _is_clean_enabled():
        return text, {}
    stats = {}
    # ---- 阶段一：全文级（含对话）标点/句式规则 ----
    # AI 特征大量藏在台词里（"我记住了——那些不说话的""不是三年五年。是三百年。"），
    # 必须先于引号占位保护执行，否则对话内的破折号/"不是X"全部漏洗
    text = _fix_dash(text, stats)
    text = _fix_not_is(text, stats)
    text = _fix_not_is_dot(text, stats)
    text = _fix_triple(text, stats)
    text = _fix_longlist(text, stats)
    text = _fix_simile(text, stats)
    text = _fix_like_density(text, stats)
    text = _fix_abrupt_adverbs(text, stats)
    text = _fix_simile_guides(text, stats)
    # 新增阶段一规则（标点修复/逗号三连/双重比喻/双框比喻/句子残缺/形容词链悬空）
    text = _fix_punct_bug(text, stats)
    text = _fix_comma_triple(text, stats)
    text = _fix_double_simile(text, stats)
    text = _fix_frame_simile(text, stats)
    text = _fix_sentence_broken(text, stats)
    text = _fix_adj_chain_dash(text, stats)
    # ---- 阶段二：引号保护后，句法/段落级规则（不伤对话） ----
    protected, placeholders = _protect_quotes(text)
    protected = _fix_colon(protected, stats)
    protected = _fix_ellipsis(protected, stats)
    protected = _fix_exclaim(protected, stats)
    protected = _fix_conjunctions(protected, stats)
    protected = _fix_redundant_subject(protected, stats)
    protected = _fix_short_sentence_tail(protected, stats)
    protected = _fix_buffer_paragraphs(protected, stats)
    protected = _fix_emotion_label(protected, stats)
    protected = _fix_even_paragraphs(protected, stats)
    protected = _fix_even_sentences(protected, stats)
    protected = _fix_duplicate_paragraphs(protected, stats)
    protected = _fix_repeated_sentences(protected, stats)
    protected = _fix_word_variants(protected, stats)
    protected = _fix_para_head_subject(protected, stats)
    # 新增阶段二规则（形容词独立段并入/短动作连排合并）
    protected = _fix_adj_independent(protected, stats)
    protected = _fix_short_action_burst(protected, stats)
    result = _restore_quotes(protected, placeholders)
    if stats:
        total = sum(stats.values())
        system_logger.info(f"[程序化清洗] 共替换 {total} 处: {stats}")
    return result, stats


# ==================== 内容层 AI 特征超标检测（供 LLM 定向改写触发） ====================
# 程序化清洗管不了内容层（比字/对仗/跟X似的/否定排队），但可以"检出"超标项，
# 交给生成流程里的轻量模型定向改写（见 chapter_service._rewrite_ai_features）。
# 纯代码检测，无 LLM 依赖。
# "比X+形容词"比较句（"比我的大""比我们都旧"；口语"总比饿死强"也会计入，占比小可容忍）
_BI_RE = re.compile(r'比[^，。；！？\n]{1,8}(?:大|旧|早|强|高|深|宽|重|快|慢|多|少|远|近|久|新|小|短|好|差|热|冷|亮|暗|长|粗|细)')
# "跟X似的"比喻（内容层红牌：全章最多1处）
_GENXI_RE = re.compile(r'跟[^。，；！？\n]{1,20}似的')
# 否定排队（"不知道。不知道。"连续短句 ≥2 次）
_NEG_QUEUE_RE = re.compile(r'(?:不知道[。！]){2,}')
# 比喻句式扩展检测：像X/跟X一样/仿佛X/犹如X/好似X（用于段落级密度统计，区别于 _GENXI_RE 的总量口径）
# 覆盖"像X一样/似的/般"和"像X+动词"（如"像金属被腐蚀了一半"）两种结构
_METAPHOR_RE = re.compile(r'(?:像[^，。；！？\n]{1,24}(?:一样|似的|般)?|跟[^。，；！？\n]{1,20}(?:一样|似的)|仿佛[^，。；！？\n]{1,20}[的样]?|犹如[^，。；！？\n]{1,20}|好似[^，。；！？\n]{1,20})')
# "是X。"判断句独立成段（"是陈述。""是它在动。""是链条本身在降温。"段首独立短句=冷峻模板感）
# 匹配段落开头的"是X。"短句（X 不含句号，长度 2-20 字），后可跟换行或同段其他内容
_IS_JUDGE_RE = re.compile(r'(?m)(?:^|\n)[ \t]*是[^，。；！？\n]{1,20}[。．]')
# 推理展开：情绪/语气判断句后紧跟"是..."的解释链（"是陈述。是等了很久..."）
_REASONING_CHAIN_RE = re.compile(r'是[^，。；！？\n]{1,12}[。．]\s*是[^，。；！？\n]{4,40}[。．]')
# 台词对仗候选：连续两句台词字数差 ≤2 且都 ≤14 字（"比我的大。""也比我的旧。"）
# ---- 新增检测正则（交 LLM 改写） ----
# "没有X，没有Y，只有Z" 三连否定排比（"没有恐惧，没有厌恶，只有熟悉感"=AI 情绪层次模板）
_NEG_HAVE3_RE = re.compile(r'没有([^，。；！？\n]{1,10})[，,]\s*没有([^，。；！？\n]{1,10})[，,]\s*(?:只有|就是|是)([^，。；！？\n]{1,30})')
# "某种X""说不清的X" 半解释（骑墙描写=AI 怕说死又怕说太死的特征）
_HALF_EXPLAIN_RE = re.compile(r'某种[^，。；！？\n]{1,20}|说不清[的了]?[^，。；！？\n]{0,20}|某种说不清的[^，。；！？\n]{1,20}')
# 书面连词超频（不仅X而且Y / 既X又Y / 与其X不如Y / 与其说X不如说Y）
_FORMAL_CONJ_RE = re.compile(r'不仅[^，。；！？\n]{1,20}[，,]?\s*(?:而且|还|也)|既[^，。；！？\n]{1,15}又[^，。；！？\n]{1,15}|与其(?:说)?[^，。；！？\n]{1,20}(?:不如|莫如)(?:说)?')
# 四字格密度（单段内"[\u4e00-\u9fff]{4}，/、"≥3 个=成语堆砌）
_IDIOM_QUAD_RE = re.compile(r'[\u4e00-\u9fff]{4}[，、]')


def check_ai_features(text: str) -> dict:
    """内容层 AI 特征超标检测（红牌口径，超配额才列入报告）：
    - 比字比较句：每300字上限2个（手册"比"字密度）
    - 跟X似的：全章最多1处
    - 否定排队："不知道。不知道。"连续出现
    - 情绪标签独立段：清洗后不应残留
    - 段落大段雷同：相邻/跨段连续≥16字相同（七猫"复制粘贴式重复"驳回项），清洗后不应残留
    返回 {特征名: 数量}，全达标返回空 dict。
    程序化删不动这些（伤语义），需由 LLM 定向改写或生成端规避。"""
    report = {}
    bi = len(_BI_RE.findall(text))
    quota_bi = max(2, len(text) // 300)
    if bi > quota_bi:
        report["比字比较句"] = bi
    genxi = len(_GENXI_RE.findall(text))
    if genxi > 1:
        report["跟X似的"] = genxi
    neg = len(_NEG_QUEUE_RE.findall(text))
    if neg:
        report["否定排队"] = neg
    emo = len(_EMOTION_LABEL_RE.findall(text))
    if emo:
        report["情绪标签独立段"] = emo
    # 台词对仗：相邻两句台词都含"比X+形容词"且长度差≤2（"比我的大。""也比我的旧。"成对=对仗红牌）
    try:
        quotes = re.findall(r'“[^”\n]{2,24}”', text)
        pairs = 0
        for i in range(len(quotes) - 1):
            a, b = quotes[i], quotes[i + 1]
            if abs(len(a) - len(b)) <= 2 and _BI_RE.search(a) and _BI_RE.search(b):
                pairs += 1
        if pairs:
            report["台词对仗"] = pairs
    except Exception:
        pass
    # 一问一答剧本式：连续3句以上台词"问？答。问？"且台词之间零叙述紧邻
    # （"多远？""两刻钟。""现在走？""现在走。"连排=剧本节拍；
    #  中间插了动作"女人没回头"就不算）
    try:
        parts = re.split(r'([“”][^“”\n]{1,24}[“”])', text)
        seq = []
        for idx in range(1, len(parts), 2):
            body = parts[idx].strip("“”")
            if body.endswith("？"):
                kind = "Q"
            elif body.endswith("。") or body.endswith("！"):
                kind = "A"
            else:
                kind = "O"
            gap = parts[idx - 1] if idx > 0 else ""
            seq.append((kind, not gap.strip()))
        qa = 0
        for i in range(len(seq) - 2):
            if (seq[i][0] == "Q" and seq[i + 1][0] == "A" and seq[i + 2][0] == "Q"
                    and seq[i + 1][1] and seq[i + 2][1]):
                qa += 1
                break
        if qa:
            report["一问一答剧本式"] = qa
    except Exception:
        pass
    # 段落级大段雷同检测（七猫"相邻或跨段大段雷同/复述"驳回项）
    try:
        paras = [p.strip() for p in text.split("\n\n") if p.strip()]
        _n = DUP_NGRAM_LEN
        pg_list = []
        for p in paras:
            if "\x00" in p or len(p) <= _n:
                pg_list.append(set())
            else:
                pg_list.append({p[i:i + _n] for i in range(len(p) - _n + 1)})
        seen_g = {}
        dup_cnt = 0
        for i, pg in enumerate(pg_list):
            if not pg:
                continue
            is_dup = False
            for g in pg:
                prev = seen_g.get(g)
                if prev is not None and prev != i:
                    shared = pg & pg_list[prev]
                    if shared:
                        shorter = min(len(paras[i]), len(paras[prev]))
                        if shorter > 0 and len(shared) * _n / shorter >= DUP_PARA_MIN_RATIO:
                            is_dup = True
                            break
            if is_dup:
                dup_cnt += 1
            else:
                for g in pg:
                    seen_g.setdefault(g, i)
        if dup_cnt:
            report["段落大段雷同"] = dup_cnt
    except Exception:
        pass
    # 比喻密度超标检测（红牌：按密度比率，每 1000 字允许 1 处，全章上限 3 处）
    # 含「像X一样/似的/般」「跟X一样/似的」「仿佛X」「犹如X」「好似X」+「跟X似的」
    # AI 强特征：同一段落内比喻句式扎堆，检测器对密度敏感
    try:
        all_metaphors = _METAPHOR_RE.findall(text) + _GENXI_RE.findall(text)
        # 动态阈值：每 1000 字允许 1 处，至少允许 2 处，最多允许 5 处
        text_len = max(len(text), 1)
        quota = max(2, min(5, text_len // 1000))
        if len(all_metaphors) > quota:
            report["比喻密度超标"] = len(all_metaphors)
        # 单段密度：任一段落超 2 处即标记（段落级不受全章配额影响）
        paras_m = [p for p in re.split(r'\n\s*\n', text) if p.strip()]
        dense_para_cnt = 0
        for p in paras_m:
            mc = len(_METAPHOR_RE.findall(p)) + len(_GENXI_RE.findall(p))
            if mc > 2:
                dense_para_cnt += 1
        if dense_para_cnt:
            report["段落比喻扎堆"] = dense_para_cnt
    except Exception:
        pass
    # "是X。"判断句独立成段检测（红牌：连续段落以"是X。"开头=冷峻模板感）
    # AI 强特征：用"是陈述。""是它在动。"独立成段制造冷峻，密度高了是模板
    try:
        is_judges = _IS_JUDGE_RE.findall(text)
        if len(is_judges) > 2:
            report["判断句排比"] = len(is_judges)
    except Exception:
        pass
    # 推理展开链检测（红牌：情绪/语气判断后紧跟"是..."解释链）
    # AI 强特征："是陈述。是等了很久很久..."这种判断+解释枚举是教科书式推理
    try:
        chains = _REASONING_CHAIN_RE.findall(text)
        if chains:
            report["推理展开链"] = len(chains)
    except Exception:
        pass
    # "没有X，没有Y，只有Z" 三连否定排比检测（AI 情绪层次模板）
    try:
        neg3 = _NEG_HAVE3_RE.findall(text)
        if len(neg3) > NEG_HAVE3_MAX:
            report["三连否定排比"] = len(neg3)
    except Exception:
        pass
    # "某种X""说不清的X" 半解释检测（AI 骑墙描写）
    try:
        half = _HALF_EXPLAIN_RE.findall(text)
        if len(half) > HALF_EXPLAIN_MAX:
            report["半解释骑墙"] = len(half)
    except Exception:
        pass
    # 书面连词超频检测（不仅/既又/与其不如）
    try:
        formal = _FORMAL_CONJ_RE.findall(text)
        if len(formal) > FORMAL_CONJ_MAX:
            report["书面连词超频"] = len(formal)
    except Exception:
        pass
    # 四字格密度检测（单段内≥3个"XXXX，/、"=成语堆砌）
    try:
        paras_idiom = [p for p in re.split(r'\n\s*\n', text) if p.strip()]
        dense_idiom_cnt = 0
        for p in paras_idiom:
            if len(_IDIOM_QUAD_RE.findall(p)) >= IDION_QUAD_DENSITY_MAX:
                dense_idiom_cnt += 1
        if dense_idiom_cnt:
            report["四字格堆砌"] = dense_idiom_cnt
    except Exception:
        pass
    # 短句独立段密度检测（≤12字独立段占比>15%=AI 节奏模板）
    try:
        paras_short = [p.strip() for p in text.split("\n\n") if p.strip()]
        if paras_short:
            short_cnt = sum(1 for p in paras_short if len(p) <= 12)
            ratio = short_cnt / len(paras_short)
            if ratio > SHORT_PARA_DENSITY_MAX:
                report["短句独立段密度"] = round(ratio, 2)
    except Exception:
        pass
    # 句子残缺检测（"X的、。"顿号/逗号后直接句号=AI 输出 bug）
    try:
        broken = _SENTENCE_BROKEN_RE.findall(text)
        if len(broken) > SENTENCE_BROKEN_MAX:
            report["句子残缺"] = len(broken)
    except Exception:
        pass
    # 句子粘连检测（两句无标点直接连"涌出来不是渗"）
    try:
        fused = _SENTENCE_FUSED_RE.findall(text)
        if len(fused) > SENTENCE_FUSED_MAX:
            report["句子粘连"] = len(fused)
    except Exception:
        pass
    # 顿号形容词链悬空检测（"X的、Y的、"结尾=残缺）
    try:
        chains = _ADJ_CHAIN_DASH_RE.findall(text)
        if len(chains) > ADJ_CHAIN_DASH_MAX:
            report["形容词链悬空"] = len(chains)
    except Exception:
        pass
    # "X得。"残缺句检测（"声音干得。""平得。"=形容词+得+句号残缺）
    try:
        de_broken = _DE_BROKEN_RE.findall(text)
        if de_broken:
            report["得字残缺句"] = len(de_broken)
    except Exception:
        pass
    # 单字残缺句检测（"又。""嗯。"独立成句=残缺）
    try:
        single_broken = _SINGLE_CHAR_BROKEN_RE.findall(text)
        if single_broken:
            report["单字残缺句"] = len(single_broken)
    except Exception:
        pass
    # 名词+代词粘连检测（"心跳他开口了"=两句无标点粘连）
    try:
        noun_fused = _NOUN_PRONOUN_FUSED_RE.findall(text)
        if noun_fused:
            report["名词代词粘连"] = len(noun_fused)
    except Exception:
        pass
    # 连续短句独立段排比检测（≥3个连续短句独立段=AI 节奏模板）
    try:
        paras_run = [p.strip() for p in text.split("\n\n") if p.strip()]
        run_cnt = 0
        cur_run = 0
        for p in paras_run:
            if len(p) <= 12:
                cur_run += 1
                if cur_run >= 3:
                    run_cnt += 1
            else:
                cur_run = 0
        if run_cnt > SHORT_PARA_RUN_MAX:
            report["连续短句排比"] = run_cnt
    except Exception:
        pass
    return report


def collect_feature_sentences(text: str) -> list:
    """收集含内容层 AI 特征的句子（按标点切句、去重），供 LLM 定向改写：
    只挑命中的句子，其余不动，降低改写成本与风险。
    覆盖：比字比较句/跟X似的/否定排队/比喻密度/判断句排比/推理展开链/
          三连否定排比/半解释骑墙/书面连词超频。"""
    sents = re.split(r'(?<=[。！？])', text)
    out = []
    seen = set()
    for s in sents:
        s2 = s.strip()
        if not s2 or s2 in seen:
            continue
        # 命中任一特征即收集
        if (_BI_RE.search(s2) or _GENXI_RE.search(s2) or _NEG_QUEUE_RE.search(s2)
                or _METAPHOR_RE.search(s2) or _IS_JUDGE_RE.search(s2)
                or _HALF_EXPLAIN_RE.search(s2) or _FORMAL_CONJ_RE.search(s2)):
            seen.add(s2)
            out.append(s2)
    # 推理展开链：跨句命中，按链收集（取链的首句）
    for m in _REASONING_CHAIN_RE.finditer(text):
        chain_head = m.group(0).split('。')[0].strip()
        if chain_head and chain_head not in seen:
            # 推理链需要整链一起改写，收集完整链
            full_chain = m.group(0).strip()
            seen.add(chain_head)
            out.append(full_chain)
    # 三连否定排比：跨逗号命中，收集完整句
    for m in _NEG_HAVE3_RE.finditer(text):
        # 扩展到包含整句（从上一个句号到下一个句号）
        start = text.rfind('。', 0, m.start())
        end = text.find('。', m.end())
        full = text[start + 1:end + 1].strip() if end != -1 else m.group(0).strip()
        if full and full not in seen:
            seen.add(full)
            out.append(full)
    # 句子粘连：收集粘连的完整句（交 LLM 补标点）
    for m in _SENTENCE_FUSED_RE.finditer(text):
        start = text.rfind('。', 0, m.start())
        end = text.find('。', m.end())
        full = text[start + 1:end + 1].strip() if end != -1 else m.group(0).strip()
        if full and full not in seen:
            seen.add(full)
            out.append(full)
    # 名词+代词粘连：收集粘连的完整句（交 LLM 补逗号）
    for m in _NOUN_PRONOUN_FUSED_RE.finditer(text):
        start = text.rfind('。', 0, m.start())
        end = text.find('。', m.end())
        full = text[start + 1:end + 1].strip() if end != -1 else m.group(0).strip()
        if full and full not in seen:
            seen.add(full)
            out.append(full)
    # "X得。"残缺句：收集残缺句（交 LLM 补全）
    for m in _DE_BROKEN_RE.finditer(text):
        start = text.rfind('。', 0, m.start())
        end = text.find('。', m.end())
        full = text[start + 1:end + 1].strip() if end != -1 else m.group(0).strip()
        if full and full not in seen:
            seen.add(full)
            out.append(full)
    return out

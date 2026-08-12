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
from app.service.feature_rules import (apply_config_clean, apply_config_detect,
                                       get_regex, get_wordlist)

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
NEG_HAVE3_MAX = 0              # "没有X，没有Y，只有Z"三连否定：全文0处（交LLM改写）
FAKE_SENSORY_MAX = 1           # "得发X"假感官词（干得发涩/疼得发抖）：全文最多1处
DE_COMMA_MAX = 3               # "X得，"状态词后逗号误用（"静得，一条弹幕都没有"）：全文最多修3处
SHORT_PARA_DENSITY_HARD = 0.35 # 短句独立段密度熔断：超过则合并部分纯叙述短段（朱雀对碎片化敏感）
REPEAT_QUOTE_TRIGGER = 3       # 完全相同台词/弹幕行出现≥3次即压减（AI 复读填充）
REPEAT_QUOTE_KEEP = 1          # 保留第1次，其余删除
# ---- 句子残缺/悬空检测（AI 输出最显眼的断句bug） ----
SENTENCE_BROKEN_MAX = 1        # 句子残缺（"X的、。""X、。"顿号/逗号后直接句号）：全文≤1处
SENTENCE_FUSED_MAX = 1         # 句子粘连（两句无标点直接连，"涌出来不是渗"）：全文≤1处
ADJ_CHAIN_DASH_MAX = 1         # 顿号形容词链悬空（"X的、Y的、"结尾）：全文≤1处
SHORT_PARA_RUN_MAX = 2         # 连续短句独立段排比（≥3连触发，全文最多2处）
AUX_BROKEN_MAX = 2             # 助词残缺（"每吐一个字都。"都/会/能直接断句）：全文≤2处
ADJ_INDEP_DANGLING_MAX = 2     # "XX的，"悬空形容词独立成分：全文≤2处
FUSED_CHAR_REPEAT_MAX = 2      # 字重复粘连（"落落在地上"落+落）：全文≤2处
NEG_TRIPLE_MIX_MAX = 0         # 混合标点否定三连（不是X。不是Y，不是Z）：全文0处
RANGE_SCAN_MAX = 2             # "从A到B，到C，到D"部位范围扫描：全文≤2处
VERB_TRIPLE_SCAN_MAX = 2       # 同动词三连排比扫描（落在A，落在B，落在C）：全文≤2处
IS_IS_STACK_MAX = 1            # 判断句堆叠（是X，是Y）：全文≤1处
REDUP_ABAB_MAX = 3             # ABAB式多字叠词（太久太久/一根一根）：全文≤3处
# ---- _NOT_IS_RE 修复：X 最小长度从 2 改 1，覆盖"不是渗，是涌" ----

# ==================== 正则（全部从 conf/ai_feature_rules.json 读取，按名查找；新增特征只改配置） ====================
# 引号保护：中文引号（成对/行尾未闭合）+ 半角引号（不跨行，防止未闭合引号吞噬正文）
_QUOTE_RE = get_regex("quote")
# 断句符（含换行边界）
_SENT_END_RE = get_regex("sent_end")
# "不是X，是Y" 解释句式（逗号版；X 最短1字覆盖"不是渗，是涌"）
_NOT_IS_RE = get_regex("not_is")
# "不是X，(也)不是Y" 双重否定（"不是第一次画，也不是第十次"或"不是兴奋，不是紧张"=AI 双重否定强调）
# 也字可选：覆盖"不是X，不是Y"无也字版（AI 同样用双重否定制造假精确感）
_NOT_IS_DUAL_RE = get_regex("not_is_dual")
# "不是X。是Y[。！，,]" 句号短句版（两连：不是三年五年。是三百年。；不跨段落）
# Y 末尾可为句号/感叹号/逗号（覆盖"不是刷屏。是零星的几条，"混合标点版）
_NOT_IS_DOT2_RE = get_regex("not_is_dot2")
# "不是X。不是Y。是Z。" 短句排比版（三连：不是白色。不是红色。是金色。；允许跨单行，匹配区间含 \n\n 段落边界时跳过）
_NOT_IS_DOT3_RE = get_regex("not_is_dot3")
# "不是X，不是Y，是Z。" 逗号版三连否定排比（不是霉，不是灰，是更淡的什么）
_NOT_IS_COMMA3_RE = get_regex("not_is_comma3")
# 三连顿号排比（如 震惊、愤怒、不解）
_TRIPLE_RE = get_regex("triple")
# "像X，像Y，像Z" 三连排比（AI 高频：像潮水，像棉絮，像没有尽头的白）
_LIKE_TRIPLE_RE = get_regex("like_triple")
# 书面感明喻词（优先替换，越靠前越书卷气）
_SIMILE_WORDS = tuple(get_wordlist("SIMILE_WORDS"))
# 引语冒号前缀（说：/道：等保留）
_SPEECH_TAIL_RE = get_regex("speech_tail")
# 高频转折/突发副词（超出即删除，靠动词/语境承接）
_ABRUPT_WORDS = tuple(get_wordlist("ABRUPT_WORDS"))
# 句首连接词（超出即删除；检测器红牌项）
_CONJ_WORDS = tuple(get_wordlist("CONJ_WORDS"))
# "那种…像/仿佛"引导句式 + "那种X"模糊限定词（检测器红牌项；配置 guide 已含扩展词表：
# 亮/笑/东西/眼神/气息/味道/声音/光/感觉/安静/沉默/平/静/冷/热/疼/紧/重/轻/干/湿/黏/涩/颤/抖/软/硬）
_GUIDE_RE = get_regex("guide")
# "像"字（排除"好像"及复合词内的像）
_LIKE_ISOLATED_RE = get_regex("like_isolated")
# 句尾补丁比喻（，像X。/ 像是X。→ 跟X似的）
_LIKE_PATCH_RE = get_regex("like_patch")
# 代词/人名 + 动作白名单（删除冗余主语时校验，避免病句）
_SUBJECT_WORDS = tuple(get_wordlist("SUBJECT_WORDS"))
# 段首主语表（段落开头词重复检测：连续2段同主语开头 → 第2段删主语）
_PARA_SUBJECTS = tuple(get_wordlist("PARA_SUBJECTS"))
# 环境词变体替换表（标签词重复红牌：同一环境词高频 → 从第 WORD_KEEP_MAX+1 次起换同义变体）
_WORD_VARIANTS = tuple((v[0], tuple(v[1])) for v in get_wordlist("WORD_VARIANTS"))
# 情绪标签词独立段（检测器红牌"直接贴情绪标签"：裸情绪词独立成段，AI 完成写作任务不留给读者推演）
_EMOTION_LABEL_RE = get_regex("emotion_label")
_SUBJECT_ACTION_RE = get_regex("subject_action")
# 缓冲垫词表（AI 节奏切换软着陆高频词）
_BUFFER_WORDS = tuple(get_wordlist("BUFFER_WORDS"))
# 连续短句（≤7字内容 + 句号）；lookbehind 确保短句从行首/断句符后开始，
# 避免从长句中间截取（"陈妄盯着她的手势。"→ 误匹配"妄盯着她的手势。"）
_SHORT_SENT_RE = get_regex("short_sent")
# 顿号4+连（扫描式列举：A、B、C、D → A、B、C，还有D）
_LONGLIST_RE = get_regex("longlist")
# 顿号3连身体/部位/衣物入口扫描（"头发上、肩膀上、断臂的截面上"或"领口、袖口、鞋里"=AI 系统覆盖所有部位）
# 匹配含"上/下/里/外/前/后/口/边"方位/入口词的3项顿号列举，前缀限制1-4字覆盖单字前缀（领口/袖口）
_BODY_SCAN_RE = get_regex("body_scan")
# ---- 新增清洗正则（阶段一/阶段二） ----
# 标点连用（"。，""，。""。。""！。"）：终止标点后紧跟其他终止/逗号标点 → 保留首个
_PUNCT_BUG_RE = get_regex("punct_bug")
# 逗号版三连形容词（"粗重，沉闷，一下一下的"=AI 节奏排比；与顿号版 _TRIPLE_RE 互补）
_COMMA_TRIPLE_RE = get_regex("comma_triple")
# 双重比喻标记（"像是X似的"=双标记冗余 → "像X"）
_DOUBLE_SIMILE_RE = get_regex("double_simile")
# 双框比喻尾（"仿佛X一般"/"如同X一般"/"宛如X般" → 去"一般/般"）
_FRAME_SIMILE_RE = get_regex("frame_simile")
# 形容词独立段（"粗重的。""干涩的。"独立成段=AI 标签式节奏；排除代词"我的/你的/他的"）
_ADJ_INDEP_RE = get_regex("adj_indep")
# 短动作连排（"碎了。塌了。散了。"动词+了+句号连续≥3 → 前两改逗号）
_SHORT_ACTION_BURST_RE = get_regex("short_action_burst")
# 混合标点短动作连排（"赤月暗了。亮了，暗了。亮了。"动词+了+[。，！]连续≥3 → 合并为逗号）
_SHORT_ACTION_BURST_MIXED_RE = get_regex("short_action_burst_mixed")
# 句首连接词补充（在原 _CONJ_WORDS 基础上扩展）
_CONJ_EXTRA_WORDS = tuple(get_wordlist("CONJ_EXTRA_WORDS"))
# ---- 句子残缺/悬空检测正则 ----
# 顿号/逗号后直接跟句号（"尖细的、。""湿漉漉的、。"=句子残缺，AI 输出 bug）
# 排除引号内对话，匹配"顿号或逗号 + 可选空白 + 句号/感叹号"
_SENTENCE_BROKEN_RE = get_regex("sentence_broken")
# 句子粘连（两句无标点直接连："涌出来不是渗"=动词+不是，缺逗号）
# 匹配"动词/形容词 + 不是X" 且前文非标点（缺分隔符）
_SENTENCE_FUSED_RE = get_regex("sentence_fused")
# 顿号形容词链悬空（"X的、Y的、"以顿号结尾，无后续内容=残缺）
_ADJ_CHAIN_DASH_RE = get_regex("adj_chain_dash")
# 叠词形容词（"极细极细的""很小很小的"=AI 双叠强调，人类用单次+程度副词）
# 仅匹配2字叠词（排除"长长的""慢慢的"等正常单字叠词）
_REDUPLICATIVE_ADJ_RE = get_regex("reduplicative_adj")
# "得发X"假感官词（"干得发涩""疼得发抖""冷得发僵"=AI 程度补语模板，机械感官描写）
# 匹配"汉字+得发+1-2字感官词"，排除"觉得发""记得发"等合法词
_FAKE_SENSORY_RE = get_regex("fake_sensory")
# "X得。" / "X得，"残缺句（"声音干得。""干瘪得，""清晰得，"=形容词+得+标点，AI 输出残缺）
# 匹配"汉字+得+句号/感叹号/逗号"，lookbehind 紧贴"得"前，排除"觉得""记得""获得"
# 正常用法"跑得快，"不匹配（"得"后面是"快"不是标点）
_DE_BROKEN_RE = get_regex("de_broken")
# "X得不。"残缺变体（"亮得不。""静得不。"=形容词+得+不+句号，补语被截断）
# "疼得不行。"不匹配（"不"后是"行"），只有"不"直接撞句号才命中
_DE_BU_RE = get_regex("de_bu")
# 叙述残段贴台词（"麻的，"你在干什么？" = 叙述片段直接拼接台词，缺标点/缺主语）
_DE_NARR_QUOTE_RE = get_regex("de_narr_quote")
# 序数对仗（"第一秒/第二秒/第三秒"教科书编号列举=AI 模板）
_SEQ_COUNT_RE = get_regex("seq_count")
# 假设句模板（"巨大化，一脚踩死…""无敌，…"独立排比=AI 罗列式脑补）
_IF_TEMPLATE_RE = get_regex("if_template")
# "X得，"状态词后逗号误用（"弹幕区却静得，一条弹幕都没有"=AI 输出多余逗号，正确是"静得一条弹幕都没有"）
# 仅修"状态形容词+得+逗号"（静得/疼得/热得/闷得…），"我觉得，""记得，"等口语停顿不受影响
_DE_COMMA_RE = get_regex("de_comma")
# 单字残缺句（"又。""嗯。"独立成句=残缺或无意义短句）
# 匹配段首单字+句号（排除"好。""是。""对。"等正常应答词）
_SINGLE_CHAR_BROKEN_RE = get_regex("single_char_broken")
# 名词+代词粘连（"心跳他开口了""嘴唇动了动又"=两句无标点粘连）
# 匹配"名词+他/她/它+动词"，缺逗号分隔
# 名词+代词粘连（"心跳他开口了""嘴唇动了动又"=两句无标点粘连）
# 匹配"名词+他/她/它+动词"，缺逗号分隔
# 排除「」『』“”引号字符：弹幕连续「X」「Y」「它说Z」中"」「Y」「"会被误判为名词
_NOUN_PRONOUN_FUSED_RE = get_regex("noun_pronoun_fused")
# ---- 新增 6 条 AI 特征正则 ----
# 助词残缺句："每吐一个字都。"（都/会/能/敢/要 + 句号/感叹号/逗号 = 缺补语）
# 前字必须是实义内容（排除"都都""会不会"等叠词合法用法），后面无紧随内容直接断
_AUX_BROKEN_RE = re.compile(r'([\u4e00-\u9fff]{2,8})(都|会|能|敢|要)([。！，,])(?![，。！？\u4e00-\u9fff])')
# 悬空"XX的，"独立成分（"暗红色的，看得见走向"/"裂开一道的口子"中"一道的"=残缺；
# 排除"总的来说/似的/目的"等合法词；优先匹配句中"XX的，"+前后断开的形容词悬空）
_ADJ_DANGLING_RE = re.compile(r'(?<![总目似有])的，(?=[\u4e00-\u9fff]{0,6}[，。！？]|$)')
# 字重复粘连（"落落在地上"=落+落在=两句衔接缺字，实际是"往下落 落在"缺了断字）
# 单字AA型且紧接后字（落落/碎碎/紧紧/睁睁；排除合法叠词：慢慢/轻轻/渐渐/天天/久久/往往/明明/偏偏）
_FUSED_CHAR_REPEAT_RE = re.compile(r'(?<![，。！？、\s])([松碎跌落撞碰抓攥握贴爬抖])\1(?=[\u4e00-\u9fff])')
# 混合标点否定三连"不是X。不是Y，不是Z"（第一项句号分隔，后两项逗号）
_NEG_TRIPLE_MIX_RE = re.compile(r'不是([^。！\n]{1,10})[。！]\s*不是([^，\n]{1,10})[，,]\s*不是([^，。；！？\n]{1,12})')
# "从A到B，到C，到D" 部位/范围系统性扫描（三"到"以上，含部位词=AI全覆盖式描写）
# 允许"从A开始到B，到C，到D"（起头可有"开始/起/头"），前缀从限制2-6字放宽到1-10字
_RANGE_SCAN_RE = re.compile(
    r'从[\u4e00-\u9fff]{1,10}(?:开始|起|头)?(到[\u4e00-\u9fff]{1,10}[，,])(到[\u4e00-\u9fff]{1,12}[，,])(到[\u4e00-\u9fff]{1,16})(?=[，。；！？])')
# 同动词三连排比扫描（"落在A，落在B，落在C"或"盯着A，盯着B，盯着C"）
# 限定常见及物动词（落/盯/看/走/站/蹲/握/摸/拍/敲/擦/碰/撞/捏/咬），避免误匹配"是A，是B，是C"
_VERB_TRIPLE_SCAN_RE = re.compile(
    r'(落在[\u4e00-\u9fff]{1,12}[，,])(落在[\u4e00-\u9fff]{1,12}[，,])(落在[\u4e00-\u9fff]{1,16})(?=[，。；！？])')
# 判断句堆叠（逗号版："铁牌是凉的，是另一种凉"；句号版："是凉的。是另一种凉。"= 连续双判断贴标签）
# 排除引语前缀（说/道/问/喊/叫前的直接是）
_IS_IS_STACK_RE = re.compile(
    r'(?<![说道问喊叫答叹])([\u4e00-\u9fff]{2,8})是([^，。；！？\n]{1,12})[，,]是([^，。；！？\n]{1,14})(?=[。！])')
# 句号版跨短句判断堆叠（"是陈述。是等了很久...。" / "铁牌是凉的。是另一种凉。"）
# 只要"是X断句+空白后是Y断句"，无论X是否句首都算；
# 后接另一个"是"为特征=AI推理展开链教科书写法
_IS_IS_DOT_STACK_RE = re.compile(
    r'是([^，。；！？\n]{1,12})[。！]\s*是([^，。；！？\n]{4,40})[。！]')
# ABAB 式多字叠词（太久太久/一根一根/一颤一颤/一片一片/一段一段 = AI机械式重复强调）
# 排除合法叠词（一天一天/一个一个/一步一步/一点一点/一层一层/一年一年）
_REDUP_ABAB_RE = re.compile(
    r'([\u4e00-\u9fff]{2})\1(?!的)')
_REDUP_ABAB_SAFE = frozenset(get_wordlist("REDUP_ABAB_SAFE"))
# ---- 弹幕格式规范化（「」为弹幕专用括号，AI 输出常见四种错乱） ----
# 1) 对白内部混入弹幕："……「X」……" → 弹幕拆出独立成行（对白必须同在一行内）
_DANMU_IN_DIALOGUE_RE = re.compile(r'“([^”\n]*?)「([^」\n]{1,40})」([^”\n]*?)”')
# 2) 双重右引号：「X」」 → 「X」
_DANMU_DOUBLE_CLOSE_RE = re.compile(r'」{2,}')
# 3) 弹幕行尾悬挂右双引号：「X」” → 「X」
_DANMU_HANGING_QUOTE_RE = re.compile(r'」[”"]')
# 4) 弹幕黏在叙述句尾（句号/叹号/问号/省略号后紧跟「X」，到行尾为止）→ 拆独立行；未闭合的补」
_DANMU_GLUED_RE = re.compile(r'(?<=[。！？…])(「[^」\n]{1,60}」?)(?=\n|$)')
# "像某种X"分类标签式比喻（AI 高频："像某种大型犬科动物""像某种金属碎片"=先分类再比喻=教科书式）
# "像一只猫""像他爹"不匹配（只有"某种"才命中，且后面至少跟 2 个名词/形容词）
_LIKE_SOME_KIND_RE = get_regex("like_some_kind")
# "微微X"状态形容词模板（AI 高频："微微发白""微微蠕动""微微泛红"=弱化动作副词滥用）
# 要求"微微"+2~4字状态/动词短语，不匹配"微微一笑"（正常固定搭配）
_WEIWEI_ADV_RE = get_regex("weiwei_adv")
# "得发X"状态词模板（AI 高频："干得发紧""疼得发麻""冷得发抖""亮得发晃"=程序化形容词组合）
_DE_FA_RE = get_regex("de_fa")
# "拟声词+一声+动词"动作模板（AI 高频："咔哒一声推进去""哗啦一声散一地""哐当一声掉下来"=程序化动作包装）
_ONOMATOPOEIA_TEMPLATE_RE = get_regex("onomatopoeia_template")
# 检索库弹幕连排（AI 高频：弹幕"检索X文明数据库，无此生命体"×N / "「X文明数据库无此生命体」"×N=列表式填充）
# 前缀"检索："可选（支持裸复读"「X文明数据库无此生命体」"变体），仅换文明名重复≥2次触发
_SEARCH_COLON_LIB_RE = get_regex("search_colon_lib")
# "进度条/传输条/加载条…叮/咔一声…(满格|完成|结束)"机械技术描写（AI 高频：下载/传输进度条全覆盖式描写）
# 原规则要求 0%→100% 数字过程，现放宽为"进度条+叮一声+满格/完成"即可命中（0%/100% 段可选）
_PROGRESS_BAR_TEMPLATE_RE = get_regex("progress_bar_template")
# "弹幕+状态词"节奏句（AI 跨章复读模板："弹幕懵了。""弹幕集体沉默。""弹幕又沉默了。""弹幕炸了。""弹幕突然全部消失。"）
# 放宽：允许"又/集体/全体/瞬间/突然/彻底/全都/全部"等 1-2 个修饰词前置，状态词含 安静/沉默/停/空/懵/炸/爆/消失
# 不再强制"沉默→炸"紧邻（单独的状态句本身即为 AI 模板化表达）
_DANMAKU_TEMP_RE = get_regex("danmaku_temp")
# ---- 「」引号/病句/名词罗列检测（第三批，20260811） ----
# 「」引号错乱（AI 输出格式 bug：`「...「`嵌套、`」」`双右引号、`。」「`句号后引号紧邻）
# 只匹配断句符后的`。」「`（`「A！」「B」`/`「A？」「B」` 合法弹幕连排不误伤）
_QUOTE_MISMATCH_RE = get_regex("quote_mismatch")
# 副词裸逗号病句（"每个字都，"=副词后直接逗号=话没说完/输出截断）
_ADV_BARE_COMMA_RE = get_regex("adv_bare_comma")
# 叠字白名单（称呼/副词/量词/ABB尾缀/常见动词叠词；白名单外的单字叠=重复字病句）
_REDUP_OK = frozenset(get_wordlist("REDUP_OK"))
# 被动判断句（"是被更强烈的感觉盖过去了。"=AI 冷峻被动判断模板）
_IS_BEI_RE = get_regex("is_bei")
# "名词+句号"堆叠（"一张床。一张桌子。一把椅子。"=AI 名词罗列节奏）
_NOUN_DOT_STACK_RE = get_regex("noun_dot_stack")
# 属性说明罗列（"功法等级未知。上限未知。"=AI 属性说明书，≥2 处触发）
_ATTR_DOT_RE = get_regex("attr_dot")


def _find_redup(text: str) -> list:
    """白名单外的单字叠字（"流流过锁骨"=重复字病句；称呼/副词/量词/常见动词叠词不报）"""
    return [m.group(0) for m in re.finditer(get_regex("redup_scan"), text)
            if m.group(1) * 2 not in _REDUP_OK]



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

# ==================== 通用工具 ====================

def _add_stats(stats: dict, key: str, n: int) -> None:
    """记录清洗统计（n=0 时忽略，保持 stats 只含实际改动）"""
    if n:
        stats[key] = stats.get(key, 0) + n


def _rebuild_matches(text: str, regex, keep: int = 0, limit=None, transform=None) -> tuple:
    """对 regex 的全部匹配逐段重建文本（通用"保留前N/限制处理数+替换"骨架）：
    - 前 keep 个匹配保留原文不动（keep=0 时全部进入替换）
    - 其余匹配用 transform(m) 的结果替换；transform 返回 None 表示删除
    - limit：最多替换 limit 个匹配（超过的保留原文），用于"修前 N 处"类规则
    返回 (新文本, 实际替换次数)；无匹配或无需处理时原样返回。"""
    matches = list(regex.finditer(text))
    if not matches:
        return text, 0
    if keep and len(matches) <= keep:
        return text, 0
    out = []
    last = 0
    changed = 0
    for idx, m in enumerate(matches):
        out.append(text[last:m.start()])
        if idx < keep:
            out.append(m.group(0))
        elif limit is not None and changed >= limit:
            out.append(m.group(0))
        else:
            repl = transform(m) if transform else None
            if repl is not None:
                out.append(repl)
            changed += 1
        last = m.end()
    out.append(text[last:])
    return "".join(out), changed


def _collapse_blank_lines(lines: list) -> list:
    """删除后清理连续空行（保留单个空行分隔）"""
    res = []
    prev_empty = False
    for ln in lines:
        empty = not ln.strip()
        if empty and prev_empty:
            continue
        res.append(ln)
        prev_empty = empty
    return res


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

    def transform(m):
        y = m.group(2)
        # 避免 "是是Y"；Y 以"是/而"开头时直接使用
        prefix = "" if y.startswith(("是", "而", "就")) else "是"
        return prefix + y

    new_text, n = _rebuild_matches(text, _NOT_IS_RE, keep=NOT_IS_KEEP_MAX, transform=transform)
    _add_stats(stats, "not_is", n)
    return new_text


def _fix_not_is_dot(text: str, stats: dict) -> str:
    """句号版"不是X"压减（检测器红牌项，AI 爱用短句排比做强调）：
    - 句号三连"不是X。不是Y。是Z。"（含跨行）→ 出现即压缩为"是Z。"
    - 逗号三连"不是X，不是Y，是Z" → 出现即压缩为"是Z"
    - 两连"不是X。是Y。" → 全文最多保留 NOT_IS_KEEP_MAX 处
    压缩均删否定补丁留肯定句，语义保留。注意顺序：先逗号三连 → 再句号三连 → 最后两连。"""
    replaced = 0

    def prefix_of(z: str) -> str:
        return "" if z.startswith(("是", "而", "就")) else "是"

    # --- 逗号版三连：出现即压缩（不是霉，不是灰，是更淡的什么 → 是更淡的什么）---
    text, n = _rebuild_matches(text, _NOT_IS_COMMA3_RE,
                               transform=lambda m: prefix_of(m.group(3)) + m.group(3))
    replaced += n
    # --- 句号版三连：出现即压缩 ---
    text, n = _rebuild_matches(text, _NOT_IS_DOT3_RE,
                               transform=lambda m: prefix_of(m.group(3)) + m.group(3) + "。")
    replaced += n
    # --- 两连版：超过配额才压缩；未超配额时保持原语义（不记录 stats）---
    m2 = list(_NOT_IS_DOT2_RE.finditer(text))
    if not m2 or len(m2) <= NOT_IS_KEEP_MAX:
        return text
    text, n = _rebuild_matches(text, _NOT_IS_DOT2_RE, keep=NOT_IS_KEEP_MAX,
                               transform=lambda m: prefix_of(m.group(2)) + m.group(2) + "。")
    replaced += n
    _add_stats(stats, "not_is_dot", replaced)
    return text


def _fix_not_is_dual(text: str, stats: dict) -> str:
    """双重否定压减："不是X，(也)不是Y" → "(也)不是Y"（删前半否定补丁，留后半）
    与 _fix_not_is 互补：_NOT_IS_RE 只匹配"不是X，是Y"，
    此函数处理"不是X，也不是Y"和"不是X，不是Y"双重否定版
    （AI 用双重否定制造"排除了所有选项"的假精确感）。
    全文最多保留 NOT_IS_KEEP_MAX 处。"""
    matches = list(_NOT_IS_DUAL_RE.finditer(text))
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
            ye = m.group(2)  # 可选"也"字
            y = m.group(3)
            out.append(ye + "不是" + y)
            replaced += 1
        last = m.end()
    out.append(text[last:])
    if replaced:
        stats["not_is_dual"] = stats.get("not_is_dual", 0) + replaced
    return "".join(out)


def _fix_triple(text: str, stats: dict) -> str:
    """三连排比拆散：
    - 顿号三连（X、Y、Z → X、Y，还有Z）
    - "像"字三连（像X，像Y，像Z → 像X和Y，还有Z，降"像"字密度）
    超过配额才处理（保留前 N 个不动）。注意顺序：先顿号三连 → 再"像"字三连。"""
    quota = max(1, len(text) // TRIPLE_KEEP_PER_CHARS)
    replaced = 0
    # --- 顿号三连（保留前 quota 个）---
    text, n = _rebuild_matches(text, _TRIPLE_RE, keep=quota,
                               transform=lambda m: f"{m.group(1)}、{m.group(2)}，还有{m.group(3)}")
    replaced += n
    # --- "像"字三连（强 AI 特征：出现即拆，不保留配额） ---
    text, n = _rebuild_matches(text, _LIKE_TRIPLE_RE,
                               transform=lambda m: f"像{m.group(1)}和{m.group(2)}，还有{m.group(3)}")
    replaced += n
    _add_stats(stats, "triple", replaced)
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
    new_text, n = _rebuild_matches(text, _GUIDE_RE, keep=GUIDE_KEEP_MAX)  # transform=None → 删除匹配
    _add_stats(stats, "guide", n)
    return new_text


def _fix_punct_bug(text: str, stats: dict) -> str:
    """标点连用修复："。，""，。""。。""！。" → 保留首个终止标点
    （AI 输出偶发的标点叠加，"是空的。，底下" → "是空的。底下"）
    限制 PUNCT_BUG_MAX 处，避免误伤引号边界。"""
    new_text, n = _rebuild_matches(text, _PUNCT_BUG_RE, limit=PUNCT_BUG_MAX,
                                   transform=lambda m: m.group(0)[0])  # 保留首个标点
    _add_stats(stats, "punct_bug", n)
    return new_text


def _fix_comma_triple(text: str, stats: dict) -> str:
    """逗号版三连形容词拆散："粗重，沉闷，一下一下的" → "粗重沉闷，一下一下的"
    （AI 节奏排比；与顿号版 _TRIPLE_RE 互补，逗号版更隐蔽）
    全文保留 COMMA_TRIPLE_KEEP_MAX 处，其余把第一逗号删除（合并前两项）。"""
    new_text, n = _rebuild_matches(
        text, _COMMA_TRIPLE_RE, keep=COMMA_TRIPLE_KEEP_MAX,
        transform=lambda m: m.group(1) + m.group(2) + "，" + m.group(3))  # 合并前两项：A，B，C → AB，C
    _add_stats(stats, "comma_triple", n)
    return new_text


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
    new_text, n = _rebuild_matches(text, _FRAME_SIMILE_RE, keep=FRAME_SIMILE_KEEP_MAX,
                                   transform=lambda m: m.group(1) + m.group(2))
    _add_stats(stats, "frame_simile", n)
    return new_text


def _fix_sentence_broken(text: str, stats: dict) -> str:
    """句子残缺修复："X的、。""X、。"（顿号/逗号后直接句号）→ 删除悬空的顿号/逗号
    （AI 输出 bug："尖细的、。"→"尖细的。"；"湿漉漉的、。"→"湿漉漉的。"）
    全文最多修 SENTENCE_BROKEN_MAX 处（避免误伤引号边界）。"""
    new_text, n = _rebuild_matches(text, _SENTENCE_BROKEN_RE, limit=SENTENCE_BROKEN_MAX,
                                   transform=lambda m: m.group(0)[-1])  # 保留句号，删悬空的顿号/逗号
    _add_stats(stats, "sentence_broken", n)
    return new_text


def _fix_adj_chain_dash(text: str, stats: dict) -> str:
    """顿号形容词链悬空修复："X的、Y的、"（以顿号结尾无后续）→ 删除尾部顿号
    （AI 输出 bug："那种没来由的、尖细的、"→"那种没来由的、尖细的"）
    全文最多修 ADJ_CHAIN_DASH_MAX 处。"""
    new_text, n = _rebuild_matches(text, _ADJ_CHAIN_DASH_RE, limit=ADJ_CHAIN_DASH_MAX,
                                   transform=lambda m: m.group(0)[:-1])  # 删尾部顿号
    _add_stats(stats, "adj_chain_dash", n)
    return new_text


# "X得[。！]"残缺句修复阈值："烫得。""速度快得。"这类 AI 把程度补语写丢的断句，全文最多修5处
DE_BROKEN_FIX_MAX = 5
# 排除"动词+得"合法词的前字（觉得/记得/晓得/懂得/值得/舍得/认得/获得/了得/怪不得/显得/免得/说得），
# 避免误伤"这一切值得。""他说得。"式合法句；集合=觉记获晓舍得值懂认了怪显免得说
_DE_BROKEN_SAFE_PREV = "觉得记得晓得懂得值得舍得认得获得了怪显免得说"


def _fix_de_broken(text: str, stats: dict) -> str:
    """"X得[。！]"残缺句修复：AI 写"烫得。""速度快得。"（程度补语写丢）→ 补"得厉害"
    只修句号/感叹号版（"X得，"逗号版可能是合法停顿如"他说得，再好听也没用"，不修）；
    另处理"X得不[。！]"粘连（"力气大得不。"→"力气大得厉害。"）。
    排除合法"动词+得"词，避免误伤"这一切值得。"式结尾。"""
    # 句号/感叹号版：X得[。！]
    m_re = re.compile(r'([\u4e00-\u9fff])(?<![' + _DE_BROKEN_SAFE_PREV + r'])(?:得)([。．！])')
    matches = list(m_re.finditer(text))
    # "得不[。！]"粘连版：力气大得不。 → 力气大得厉害。
    m_re2 = re.compile(r'([\u4e00-\u9fff])(?<![' + _DE_BROKEN_SAFE_PREV + r'])得不([。．！])')
    matches2 = list(m_re2.finditer(text))
    if not matches and not matches2:
        return text
    # 两批匹配按位置合并
    all_m = sorted(matches + matches2, key=lambda x: x.start())
    fixed = 0
    out = []
    last = 0
    for m in all_m:
        if fixed >= DE_BROKEN_FIX_MAX:
            break
        # 保留"得"前的形容词（捕获组1），补"得厉害"+标点（捕获组2）
        out.append(text[last:m.start()])
        out.append(m.group(1))
        out.append("得厉害")
        out.append(m.group(2))
        last = m.end()
        fixed += 1
    out.append(text[last:])
    if fixed:
        stats["de_broken"] = stats.get("de_broken", 0) + fixed
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


def _fix_de_comma(text: str, stats: dict) -> str:
    """状态词+得+逗号误用修复（"弹幕区却静得，一条弹幕都没有"=AI 输出多余逗号）：
    白名单状态形容词（静/疼/热/闷…）后"得，"→"得"，去掉多余逗号，让补语直接接上。
    全文最多 DE_COMMA_MAX 处；"我觉得，""记得，"等口语停顿不匹配（白名单不含觉/记）。"""
    budget = DE_COMMA_MAX

    def repl(m):
        nonlocal budget
        if budget <= 0:
            return m.group(0)
        budget -= 1
        return m.group(1) + "得"

    new_text, n = _DE_COMMA_RE.subn(repl, text)
    if n:
        stats["de_comma"] = stats.get("de_comma", 0) + n
        return new_text
    return text


def _fix_repeated_quote_lines(text: str, stats: dict) -> str:
    """完全相同台词/弹幕行压减：AI 用同一句弹幕/台词整行复读做填充
    （"检索修仙文明，无此生命体"×5），检测器对整句重复敏感。
    仅处理"整行都是引号内容"的台词/弹幕行，完全相同≥3次 → 只保留第1次，其余删除。
    对话语义重复本身是 AI 复读特征，删除安全；删除后清理连续空行。"""
    lines = text.split("\n")
    groups = {}
    for i, ln in enumerate(lines):
        m = _REPEAT_QUOTE_LINE_RE.match(ln)
        if m:
            groups.setdefault(m.group(1), []).append(i)
    removals = []
    removed = 0
    for content, idxs in groups.items():
        if len(idxs) < REPEAT_QUOTE_TRIGGER:
            continue
        for idx in idxs[REPEAT_QUOTE_KEEP:]:
            removals.append(idx)
            removed += 1
    if not removed:
        return text
    drop_set = set(removals)
    res = [ln for i, ln in enumerate(lines) if i not in drop_set]
    res = _collapse_blank_lines(res)  # 删除后清理连续空行
    _add_stats(stats, "repeat_quote", removed)
    return "\n".join(res)


def _fix_short_para_density(text: str, stats: dict) -> str:
    """短句独立段密度熔断：碎片化节奏（≤12字独立段占比过高）让检测器判定 AI 模板。
    密度口径与 check_ai_features 一致：统计全部独立段（含对话/弹幕短段），
    仅当密度超过 SHORT_PARA_DENSITY_HARD 时触发：把"纯叙述短段"并入相邻叙述段，
    压到硬上限以内；对话段（含占位符/纯「」弹幕行）绝不并段，保留对话节奏。
    并段=去掉 \n\n 边界，短段并入前一段末尾（前段非纯叙述则并入后一段开头）。"""
    paras = text.split("\n\n")
    if len(paras) < 4:
        return text

    def _is_pure_narr(p: str) -> bool:
        """纯叙述段：无对话占位符，且不是整行「」弹幕/台词"""
        s = p.strip()
        if not s or "\x00" in s:
            return False
        if re.fullmatch(r'「[^」\n]+」[。！？…]*', s):
            return False
        return True

    # 全部独立段（与检测器同口径：对话短段同样计入碎片）
    all_idx = [i for i, p in enumerate(paras) if p.strip()]
    all_short = [i for i in all_idx if len(paras[i].strip()) <= 12]
    if not all_short:
        return text
    ratio = len(all_short) / len(all_idx)
    if ratio <= SHORT_PARA_DENSITY_HARD:
        return text
    # 精确计算：并掉 k 个短段后 (short-k)/(total-k) 才降到硬上限以内
    target = 0
    while (len(all_short) - target) / (len(all_idx) - target) > SHORT_PARA_DENSITY_HARD:
        target += 1
        if target >= len(all_short):
            break
    narr_short = [i for i in all_short if _is_pure_narr(paras[i])]
    drop = set()
    for i in narr_short:
        if len(drop) >= target:
            break
        prev_ok = i > 0 and _is_pure_narr(paras[i - 1])
        nxt_ok = i < len(paras) - 1 and _is_pure_narr(paras[i + 1])
        if not prev_ok and not nxt_ok:
            continue  # 前后都是对话段，孤立叙述短段保留（节奏点）
        drop.add(i)
    if not drop:
        return text
    out = []
    i = 0
    while i < len(paras):
        if i in drop:
            frag = paras[i].strip()
            if out and _is_pure_narr(out[-1]):
                # 并入前一段末尾
                out[-1] = out[-1].rstrip() + frag
                i += 1
                continue
            # 前段是对话/为空 → 拼到下一个保留段开头
            j = i + 1
            carry = frag
            while j < len(paras) and j in drop:
                carry += paras[j].strip()
                j += 1
            if j < len(paras):
                paras[j] = carry + paras[j]
            else:
                out.append(carry)
            i = j
            continue
        out.append(paras[i])
        i += 1
    result = "\n\n".join(out)
    stats["short_para"] = stats.get("short_para", 0) + len(drop)
    return result


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
    new_text, n = _rebuild_matches(
        text, _LONGLIST_RE,
        transform=lambda m: m.group(1) + m.group(2) + "，还有" + m.group(4))
    _add_stats(stats, "longlist", n)
    return new_text


def _fix_body_scan(text: str, stats: dict) -> str:
    """身体/部位扫描3连拆散："头发上、肩膀上、断臂的截面上"→ 只保留前2项，
    删第3项（AI 系统性覆盖身体各部位=扫描式描写；人类只给1-2个关键细节）。
    全文最多处理3处（避免过度删减环境细节）。"""
    matches = list(_BODY_SCAN_RE.finditer(text))
    if not matches:
        return text
    max_fix = 3
    replaced = 0
    out = []
    last = 0
    for m in matches:
        out.append(text[last:m.start()])
        # 保留前2项 + 顿号 → "头发上、肩膀上"（后续标点由 lookahead 保证已存在）
        out.append(m.group(1) + "、" + m.group(2))
        replaced += 1
        last = m.end()
        if replaced >= max_fix:
            break
    out.append(text[last:])
    if replaced:
        stats["body_scan"] = stats.get("body_scan", 0) + replaced
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
    kept = [line for line in lines if not _EMOTION_LABEL_RE.match(line)]
    removed = len(lines) - len(kept)
    if not removed:
        return text
    kept = _collapse_blank_lines(kept)  # 删除后清理连续空行
    _add_stats(stats, "emotion", removed)
    return "\n".join(kept)


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


def _fix_short_para_density(text: str, stats: dict) -> str:
    """短叙事独立段密度压减：≤12字独立段占比 > SHORT_PARA_DENSITY_MAX 时，
    将多余的短段并入相邻长段（用句号衔接，不丢内容）。
    迭代最多3次：一次合并后总段数减少、密度再核算仍超阈值时继续合并。
    跳过：纯对话行（引号包裹/占位/弹幕）、纯缓冲词、纯情绪标签、纯形容词独立段。"""
    def _is_dialogue(p: str) -> bool:
        p = p.strip()
        if p.startswith("__Q") and p.endswith("__"):
            return True
        # 引号占位符（\x00N\x00）：阶段二对话已被占位保护，占位段=对话
        if p.startswith("\x00") and p.endswith("\x00"):
            return True
        # 以各种引号开头的整段对话（含中文引号「」『』「」、半角引号""''）
        for q in ('"', "'", '\u300c', '\u300d', '\u300e', '\u300f', '\uff02',
                  '\u201c', '\u201d', '\u2018', '\u2019'):
            if p.startswith(q):
                return True
        return False

    def _is_short_narrative(p: str) -> bool:
        p = p.strip()
        if not p or len(p) > 12:
            return False
        if _is_dialogue(p):  # ⭐ 对话整段跳过（台词短是正常的，不是AI节奏）
            return False
        if p in ("沉默。", "安静。", "寂静。", "安静，", "沉默，"):
            return False
        has_verb = any(c in p for c in "了着过个动走说看停碎坐站来去笑哭打拍抓顿醒收写回转起落"
                                         "扔拿放闭睁举伸推拉开门关裂塌倒退跑跳跪趴靠躺弯握低"
                                         "听见知道见想问答喊叫念叹费劲紧松")
        has_judge_pattern = bool(re.search(r'(?:^|[^是])是[^，。！？]|[一二三四五六七八九十百千\d]+[个次块]', p))
        has_noun_label = bool(re.match(r'^[\u4e00-\u9fff]{1,6}[。！]$', p)) and \
                          not p.rstrip('。！').isdigit()
        return has_verb or has_judge_pattern or has_noun_label

    import math
    paras = text.split("\n\n")
    if len(paras) < 4:
        return text
    total_merged = 0
    # 最多迭代3次，密度超限就继续合并（第一次合并后总段数变少，密度可能还超）
    for _round in range(3):
        short_indices = [i for i, p in enumerate(paras) if _is_short_narrative(p)]
        if not short_indices:
            break
        # 核算密度时基数也是非对话段（对话不参与密度计算，保持与 check_ai_features 一致）
        narrative_count = sum(1 for p in paras if not _is_dialogue(p.strip()))
        total = max(1, narrative_count)
        density = len(short_indices) / total
        if density <= SHORT_PARA_DENSITY_MAX:
            break
        need_merge = math.ceil((len(short_indices) - SHORT_PARA_DENSITY_MAX * total) / (1 - SHORT_PARA_DENSITY_MAX))
        need_merge = max(0, need_merge)
        merged = 0
        for i in reversed(short_indices):
            if merged >= need_merge:
                break
            prev_idx = i - 1
            while prev_idx >= 0 and _is_short_narrative(paras[prev_idx]):
                prev_idx -= 1
            if prev_idx >= 0:
                short_content = paras[i].strip()
                paras[prev_idx] = paras[prev_idx].rstrip() + short_content
                paras[i] = ""
                merged += 1
            else:
                next_idx = i + 1
                while next_idx < len(paras) and _is_short_narrative(paras[next_idx]):
                    next_idx += 1
                if next_idx < len(paras):
                    short_content = paras[i].strip()
                    paras[next_idx] = short_content + paras[next_idx].lstrip()
                    paras[i] = ""
                    merged += 1
        total_merged += merged
        if merged == 0:
            break
        paras = [p for p in paras if p.strip()]
    if total_merged:
        stats["short_para_merge"] = stats.get("short_para_merge", 0) + total_merged
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
        if "「" in s or "」" in s or "“" in s or "”" in s:
            continue  # 跳过含引号的句子（直角引号不被 _protect_quotes 保护，系统消息/台词可能重复属叙事设计）
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


def _fix_aux_broken(text: str, stats: dict) -> str:
    """助词残缺句修复："每吐一个字都[。！，]" → 补最常见补语"像被掐住"或补"都费劲"，
    根据前文字数选短款：3字内补"都费劲"，长句补"都像被勒住"（不丢原文残缺感，只补成完整句）。
    全文最多修 AUX_BROKEN_MAX 处。"""
    matches = list(_AUX_BROKEN_RE.finditer(text))
    if not matches:
        return text
    fixed = 0
    out = []
    last = 0
    for m in matches:
        if fixed >= AUX_BROKEN_MAX:
            break
        prev_content = m.group(1)  # 助词前的实义内容："每吐一个字"
        aux = m.group(2)  # 都/会/能/敢/要
        punct = m.group(3)
        out.append(text[last:m.start()])
        # 短款补"都费劲"，长款补"都发紧"，保留语气助词与断句标点
        if len(prev_content) <= 4:
            out.append(prev_content + aux + "发紧" + punct)
        else:
            out.append(prev_content + aux + "费劲" + punct)
        last = m.end()
        fixed += 1
    out.append(text[last:])
    if fixed:
        stats["aux_broken"] = stats.get("aux_broken", 0) + fixed
    return "".join(out)


def _fix_adj_dangling(text: str, stats: dict) -> str:
    """悬空"XX的，"独立成分修复：把句中"的，"拆为"的。"做硬断（形容词独立成短句），
    避免AI输出的"暗红色的，看得见走向"这类形容词与谓语粘连的别扭句法。
    全文最多修 ADJ_INDEP_DANGLING_MAX 处。"""
    matches = list(_ADJ_DANGLING_RE.finditer(text))
    if not matches:
        return text
    fixed = 0
    out = []
    last = 0
    for m in matches:
        if fixed >= ADJ_INDEP_DANGLING_MAX:
            break
        # "的，" → "的。" 让形容词自成一短句
        out.append(text[last:m.start()])
        out.append("的。")
        last = m.end()
        fixed += 1
    out.append(text[last:])
    if fixed:
        stats["adj_dangling"] = stats.get("adj_dangling", 0) + fixed
    return "".join(out)


def _fix_fused_char_repeat(text: str, stats: dict) -> str:
    """字重复粘连修复："落落在地上"→"落，落在地上"（中间补逗号断句）；
    "碎碎成粉"→"碎，碎成粉"。 用逗号断开叠词重复，保留原动作节奏不丢语义。
    全文最多修 FUSED_CHAR_REPEAT_MAX 处。"""
    matches = list(_FUSED_CHAR_REPEAT_RE.finditer(text))
    if not matches:
        return text
    fixed = 0
    out = []
    last = 0
    for m in matches:
        if fixed >= FUSED_CHAR_REPEAT_MAX:
            break
        ch = m.group(1)
        out.append(text[last:m.start()])
        out.append(ch + "，" + ch)  # 落落 → 落，落
        last = m.end()
        fixed += 1
    out.append(text[last:])
    if fixed:
        stats["fused_char_repeat"] = stats.get("fused_char_repeat", 0) + fixed
    return "".join(out)


def _fix_neg_triple_mix(text: str, stats: dict) -> str:
    """混合标点否定三连压缩："不是X。不是Y，不是Z" → "不是Z"（只留最后一项否定）。
    全文 NEG_TRIPLE_MIX_MAX=0 处（彻底消除，AI否定三连排比最扎眼）。"""
    matches = list(_NEG_TRIPLE_MIX_RE.finditer(text))
    if not matches:
        return text
    # 反向替换避免索引偏移
    replaced = 0
    out = text
    for m in reversed(matches):
        z = m.group(3)
        out = out[:m.start()] + "不是" + z + out[m.end():]
        replaced += 1
    if replaced:
        stats["neg_triple_mix"] = stats.get("neg_triple_mix", 0) + replaced
    return out


def _fix_range_scan(text: str, stats: dict) -> str:
    """部位/范围系统性扫描压缩："从A到B，到C，到D" → "从A到C"（只保留起点和终点，跳过中间覆盖项）。
    AI最爱的"从巨眼到脖子，到肩膀，到躯干，到下半身"类全覆盖式列举=机械感。
    人类写法只给关键两点。 全文最多修 RANGE_SCAN_MAX 处。"""
    matches = list(_RANGE_SCAN_RE.finditer(text))
    if not matches:
        return text
    fixed = 0
    out = []
    last = 0
    for m in matches:
        if fixed >= RANGE_SCAN_MAX:
            break
        # m.group(0) = "从A开始到B，到C，到D"
        # m.group(1) = "到B，"   m.group(2) = "到C，"   m.group(3) = "到D"
        # 找到 "从" 的位置到 "到B，" 的开头 = 起点段；最后加 "到D"
        to_d = m.group(3)  # "到D"（无尾标点）
        # 提取起点（从X开始/从X）：从 "从" 到 第一个"到"字前
        prefix_end = m.group(0).find(m.group(1))  # 第一个"到B，"位置
        start = m.group(0)[:prefix_end]  # "从巨眼开始"
        out.append(text[last:m.start()])
        out.append(start + to_d)  # "从巨眼开始到埋在墙里的下半身"
        last = m.end()
        fixed += 1
    out.append(text[last:])
    if fixed:
        stats["range_scan"] = stats.get("range_scan", 0) + fixed
    return "".join(out)


def _fix_verb_triple_scan(text: str, stats: dict) -> str:
    """同动词三连排比扫描压缩："落在A，落在B，落在C" → "落在A、B，还有C"（先顿号+还有，拆排比节奏）。
    与_longlist三连顿号拆散逻辑同型，消除3连同动作对象的机械节奏感。
    全文最多修 VERB_TRIPLE_SCAN_MAX 处。"""
    matches = list(_VERB_TRIPLE_SCAN_RE.finditer(text))
    if not matches:
        return text
    fixed = 0
    out = []
    last = 0
    for m in matches:
        if fixed >= VERB_TRIPLE_SCAN_MAX:
            break
        # "落在A，落在B，落在C" → "落在A、B，还有C"
        # 提取 A=落在[X，]的X（剥"落在"前缀和尾标点）
        a = m.group(1)[len("落在"):-1]  # 去尾"，"
        b = m.group(2)[len("落在"):-1]
        c = m.group(3)[len("落在"):]
        out.append(text[last:m.start()])
        out.append(f"落在{a}、{b}，还有{c}")
        last = m.end()
        fixed += 1
    out.append(text[last:])
    if fixed:
        stats["verb_triple_scan"] = stats.get("verb_triple_scan", 0) + fixed
    return "".join(out)


def _fix_is_is_stack(text: str, stats: dict) -> str:
    """判断句堆叠压缩：
    - 逗号版："XX是A，是B[。！]" → "XX是B"（最多保留 IS_IS_STACK_MAX 处）
    - 句号版："是A[。！] 是B[。！]" → "是B"（0配额=彻底清除，直接命中推理展开链红牌）"""
    replaced = 0
    out = text
    # ---- 逗号版：XX是A，是B ----
    matches = list(_IS_IS_STACK_RE.finditer(out))
    if len(matches) > IS_IS_STACK_MAX:
        need = len(matches) - IS_IS_STACK_MAX
        for m in reversed(matches):
            if replaced >= need:
                break
            subj = m.group(1)
            b = m.group(3)
            out = out[:m.start()] + subj + "是" + b + out[m.end():]
            replaced += 1
    # ---- 句号版：是A。是B。= 推理展开链（检测器红牌，0配额彻底清除） ----
    dot_matches = list(_IS_IS_DOT_STACK_RE.finditer(out))
    for m in reversed(dot_matches):
        b = m.group(2)
        out = out[:m.start()] + "是" + b + "。" + out[m.end():]
        replaced += 1
    if replaced:
        stats["is_is_stack"] = stats.get("is_is_stack", 0) + replaced
    return out


def _fix_redup_abab(text: str, stats: dict) -> str:
    """ABAB式多字叠词压减："太久太久"→"太久"、"一根一根"→"一根根"。
    排除 _REDUP_ABAB_SAFE 白名单（时间递进类叠词合法）。
    全文最多压 REDUP_ABAB_MAX 处（默认3处，避免过度改写节奏感强的动作叠词）。"""
    matches_all = list(_REDUP_ABAB_RE.finditer(text))
    if not matches_all:
        return text
    # 过滤白名单
    matches = [m for m in matches_all if m.group(0) not in _REDUP_ABAB_SAFE]
    if len(matches) <= REDUP_ABAB_MAX:
        return text
    need = len(matches) - REDUP_ABAB_MAX
    replaced = 0
    out = text
    for m in reversed(matches):
        if replaced >= need:
            break
        pair = m.group(1)
        # pair 第二个字是量词 → 一根根；否则只留一次：太久
        if pair[-1] in "根片段落条颗粒秒帧寸":
            sub = pair + pair[-1]  # 一根 → 一根根
        else:
            sub = pair
        out = out[:m.start()] + sub + out[m.end():]
        replaced += 1
    if replaced:
        stats["redup_abab"] = stats.get("redup_abab", 0) + replaced
    return out


SENTENCE_FUSED_FIX_MAX = 2
NOUN_PRONOUN_FUSED_FIX_MAX = 2


def _fix_sentence_fused(text: str, stats: dict) -> str:
    """句子粘连修复："XX不是Y"型粘连（缺逗号分隔两句）→ "XX，不是Y"。
    例："暗红色的液体不是血" → "暗红色的液体，不是血"。
    全文最多修 SENTENCE_FUSED_FIX_MAX 处。"""
    matches = list(_SENTENCE_FUSED_RE.finditer(text))
    if not matches:
        return text
    fixed = 0
    out = []
    last = 0
    for m in matches:
        if fixed >= SENTENCE_FUSED_FIX_MAX:
            break
        # "前内容不是Y" → "前内容，不是Y"
        prefix = m.group(1)  # e.g. "一种暗红色的液体"
        out.append(text[last:m.start()])
        out.append(prefix + "，不是" + m.group(2))
        last = m.end()
        fixed += 1
    out.append(text[last:])
    if fixed:
        stats["sentence_fused"] = stats.get("sentence_fused", 0) + fixed
    return "".join(out)


def _fix_noun_pronoun_fused(text: str, stats: dict) -> str:
    """名词+代词粘连修复："心跳他开口了"→"心跳，他开口了"（名/动名词后缺逗号）。
    例："嘴唇动了动又" → "嘴唇动了动，又"。
    全文最多修 NOUN_PRONOUN_FUSED_FIX_MAX 处。"""
    matches = list(_NOUN_PRONOUN_FUSED_RE.finditer(text))
    if not matches:
        return text
    fixed = 0
    out = []
    last = 0
    for m in matches:
        if fixed >= NOUN_PRONOUN_FUSED_FIX_MAX:
            break
        noun = m.group(1)
        pron = m.group(2)
        verb = m.group(3)
        out.append(text[last:m.start()])
        out.append(f"{noun}，{pron}{verb}")
        last = m.end()
        fixed += 1
    out.append(text[last:])
    if fixed:
        stats["noun_pronoun_fused"] = stats.get("noun_pronoun_fused", 0) + fixed
    return "".join(out)


def _fix_reduplicative_adj(text: str, stats: dict) -> str:
    """叠词形容词去重："极细极细的"→"极细的"（AI 双叠强调=机械节奏）
    全文最多处理3处，避免过度改写。排除正常叠词如"长长的""慢慢的"（单字叠）。"""
    matches = list(_REDUPLICATIVE_ADJ_RE.finditer(text))
    if not matches:
        return text
    max_fix = 3
    replaced = 0
    out = []
    last = 0
    for m in matches:
        if replaced >= max_fix:
            break
        out.append(text[last:m.start()])
        # 保留单次：XX→X
        out.append(m.group(1) + "的")
        replaced += 1
        last = m.end()
    out.append(text[last:])
    if replaced:
        stats["redup_adj"] = stats.get("redup_adj", 0) + replaced
    return "".join(out)


def _fix_fake_sensory(text: str, stats: dict) -> str:
    """假感官词清洗："干得发涩""疼得发抖""冷得发僵"超 FAKE_SENSORY_MAX 处时，
    将多余的"得发X"替换为"得厉害"（通用程度补语，不丢强度语义，去机械模板感）。
    如"嗓子干得发涩"→"嗓子干得厉害"。"""
    matches = list(_FAKE_SENSORY_RE.finditer(text))
    if len(matches) <= FAKE_SENSORY_MAX:
        return text
    need = len(matches) - FAKE_SENSORY_MAX
    replaced = 0
    # 反向遍历避免位置偏移
    out = text
    for m in reversed(matches):
        if replaced >= need:
            break
        # "X得发Y" → "X得厉害"
        out = out[:m.start()] + m.group(1) + "得厉害" + out[m.end():]
        replaced += 1
    if replaced:
        stats["fake_sensory"] = stats.get("fake_sensory", 0) + replaced
    return out


def _fix_half_explain(text: str, stats: dict) -> str:
    """半解释骑墙清洗："某种X""说不清的X""说不出的X" 超 HALF_EXPLAIN_MAX 处时，
    删除多余的"某种"/"说不清的"/"说不出的"前缀（保留后续内容，语义不丢）。
    如"某种被压得很平的东西"→"被压得很平的东西"。
    阶段一执行（含对话），因为台词里也有"某种"骑墙。
    删除"某种"后可能暴露内嵌的"说不清的"（如"某种X...说不清的Y"删"某种"后剩"说不清的Y"），
    所以做二次扫描确保不残留。"""
    for _ in range(2):  # 最多两轮：第二轮清理第一轮暴露的"说不清/出的"
        all_hits = list(_HALF_EXPLAIN_RE.finditer(text))
        if len(all_hits) <= HALF_EXPLAIN_MAX:
            break
        need = len(all_hits) - HALF_EXPLAIN_MAX
        removed = 0
        to_delete = []  # [(start, length), ...]
        for m in reversed(all_hits):
            if removed >= need:
                break
            matched = m.group(0)
            if matched.startswith("某种说不"):
                prefix_len = len("某种说不") + 1  # +1 for 清/出
                if matched[prefix_len:prefix_len + 1] in "的了":
                    prefix_len += 1
                to_delete.append((m.start(), prefix_len))
                removed += 1
            elif matched.startswith("某种"):
                to_delete.append((m.start(), 2))  # 删"某种"
                removed += 1
            elif matched.startswith("说不"):
                prefix_len = len("说不") + 1  # +1 for 清/出
                if matched[prefix_len:prefix_len + 1] in "的了":
                    prefix_len += 1
                to_delete.append((m.start(), prefix_len))
                removed += 1
        if not to_delete:
            break
        for start, length in to_delete:
            text = text[:start] + text[start + length:]
        stats["half_explain"] = stats.get("half_explain", 0) + removed
    return text


def _fix_short_action_burst(text: str, stats: dict) -> str:
    """短动作连排合并："碎了。塌了。散了。"（动词+了+句号连续≥3）→ "碎了，塌了，散了。"
    同时处理混合标点版："赤月暗了。亮了，暗了。亮了。"（动词+了+[。，！]连续≥3）
    （AI 节奏模板：连续短动作独立成句制造紧凑感，人类会用逗号一气呵成）
    全文最多处理 SHORT_ACTION_BURST_MAX 处。"""
    # 优先匹配纯句号版（更严格），再匹配混合标点版
    matches = list(_SHORT_ACTION_BURST_RE.finditer(text))
    # 收集已匹配区间，避免混合版重复匹配
    matched_ranges = [(m.start(), m.end()) for m in matches]
    mixed_matches = []
    for m in _SHORT_ACTION_BURST_MIXED_RE.finditer(text):
        # 跳过与纯句号版重叠的区间
        if not any(m.start() >= s and m.end() <= e for s, e in matched_ranges):
            mixed_matches.append(m)
    all_matches = sorted(matches + mixed_matches, key=lambda x: x.start())
    if not all_matches:
        return text
    fixed = 0
    out = []
    last = 0
    for m in all_matches:
        if fixed >= SHORT_ACTION_BURST_MAX:
            break
        out.append(text[last:m.start()])
        chunk = m.group(1)
        # 把内部的句号/感叹号换成逗号，末尾标点保留
        inner = chunk[:-1].replace("。", "，").replace("！", "，")
        out.append(inner + chunk[-1])
        last = m.end()
        fixed += 1
    out.append(text[last:])
    if fixed:
        stats["short_action_burst"] = stats.get("short_action_burst", 0) + fixed
    return "".join(out)


# ==================== 结构性去模板改写（零 token 平替 LLM 定向改写） ====================
# 针对固定结构模板（弹幕节奏/说明书标签/序号群像），纯程序化改写，不调 LLM、不耗 token。
# 与 LLM 改写的边界：LLM 能理解语义重写整段；程序化只能识别"固定句式"做打散/替换。
# 覆盖面：弹幕7连拍、简介3连插、序号声音4连 —— 正是结构性 AI 味的主要来源。

# 弹幕独立引导段（整段只有"弹幕X了。"）：保留第1个，后续删除（弹幕内容自带情绪，引导句冗余）
_DANMAKU_GUIDE_RE = re.compile(r"^弹幕[^。！？\n]{0,10}?[了的。！？]?[。！？]?$")


def _fix_danmaku_rhythm(text: str, stats: dict) -> str:
    """弹幕节奏去模板（零 token）：独立成段的"弹幕X了。"引导句全文只保留第1个，
    后续整段删除——弹幕内容自带情绪，引导句是纯冗余转场（"停了→活了→炸了→又炸了
    →沉默→骂不动→刷得飞快"7连拍=AI 固定节奏）。
    段内弹幕描写（"弹幕停了。刚才还刷得飞起的...全消失了"）不处理，保留信息量。"""
    paras = text.split("\n\n")
    if len(paras) < 2:
        return text
    kept = False
    removed = 0
    out = []
    for seg in paras:
        s = seg.strip()
        if _DANMAKU_GUIDE_RE.match(s):
            if not kept:
                kept = True
                out.append(seg)
            else:
                removed += 1
                continue
        else:
            out.append(seg)
    if removed:
        stats["danmaku_rhythm"] = stats.get("danmaku_rhythm", 0) + removed
        return "\n\n".join(out)
    return text


# 说明书标签"。简介"（《X》。简介：「…」 / 《X》。简介，「…」 / 《X》。简介只有一行字：「…」）
# 注意：_fix_colon 可能先把冒号压成逗号，故标点类需同时兼容冒号/逗号
_INTRO_LABEL_RE1 = re.compile(r"。简介只有一行字([，,：:])")
_INTRO_LABEL_RE2 = re.compile(r"。简介([，,：:])")


def _fix_intro_label(text: str, stats: dict) -> str:
    """说明书式设定去标签（零 token）：删掉"。简介"标签词，让功法名直接引出内容——
    "《九转元功》。简介只有一行字：「无属性。修炼速度极慢...」" → "《九转元功》只有一行字：「...」"，
    "《碎骨重铸诀》。简介：「...」" → "《碎骨重铸诀》：「...」"。
    三连"简介"直插=说明书式叙述（AI 味）；去标签后变为系统面板式呈现，阅读更自然。
    规则1（只有一行字）必须先于规则2执行，避免二次匹配。"""
    t, n1 = _INTRO_LABEL_RE1.subn(lambda m: "只有一行字" + m.group(1), text)
    t, n2 = _INTRO_LABEL_RE2.subn("：", t)
    n = n1 + n2
    if n:
        stats["intro_label"] = stats.get("intro_label", 0) + n
    return t


# 序号化声音（"第一个声音/第二个声音/第四个声音"连续罗列=AI 群像模板）
_VOICE_INDEX_RE = re.compile(r"第[一二三四五六七八九十\d]+个声音")
_VOICE_VARIANTS = ("另一个声音", "又一个声音", "一个声音")


def _fix_voice_index(text: str, stats: dict) -> str:
    """序号声音去模板（零 token）："第X个声音"只保留第1个建立群像语境，
    后续按变体池轮换为"另一个声音/又一个声音/一个声音"——打破教科书编号式罗列。"""
    matches = list(_VOICE_INDEX_RE.finditer(text))
    if len(matches) <= 1:
        return text
    out = []
    last = 0
    changed = 0
    for i, m in enumerate(matches):
        out.append(text[last:m.start()])
        if i == 0:
            out.append(m.group(0))
        else:
            out.append(_VOICE_VARIANTS[(i - 1) % len(_VOICE_VARIANTS)])
            changed += 1
        last = m.end()
    out.append(text[last:])
    if changed:
        stats["voice_index"] = stats.get("voice_index", 0) + changed
        return "".join(out)
    return text


def _fix_danmu_format(text: str, stats: dict) -> str:
    """弹幕格式规范化（「」为弹幕专用括号，AI 输出常见四种错乱）：
    1) 对白内部混入弹幕："……「X」……" → 弹幕拆出独立成行
    2) 双重右引号：「X」」 → 「X」
    3) 弹幕行尾悬挂右双引号：「X」” → 「X」
    4) 弹幕黏在叙述句尾（含未闭合）→ 拆独立行并补「」
    必须放在阶段一（引号占位保护之前）执行，否则对白内的弹幕看不到。"""
    changed = 0
    # 1) 对白内弹幕拆出（subn 循环最多3轮，覆盖同句多条弹幕）
    for _ in range(3):
        def _extract(m):
            inner = m.group(1) + m.group(3)
            if not inner.strip():
                return f'「{m.group(2)}」'
            return f'“{inner}”\n\n「{m.group(2)}」'
        text, n = _DANMU_IN_DIALOGUE_RE.subn(_extract, text)
        changed += n
        if not n:
            break
    # 2) 双重右引号
    text, n = _DANMU_DOUBLE_CLOSE_RE.subn('」', text)
    changed += n
    # 3) 行尾悬挂右双引号
    text, n = _DANMU_HANGING_QUOTE_RE.subn('」', text)
    changed += n
    # 4) 黏在叙述句尾的弹幕拆独立行（未闭合自动补」）
    def _split_glued(m):
        g = m.group(1)
        if not g.endswith('」'):
            g += '」'
        return '\n\n' + g
    text, n = _DANMU_GLUED_RE.subn(_split_glued, text)
    changed += n
    if changed:
        stats["danmu_format"] = stats.get("danmu_format", 0) + changed
    return text


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
    # ---- 阶段零：配置化规则（conf/ai_feature_rules.json，新增特征无需改代码，优先执行） ----
    # 置于最前，保证用户新增特征先于内置规则生效，不被后续规则改动影响匹配
    text, cfg_stats = apply_config_clean(text)
    if cfg_stats:
        stats.update(cfg_stats)
    # ---- 阶段一：全文级（含对话）标点/句式规则 ----
    # AI 特征大量藏在台词里（"我记住了——那些不说话的""不是三年五年。是三百年。"），
    # 必须先于引号占位保护执行，否则对话内的破折号/"不是X"全部漏洗
    # 弹幕格式错乱也藏在对白内部（"……「X」……"），必须最先执行
    text = _fix_danmu_format(text, stats)
    text = _fix_dash(text, stats)
    text = _fix_not_is(text, stats)
    text = _fix_not_is_dual(text, stats)
    text = _fix_not_is_dot(text, stats)
    text = _fix_triple(text, stats)
    text = _fix_longlist(text, stats)
    text = _fix_body_scan(text, stats)
    text = _fix_simile(text, stats)
    text = _fix_like_density(text, stats)
    text = _fix_abrupt_adverbs(text, stats)
    text = _fix_simile_guides(text, stats)
    text = _fix_half_explain(text, stats)
    text = _fix_reduplicative_adj(text, stats)
    text = _fix_fake_sensory(text, stats)
    # 新增阶段一规则（标点修复/逗号三连/双重比喻/双框比喻/句子残缺/形容词链悬空）
    text = _fix_punct_bug(text, stats)
    text = _fix_comma_triple(text, stats)
    text = _fix_double_simile(text, stats)
    text = _fix_frame_simile(text, stats)
    text = _fix_sentence_broken(text, stats)
    text = _fix_adj_chain_dash(text, stats)
    text = _fix_de_broken(text, stats)
    # 状态词+得+逗号误用（"静得，一条弹幕都没有"）
    text = _fix_de_comma(text, stats)
    # 完全相同台词/弹幕行复读压减（"检索修仙文明，无此生命体"×5）
    text = _fix_repeated_quote_lines(text, stats)
    # 新增阶段一规则：助词残缺/形容词悬空/字重复/否定三连/部位扫描/同动排比/判断堆叠/ABAB叠词
    text = _fix_aux_broken(text, stats)
    text = _fix_adj_dangling(text, stats)
    text = _fix_fused_char_repeat(text, stats)
    text = _fix_sentence_fused(text, stats)
    text = _fix_noun_pronoun_fused(text, stats)
    text = _fix_neg_triple_mix(text, stats)
    text = _fix_range_scan(text, stats)
    text = _fix_verb_triple_scan(text, stats)
    text = _fix_is_is_stack(text, stats)
    text = _fix_redup_abab(text, stats)
    # ---- 阶段二：引号保护后，句法/段落级规则（不伤对话） ----
    protected, placeholders = _protect_quotes(text)
    protected = _fix_colon(protected, stats)
    protected = _fix_ellipsis(protected, stats)
    protected = _fix_exclaim(protected, stats)
    protected = _fix_conjunctions(protected, stats)
    protected = _fix_redundant_subject(protected, stats)
    protected = _fix_short_sentence_tail(protected, stats)
    protected = _fix_buffer_paragraphs(protected, stats)
    # 短句独立段密度熔断（碎片化占比过高时合并纯叙述短段）
    protected = _fix_short_para_density(protected, stats)
    protected = _fix_emotion_label(protected, stats)
    protected = _fix_even_paragraphs(protected, stats)
    protected = _fix_short_para_density(protected, stats)
    protected = _fix_even_sentences(protected, stats)
    protected = _fix_duplicate_paragraphs(protected, stats)
    protected = _fix_repeated_sentences(protected, stats)
    protected = _fix_word_variants(protected, stats)
    protected = _fix_para_head_subject(protected, stats)
    # 新增阶段二规则（形容词独立段并入/短动作连排合并）
    protected = _fix_adj_independent(protected, stats)
    protected = _fix_short_action_burst(protected, stats)
    # 新增阶段二规则（结构性去模板：弹幕节奏/说明书标签/序号群像，零 token 平替 LLM 改写）
    protected = _fix_danmaku_rhythm(protected, stats)
    protected = _fix_intro_label(protected, stats)
    protected = _fix_voice_index(protected, stats)
    result = _restore_quotes(protected, placeholders)
    if stats:
        total = sum(stats.values())
        system_logger.info(f"[程序化清洗] 共替换 {total} 处: {stats}")
    return result, stats


# ==================== 内容层 AI 特征检测（纯代码正则，无 LLM 依赖） ====================
# 检测项供写作时规避参考；章节生成不再做 LLM 定向改写（20260811 起仅正则清洗）。
# "比X+形容词"比较句（"比我的大""比我们都旧"；口语"总比饿死强"也会计入，占比小可容忍）
_BI_RE = get_regex("bi")
# "跟X似的"/"跟X一样"比喻（内容层红牌：全章最多1处）
_GENXI_RE = get_regex("genxi")
# 否定排队（"不知道。不知道。"连续短句 ≥2 次）
_NEG_QUEUE_RE = get_regex("neg_queue")
# 比喻句式扩展检测：像X/跟X一样/仿佛X/犹如X/好似X（用于段落级密度统计，区别于 _GENXI_RE 的总量口径）
# 覆盖"像X一样/似的/般"和"像X+动词"（如"像金属被腐蚀了一半"）两种结构
_METAPHOR_RE = get_regex("metaphor")
# "是X。"判断句独立成段（"是陈述。""是它在动。""是链条本身在降温。"段首独立短句=冷峻模板感）
# 匹配段落开头的"是X。"短句（X 不含句号，长度 2-20 字），后可跟换行或同段其他内容
_IS_JUDGE_RE = get_regex("is_judge")
# 推理展开：情绪/语气判断句后紧跟"是..."的解释链（"是陈述。是等了很久..."）
_REASONING_CHAIN_RE = get_regex("reasoning_chain")
# 台词对仗候选：连续两句台词字数差 ≤2 且都 ≤14 字（"比我的大。""也比我的旧。"）
# ---- 新增检测正则 ----
# "没有X，没有Y，只有Z" 三连否定排比（"没有恐惧，没有厌恶，只有熟悉感"=AI 情绪层次模板）
_NEG_HAVE3_RE = get_regex("neg_have3")
# "没有X，没有Y，没有Z" 纯否定三连（第三个也是"没有"："没有怒气，没有恨意，没有一丝波动"=AI 情绪层次模板）
_NEG_HAVE3_NEG_RE = get_regex("neg_have3_neg")
# 纯三连否定（"没有血没有骨头，没有内脏"=AI 三重否定堆砌，无"只有Z"结尾变体）
# 匹配"没有X没有Y，没有Z"（前两项无逗号分隔，第三项以逗号/句号结尾）
_NEG_PURE_TRIPLE_RE = get_regex("neg_pure_triple")
# 完全相同台词/弹幕行（整行都在引号内）：≥3次=AI 复读填充（"检索修仙文明，无此生命体"×5）
_REPEAT_QUOTE_LINE_RE = get_regex("repeat_quote_line")
# "某种X""说不清的X""说不出的X" 半解释（骑墙描写=AI 怕说死又怕说太死的特征）
_HALF_EXPLAIN_RE = get_regex("half_explain")
# 书面连词超频（不仅X而且Y / 既X又Y / 与其X不如Y / 与其说X不如说Y）
_FORMAL_CONJ_RE = get_regex("formal_conj")
# 四字格堆叠（单段内连续 3+ 个"4字+，/、"且其中至少1个为真成语=成语堆砌；排除弹幕内容）
_IDIOM_QUAD_RE = get_regex("idiom_quad")
# 常用成语集（四字格判定用：仅连续 4 字串命中本集才算真堆砌，避免"不是肠子，粗一大圈"类误报）
_IDIOM_SET = frozenset(get_wordlist("IDIOM_SET"))
# 弹幕内容（用于四字格等统计前剔除，避免弹幕碎片拉高密度）
_DANMAKU_STRIP_RE = get_regex("danmaku_strip")
# 枚举式列举（"第一条线往西…第二条线往东北…第三条线往东…"=AI 系统性逐条覆盖）
# 匹配"第N[条个层种步]"连续出现≥3次（跨句/跨行，中间可有任何内容）
_ENUM_ITEM_RE = get_regex("enum_item")


def _find_repeated_phrases(text: str, min_count: int = 3) -> list:
    """扫描纯叙述文本，找出同一中文短语（5~12字）出现≥3次的"复读描写"
    （"左肩的倒刺"同一章5次=AI 复读机，检测器对整句/整词重复敏感）。
    只统计引号外叙述（台词里的重复另算），子串不重复报（只报最长短语）。
    :return: [(短语, 出现次数), ...] 按短语长度降序
    """
    from collections import Counter
    body = _QUOTE_RE.sub("", text)          # 去掉引号内台词，只统计叙述
    chunks = re.findall(r'[\u4e00-\u9fff]{5,}', body)  # 只取中文连续串
    counter = Counter()
    for chunk in chunks:
        L = len(chunk)
        for n in range(12, 4, -1):
            if n > L:
                continue
            for i in range(L - n + 1):
                counter[chunk[i:i + n]] += 1
    cand = sorted(((p, c) for p, c in counter.items() if c >= min_count),
                  key=lambda x: -len(x[0]))
    out = []
    for p, c in cand:
        if any(p in longer for longer, _ in out):
            continue
        out.append((p, c))
    return out


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
    # "没有X，没有Y，只有Z" / "没有X，没有Y，没有Z" 三连否定排比检测（AI 情绪层次模板）
    try:
        neg3 = _NEG_HAVE3_RE.findall(text) + _NEG_HAVE3_NEG_RE.findall(text) + _NEG_PURE_TRIPLE_RE.findall(text)
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
    # 四字格堆叠检测（单段内连续2+个"XXXX，/、"=成语/短语堆砌；排除弹幕内容）
    try:
        paras_idiom = [p for p in re.split(r'\n\s*\n', text) if p.strip()]
        dense_idiom_cnt = 0
        for p in paras_idiom:
            s = _DANMAKU_STRIP_RE.sub('', p)
            for frag in _IDIOM_QUAD_RE.findall(s):
                parts = re.findall(r'[\u4e00-\u9fff]{4}(?=[，、])', frag)
                if any(part in _IDIOM_SET for part in parts):
                    dense_idiom_cnt += 1
                    break
        if dense_idiom_cnt:
            report["四字格堆砌"] = dense_idiom_cnt
    except Exception:
        pass
    # 短句独立段密度检测（≤12字独立段占比>15%=AI 节奏模板）
    # 排除纯对话行（引号包裹的弹幕/台词），对话短是正常的不是 AI 特征
    try:
        paras_short = [p.strip() for p in text.split("\n\n") if p.strip()]
        if paras_short:
            # 排除纯对话行：以「」""''包裹或 __Q占位
            def _is_dialogue(p: str) -> bool:
                if p.startswith("__Q") and p.endswith("__"):
                    return True
                for q in ("“", "”", "「", "」", "『", "』", '"', "'", "\uff02"):
                    if p.startswith(q):
                        return True
                return False
            narrative = [p for p in paras_short if not _is_dialogue(p)]
            if narrative:
                short_cnt = sum(1 for p in narrative if len(p) <= 12)
                ratio = short_cnt / len(narrative)
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
    # "X得不。"残缺变体检测（"亮得不。""静得不。"=补语被截断）
    try:
        de_bu = _DE_BU_RE.findall(text)
        if de_bu:
            report["得不截断句"] = len(de_bu)
    except Exception:
        pass
    # 叙述残段贴台词（"麻的，"直接接台词=叙述断句错误）
    try:
        narr_quote = _DE_NARR_QUOTE_RE.findall(text)
        if narr_quote:
            report["叙述残段贴台词"] = len(narr_quote)
    except Exception:
        pass
    # 序数对仗（"第一秒/第二秒/第三秒"教科书编号列举）
    try:
        seq = _SEQ_COUNT_RE.findall(text)
        if len(seq) >= 3:
            report["序数对仗"] = len(seq)
    except Exception:
        pass
    # 假设句模板（"巨大化，一脚踩死…""无敌，…"罗列式脑补）
    try:
        if_tmpl = _IF_TEMPLATE_RE.findall(text)
        if len(if_tmpl) >= 2:
            report["假设句模板"] = len(if_tmpl)
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
    # "像某种X"分类标签比喻（AI 教科书化：先分类再描述=最典型的 AI 比喻格式）
    try:
        like_some = _LIKE_SOME_KIND_RE.findall(text)
        if len(like_some) >= 1:
            report["像某种分类比喻"] = len(like_some)
    except Exception:
        pass
    # "微微X"状态副词模板（AI 高频滥用弱化副词：微微发白/蠕动/泛红=用"微微"代替具体动作）
    try:
        weiwei = _WEIWEI_ADV_RE.findall(text)
        if len(weiwei) >= 2:
            report["微微副词模板"] = len(weiwei)
    except Exception:
        pass
    # "得发X"程序化形容词组合（AI 高频：干得发紧/疼得发麻=不用"发干/发疼"这种单字口语，非得"得发"拼接）
    try:
        de_fa = _DE_FA_RE.findall(text)
        if len(de_fa) >= 1:
            report["得发X形容词模板"] = len(de_fa)
    except Exception:
        pass
    # "拟声词一声+动词"动作包装模板（AI 高频：咔哒一声推进去=拟声+动作程序化绑定）
    try:
        onoma = _ONOMATOPOEIA_TEMPLATE_RE.findall(text)
        if len(onoma) >= 2:
            report["拟声动作模板"] = len(onoma)
    except Exception:
        pass
    # 冒号版检索库弹幕连排（AI："检索：修仙文明数据库，无匹配"×N=带冒号变体）
    try:
        sc_lib = _SEARCH_COLON_LIB_RE.findall(text)
        if len(sc_lib) >= 2:
            report["检索库连排"] = len(sc_lib)
    except Exception:
        pass
    # 进度条0→100%叮一声完成（AI 机械数字全覆盖描写）
    try:
        pbar = _PROGRESS_BAR_TEMPLATE_RE.findall(text)
        if pbar:
            report["进度条模板"] = len(pbar)
    except Exception:
        pass
    # 弹幕停→炸节奏三连段（AI 跨章复读模板："弹幕安静了。三秒后，炸了。"）
    try:
        dktp = _DANMAKU_TEMP_RE.findall(text)
        if dktp:
            report["弹幕停炸节奏模板"] = len(dktp)
    except Exception:
        pass
    # 「」引号嵌套/错乱（AI 输出格式 bug：嵌套、双右引号、句号后引号紧邻；1 处即红牌）
    try:
        qm = _QUOTE_MISMATCH_RE.findall(text)
        if qm:
            report["引号嵌套错乱"] = len(qm)
    except Exception:
        pass
    # 副词裸逗号病句（"每个字都，"=副词后直接逗号=话没说完/输出截断）
    try:
        adv = _ADV_BARE_COMMA_RE.findall(text)
        if adv:
            report["副词裸逗号病句"] = len(adv)
    except Exception:
        pass
    # 叠字病句（"流流过锁骨"=重复字；白名单外的单字叠才报）
    try:
        red = _find_redup(text)
        if red:
            report["叠字病句"] = len(red)
    except Exception:
        pass
    # 被动判断句（"是被更强烈的感觉盖过去了。"=AI 冷峻被动判断模板）
    try:
        isb = _IS_BEI_RE.findall(text)
        if isb:
            report["是被判断句"] = len(isb)
    except Exception:
        pass
    # "名词+句号"堆叠（"一张床。一张桌子。一把椅子。"=AI 名词罗列节奏）
    try:
        nds = _NOUN_DOT_STACK_RE.findall(text)
        if nds:
            report["名词句堆叠"] = len(nds)
    except Exception:
        pass
    # 属性说明罗列（"功法等级未知。上限未知。"=AI 属性说明书，≥2 处触发）
    try:
        atr = _ATTR_DOT_RE.findall(text)
        if len(atr) >= 2:
            report["属性说明罗列"] = len(atr)
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
    # "得发X"假感官词检测（"干得发涩""疼得发抖"=AI 程度补语模板）
    try:
        fake_sensory = _FAKE_SENSORY_RE.findall(text)
        if len(fake_sensory) > FAKE_SENSORY_MAX:
            report["假感官词"] = len(fake_sensory)
    except Exception:
        pass
    # 枚举式列举检测（"第一条线…第二条线…第三条线…"=AI 系统性逐条覆盖）
    # 同一量词的"第N[量词]"出现≥3次=结构性枚举，交 LLM 改写打散结构
    try:
        enum_hits = _ENUM_ITEM_RE.findall(text)
        if len(enum_hits) >= 3:
            report["枚举式列举"] = len(enum_hits)
    except Exception:
        pass
    # ---- 新增 8 项 AI 特征检测 ----
    # 助词残缺（每吐一个字都。= 都/会/能直接断句缺补语）
    try:
        aux_broken = _AUX_BROKEN_RE.findall(text)
        if len(aux_broken) > AUX_BROKEN_MAX:
            report["助词残缺句"] = len(aux_broken)
    except Exception:
        pass
    # 悬空形容词独立（"暗红色的，看得见走向"="的，"句中悬空）
    try:
        adj_dangling = _ADJ_DANGLING_RE.findall(text)
        if len(adj_dangling) > ADJ_INDEP_DANGLING_MAX:
            report["悬空形容词独立"] = len(adj_dangling)
    except Exception:
        pass
    # 字重复粘连（"落落在地上"=落+落缺分隔）
    try:
        char_repeat = _FUSED_CHAR_REPEAT_RE.findall(text)
        if len(char_repeat) > FUSED_CHAR_REPEAT_MAX:
            report["字重复粘连"] = len(char_repeat)
    except Exception:
        pass
    # 混合标点否定三连（不是X。不是Y，不是Z）
    try:
        neg_mix = _NEG_TRIPLE_MIX_RE.findall(text)
        if len(neg_mix) > NEG_TRIPLE_MIX_MAX:
            report["混合标点否定三连"] = len(neg_mix)
    except Exception:
        pass
    # "从A到B，到C，到D" 部位范围系统性扫描
    try:
        range_scan = _RANGE_SCAN_RE.findall(text)
        if len(range_scan) >= 1:
            report["部位范围系统扫描"] = len(range_scan)
    except Exception:
        pass
    # 同动词三连排比扫描（落在A，落在B，落在C）
    try:
        verb_scan = _VERB_TRIPLE_SCAN_RE.findall(text)
        if len(verb_scan) >= 1:
            report["同动词三连排比"] = len(verb_scan)
    except Exception:
        pass
    # 判断句堆叠（XX是A，是B）
    try:
        is_stack = _IS_IS_STACK_RE.findall(text)
        if len(is_stack) > IS_IS_STACK_MAX:
            report["判断句堆叠"] = len(is_stack)
    except Exception:
        pass
    # ABAB式多字叠词（太久太久/一根一根，排除白名单）
    try:
        abab_all = _REDUP_ABAB_RE.findall(text)
        abab_cnt = sum(1 for m in _REDUP_ABAB_RE.finditer(text) if m.group(0) not in _REDUP_ABAB_SAFE)
        if abab_cnt > REDUP_ABAB_MAX:
            report["ABAB多字叠词"] = abab_cnt
    except Exception:
        pass
    # 同场景复读短语检测（"左肩的倒刺"同一章多次=AI 复读描写，检测器对整词重复敏感）
    try:
        reps = _find_repeated_phrases(text)
        if reps:
            report["同场景复读短语"] = len(reps)
    except Exception:
        pass
    # 配置化检测规则（conf/ai_feature_rules.json，新增特征无需改代码；命中数 >= threshold 才上报）
    cfg_report = apply_config_detect(text)
    if cfg_report:
        report.update(cfg_report)
    return report

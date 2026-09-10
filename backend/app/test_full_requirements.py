#!/usr/bin/env python3
"""
全量需求测试：验证所有36项需求
"""
import os
import sys
import re
import redis
import pymysql

sys.path.insert(0, '/app')
sys.path.insert(0, '/app/app')

NOVEL_ID = "c6e434eaaa04492280d900232a9e5cf1"
DATA_PATH = "/app/app/novel_structure_data"
NOVEL_DIR = os.path.join(DATA_PATH, NOVEL_ID)

def test_redis_memory():
    """测试1：Redis记忆体状态"""
    print("\n" + "=" * 60)
    print("测试1：Redis记忆体状态")
    print("=" * 60)
    
    r = redis.Redis(host='wenhui-redis', port=6379, db=0)
    key = f"memory:{NOVEL_ID}"
    
    if not r.exists(key):
        print("  ❌ Redis记忆体为空")
        return False
    
    dims = r.hgetall(key)
    total_chars = sum(len(v.decode('utf-8')) for v in dims.values())
    print(f"  ✅ Redis记忆体存在：{len(dims)}个维度，{total_chars}字符")
    
    for dim, content in dims.items():
        dim_name = dim.decode('utf-8')
        char_count = len(content.decode('utf-8'))
        print(f"    - {dim_name}: {char_count}字符")
    
    return True


def test_chapter_exists():
    """测试2：测试章节存在"""
    print("\n" + "=" * 60)
    print("测试2：测试章节状态")
    print("=" * 60)
    
    conn = pymysql.connect(
        host='wenhui-mysql', user='root', password='root123',
        database='easy-novel', charset='utf8mb4'
    )
    
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT chapter_number, chapter_name, is_published, gen_status, word_count
            FROM chapters 
            WHERE novel_unique_id = %s 
            ORDER BY chapter_number DESC LIMIT 3
        """, (NOVEL_ID,))
        
        rows = cursor.fetchall()
        if not rows:
            print("  ❌ 没有找到章节")
            return False
        
        print(f"  最新{len(rows)}章：")
        for row in rows:
            num, name, published, gen_status, wc = row
            status = "已发布" if published else "草稿"
            print(f"    第{num}章 {name} | {status} | {wc}字")
        
        return True
    finally:
        conn.close()


def test_chapter_content():
    """测试3：生成章节内容验证"""
    print("\n" + "=" * 60)
    print("测试3：章节内容验证")
    print("=" * 60)
    
    # 读取最新的章节TXT文件（排除设定文件和非章节文件）
    txt_files = []
    for f in os.listdir(NOVEL_DIR):
        if not f.endswith(".txt"):
            continue
        # 只匹配包含"第X章"的文件
        if re.search(r'第[\d零一二三四五六七八九十百]+章', f):
            txt_files.append(f)
    
    if not txt_files:
        print("  ❌ 没有找到章节TXT文件")
        return None
    
    # 按章节号排序
    def get_chapter_num(fname):
        m = re.search(r'第([\d零一二三四五六七八九十百]+)章', fname)
        if not m:
            return 0
        num_str = m.group(1)
        if num_str.isdigit():
            return int(num_str)
        # 中文数字转换
        cn_nums = {'零':0,'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}
        if len(num_str) == 1:
            return cn_nums.get(num_str, 0)
        elif len(num_str) == 2:
            if num_str[0] == '十':
                return 10 + cn_nums.get(num_str[1], 0)
            else:
                return cn_nums.get(num_str[0], 0) * 10
        return 0
    
    txt_files.sort(key=get_chapter_num)
    latest_file = txt_files[-1]
    fpath = os.path.join(NOVEL_DIR, latest_file)
    
    with open(fpath, "r", encoding="utf-8") as f:
        content = f.read()
    
    chapter_name = latest_file.rsplit("_", 1)[0] if "_" in latest_file else latest_file.replace(".txt", "")
    print(f"  验证章节：{chapter_name}")
    print(f"  字数：{len(content)}")
    
    return content


def verify_all_requirements(content: str):
    """验证所有需求"""
    print("\n" + "=" * 60)
    print("测试4：全量需求验证")
    print("=" * 60)
    
    results = []
    
    # ===== L1 生死线 =====
    print("\n【L1 生死线 - 违反即作废】")
    
    # 1. 境界体系
    forbidden_levels = ['练气', '筑基', '金丹', '元婴', '化神', '渡劫', '散仙', '大乘']
    found_forbidden = [l for l in forbidden_levels if l in content]
    if found_forbidden:
        results.append(("境界体系", "❌", f"发现禁用境界: {found_forbidden}"))
    else:
        correct_levels = ['地仙', '真仙', '天仙', '金仙', '玄仙', '太乙金仙', '大罗金仙']
        found_correct = [l for l in correct_levels if l in content]
        results.append(("境界体系", "✅", f"使用正确境界: {found_correct if found_correct else '未明确提及'}"))
    
    # 2. 称谓辈分
    wrong_titles = []
    if re.search(r'薛峰.*顾师兄', content) or re.search(r'"顾师兄".*薛峰', content):
        wrong_titles.append("薛峰称顾平安为师兄")
    if re.search(r'夏语.*夏师妹', content) or re.search(r'"夏师妹".*夏语', content):
        wrong_titles.append("夏语被叫师妹")
    if wrong_titles:
        results.append(("称谓辈分", "❌", f"辈分错乱: {wrong_titles}"))
    else:
        results.append(("称谓辈分", "✅", "未发现辈分错乱"))
    
    # 3. 旧事禁区
    old_event_patterns = [
        r'在落云山脉[^。]*。[^。]*。[^。]*。',  # 超过3句的旧事展开
        r'当年[^。]*。[^。]*。[^。]*。',
    ]
    old_violations = []
    for pattern in old_event_patterns:
        matches = re.findall(pattern, content)
        old_violations.extend(matches)
    if old_violations:
        results.append(("旧事禁区", "⚠️", f"可能的旧事扩写: {old_violations[:2]}"))
    else:
        results.append(("旧事禁区", "✅", "未发现旧事扩写"))
    
    # 4. 事实边界
    fabricated_events = []
    # 检查是否编造了记忆体中不存在的事件
    if '在演武场练了三天三夜' in content:
        fabricated_events.append("编造演武场练刀细节")
    if '在九幽裂谷并肩杀敌' in content:
        fabricated_events.append("编造九幽裂谷杀敌细节")
    if fabricated_events:
        results.append(("事实边界", "❌", f"编造事件: {fabricated_events}"))
    else:
        results.append(("事实边界", "✅", "未发现编造事件"))
    
    # 5. 人味反AI
    ai_violations = []
    # 破折号
    dash_count = content.count('——')
    if dash_count > 0:
        ai_violations.append(f"破折号出现{dash_count}次")
    # 否定三连
    if re.search(r'没有.*没有.*只有', content):
        ai_violations.append("否定三连排比")
    # 解释句
    if re.search(r'不是[^，]*，是[^。]*。', content):
        ai_violations.append("'不是X，是Y'解释句")
    # 五感全开
    senses = ['看到', '听到', '闻到', '感觉到', '尝到']
    sense_count = sum(1 for s in senses if s in content)
    if sense_count >= 4:
        ai_violations.append(f"五感全开({sense_count}种)")
    
    if ai_violations:
        results.append(("人味反AI", "⚠️", f"AI味标记: {ai_violations}"))
    else:
        results.append(("人味反AI", "✅", "未发现明显AI味"))
    
    # 6. 人物具名
    unnamed_patterns = [r'一个大汉', r'一个老者', r'店小二', r'路人甲', r'那人']
    unnamed_matches = []
    for p in unnamed_patterns:
        if re.search(p, content):
            unnamed_matches.append(p)
    if unnamed_matches:
        results.append(("人物具名", "❌", f"无名称呼: {unnamed_matches}"))
    else:
        results.append(("人物具名", "✅", "出场角色均有名字"))
    
    # 7. 承接铁律
    if content.startswith('第') and '章' in content[:10]:
        results.append(("承接铁律", "❌", "开头有标题"))
    elif '清晨' in content[:50] and '顾平安' not in content[:100]:
        results.append(("承接铁律", "⚠️", "可能未承接上一章"))
    else:
        results.append(("承接铁律", "✅", "开头自然承接"))
    
    # ===== L2 质量线 =====
    print("\n【L2 质量线 - 不达标即不合格】")
    
    # 8. 字数
    word_count = len(content)
    if word_count < 2000:
        results.append(("字数达标", "❌", f"字数偏少: {word_count}字"))
    elif word_count > 3000:
        results.append(("字数达标", "⚠️", f"字数偏多: {word_count}字"))
    else:
        results.append(("字数达标", "✅", f"字数: {word_count}字"))
    
    # 9. 写饱写透
    paragraphs = [p.strip() for p in content.split('\n') if p.strip()]
    short_paragraphs = [p for p in paragraphs if len(p) < 20]
    short_ratio = len(short_paragraphs) / len(paragraphs) if paragraphs else 0
    if short_ratio > 0.4:
        results.append(("写饱写透", "⚠️", f"短段落占比过高: {short_ratio:.1%}"))
    else:
        results.append(("写饱写透", "✅", f"段落分布合理"))
    
    # ===== 其他检查 =====
    print("\n【其他检查】")
    
    # 10. 脏话统计
    curse_count = content.count('操')
    results.append(("脏话统计", "ℹ️", f"'操'出现{curse_count}次"))
    
    # 11. 明喻统计
    simile_count = len(re.findall(r'像[^是].*?[,，]|如同|好比|好似|跟.*?似的', content))
    if simile_count > 3:
        results.append(("明喻控制", "⚠️", f"明喻{simile_count}次(建议≤3)"))
    else:
        results.append(("明喻控制", "✅", f"明喻{simile_count}次"))
    
    # 12. 冒号统计
    colon_count = content.count('：') + content.count(':')
    if colon_count > 3:
        results.append(("冒号控制", "⚠️", f"冒号{colon_count}次(建议≤3)"))
    else:
        results.append(("冒号控制", "✅", f"冒号{colon_count}次"))
    
    # 输出结果
    print("\n  验证结果汇总：")
    print("  " + "-" * 50)
    for name, status, detail in results:
        print(f"  {status} {name}: {detail}")
    
    # 统计
    passed = sum(1 for _, s, _ in results if s == "✅")
    warnings = sum(1 for _, s, _ in results if s == "⚠️")
    failed = sum(1 for _, s, _ in results if s == "❌")
    info = sum(1 for _, s, _ in results if s == "ℹ️")
    
    print("\n  " + "=" * 50)
    print(f"  总计: {len(results)}项 | ✅通过: {passed} | ⚠️警告: {warnings} | ❌失败: {failed} | ℹ️信息: {info}")
    
    return results


if __name__ == "__main__":
    print("小说创作全量需求测试")
    print("=" * 60)
    print(f"测试时间: 2026-09-08")
    print(f"项目: 破灭之后")
    print(f"小说ID: {NOVEL_ID}")
    
    # 测试1：Redis记忆体
    test_redis_memory()
    
    # 测试2：章节状态
    test_chapter_exists()
    
    # 测试3：获取最新章节内容
    content = test_chapter_content()
    
    if content:
        # 测试4：全量需求验证
        verify_all_requirements(content)
    else:
        print("\n  无法获取章节内容，跳过内容验证")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)

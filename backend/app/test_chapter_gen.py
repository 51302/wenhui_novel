#!/usr/bin/env python3
"""
测试章节生成：验证所有优化需求
1. 从TXT文件重建Redis记忆体
2. 创建测试章节
3. 调用AI生成
4. 验证输出
"""
import os
import sys
import json
import re
import redis

# 添加backend路径
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/app')

NOVEL_ID = "c6e434eaaa04492280d900232a9e5cf1"
DATA_PATH = "/app/app/novel_structure_data"
NOVEL_DIR = os.path.join(DATA_PATH, NOVEL_ID)

def build_memory_from_files():
    """从TXT文件构建简化记忆体"""
    print("=" * 60)
    print("步骤1：从TXT文件构建记忆体")
    print("=" * 60)
    
    # 读取作品设定
    settings_path = os.path.join(NOVEL_DIR, "作品设定.txt")
    settings = ""
    if os.path.exists(settings_path):
        with open(settings_path, "r", encoding="utf-8") as f:
            settings = f.read()
    
    # 读取所有章节TXT
    txt_files = sorted([f for f in os.listdir(NOVEL_DIR) 
                       if f.endswith(".txt") and f != "作品设定.txt"],
                      key=lambda x: int(re.search(r'第([\d]+)章', x).group(1)) if re.search(r'第([\d]+)章', x) else 9999)
    
    print(f"  找到 {len(txt_files)} 个章节文件")
    
    # 构建各维度记忆
    memory = {
        "人物": "",
        "组织势力": "",
        "地点": "",
        "功法技能法宝": "",
        "关键事件": "",
        "时间线": "",
        "伏笔悬念": "",
        "关键物品": "",
        "实力变化": "",
        "人物关系": "",
        "情感状态": ""
    }
    
    # 从各章节提取关键信息
    for fname in txt_files:
        fpath = os.path.join(NOVEL_DIR, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
        except:
            continue
        
        chapter_name = fname.rsplit("_", 1)[0] if "_" in fname else fname.replace(".txt", "")
        
        # 简单提取人物
        chars = re.findall(r'(顾平安|夏语|沈清岚|薛峰|赵小栓|苏晴|顾天行|青姨|阿狗)', content)
        unique_chars = list(set(chars))
        
        # 简单提取地点
        places = re.findall(r'(落空城|落云山脉|归元宗|五行宗|雷灵泉|演武场|藏经阁|九幽裂谷|地脉之眼)', content)
        unique_places = list(set(places))
        
        # 简单提取境界
        levels = re.findall(r'(地仙|真仙|天仙|金仙|玄仙|太乙金仙|太乙玄仙|大罗金仙)', content)
        unique_levels = list(set(levels))
        
        # 简单提取事件
        events = re.findall(r'(收徒大典|演武切磋|血煞图谋|吞源之秘|九窍蕴灵|琴笛和鸣|心意难明|风暴前夜|挑明心意)', content)
        unique_events = list(set(events))
        
        if unique_chars:
            memory["人物"] += f"{chapter_name}: {', '.join(unique_chars)}\n"
        if unique_places:
            memory["地点"] += f"{chapter_name}: {', '.join(unique_places)}\n"
        if unique_levels:
            memory["实力变化"] += f"{chapter_name}: {', '.join(unique_levels)}\n"
        if unique_events:
            memory["关键事件"] += f"{chapter_name}: {', '.join(unique_events)}\n"
    
    # 添加人物关系（基于代码中的设定）
    memory["人物关系"] = """
顾平安 - 夏语：师兄妹关系，夏语是师姐，顾平安是师弟（辈分正确）
顾平安 - 沈清岚：同门师兄妹，沈清岚是师妹
顾平安 - 薛峰：师兄弟关系，薛峰是师兄
顾平安 - 赵小栓：同门师兄弟
顾平安 - 苏晴：同门师兄妹
顾天行 - 顾平安：父子关系
青姨 - 顾平安：照顾者关系
"""
    
    # 添加情感状态
    memory["情感状态"] = """
顾平安对夏语：深爱，但一直隐藏感情，第84章挑明心意
顾平安对沈清岚：同门之情，有保护欲
夏语对顾平安：感情复杂，有牵挂但一直回避
沈清岚对顾平安：同门之情
"""
    
    # 添加关键事件
    memory["关键事件"] = """
第80章 情丝暗涌：顾平安和夏语之间的情感暗流
第81章 演武切磋：归元宗内部演武
第82章 心意难明：顾平安对感情的纠结
第83章 风暴前夜：重大事件前的平静
第84章 挑明心意：顾平安向夏语表白心意
"""
    
    # 添加伏笔悬念
    memory["伏笔悬念"] = """
血煞图谋：反派势力的阴谋
吞源之秘：关于力量来源的秘密
九窍蕴灵：修炼相关的秘密
"""
    
    # 添加境界体系
    memory["功法技能法宝"] = """
境界体系（铁律，只能使用这些）：
仙人（仙界普通人）→ 地仙 → 真仙 → 天仙 → 金仙（仙将）→ 玄仙（仙君）→ 太乙金仙（仙王）→ 太乙玄仙（准仙帝）→ 大罗金仙（仙帝）→ 混元金仙（准圣）→ 混元大罗金仙（圣人/大帝）

禁止使用的境界：练气期、筑基、金丹、元婴、化神、渡劫、散仙、仙君（非玄仙）等一切不在上述体系内的境界
"""
    
    print("  记忆体构建完成")
    for dim, content in memory.items():
        lines = content.strip().split('\n') if content.strip() else []
        print(f"    {dim}: {len(lines)}行")
    
    return memory


def save_memory_to_redis(memory: dict):
    """保存记忆体到Redis"""
    print("\n" + "=" * 60)
    print("步骤2：保存记忆体到Redis")
    print("=" * 60)
    
    r = redis.Redis(host='wenhui-redis', port=6379, db=0)
    if not r.ping():
        print("  Redis连接失败！")
        return False
    
    key = f"memory:{NOVEL_ID}"
    # 清空旧记忆
    r.delete(key)
    
    # 写入各维度
    for dim, content in memory.items():
        r.hset(key, dim, content)
    
    # 验证
    saved = r.hgetall(key)
    total_chars = sum(len(v.decode('utf-8')) for v in saved.values())
    print(f"  保存成功！共 {len(saved)} 个维度，{total_chars} 字符")
    for dim, content in saved.items():
        print(f"    {dim.decode('utf-8')}: {len(content.decode('utf-8'))} 字符")
    
    return True


def create_test_chapter():
    """创建测试章节（第85章）"""
    print("\n" + "=" * 60)
    print("步骤3：创建测试章节")
    print("=" * 60)
    
    import pymysql
    
    conn = pymysql.connect(
        host='wenhui-mysql',
        user='root',
        password='root123',
        database='easy-novel',
        charset='utf8mb4'
    )
    
    try:
        cursor = conn.cursor()
        
        # 检查是否已有第85章
        cursor.execute("SELECT id FROM chapters WHERE novel_unique_id = %s AND chapter_number = 85", (NOVEL_ID,))
        if cursor.fetchone():
            print("  第85章已存在，跳过创建")
            cursor.execute("SELECT chapter_unique_id FROM chapters WHERE novel_unique_id = %s AND chapter_number = 85", (NOVEL_ID,))
            return cursor.fetchone()[0]
        
        # 创建第85章
        chapter_unique_id = f"test_ch85_{int(__import__('time').time())}"
        summary = """顾平安在归元宗内继续修炼，尝试突破天仙境界。夏语在藏经阁整理古籍时发现了一本关于血煞图谋的残卷。薛峰从外门传来消息，说有可疑人物在宗门附近出没。顾平安决定去调查，夏语坚持同行。两人在途中再次谈起当年落云山脉的事，顾平安第一次正面回应了夏语的感情。"""
        
        cursor.execute("""
            INSERT INTO chapters (novel_unique_id, user_id, chapter_unique_id, chapter_name, chapter_number, chapter_summary, is_published, gen_status)
            VALUES (%s, 1, %s, '第八十五章 古卷疑踪', 85, %s, 0, 0)
        """, (NOVEL_ID, chapter_unique_id, summary))
        conn.commit()
        
        print(f"  创建成功！chapter_unique_id = {chapter_unique_id}")
        print(f"  章节概要: {summary[:80]}...")
        return chapter_unique_id
        
    finally:
        conn.close()


def generate_chapter(chapter_unique_id: str):
    """调用AI生成章节"""
    print("\n" + "=" * 60)
    print("步骤4：调用AI生成章节")
    print("=" * 60)
    
    import asyncio
    from sqlalchemy import text
    from app.service.chapter_gen_graph import run_chapter_gen
    from app.models.base import SessionLocal
    from app.utils.redis_cache import RedisCache
    import app.utils.redis_cache as mod_redis
    
    # 初始化Redis客户端（应用启动时会自动初始化，这里手动初始化）
    if not mod_redis.redis_client:
        mod_redis.redis_client = RedisCache(
            host="wenhui-redis",
            port=6379,
            password="",
            db=0
        )
        print("  Redis客户端已初始化")
    
    db = SessionLocal()
    try:
        # 获取章节信息
        cursor = db.execute(
            text("SELECT chapter_name, chapter_summary, user_id FROM chapters WHERE chapter_unique_id = :cid"),
            {"cid": chapter_unique_id}
        )
        row = cursor.fetchone()
        if not row:
            print(f"  错误：找不到章节 {chapter_unique_id}")
            return None
        
        chapter_name = row[0]
        chapter_summary = row[1] or ""
        user_id = row[2] or 1
        
        print(f"  章节名称: {chapter_name}")
        print(f"  章节概要: {chapter_summary[:100]}...")
        
        # 构建状态
        state = {
            "mode": "new",
            "novel_unique_id": NOVEL_ID,
            "user_id": user_id,
            "chapter_name": chapter_name,
            "chapter_summary": chapter_summary,
            "chapter_unique_id": chapter_unique_id,
            "word_count": 2500,
            "db": db,
        }
        
        # 调用生成
        try:
            result = asyncio.run(run_chapter_gen(state))
        except Exception as e:
            print(f"  生成异常: {e}")
            import traceback
            traceback.print_exc()
            return None
        
        # 兼容两种结果格式
        if result.get("success") or result.get("状态码") == 200:
            data = result.get("data") or result.get("数据") or {}
            content = data.get("content", "")
            word_count = data.get("word_count", len(content))
            print(f"\n  生成成功！")
            print(f"  字数: {word_count}")
            print(f"  前300字: {content[:300]}...")
            
            # 输出完整内容到文件
            output_path = os.path.join(DATA_PATH, NOVEL_ID, "test_ch85_output.txt")
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"\n  完整内容已保存到: {output_path}")
            
            return content
        else:
            print(f"  生成失败: {result.get('message') or result.get('消息', '未知错误')}")
            print(f"  完整结果: {result}")
            return None
            
    finally:
        db.close()


def verify_requirements(content: str, chapter_summary: str):
    """验证所有需求"""
    print("\n" + "=" * 60)
    print("步骤5：验证所有需求")
    print("=" * 60)
    
    results = []
    
    # 1. 境界体系验证
    forbidden_levels = ['练气期', '筑基', '金丹', '元婴', '化神', '渡劫', '散仙']
    found_forbidden = [l for l in forbidden_levels if l in content]
    if found_forbidden:
        results.append(f"❌ 境界体系违规: 发现禁用境界 {found_forbidden}")
    else:
        # 检查是否使用了正确境界
        correct_levels = ['地仙', '真仙', '天仙', '金仙', '玄仙', '太乙金仙', '太乙玄仙', '大罗金仙']
        found_correct = [l for l in correct_levels if l in content]
        results.append(f"✅ 境界体系: 使用了正确境界 {found_correct if found_correct else '未明确提及'}")
    
    # 2. 称谓验证
    wrong_titles = []
    # 薛峰是顾平安的师兄，不应该叫顾平安"师兄"
    if '薛峰' in content and '顾师兄' in content:
        # 检查是否是薛峰叫顾平安师兄
        if re.search(r'薛峰.*顾师兄', content) or re.search(r'"顾师兄".*薛峰', content):
            wrong_titles.append("薛峰称顾平安为'师兄'（辈分错乱）")
    
    if wrong_titles:
        results.append(f"❌ 称谓违规: {wrong_titles}")
    else:
        results.append("✅ 称谓: 未发现辈分错乱")
    
    # 3. 旧事禁区验证
    old_event_expansions = re.findall(r'(在落云山脉[^。]*。[^。]*。|背着[^。]*从[^。]*出来)', content)
    if old_event_expansions:
        results.append(f"⚠️ 旧事禁区: 发现可能的旧事扩写 {old_event_expansions[:2]}")
    else:
        results.append("✅ 旧事禁区: 未发现旧事扩写")
    
    # 4. 概要事件覆盖验证
    summary_events = re.findall(r'[\u4e00-\u9fa5]{2,10}(?:了|着|过|中)', chapter_summary)
    covered_events = []
    uncovered_events = []
    for event in summary_events:
        if event in content:
            covered_events.append(event)
        else:
            uncovered_events.append(event)
    
    if uncovered_events:
        results.append(f"⚠️ 概要覆盖: 部分事件未在正文中体现 {uncovered_events[:3]}")
    else:
        results.append(f"✅ 概要覆盖: 概要事件基本覆盖")
    
    # 5. 字数验证
    word_count = len(content)
    if word_count < 2000:
        results.append(f"⚠️ 字数偏少: {word_count}字 (目标2000-2500)")
    elif word_count > 3000:
        results.append(f"⚠️ 字数偏多: {word_count}字 (目标2000-2500)")
    else:
        results.append(f"✅ 字数: {word_count}字 (符合目标)")
    
    # 6. 脏话验证
    curse_count = content.count('操')
    results.append(f"ℹ️ 脏话统计: '操'出现 {curse_count} 次")
    
    # 输出结果
    print("\n  验证结果:")
    for r in results:
        print(f"    {r}")
    
    return results


if __name__ == "__main__":
    print("小说章节生成测试")
    print("=" * 60)
    
    # 1. 构建记忆体
    memory = build_memory_from_files()
    
    # 2. 保存到Redis
    if not save_memory_to_redis(memory):
        print("记忆体保存失败，退出")
        sys.exit(1)
    
    # 3. 创建测试章节
    chapter_uid = create_test_chapter()
    
    # 4. 生成章节
    content = generate_chapter(chapter_uid)
    
    if content:
        # 5. 验证需求
        summary = """顾平安在归元宗内继续修炼，尝试突破天仙境界。夏语在藏经阁整理古籍时发现了一本关于血煞图谋的残卷。薛峰从外门传来消息，说有可疑人物在宗门附近出没。顾平安决定去调查，夏语坚持同行。两人在途中再次谈起当年落云山脉的事，顾平安第一次正面回应了夏语的感情。"""
        verify_requirements(content, summary)
        
        # 保存生成结果
        output_path = os.path.join(DATA_PATH, NOVEL_ID, "test_ch85_output.txt")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"\n  生成结果已保存到: {output_path}")
    else:
        print("\n  章节生成失败")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)

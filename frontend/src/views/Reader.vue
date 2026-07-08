<template>
  <div class="reader-page">
    <!-- 左侧章节列表 -->
    <div class="sidebar">
      <div class="sidebar-header">
        <h2>{{ novel.title }}</h2>
        <p class="author">作者：{{ novel.author_name }}</p>
        <p class="stats">
          <span class="stat-badge">已更新 <strong>{{ publishedChapters.length }}</strong> 章</span>
        </p>
      </div>
      <div class="chapter-list">
        <h3>📑 章节列表</h3>
        <div v-if="publishedChapters.length === 0" class="empty">暂无已发布章节</div>
        <div v-for="(ch, idx) in publishedChapters" :key="ch.chapter_unique_id"
             :class="['chapter-item', { active: currentChapterId === ch.chapter_unique_id }]"
             @click="openChapter(ch)">
          <span class="ch-name">第{{ idx + 1 }}章 - {{ ch.chapter_name }}</span>
          <span class="ch-words">{{ ch.word_count }}字</span>
        </div>
      </div>
    </div>

    <!-- 右侧内容区 -->
    <div class="content-area">
      <div v-if="!currentChapter" class="welcome">
        <div class="welcome-icon">📖</div>
        <h2>{{ novel.title }}</h2>
        <p class="welcome-desc">{{ novel.description }}</p>
        <p v-if="publishedChapters.length > 0" class="hint">请从左侧选择章节开始阅读</p>
        <p v-else class="hint">作者还没发布章节，敬请期待 ✨</p>
      </div>
      <div v-else class="chapter-content">
        <h2 class="chapter-title">{{ currentChapter.chapter_name }}</h2>
        <div class="chapter-body" v-html="formattedContent"></div>
        <div class="chapter-nav">
          <button v-if="prevChapter" @click="openChapter(prevChapter)">‹ 上一章：{{ prevChapter.chapter_name }}</button>
          <span v-else></span>
          <button v-if="nextChapter" @click="openChapter(nextChapter)">下一章：{{ nextChapter.chapter_name }} ›</button>
          <span v-else></span>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import api from '../api'

export default {
  name: 'Reader',
  setup() {
    const route = useRoute()
    const novel = ref({})
    const allChapters = ref([])
    const currentChapter = ref(null)
    const currentChapterId = ref(null)

    const publishedChapters = computed(() => 
      allChapters.value.filter(c => c.is_published === 1)
    )

    const currentIndex = computed(() => 
      publishedChapters.value.findIndex(c => c.chapter_unique_id === currentChapterId.value)
    )
    const prevChapter = computed(() => 
      currentIndex.value > 0 ? publishedChapters.value[currentIndex.value - 1] : null
    )
    const nextChapter = computed(() => 
      currentIndex.value < publishedChapters.value.length - 1 ? publishedChapters.value[currentIndex.value + 1] : null
    )

    const formattedContent = computed(() => {
      if (!currentChapter.value || !currentChapter.value.content) return ''
      return currentChapter.value.content
        .split('\n')
        .filter(line => line.trim())
        .map(line => `<p>${line}</p>`)
        .join('')
    })

    const loadNovel = async () => {
      try {
        const res = await api.get(`/novels/detail/${route.params.novel_unique_id}`)
        if (res.状态码 === 200) novel.value = res.数据
      } catch (e) { }
    }

    const loadChapters = async () => {
      try {
        const res = await api.get(`/chapters/novel/${route.params.novel_unique_id}`)
        if (res.状态码 === 200) {
          allChapters.value = res.数据 || []
          const chapterId = route.params.chapter_unique_id
          if (chapterId) {
            const target = allChapters.value.find(c => c.chapter_unique_id === chapterId)
            if (target) openChapter(target)
          }
        }
      } catch (e) { }
    }

    const openChapter = (ch) => {
      currentChapter.value = ch
      currentChapterId.value = ch.chapter_unique_id
    }

    onMounted(async () => { await loadNovel(); await loadChapters() })
    return { novel, allChapters, publishedChapters, currentChapter, currentChapterId, prevChapter, nextChapter, openChapter, formattedContent }
  }
}
</script>

<style scoped>
.reader-page { display: flex; gap: 24px; min-height: calc(100vh - 128px); }

/* 侧边栏 */
.sidebar { 
  width: 320px; flex-shrink: 0;
  background: rgba(15, 15, 40, 0.7); 
  border: 1px solid rgba(102, 126, 234, 0.12);
  border-radius: 14px; overflow: hidden;
  backdrop-filter: blur(10px);
  display: flex; flex-direction: column;
}
.sidebar-header { 
  padding: 24px; border-bottom: 1px solid rgba(102, 126, 234, 0.12);
  background: linear-gradient(135deg, rgba(6,182,212,0.05), rgba(139,92,246,0.05));
}
.sidebar-header h2 { font-size: 18px; color: #e0e0e0; margin-bottom: 6px; font-weight: 700; }
.sidebar-header .author { font-size: 12px; color: #6b7280; margin-bottom: 10px; }
.stats { }
.stat-badge { 
  font-size: 12px; color: #06b6d4; 
  background: rgba(6, 182, 212, 0.1); border: 1px solid rgba(6, 182, 212, 0.2);
  padding: 4px 12px; border-radius: 10px;
}
.stat-badge strong { font-size: 15px; }

.chapter-list { flex: 1; overflow-y: auto; padding: 16px; }
.chapter-list h3 { font-size: 13px; color: #6b7280; margin-bottom: 12px; font-weight: 600; }
.chapter-item { 
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 14px; border-radius: 8px; cursor: pointer; margin-bottom: 4px;
  transition: all 0.2s; border: 1px solid transparent;
}
.chapter-item:hover { background: rgba(6, 182, 212, 0.06); border-color: rgba(6, 182, 212, 0.15); }
.chapter-item.active { 
  background: linear-gradient(135deg, rgba(6,182,212,0.12), rgba(139,92,246,0.12));
  border-color: rgba(6, 182, 212, 0.3);
  box-shadow: 0 0 15px rgba(6, 182, 212, 0.08);
}
.ch-name { font-size: 13px; font-weight: 500; color: #c0c8e0; }
.chapter-item.active .ch-name { color: #06b6d4; }
.ch-words { font-size: 11px; color: #5a6080; }
.empty { text-align: center; padding: 20px 0; color: #5a6080; font-size: 13px; }

/* 内容区 */
.content-area { 
  flex: 1; 
  background: rgba(15, 15, 40, 0.7); 
  border: 1px solid rgba(102, 126, 234, 0.12);
  border-radius: 14px; padding: 48px;
  backdrop-filter: blur(10px);
  overflow-y: auto; min-width: 0;
}

.welcome { text-align: center; padding: 100px 0; }
.welcome-icon { font-size: 64px; margin-bottom: 16px; opacity: 0.6; }
.welcome h2 { font-size: 24px; margin-bottom: 12px; color: #e0e0e0; }
.welcome-desc { color: #8892b0; font-size: 14px; line-height: 1.6; max-width: 500px; margin: 0 auto 16px; }
.welcome .hint { color: #5a6080; font-size: 13px; margin-top: 8px; }

.chapter-content { max-width: 760px; margin: 0 auto; }
.chapter-title { 
  font-size: 22px; font-weight: 700; color: #e0e0e0; 
  text-align: center; margin-bottom: 32px; padding-bottom: 20px;
  border-bottom: 1px solid rgba(102, 126, 234, 0.15);
}
.chapter-body p { 
  font-size: 16px; line-height: 2; color: #b0b8d0; text-indent: 2em; margin-bottom: 14px;
}

.chapter-nav { 
  display: flex; justify-content: space-between; margin-top: 40px; padding-top: 24px;
  border-top: 1px solid rgba(102, 126, 234, 0.15);
}
.chapter-nav button { 
  padding: 10px 20px; border-radius: 10px; cursor: pointer; font-size: 13px; font-weight: 500;
  border: 1px solid rgba(102, 126, 234, 0.2);
  background: rgba(15, 15, 40, 0.7); color: #8892b0;
  transition: all 0.3s;
}
.chapter-nav button:hover { color: #06b6d4; border-color: rgba(6, 182, 212, 0.4); }
</style>

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
        <button class="btn-bookshelf" @click="toggleBookshelf">
          {{ inBookshelf ? '📚 已加入书架' : '📚 加入书架' }}
        </button>
        <p v-if="publishedChapters.length > 0" class="hint">请从左侧选择章节开始阅读</p>
        <p v-else class="hint">作者还没发布章节，敬请期待 ✨</p>
      </div>
      <div v-else class="chapter-content">
        <div class="chapter-title-row">
          <h2 class="chapter-title">{{ currentChapter.chapter_name }}</h2>
          <button class="btn-bookshelf small" @click="toggleBookshelf">
            {{ inBookshelf ? '📚 已加入' : '📚 加入书架' }}
          </button>
        </div>

        <!-- 非 VIP：模糊预览 + 遮罩 -->
        <div class="vip-lock" v-if="!isVip">
          <div class="lock-overlay">
            <div class="lock-icon">🔒</div>
            <h3>VIP 专享章节</h3>
            <p>开通 VIP 即可畅读全部内容，解锁 AI 创作功能</p>
            <router-link to="/vip" class="btn-go-vip">💎 开通 VIP</router-link>
          </div>
          <div class="chapter-body preview-blur" v-html="previewContent"></div>
        </div>

        <!-- VIP：正常阅读（禁止复制） -->
        <div v-else class="chapter-body chapter-protected" v-html="formattedContent"
             @contextmenu.prevent="showCopyTip"
             @copy.prevent="showCopyTip"
             @selectstart.prevent></div>

    <!-- 复制提示弹窗 -->
    <div class="copy-toast" :class="{ show: copyToastShow }">
      🔒 该内容为 VIP 专属保护，请<a href="/vip" class="toast-vip-link">开通 VIP</a>后享受完整阅读体验
    </div>

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
    const inBookshelf = ref(false)
    const isVip = ref(false)
    const copyToastShow = ref(false)
    let copyToastTimer = null

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

    // 预览前 200 字
    const previewContent = computed(() => {
      if (!currentChapter.value || !currentChapter.value.content) return ''
      const text = currentChapter.value.content.replace(/\n/g, ' ').slice(0, 200)
      return `<p>${text}...</p>`
    })

    const showCopyTip = () => {
      copyToastShow.value = true
      clearTimeout(copyToastTimer)
      copyToastTimer = setTimeout(() => { copyToastShow.value = false }, 2500)
    }

    const checkVip = async () => {
      // 先从 localStorage 快速判断
      const stored = localStorage.getItem('novel_user')
      if (stored) {
        try {
          const u = JSON.parse(stored)
          if (u.is_super_admin === 1) { isVip.value = true; return }
          if (u.vip_expire_at && new Date(u.vip_expire_at) > new Date()) { isVip.value = true; return }
        } catch (e) { }
      }
      // 再从 API 实时查询
      try {
        const res = await api.get('/auth/me')
        if (res.状态码 === 200) {
          const u = res.数据
          if (u.is_super_admin === 1) isVip.value = true
          else if (u.vip_expire_at && new Date(u.vip_expire_at) > new Date()) isVip.value = true
          else isVip.value = false
        }
      } catch (e) { isVip.value = false }
    }

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
          const chapterId = route.params.chapter_unique_id || route.query.chapter
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
      api.post('/bookshelf/progress', null, {
        params: {
          novel_unique_id: route.params.novel_unique_id,
          chapter_unique_id: ch.chapter_unique_id,
          chapter_name: ch.chapter_name || ''
        }
      }).catch(() => {})
    }

    const checkBookshelf = async () => {
      try {
        const res = await api.get('/bookshelf/check', { params: { novel_unique_id: route.params.novel_unique_id } })
        if (res.状态码 === 200) inBookshelf.value = res.数据?.in_bookshelf || false
      } catch (e) { }
    }

    const toggleBookshelf = async () => {
      try {
        if (inBookshelf.value) {
          await api.post('/bookshelf/remove', null, { params: { novel_unique_id: route.params.novel_unique_id } })
          inBookshelf.value = false
        } else {
          await api.post('/bookshelf/add', null, { params: { novel_unique_id: route.params.novel_unique_id } })
          inBookshelf.value = true
        }
      } catch (e) { }
    }

    onMounted(async () => { await checkVip(); await loadNovel(); await loadChapters(); await checkBookshelf() })
    return { novel, allChapters, publishedChapters, currentChapter, currentChapterId, prevChapter, nextChapter, openChapter, formattedContent, previewContent, inBookshelf, toggleBookshelf, isVip, copyToastShow, showCopyTip }
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

.btn-bookshelf {
  padding: 10px 22px; border-radius: 10px; cursor: pointer; font-size: 14px; font-weight: 600;
  border: 1px solid rgba(6, 182, 212, 0.3);
  background: var(--brand-gradient); color: #fff;
  transition: all 0.3s; margin-top: 16px;
}
.btn-bookshelf:hover { box-shadow: 0 0 16px var(--accent-glow); }
.btn-bookshelf.small { margin-top: 0; padding: 6px 14px; font-size: 12px; white-space: nowrap; }

.chapter-title-row { 
  display: flex; align-items: center; justify-content: center; gap: 16px;
  margin-bottom: 32px; padding-bottom: 20px;
  border-bottom: 1px solid rgba(102, 126, 234, 0.15);
}

.chapter-content { max-width: 760px; margin: 0 auto; }
.chapter-title { 
  font-size: 22px; font-weight: 700; color: #e0e0e0; text-align: center;
  border-bottom: none; margin-bottom: 0; padding-bottom: 0;
}
.chapter-body p { 
  font-size: 16px; line-height: 2; color: #b0b8d0; text-indent: 2em; margin-bottom: 14px;
}

/* VIP 锁定区 */
.vip-lock { position: relative; }
.lock-overlay {
  position: absolute; inset: -20px -30px; z-index: 10;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px;
  background: rgba(8,8,30,0.75); backdrop-filter: blur(6px);
  border-radius: 12px; border: 1px solid rgba(255,255,255,0.06);
}
.lock-icon { font-size: 48px; }
.lock-overlay h3 { font-size: 20px; color: #e0e0e0; margin: 0; }
.lock-overlay p { font-size: 13px; color: #8892b0; margin: 0; text-indent: 0; }

.btn-go-vip {
  display: inline-block; padding: 12px 28px; border-radius: 10px; font-size: 15px; font-weight: 700;
  background: linear-gradient(135deg, #f59e0b, #d97706); color: #fff; text-decoration: none;
  box-shadow: 0 4px 20px rgba(245,158,11,0.3); transition: all 0.3s;
}
.btn-go-vip:hover { box-shadow: 0 4px 35px rgba(245,158,11,0.5); transform: translateY(-1px); }

/* 模糊预览 */
.preview-blur { filter: blur(6px); opacity: 0.4; position: relative; }
.preview-blur p { color: #6b7280; }

/* 禁止复制的正文 */
.chapter-protected {
  -webkit-user-select: none; user-select: none;
  -webkit-touch-callout: none;
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

/* 复制提示弹窗 */
.copy-toast {
  position: fixed; bottom: 30px; left: 50%; transform: translateX(-50%) translateY(20px);
  background: rgba(15,15,40,0.95); border: 1px solid rgba(245,158,11,0.4);
  padding: 12px 24px; border-radius: 12px; font-size: 13px; color: #fbbf24;
  z-index: 1000; opacity: 0; pointer-events: none; transition: all 0.35s ease;
  box-shadow: 0 8px 30px rgba(0,0,0,0.5), 0 0 20px rgba(245,158,11,0.1);
  backdrop-filter: blur(12px); white-space: nowrap;
}
.copy-toast.show { opacity: 1; transform: translateX(-50%) translateY(0); pointer-events: auto; }
.toast-vip-link { color: #f59e0b; font-weight: 700; text-decoration: underline; margin: 0 2px; }
</style>

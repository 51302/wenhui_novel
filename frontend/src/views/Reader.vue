<template>
  <div class="reader-page">

    <!-- 阅读内容区 -->
    <main class="content-area"
          :class="contentAreaClass"
          @contextmenu="onContextMenu"
          @copy="onCopy"
          @selectstart="onSelectStart"
          @mousedown="onBeforeSelect"
          @mouseup="onBeforeSelect">

      <!-- 主体：章节列表 + 阅读内容 -->
      <div class="reader-body" :class="{ 'sidebar-hidden': !sidebarVisible }">

        <!-- 左侧章节列表 -->
        <aside class="chapter-sidebar">
          <div class="sidebar-toolbar">
            <div class="search-box">
              <span class="search-icon">🔍</span>
              <input v-model="searchKeyword" type="text" placeholder="搜索章节..." />
            </div>
            <button class="sort-btn" @click="toggleSortOrder" :title="sortOrder === 'asc' ? '倒序排列' : '正序排列'">
              {{ sortOrder === 'asc' ? '⬇' : '⬆' }}
            </button>
          </div>

          <div class="chapter-list">
            <div v-if="filteredChapters.length === 0" class="empty">
              {{ searchKeyword ? '没有找到匹配的章节' : '暂无章节' }}
            </div>
            <div v-for="(ch, idx) in filteredChapters" :key="ch.chapter_unique_id"
                 :class="['chapter-item', {
                   active: currentChapterId === ch.chapter_unique_id,
                   read: isChapterRead(ch.chapter_unique_id)
                 }]"
                 @click="openChapter(ch)">
              <span class="ch-index">{{ displayIndex(idx) }}</span>
              <span class="ch-name">{{ ch.chapter_name }}</span>
              <span class="ch-words">{{ formatWords(ch.word_count) }}</span>
              <span v-if="isChapterRead(ch.chapter_unique_id)" class="read-dot" title="已读">✓</span>
            </div>
          </div>

          <div class="sidebar-footer">
            <button class="btn-bookshelf" @click="toggleBookshelf">
              {{ inBookshelf ? '✓ 已在书架' : '+ 加入书架' }}
            </button>
          </div>
        </aside>

        <!-- 右侧阅读内容 -->
        <div class="reader-content"
             @scroll="onContentScroll"
             ref="contentAreaRef">

          <!-- 欢迎页 -->
          <div v-if="!currentChapter" class="welcome">
            <div class="welcome-inner">
              <div class="welcome-cover" v-if="novel.cover_image">
                <img :src="novel.cover_image" :alt="novel.title" />
              </div>
              <h2 class="welcome-title">{{ novel.title }}</h2>
              <p class="welcome-author">作者：{{ novel.author_name || '未知' }}</p>
              <p class="welcome-desc">{{ novel.description }}</p>
              <button v-if="publishedChapters.length > 0" class="btn-start-read" @click="startReading">
                {{ lastReadChapter ? '继续阅读' : '开始阅读' }}
              </button>
              <p v-else class="welcome-empty">作者还没发布章节，敬请期待 ✨</p>
            </div>
          </div>

          <!-- 章节内容 -->
          <div v-else class="chapter-content">
            <header class="chapter-header">
              <h1 class="chapter-title">{{ currentChapter.chapter_name }}</h1>
              <div class="chapter-meta">
                <span>{{ formatWords(currentChapter.word_count) }} 字</span>
              </div>
            </header>

            <article class="chapter-body" v-html="formattedContent"></article>

            <!-- 章节导航 -->
            <nav class="chapter-nav">
              <button v-if="prevChapter" @click="openChapter(prevChapter)" class="nav-btn prev">
                <span class="nav-arrow">‹</span>
                <span class="nav-text">
                  <span class="nav-label">上一章</span>
                  <span class="nav-name">{{ prevChapter.chapter_name }}</span>
                </span>
              </button>
              <button v-else class="nav-btn disabled">
                <span class="nav-arrow">‹</span>
                <span class="nav-text"><span class="nav-label">已是第一章</span></span>
              </button>

              <button @click="scrollToTop" class="nav-btn back-top" title="回到顶部">
                <span>↑</span>
              </button>

              <button v-if="nextChapter" @click="openChapter(nextChapter)" class="nav-btn next">
                <span class="nav-text">
                  <span class="nav-label">下一章</span>
                  <span class="nav-name">{{ nextChapter.chapter_name }}</span>
                </span>
                <span class="nav-arrow">›</span>
              </button>
              <button v-else class="nav-btn disabled">
                <span class="nav-text"><span class="nav-label">已是最后一章</span></span>
                <span class="nav-arrow">›</span>
              </button>
            </nav>
          </div>
        </div>
      </div>
    </main>

    <!-- VIP复制弹窗 -->
    <div class="vip-copy-overlay" v-if="vipModalShow" @click.self="closeVipModal">
      <div class="vip-copy-modal">
        <div class="vip-modal-icon">💎</div>
        <h3 class="vip-modal-title">VIP 专属功能</h3>
        <p class="vip-modal-desc">复制小说内容需要<b>开通 VIP</b> 才能使用</p>
        <div class="vip-modal-actions">
          <button class="vip-modal-btn btn-cancel" @click="closeVipModal">暂不需要</button>
          <button class="vip-modal-btn btn-confirm" @click="goVip">立即开通 VIP</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../api'

const FONT_SIZES = ['xs', 'sm', 'md', 'lg', 'xl']
const FONT_SIZE_LABELS = { xs: '小', sm: '较小', md: '标准', lg: '较大', xl: '大' }
const LINE_HEIGHTS = ['tight', 'normal', 'relaxed']
const LINE_HEIGHT_LABELS = { tight: '紧', normal: '标准', relaxed: '松' }

export default {
  name: 'Reader',
  setup() {
    const route = useRoute()
    const router = useRouter()

    const novel = ref({})
    const allChapters = ref([])
    const currentChapter = ref(null)
    const currentChapterId = ref(null)
    const inBookshelf = ref(false)
    const vipModalShow = ref(false)
    const contentAreaRef = ref(null)

    // 阅读设置
    const fontSize = ref('md')
    const lineHeight = ref('normal')
    const readProgress = ref(0)
    const sidebarVisible = ref(true)

    // 章节列表
    const searchKeyword = ref('')
    const sortOrder = ref('asc') // asc 正序, desc 倒序
    const readChapters = ref(new Set()) // 已读章节ID集合

    // VIP 判断
    const user = JSON.parse(localStorage.getItem('novel_user') || '{}')
    const isVip = computed(() => !!user.is_vip)

    const fontSizeLabel = computed(() => FONT_SIZE_LABELS[fontSize.value])
    const lineHeightLabel = computed(() => LINE_HEIGHT_LABELS[lineHeight.value])

    const contentAreaClass = computed(() => [
      !isVip.value ? 'protected-area' : '',
      'font-size-' + fontSize.value,
      'line-height-' + lineHeight.value
    ])

    // 全局 Ctrl+C 拦截（仅非VIP）
    const onKeyDown = (e) => {
      if (isVip.value) return
      if (e.ctrlKey && (e.key === 'c' || e.key === 'C' || e.key === 'Insert')) {
        e.preventDefault()
        showVipModal()
      }
      // 键盘快捷键
      if (e.key === 'ArrowLeft' && prevChapter.value) {
        openChapter(prevChapter.value)
      } else if (e.key === 'ArrowRight' && nextChapter.value) {
        openChapter(nextChapter.value)
      }
    }

    const publishedChapters = computed(() =>
      allChapters.value.filter(c => c.is_published === 1)
    )

    // 过滤 + 排序后的章节
    const filteredChapters = computed(() => {
      let list = publishedChapters.value
      if (searchKeyword.value.trim()) {
        const kw = searchKeyword.value.toLowerCase()
        list = list.filter(ch =>
          ch.chapter_name?.toLowerCase().includes(kw)
        )
      }
      if (sortOrder.value === 'desc') {
        return [...list].reverse()
      }
      return list
    })

    const currentIndex = computed(() =>
      publishedChapters.value.findIndex(c => c.chapter_unique_id === currentChapterId.value)
    )
    const prevChapter = computed(() =>
      currentIndex.value > 0 ? publishedChapters.value[currentIndex.value - 1] : null
    )
    const nextChapter = computed(() =>
      currentIndex.value < publishedChapters.value.length - 1
        ? publishedChapters.value[currentIndex.value + 1]
        : null
    )

    const lastReadChapter = computed(() => {
      try {
        const key = `last_read_${route.params.novel_unique_id}`
        const saved = localStorage.getItem(key)
        if (saved) {
          return publishedChapters.value.find(c => c.chapter_unique_id === saved)
        }
      } catch {}
      return null
    })

    const formattedContent = computed(() => {
      if (!currentChapter.value || !currentChapter.value.content) return ''
      return currentChapter.value.content
        .split('\n')
        .filter(line => line.trim())
        .map(line => `<p>${line}</p>`)
        .join('')
    })

    // 显示章节序号
    const displayIndex = (filteredIdx) => {
      const ch = filteredChapters.value[filteredIdx]
      const originalIdx = publishedChapters.value.findIndex(c => c.chapter_unique_id === ch.chapter_unique_id)
      return `第${originalIdx + 1}章`
    }

    const formatWords = (words) => {
      if (!words) return ''
      if (words >= 10000) return (words / 10000).toFixed(1) + 'w'
      if (words >= 1000) return (words / 1000).toFixed(1) + 'k'
      return words + '字'
    }

    const isChapterRead = (id) => readChapters.value.has(id)

    const showVipModal = () => { vipModalShow.value = true }
    const closeVipModal = () => { vipModalShow.value = false }
    const goVip = () => { vipModalShow.value = false; router.push('/vip') }

    // 右键菜单
    const onContextMenu = (e) => {
      if (!isVip.value) { e.preventDefault(); showVipModal() }
    }
    const onCopy = (e) => {
      if (!isVip.value) { e.preventDefault(); showVipModal() }
    }
    const onBeforeSelect = () => {
      if (isVip.value) return
      const sel = window.getSelection()
      if (sel) sel.removeAllRanges()
    }
    const onSelectStart = (e) => {
      if (isVip.value) return
      showVipModal(); e.preventDefault()
    }

    const toggleSortOrder = () => {
      sortOrder.value = sortOrder.value === 'asc' ? 'desc' : 'asc'
    }

    const increaseFontSize = () => {
      const idx = FONT_SIZES.indexOf(fontSize.value)
      if (idx < FONT_SIZES.length - 1) fontSize.value = FONT_SIZES[idx + 1]
    }
    const decreaseFontSize = () => {
      const idx = FONT_SIZES.indexOf(fontSize.value)
      if (idx > 0) fontSize.value = FONT_SIZES[idx - 1]
    }
    const cycleLineHeight = () => {
      const idx = LINE_HEIGHTS.indexOf(lineHeight.value)
      lineHeight.value = LINE_HEIGHTS[(idx + 1) % LINE_HEIGHTS.length]
    }

    const toggleSidebar = () => {
      sidebarVisible.value = !sidebarVisible.value
    }

    const scrollToTop = () => {
      if (contentAreaRef.value) {
        contentAreaRef.value.scrollTo({ top: 0, behavior: 'smooth' })
      }
    }

    const onContentScroll = (e) => {
      const el = e.target
      const scrollTop = el.scrollTop
      const scrollHeight = el.scrollHeight - el.clientHeight
      if (scrollHeight > 0) {
        readProgress.value = Math.min(100, Math.round((scrollTop / scrollHeight) * 100))
      }
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

    // 加载已读记录
    const loadReadHistory = () => {
      try {
        const key = `read_history_${route.params.novel_unique_id}`
        const saved = localStorage.getItem(key)
        if (saved) readChapters.value = new Set(JSON.parse(saved))
      } catch {}
    }

    // 保存已读记录
    const saveReadHistory = () => {
      try {
        const key = `read_history_${route.params.novel_unique_id}`
        localStorage.setItem(key, JSON.stringify([...readChapters.value]))
      } catch {}
    }

    const openChapter = (ch) => {
      currentChapter.value = ch
      currentChapterId.value = ch.chapter_unique_id

      // 标记已读
      readChapters.value.add(ch.chapter_unique_id)
      saveReadHistory()

      // 保存最后阅读位置
      try {
        localStorage.setItem(`last_read_${route.params.novel_unique_id}`, ch.chapter_unique_id)
      } catch {}

      // 上报进度
      api.post('/bookshelf/progress', null, {
        params: {
          novel_unique_id: route.params.novel_unique_id,
          chapter_unique_id: ch.chapter_unique_id,
          chapter_name: ch.chapter_name || ''
        }
      }).catch(() => {})

      // 滚动到顶部
      nextTick(() => {
        if (contentAreaRef.value) {
          contentAreaRef.value.scrollTop = 0
        }
        readProgress.value = 0
      })
    }

    const startReading = () => {
      if (lastReadChapter.value) {
        openChapter(lastReadChapter.value)
      } else if (publishedChapters.value.length > 0) {
        openChapter(publishedChapters.value[0])
      }
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

    // 监听侧边栏显隐，同步body类
    watch(sidebarVisible, (val) => {
      document.body.classList.toggle('sidebar-hidden', !val)
    })

    onMounted(async () => {
      loadReadHistory()
      await loadNovel()
      await loadChapters()
      await checkBookshelf()
      document.addEventListener('keydown', onKeyDown)

      // 读取保存的阅读设置
      try {
        const savedFont = localStorage.getItem('reader_font_size')
        if (savedFont && FONT_SIZES.includes(savedFont)) fontSize.value = savedFont
        const savedLine = localStorage.getItem('reader_line_height')
        if (savedLine && LINE_HEIGHTS.includes(savedLine)) lineHeight.value = savedLine
      } catch {}

      // 普通用户进入阅读页弹窗引导VIP
      if (!isVip.value) {
        setTimeout(() => { vipModalShow.value = true }, 1500)
      }
    })

    onUnmounted(() => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.classList.remove('sidebar-hidden')
    })

    // 保存阅读设置
    watch(fontSize, (val) => {
      try { localStorage.setItem('reader_font_size', val) } catch {}
    })
    watch(lineHeight, (val) => {
      try { localStorage.setItem('reader_line_height', val) } catch {}
    })

    return {
      novel, allChapters, publishedChapters, filteredChapters,
      currentChapter, currentChapterId, prevChapter, nextChapter,
      openChapter, formattedContent, inBookshelf, toggleBookshelf,
      vipModalShow, showVipModal, closeVipModal, goVip, isVip,
      onContextMenu, onCopy, onSelectStart, onBeforeSelect,
      searchKeyword, sortOrder, toggleSortOrder,
      displayIndex, formatWords, isChapterRead,
      fontSize, lineHeight, fontSizeLabel, lineHeightLabel,
      contentAreaClass,
      increaseFontSize, decreaseFontSize, cycleLineHeight,
      contentAreaRef, readProgress, onContentScroll, scrollToTop,
      sidebarVisible, toggleSidebar,
      lastReadChapter, startReading,
    }
  }
}
</script>

<style scoped>
.reader-page {
  display: flex;
  min-height: calc(100vh - 64px);
  position: relative;
  max-width: 1200px;
  margin: 0 auto;
  background: var(--bg-card);
  border-left: 1px solid var(--border);
  border-right: 1px solid var(--border);
}

/* 顶部进度条（已移除） */

/* 主体布局 */
.reader-body {
  display: flex;
  flex: 1;
  min-height: 0;
}
.reader-body.sidebar-hidden .chapter-sidebar {
  width: 0;
  padding: 0;
  opacity: 0;
  overflow: hidden;
}

/* 章节侧边栏 */
.chapter-sidebar {
  width: 200px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border);
  transition: all 0.25s ease;
  background: var(--bg-card);
}

/* 工具栏 */
.sidebar-toolbar {
  padding: 8px 10px;
  display: flex;
  gap: 6px;
  border-bottom: 1px solid var(--border);
}
.search-box {
  flex: 1;
  position: relative;
  display: flex;
  align-items: center;
}
.search-icon {
  position: absolute;
  left: 8px;
  font-size: 11px;
  opacity: 0.5;
}
.search-box input {
  width: 100%;
  padding: 5px 8px 5px 24px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 11px;
  background: var(--bg-input);
  color: var(--text-primary);
  outline: none;
  transition: all 0.2s;
}
.search-box input:focus { border-color: var(--accent-text); }
.sort-btn {
  padding: 5px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg-input);
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.2s;
}
.sort-btn:hover { border-color: var(--accent-text); color: var(--accent-text); }

/* 章节列表 */
.chapter-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px 8px;
}
.chapter-list .empty {
  text-align: center;
  padding: 40px 0;
  color: var(--text-muted);
  font-size: 12px;
}
.chapter-item {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 6px 8px;
  border-radius: 5px;
  cursor: pointer;
  margin-bottom: 1px;
  transition: all 0.15s;
  position: relative;
}
.chapter-item:hover { background: var(--bg-input); }
.chapter-item.active {
  background: var(--accent-bg);
  border-left: 2px solid var(--accent-text);
  padding-left: 6px;
}
.chapter-item .ch-index {
  font-size: 10px;
  color: var(--text-muted);
  flex-shrink: 0;
  width: 32px;
}
.chapter-item.active .ch-index { color: var(--accent-text); }
.ch-name {
  flex: 1;
  font-size: 12px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
}
.chapter-item.read .ch-name {
  color: var(--text-muted);
  font-weight: 400;
}
.chapter-item.active .ch-name { color: var(--accent-text); font-weight: 600; }
.ch-words {
  font-size: 10px;
  color: var(--text-muted);
  flex-shrink: 0;
}
.read-dot {
  color: var(--success-text);
  font-size: 10px;
  flex-shrink: 0;
}

/* 侧边栏底部 */
.sidebar-footer {
  padding: 8px 10px;
  border-top: 1px solid var(--border);
}
.sidebar-footer .btn-bookshelf {
  width: 100%;
  padding: 6px 10px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 11px;
  font-weight: 500;
  border: 1px solid var(--accent-text);
  background: transparent;
  color: var(--accent-text);
  transition: all 0.2s;
}
.sidebar-footer .btn-bookshelf:hover {
  background: var(--accent-text);
  color: #fff;
}

/* 阅读内容区 */
.reader-content {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
}

/* 内容区 */
.content-area {
  display: flex;
  flex-direction: column;
  flex: 1;
  background: var(--bg-card);
  overflow: hidden;
  position: relative;
  scroll-behavior: smooth;
}
.protected-area {
  -webkit-user-select: none;
  user-select: none;
  -webkit-touch-callout: none;
}

/* 阅读工具栏 */
/* 阅读设置 */
.reader-settings {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
}
.setting-group {
  display: flex;
  align-items: center;
  gap: 3px;
}
.setting-group.right {
  margin-left: auto;
}
.setting-label {
  font-size: 10px;
  color: var(--text-muted);
  min-width: 20px;
  text-align: center;
}
.progress-mini {
  font-size: 10px;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}
.tool-btn {
  padding: 3px 7px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-input);
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 2px;
  transition: all 0.2s;
  white-space: nowrap;
}
.tool-btn:hover { border-color: var(--accent-text); color: var(--accent-text); }
.tool-btn.sm { padding: 2px 6px; font-size: 10px; }
.tool-btn.wide { min-width: 44px; justify-content: center; }

/* 欢迎页 */
.welcome {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: calc(100vh - 64px - 50px);
  padding: 40px 20px;
}
.welcome-inner { text-align: center; }
.welcome-cover {
  width: 160px;
  height: 220px;
  margin: 0 auto 24px;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 12px 40px rgba(0,0,0,0.3);
}
.welcome-cover img { width: 100%; height: 100%; object-fit: cover; }
.welcome-title {
  font-size: 28px;
  color: var(--text-primary);
  margin: 0 0 8px 0;
  font-weight: 700;
}
.welcome-author {
  font-size: 14px;
  color: var(--text-secondary);
  margin: 0 0 20px 0;
}
.welcome-desc {
  color: var(--text-muted);
  font-size: 14px;
  line-height: 1.8;
  margin: 0 0 24px 0;
}
.btn-start-read {
  padding: 12px 40px;
  border-radius: 30px;
  cursor: pointer;
  font-size: 15px;
  font-weight: 600;
  border: none;
  background: linear-gradient(135deg, var(--accent-text), #8b5cf6);
  color: #fff;
  transition: all 0.3s;
  box-shadow: 0 4px 16px var(--accent-glow);
}
.btn-start-read:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 24px var(--accent-glow);
}
.welcome-empty {
  color: var(--text-muted);
  font-size: 14px;
  margin-top: 16px;
}

/* 章节内容 */
.chapter-content {
  padding: 36px 40px 60px;
}
.chapter-header {
  text-align: center;
  margin-bottom: 36px;
  padding-bottom: 24px;
  border-bottom: 1px solid var(--border);
}
.chapter-title {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 10px 0;
  line-height: 1.4;
}
.chapter-meta {
  font-size: 12px;
  color: var(--text-muted);
}
.chapter-body p {
  font-size: 16px;
  line-height: 2;
  color: var(--text-secondary);
  text-indent: 2em;
  margin: 0 0 16px 0;
}

/* 字号 */
.font-size-xs .chapter-body p { font-size: 14px; }
.font-size-sm .chapter-body p { font-size: 15px; }
.font-size-md .chapter-body p { font-size: 16px; }
.font-size-lg .chapter-body p { font-size: 18px; }
.font-size-xl .chapter-body p { font-size: 20px; }

/* 行距 */
.line-height-tight .chapter-body p { line-height: 1.6; }
.line-height-normal .chapter-body p { line-height: 2; }
.line-height-relaxed .chapter-body p { line-height: 2.4; }

/* 章节导航 */
.chapter-nav {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 48px;
  padding-top: 28px;
  border-top: 1px solid var(--border);
}
.nav-btn {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 18px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg-card);
  color: var(--text-primary);
  cursor: pointer;
  transition: all 0.2s;
  text-align: left;
}
.nav-btn:hover:not(.disabled):not(.back-top) {
  border-color: var(--accent-text);
  background: var(--accent-bg);
}
.nav-btn.disabled { opacity: 0.4; cursor: not-allowed; }
.nav-btn.next { flex-direction: row-reverse; text-align: right; }
.nav-arrow {
  font-size: 24px;
  color: var(--accent-text);
  flex-shrink: 0;
  width: 24px;
  text-align: center;
}
.nav-text { flex: 1; min-width: 0; }
.nav-label {
  display: block;
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 2px;
}
.nav-name {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.nav-btn.back-top {
  flex: none;
  width: 44px;
  height: 44px;
  padding: 0;
  justify-content: center;
  border-radius: 50%;
  font-size: 16px;
}

/* VIP弹窗 */
.vip-copy-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0,0,0,0.65);
  backdrop-filter: blur(4px);
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  animation: fadeIn 0.25s ease;
}
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
.vip-copy-modal {
  background: var(--bg-card);
  border: 1px solid var(--gold, #fbbf24);
  border-radius: 20px;
  padding: 40px 36px 32px;
  text-align: center;
  max-width: 420px;
  width: 90%;
  box-shadow: 0 20px 60px rgba(0,0,0,0.6), 0 0 40px rgba(245,158,11,0.08);
  animation: slideUp 0.3s ease;
}
@keyframes slideUp { from { opacity: 0; transform: translateY(30px); } to { opacity: 1; transform: translateY(0); } }
.vip-modal-icon { font-size: 48px; margin-bottom: 12px; }
.vip-modal-title { font-size: 20px; color: var(--gold, #fbbf24); margin: 0 0 10px; font-weight: 700; }
.vip-modal-desc { font-size: 14px; color: var(--text-secondary); margin: 0 0 28px; line-height: 1.6; }
.vip-modal-desc b { color: var(--gold, #fbbf24); }
.vip-modal-actions { display: flex; gap: 14px; justify-content: center; }
.vip-modal-btn {
  padding: 10px 24px;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  border: none;
}
.btn-cancel { background: var(--bg-input); color: var(--text-secondary); border: 1px solid var(--border); }
.btn-cancel:hover { background: var(--accent-bg); }
.btn-confirm {
  background: linear-gradient(135deg, #f59e0b, #d97706);
  color: #fff;
  box-shadow: 0 4px 16px rgba(245,158,11,0.3);
}
.btn-confirm:hover { box-shadow: 0 6px 24px rgba(245,158,11,0.45); transform: translateY(-1px); }

/* 响应式 */
@media (max-width: 900px) {
  .sidebar {
    position: fixed;
    left: 0; top: 64px; bottom: 0;
    z-index: 50;
    transform: translateX(-100%);
    transition: transform 0.3s ease;
  }
  body.sidebar-mobile-open .sidebar { transform: translateX(0); }
  .progress-bar { top: 64px; }
}

/* 滚动条美化 */
.sidebar::-webkit-scrollbar,
.content-area::-webkit-scrollbar,
.chapter-list::-webkit-scrollbar { width: 6px; }
.sidebar::-webkit-scrollbar-track,
.content-area::-webkit-scrollbar-track,
.chapter-list::-webkit-scrollbar-track { background: transparent; }
.sidebar::-webkit-scrollbar-thumb,
.content-area::-webkit-scrollbar-thumb,
.chapter-list::-webkit-scrollbar-thumb {
  background: var(--border);
  border-radius: 3px;
}
.sidebar::-webkit-scrollbar-thumb:hover,
.content-area::-webkit-scrollbar-thumb:hover,
.chapter-list::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }
</style>

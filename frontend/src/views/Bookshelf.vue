<template>
  <div class="bookshelf-page">
    <div class="page-header">
      <h1>📚 我的书架</h1>
      <p>{{ items.length }} 本书在书架上</p>
    </div>

    <div v-if="loading" class="loading">
      <span class="spinner"></span> 加载中...
    </div>

    <div v-else-if="items.length === 0" class="empty">
      <div class="empty-icon">📖</div>
      <p>书架空空如也</p>
      <span>去作品列表逛逛，找到喜欢的书加入书架吧</span>
    </div>

    <div v-else class="book-grid">
      <div v-for="book in items" :key="book.novel_unique_id" class="book-card">
        <!-- 封面区域（点击继续阅读） -->
        <div class="book-main" @click="continueRead(book)">
          <img v-if="book.cover_image" :src="book.cover_image" class="book-cover" />
          <div v-else class="book-cover placeholder">📖</div>
          <div class="book-info">
            <strong class="book-title">{{ book.title }}</strong>
            <span class="book-author">{{ book.author_name }}</span>
            <span class="book-genre" v-if="book.genre">{{ book.genre }}</span>
            <p class="book-desc" v-if="book.description">{{ book.description }}</p>
            <!-- 阅读进度 -->
            <div class="progress-bar" v-if="book.last_chapter_name">
              <span class="progress-label">📌 上次看到：{{ book.last_chapter_name }}</span>
              <span class="progress-hint">点击继续阅读 →</span>
            </div>
            <div class="progress-bar new" v-else>
              <span class="progress-label">🆕 还没开始读</span>
            </div>
          </div>
        </div>
        <button class="btn-remove" @click.stop="removeBook(book)">移除</button>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import api from '../api'

export default {
  name: 'Bookshelf',
  setup() {
    const router = useRouter()
    const items = ref([])
    const loading = ref(true)

    const fetchBookshelf = async () => {
      try {
        const res = await api.get('/bookshelf/list')
        if (res.状态码 === 200) {
          items.value = res.数据?.items || []
        }
      } catch (e) { } finally { loading.value = false }
    }

    const removeBook = async (book) => {
      try {
        await api.post('/bookshelf/remove', null, { params: { novel_unique_id: book.novel_unique_id } })
        items.value = items.value.filter(i => i.novel_unique_id !== book.novel_unique_id)
      } catch (e) { }
    }

    // 有进度 → 跳转到上次章节；没进度 → 跳转到作品首页
    const continueRead = (book) => {
      if (book.last_chapter_unique_id) {
        router.push(`/reader/${book.novel_unique_id}?chapter=${book.last_chapter_unique_id}`)
      } else {
        router.push(`/reader/${book.novel_unique_id}`)
      }
    }

    onMounted(() => fetchBookshelf())

    return { items, loading, removeBook, continueRead }
  }
}
</script>

<style scoped>
.bookshelf-page { max-width: 1000px; margin: 0 auto; padding: 20px; }
.page-header { text-align: center; margin-bottom: 30px; }
.page-header h1 { font-size: 24px; color: var(--text-primary); }
.page-header p { color: var(--text-secondary); font-size: 13px; margin-top: 4px; }

.loading { display: flex; align-items: center; justify-content: center; gap: 10px; padding: 60px 0; color: var(--text-secondary); }
.spinner { width: 20px; height: 20px; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; display: inline-block; }
@keyframes spin { to { transform: rotate(360deg) } }

.empty { text-align: center; padding: 80px 0; color: var(--text-muted); }
.empty-icon { font-size: 64px; margin-bottom: 16px; opacity: 0.5; }
.empty p { font-size: 18px; color: var(--text-secondary); margin-bottom: 8px; }

.book-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }

.book-card {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 14px; padding: 16px; display: flex; gap: 14px;
  transition: all 0.3s; position: relative;
  backdrop-filter: blur(20px); box-shadow: var(--card-shadow);
}
.book-card:hover { border-color: var(--border-hover); transform: translateY(-2px); box-shadow: 0 8px 24px rgba(0,0,0,0.3); }

.book-main { display: flex; gap: 14px; cursor: pointer; flex: 1; min-width: 0; }

.book-cover { width: 72px; height: 96px; border-radius: 8px; object-fit: cover; flex-shrink: 0; }
.book-cover.placeholder { display: flex; align-items: center; justify-content: center; background: var(--btn-bg); font-size: 32px; }

.book-info { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.book-title { color: var(--text-primary); font-size: 16px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.book-author { color: var(--accent); font-size: 12px; }
.book-genre { color: var(--text-muted); font-size: 11px; background: var(--btn-bg); padding: 2px 8px; border-radius: 4px; display: inline-block; width: fit-content; }
.book-desc { color: var(--text-secondary); font-size: 12px; line-height: 1.5; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; margin-top: 4px; }

.progress-bar { margin-top: 8px; padding: 6px 10px; border-radius: 6px; background: var(--accent-bg); border: 1px solid var(--accent-bg); display: flex; justify-content: space-between; align-items: center; }
.progress-bar.new { background: rgba(148,163,184,0.06); border-color: rgba(148,163,184,0.1); }
.progress-label { font-size: 11px; color: var(--accent); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.progress-bar.new .progress-label { color: var(--text-muted); }
.progress-hint { font-size: 10px; color: var(--text-muted); white-space: nowrap; margin-left: 8px; }

.btn-remove {
  position: absolute; top: 10px; right: 10px; padding: 4px 10px;
  border-radius: 6px; border: none; cursor: pointer;
  background: rgba(239,68,68,0.15); color: var(--error-text); font-size: 12px;
  transition: all 0.3s;
}
.btn-remove:hover { background: rgba(239,68,68,0.3); }
</style>

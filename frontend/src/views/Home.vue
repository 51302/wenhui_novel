<template>
  <div class="home-page">
    <!-- 搜索栏 -->
    <div class="search-bar">
      <div class="search-input-wrap">
        <span class="search-icon">🔍</span>
        <input v-model="keyword" placeholder="搜索小说名称或作者..." @keyup.enter="doSearch" />
      </div>
      <button class="btn-search" @click="doSearch">
        <span>搜 索</span>
      </button>
    </div>

    <!-- 筛选项 -->
    <div class="filters">
      <span :class="{ active: !currentReader }" @click="filterReader('')">全 部</span>
      <span :class="{ active: currentReader === '男频' }" @click="filterReader('男频')">男 频</span>
      <span :class="{ active: currentReader === '女频' }" @click="filterReader('女频')">女 频</span>
      <span class="sep">|</span>
      <template v-if="currentReader">
        <span v-for="g in genres" :key="g" :class="{ active: currentGenre === g }" @click="filterGenre(g)">{{ g }}</span>
      </template>
    </div>

    <!-- 作品列表 -->
    <div v-if="loading" class="loading">
      <span class="loading-spinner"></span>
      <span>正在加载...</span>
    </div>
    <div v-else class="novel-grid">
      <div v-for="novel in novels" :key="novel.novel_unique_id" class="novel-card" @click="openDetail(novel.novel_unique_id)">
        <div class="card-img">
          <div class="card-glow"></div>
          <img v-if="novel.cover_image" :src="novel.cover_image" @error="novel.cover_image = ''" />
          <span v-if="!novel.cover_image" class="placeholder-img">📚</span>
          <div class="card-overlay">
            <span class="overlay-btn">开始阅读 →</span>
          </div>
        </div>
        <div class="card-info">
          <h3>{{ novel.title }}</h3>
          <p class="author">{{ novel.author_name }}</p>
          <p class="desc">{{ novel.description }}</p>
          <div class="card-tags">
            <span class="tag tag-reader">{{ novel.target_reader }}</span>
            <span v-if="novel.genre" class="tag tag-genre">{{ novel.genre }}</span>
          </div>
        </div>
      </div>
    </div>

    <div v-if="novels.length === 0 && !loading" class="empty">✨ 暂无作品，快去创作吧</div>

    <!-- 分页 -->
    <div v-if="total > pageSize" class="pagination">
      <button :disabled="page <= 1" @click="page--; fetchNovels()">‹ 上一页</button>
      <span class="page-num">{{ page }} / {{ Math.ceil(total / pageSize) }}</span>
      <button :disabled="page >= Math.ceil(total / pageSize)" @click="page++; fetchNovels()">下一页 ›</button>
    </div>
  </div>
</template>

<script>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import api from '../api'

export default {
  name: 'Home',
  setup() {
    const router = useRouter()
    const keyword = ref('')
    const currentReader = ref('')
    const currentGenre = ref('')
    const novels = ref([])
    const page = ref(1)
    const total = ref(0)
    const pageSize = ref(12)
    const loading = ref(false)

    const genresByReader = {
      '男频': ['玄幻', '修仙', '都市', '科幻', '历史', '武侠', '悬疑', '游戏', '军事', '竞技', '轻小说', '奇幻', '灵异', '无限流', '末世'],
      '女频': ['古言', '现言', '穿越', '重生', '总裁', '纯爱', '种田', '宫斗', '宅斗', '女强', '悬疑', '幻想', '清穿', '穿书', '轻小说']
    }
    const genres = ref([])

    const fetchNovels = async () => {
      loading.value = true
      try {
        const url = keyword.value ? '/novels/search' : '/novels/list'
        const params = { page: page.value, page_size: pageSize.value }
        if (keyword.value) {
          params.keyword = keyword.value
        } else {
          if (currentReader.value) params.target_reader = currentReader.value
          if (currentGenre.value) params.genre = currentGenre.value
        }
        const res = await api.get(url, { params })
        if (res.状态码 === 200) {
          novels.value = res.数据.items
          total.value = res.数据.total
        }
      } catch (e) { } finally { loading.value = false }
    }

    const filterReader = (r) => { currentReader.value = r; currentGenre.value = ''; genres.value = genresByReader[r] || []; page.value = 1; fetchNovels() }
    const filterGenre = (g) => { currentGenre.value = currentGenre.value === g ? '' : g; page.value = 1; fetchNovels() }
    const doSearch = () => { page.value = 1; currentReader.value = ''; currentGenre.value = ''; fetchNovels() }
    const openDetail = (novelId) => { router.push(`/reader/${novelId}`) }

    onMounted(() => fetchNovels())
    return { keyword, currentReader, currentGenre, novels, page, total, pageSize, loading, genres, filterReader, filterGenre, doSearch, openDetail, fetchNovels }
  }
}
</script>

<style scoped>
.home-page { max-width: 100%; }

/* 搜索栏 */
.search-bar { display: flex; gap: 12px; margin-bottom: 24px; }
.search-input-wrap {
  flex: 1; display: flex; align-items: center; gap: 10px;
  padding: 0 18px; border-radius: 12px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  backdrop-filter: blur(10px);
  transition: all 0.3s;
}
.search-input-wrap:focus-within { border-color: var(--border-focus); box-shadow: 0 0 30px var(--accent-glow); }
.search-input-wrap input {
  flex: 1; padding: 14px 0; background: none; border: none; color: var(--text-primary);
  font-size: 15px; outline: none;
}
.search-input-wrap input::placeholder { color: var(--text-muted); }
.search-icon { font-size: 18px; opacity: 0.6; }

.btn-search {
  padding: 0 32px; border-radius: 12px; font-size: 15px; font-weight: 600;
  border: none; cursor: pointer; color: #fff;
  background: var(--brand-gradient);
  box-shadow: 0 4px 20px var(--accent-glow);
  transition: all 0.3s;
}
.btn-search:hover { box-shadow: 0 4px 30px var(--accent-glow-strong); transform: translateY(-1px); }

/* 筛选 */
.filters { 
  display: flex; flex-wrap: wrap; gap: 10px; align-items: center; 
  margin-bottom: 28px; font-size: 13px; 
}
.filters span { 
  padding: 6px 16px; border-radius: 20px; cursor: pointer;
  background: var(--bg-card); border: 1px solid var(--border);
  color: var(--text-secondary); transition: all 0.3s; font-weight: 500;
}
.filters span:hover { border-color: var(--border-hover); color: var(--accent); }
.filters span.active { 
  background: var(--btn-bg);
  border-color: var(--border-focus); color: var(--accent);
  box-shadow: 0 0 15px var(--accent-glow);
}
.filters .sep { background: transparent; border: none; cursor: default; color: var(--text-muted); }

/* 卡片 */
.novel-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; }
@media (max-width: 1100px) { .novel-grid { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 800px) { .novel-grid { grid-template-columns: repeat(2, 1fr); } }

.novel-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 14px; overflow: hidden;
  cursor: pointer; transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  backdrop-filter: blur(10px);
  position: relative;
  box-shadow: var(--card-shadow);
}
.novel-card:hover {
  transform: translateY(-6px);
  border-color: var(--border-hover);
  box-shadow: var(--card-shadow-hover);
}

.card-img { 
  height: 200px; position: relative; overflow: hidden;
  background: var(--bg-deep);
  display: flex; align-items: center; justify-content: center;
}
.card-glow {
  position: absolute; inset: 0;
  background: var(--brand-gradient);
  opacity: 0; transition: opacity 0.4s;
}
.novel-card:hover .card-glow { opacity: 0.08; }
.card-img img { width: 100%; height: 100%; object-fit: cover; transition: transform 0.4s; }
.novel-card:hover .card-img img { transform: scale(1.05); }
.placeholder-img { font-size: 48px; opacity: 0.4; }

.card-overlay {
  position: absolute; inset: 0;
  background: var(--bg-overlay);
  display: flex; align-items: center; justify-content: center;
  opacity: 0; transition: all 0.3s;
  backdrop-filter: blur(4px);
}
.novel-card:hover .card-overlay { opacity: 1; }
.overlay-btn { 
  padding: 8px 24px; border-radius: 8px;
  background: var(--brand-gradient);
  color: #fff; font-size: 14px; font-weight: 600;
  box-shadow: 0 4px 20px var(--accent-glow-strong);
}

.card-info { padding: 16px; }
.card-info h3 { font-size: 16px; color: var(--text-primary); margin-bottom: 6px; font-weight: 700; }
.author { font-size: 12px; color: var(--text-muted); margin-bottom: 8px; }
.desc { 
  font-size: 13px; color: var(--text-secondary); line-height: 1.5; 
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-bottom: 10px;
}
.card-tags { display: flex; gap: 6px; }
.tag { 
  font-size: 11px; padding: 3px 10px; border-radius: 10px; font-weight: 600;
}
.tag-reader { background: var(--btn-bg); color: var(--accent); border: 1px solid var(--btn-border); }
.tag-genre { background: var(--accent-glow); color: var(--accent); border: 1px solid var(--border-hover); }

/* loading */
.loading { display: flex; gap: 12px; align-items: center; justify-content: center; padding: 80px 0; color: var(--text-secondary); font-size: 15px; }
.loading-spinner {
  width: 24px; height: 24px; border: 2px solid var(--border);
  border-top-color: var(--accent); border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.empty { text-align: center; padding: 80px 0; color: var(--text-muted); font-size: 15px; }

/* 分页 */
.pagination { display: flex; justify-content: center; align-items: center; gap: 20px; margin-top: 32px; }
.pagination button { 
  padding: 10px 24px; border: 1px solid var(--border); 
  background: var(--bg-card); color: var(--text-secondary); border-radius: 10px;
  cursor: pointer; font-size: 14px; transition: all 0.3s; font-weight: 500;
}
.pagination button:hover:not(:disabled) { color: var(--accent); border-color: var(--border-hover); }
.pagination button:disabled { opacity: 0.3; cursor: not-allowed; }
.page-num { font-size: 14px; color: var(--text-secondary); font-weight: 600; }
</style>

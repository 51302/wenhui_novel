<template>
  <div class="circle-page">
    <div class="circle-header">
      <h1>🌐 作品圈</h1>
      <p>互动动态流 · 查看评论 · 发表看法</p>
    </div>

    <div v-if="loading" class="loading">
      <span class="spinner"></span> 加载中...
    </div>

    <div v-else-if="errorMsg" class="error">{{ errorMsg }}</div>

    <div v-else class="feed-list">
      <div v-for="item in feedItems" :key="item.id" class="feed-card">

        <!-- 顶部：互动者 + 作品 -->
        <div class="feed-top">
          <div class="feed-author">
            <span class="avatar">{{ (item.interactor_name || '?')[0] }}</span>
            <span class="interactor">{{ item.interactor_name }}</span>
            <span class="action-tag" v-if="item.comment_text">💬 评论了</span>
            <span class="action-tag" v-else-if="item.is_like">❤️ 点赞了</span>
            <span class="action-tag" v-else-if="item.is_follow">➕ 关注了</span>
            <span class="action-tag" v-else-if="item.is_bookmark">🔖 收藏了</span>
          </div>
          <span class="time">{{ formatTime(item.created_at) }}</span>
        </div>

        <!-- 被互动的作品 -->
        <div class="feed-work" @click="goReader(item.novel_unique_id)">
          <img v-if="item.novel?.cover_image" :src="item.novel.cover_image" class="work-cover" />
          <div v-else class="work-cover placeholder">📖</div>
          <div class="work-info">
            <strong class="work-title">{{ item.novel?.title || '未命名作品' }}</strong>
            <span class="work-author">作者: {{ item.novel?.author_name || '佚名' }}</span>
          </div>
        </div>

        <!-- 评论内容（仅评论型） -->
        <div class="feed-body" v-if="item.comment_text">
          <p class="comment-preview">"{{ item.comment_text.slice(0, 120) }}{{ item.comment_text.length > 120 ? '...' : '' }}"</p>
        </div>

        <!-- 操作栏：点赞/收藏/关注 + 展开评论 -->
        <div class="feed-actions">
          <div class="action-btns">
            <button class="action-btn" :class="{ active: likedItems[item.novel_unique_id] }" @click="doLike(item)">
              ❤️ {{ item.likes_count || 0 }}
            </button>
            <button class="action-btn" :class="{ active: bookmarkedItems[item.novel_unique_id] }" @click="doBookmark(item)">
              🔖 {{ item.bookmarks_count || 0 }}
            </button>
            <button class="action-btn" :class="{ active: followedItems[item.novel_unique_id] }" @click="doFollow(item)">
              ➕ 关注
            </button>
          </div>

          <!-- 评论展开 ▼ / ▲ -->
          <div class="comment-toggle" @click="toggleComments(item)">
            <span class="toggle-label">💬 评论
              <span v-if="commentCounts[item.novel_unique_id]" class="comment-count">({{ commentCounts[item.novel_unique_id] }})</span>
            </span>
            <span class="chevron" :class="{ open: expandedNovels[item.novel_unique_id] }">▼</span>
          </div>
        </div>

        <!-- 可展开的评论区 -->
        <div class="comments-section" v-if="expandedNovels[item.novel_unique_id]">
          <div class="comments-loading" v-if="commentsLoading[item.novel_unique_id]">
            <span class="spinner-small"></span> 加载评论...
          </div>

          <!-- 已有评论列表 -->
          <div v-else class="comments-list">
            <div v-if="novelComments[item.novel_unique_id]?.length" class="comment-items">
              <div v-for="c in novelComments[item.novel_unique_id]" :key="c.id" class="comment-item">
                <span class="commenter-avatar">{{ (c.interactor_name || '?')[0] }}</span>
                <div class="comment-bubble">
                  <div class="comment-meta">
                    <strong>{{ c.interactor_name }}</strong>
                    <span class="comment-time">{{ formatTime(c.created_at) }}</span>
                  </div>
                  <p class="comment-text">{{ c.comment_text }}</p>
                </div>
              </div>
            </div>
            <div v-else class="no-comments">暂无评论</div>
          </div>

          <!-- 发表评论输入框 -->
          <div class="comment-input-row">
            <input
              :value="commentTexts[item.novel_unique_id] || ''"
              @input="commentTexts[item.novel_unique_id] = $event.target.value"
              placeholder="写下你的评论..."
              class="comment-input"
            />
            <button
              class="btn-submit"
              :disabled="!commentTexts[item.novel_unique_id]?.trim() || submittingIds[item.novel_unique_id]"
              @click="submitComment(item)"
            >
              {{ submittingIds[item.novel_unique_id] ? '发送中' : '发送' }}
            </button>
          </div>
        </div>
      </div>

      <p v-if="feedItems.length === 0" class="empty">还没有互动动态</p>

      <button v-if="hasMore" class="btn-more" :disabled="loadingMore" @click="loadMore">
        {{ loadingMore ? '加载中...' : '加载更多' }}
      </button>
    </div>

    <!-- VIP提示弹窗 -->
    <div class="vip-toast" :class="{ show: vipToastShow }">
      💎 互动功能需要 <a href="/vip" class="toast-vip-link">开通 VIP</a> 才能使用
    </div>
  </div>
</template>

<script>
import { ref, onMounted, reactive, computed } from 'vue'
import { useRouter } from 'vue-router'
import api from '../api'

export default {
  name: 'WorkCircle',
  setup() {
    const router = useRouter()
    const feedItems = ref([])
    const loading = ref(true)
    const errorMsg = ref('')
    const page = ref(1)
    const hasMore = ref(false)
    const loadingMore = ref(false)

    // VIP 判断
    const user = JSON.parse(localStorage.getItem('novel_user') || '{}')
    const isVip = computed(() => !!user.is_vip)
    const vipToastShow = ref(false)
    let vipToastTimer = null

    const showVipTip = () => {
      vipToastShow.value = true
      clearTimeout(vipToastTimer)
      vipToastTimer = setTimeout(() => { vipToastShow.value = false }, 2500)
    }

    // 评论展开/收起
    const expandedNovels = reactive({})
    const commentsLoading = reactive({})
    const novelComments = reactive({})
    const commentCounts = reactive({})
    const commentTexts = reactive({})
    const submittingIds = reactive({})

    // 点赞/收藏/关注状态（用于高亮）
    const likedItems = reactive({})
    const bookmarkedItems = reactive({})
    const followedItems = reactive({})

    const fetchFeed = async (append = false) => {
      try {
        if (!append) loading.value = true
        const res = await api.get('/interactions/feed', { params: { page: page.value, page_size: 10 } })
        if (res.状态码 === 200) {
          const newData = res.数据?.items || []
          if (append) { feedItems.value.push(...newData) } else { feedItems.value = newData }
          if (res.数据?.pagination) { hasMore.value = res.数据.pagination.has_next }
          
          // 初始化当前用户的互动状态
          newData.forEach(item => {
            const nid = item.novel_unique_id
            likedItems[nid] = item.user_is_like === 1
            bookmarkedItems[nid] = item.user_is_bookmark === 1
            followedItems[nid] = item.user_is_follow === 1
          })
        }
      } catch (e) { errorMsg.value = '加载失败' }
      finally { loading.value = false; loadingMore.value = false }
    }

    const loadMore = async () => {
      if (loadingMore.value) return
      loadingMore.value = true; page.value++
      await fetchFeed(true)
    }

    const toggleComments = async (item) => {
      const nid = item.novel_unique_id
      if (expandedNovels[nid]) { expandedNovels[nid] = false; return }
      if (!isVip.value) { showVipTip(); return }
      expandedNovels[nid] = true
      if (!novelComments[nid]) {
        commentsLoading[nid] = true
        try {
          const res = await api.get(`/interactions/comments/${nid}`, { params: { page: 1, page_size: 50 } })
          if (res.状态码 === 200) {
            novelComments[nid] = res.数据?.items || []
            commentCounts[nid] = res.数据?.pagination?.total || novelComments[nid]?.length || 0
          }
        } catch (e) { } finally { commentsLoading[nid] = false }
      }
    }

    const submitComment = async (item) => {
      if (!isVip.value) { showVipTip(); return }
      const nid = item.novel_unique_id
      const text = (commentTexts[nid] || '').trim()
      if (!text) return
      submittingIds[nid] = true
      try {
        await api.post('/interactions/comment', null, {
          params: { novel_unique_id: nid, comment_text: text, user_id: item.user_id }
        })
        const res = await api.get(`/interactions/comments/${nid}`, { params: { page: 1, page_size: 50 } })
        if (res.状态码 === 200) {
          novelComments[nid] = res.数据?.items || []
          commentCounts[nid] = res.数据?.pagination?.total || novelComments[nid]?.length || 0
        }
        commentTexts[nid] = ''
      } catch (e) { } finally { submittingIds[nid] = false }
    }

    const doLike = async (item) => {
      if (!isVip.value) { showVipTip(); return }
      likedItems[item.novel_unique_id] = !likedItems[item.novel_unique_id]
      try {
        await api.post('/interactions/like', null, { params: { novel_unique_id: item.novel_unique_id, user_id: item.user_id } })
      } catch (e) { }
    }

    const doBookmark = async (item) => {
      if (!isVip.value) { showVipTip(); return }
      bookmarkedItems[item.novel_unique_id] = !bookmarkedItems[item.novel_unique_id]
      try {
        await api.post('/interactions/bookmark', null, { params: { novel_unique_id: item.novel_unique_id, user_id: item.user_id } })
      } catch (e) { }
    }

    const doFollow = async (item) => {
      if (!isVip.value) { showVipTip(); return }
      followedItems[item.novel_unique_id] = !followedItems[item.novel_unique_id]
      try {
        await api.post('/interactions/follow', null, { params: { novel_unique_id: item.novel_unique_id, user_id: item.user_id } })
      } catch (e) { }
    }

    const formatTime = (t) => {
      if (!t) return ''
      const d = new Date(t + (t.includes('T') ? '' : 'Z'))
      const now = new Date()
      const diff = now - d
      if (diff < 60000) return '刚刚'
      if (diff < 3600000) return Math.floor(diff / 60000) + '分钟前'
      if (diff < 86400000) return Math.floor(diff / 3600000) + '小时前'
      return d.toLocaleDateString('zh-CN')
    }

    const goReader = (nid) => router.push(`/reader/${nid}`)

    onMounted(() => fetchFeed())

    return {
      feedItems, loading, errorMsg, hasMore, loadingMore,
      expandedNovels, commentsLoading, novelComments, commentCounts,
      commentTexts, submittingIds,
      likedItems, bookmarkedItems, followedItems,
      toggleComments, submitComment, doLike, doBookmark, doFollow,
      loadMore, formatTime, goReader,
      isVip, vipToastShow, showVipTip
    }
  }
}
</script>

<style scoped>
.circle-page { max-width: 800px; margin: 0 auto; }
.circle-header { text-align: center; margin-bottom: 30px; padding: 20px 0; }
.circle-header h1 { font-size: 24px; color: var(--text-primary); }
.circle-header p { color: var(--text-secondary); font-size: 13px; margin-top: 4px; }

.loading { display: flex; align-items: center; justify-content: center; gap: 10px; padding: 60px 0; color: var(--text-secondary); }
.spinner { width: 20px; height: 20px; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; display: inline-block; }
.spinner-small { width: 14px; height: 14px; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; display: inline-block; }
@keyframes spin { to { transform: rotate(360deg) } }
.error { color: #f87171; text-align: center; padding: 40px; }
.empty { text-align: center; color: var(--text-muted); padding: 40px; }

.feed-card {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 16px; padding: 20px 24px; margin-bottom: 16px;
  backdrop-filter: blur(20px); box-shadow: var(--card-shadow); transition: all 0.3s;
}
.feed-card:hover { border-color: var(--border-hover); }

.feed-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.feed-author { display: flex; align-items: center; gap: 8px; }
.avatar {
  width: 32px; height: 32px; border-radius: 50%;
  background: var(--brand-gradient); display: flex; align-items: center; justify-content: center;
  font-size: 14px; font-weight: 700; color: #fff;
}
.interactor { font-weight: 600; color: var(--accent); font-size: 14px; }
.action-tag { font-size: 12px; color: var(--text-secondary); }
.time { font-size: 12px; color: var(--text-muted); }

.feed-work { display: flex; gap: 12px; align-items: center; padding: 12px; background: var(--bg-card-hover); border-radius: 10px; margin-bottom: 10px; cursor: pointer; transition: background 0.3s; }
.feed-work:hover { background: rgba(6,182,212,0.06); }
.work-cover { width: 48px; height: 64px; border-radius: 6px; object-fit: cover; flex-shrink: 0; }
.work-cover.placeholder { display: flex; align-items: center; justify-content: center; background: var(--btn-bg); font-size: 24px; }
.work-title { color: var(--text-primary); font-size: 15px; display: block; }
.work-author { color: var(--text-muted); font-size: 12px; margin-top: 2px; display: block; }

.feed-body { margin-bottom: 8px; }
.comment-preview { color: var(--text-secondary); font-size: 13px; line-height: 1.6; font-style: italic; }

/* 操作栏 */
.feed-actions { display: flex; align-items: center; justify-content: space-between; padding-top: 8px; border-top: 1px solid var(--border); }

.action-btns { display: flex; gap: 4px; }
.action-btn {
  background: transparent; border: 1px solid var(--border);
  color: var(--text-secondary); cursor: pointer; font-size: 13px;
  padding: 6px 14px; border-radius: 8px; transition: all 0.25s;
  display: flex; align-items: center; gap: 4px;
}
.action-btn:hover { background: var(--btn-bg); border-color: var(--border-hover); color: var(--accent); }
.action-btn.active { background: var(--btn-bg); border-color: var(--accent); color: var(--accent); box-shadow: 0 0 10px var(--accent-glow); }

/* 评论展开 */
.comment-toggle { display: flex; align-items: center; gap: 6px; cursor: pointer; padding: 6px 12px; border-radius: 8px; transition: all 0.25s; user-select: none; }
.comment-toggle:hover { background: var(--btn-bg); }
.toggle-label { font-size: 13px; color: var(--text-secondary); }
.comment-count { color: var(--accent); font-weight: 600; font-size: 12px; }
.chevron { font-size: 11px; color: var(--text-muted); transition: transform 0.3s; }
.chevron.open { transform: rotate(180deg); }

/* 评论区 */
.comments-section { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border); animation: fadeIn 0.3s ease; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(-6px); } to { opacity: 1; transform: translateY(0); } }

.comments-loading { display: flex; align-items: center; justify-content: center; gap: 8px; padding: 16px; color: var(--text-muted); font-size: 13px; }

.comment-item { display: flex; gap: 10px; margin-bottom: 12px; }
.commenter-avatar {
  width: 28px; height: 28px; border-radius: 50%; flex-shrink: 0;
  background: var(--brand-gradient); display: flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 700; color: #fff;
}
.comment-bubble { flex: 1; background: var(--bg-card-hover); border-radius: 10px; padding: 10px 14px; border: 1px solid var(--border); }
.comment-meta { display: flex; gap: 8px; align-items: center; margin-bottom: 4px; }
.comment-meta strong { font-size: 13px; color: var(--accent); }
.comment-time { font-size: 11px; color: var(--text-muted); }
.comment-text { color: var(--text-primary); font-size: 13px; line-height: 1.5; }

.no-comments { text-align: center; color: var(--text-muted); padding: 12px; font-size: 13px; }

.comment-input-row { display: flex; gap: 8px; margin-top: 12px; }
.comment-input {
  flex: 1; padding: 10px 14px; border-radius: 10px;
  background: var(--bg-card-hover); border: 1px solid var(--border);
  color: var(--text-primary); font-size: 13px; outline: none; transition: border-color 0.3s;
}
.comment-input:focus { border-color: var(--border-focus); }
.btn-submit {
  padding: 10px 20px; border-radius: 10px; border: none; cursor: pointer;
  background: var(--brand-gradient); color: #fff; font-size: 13px; font-weight: 600;
  transition: all 0.3s; white-space: nowrap;
}
.btn-submit:hover:not(:disabled) { box-shadow: 0 0 16px var(--accent-glow); }
.btn-submit:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-more {
  display: block; width: 100%; padding: 14px; border: 1px solid var(--border);
  border-radius: 12px; background: var(--bg-card); color: var(--accent);
  cursor: pointer; font-size: 14px; font-weight: 600; margin-top: 16px; transition: all 0.3s;
}
.btn-more:hover { border-color: var(--border-hover); box-shadow: 0 0 16px var(--accent-glow); }

/* VIP 提示弹窗 */
.vip-toast {
  position: fixed; bottom: 30px; left: 50%; transform: translateX(-50%) translateY(20px);
  background: rgba(15,15,40,0.95); border: 1px solid rgba(245,158,11,0.4);
  padding: 12px 24px; border-radius: 12px; font-size: 13px; color: #fbbf24;
  z-index: 9999; opacity: 0; pointer-events: none; transition: all 0.35s ease;
  box-shadow: 0 8px 30px rgba(0,0,0,0.5), 0 0 20px rgba(245,158,11,0.1);
  backdrop-filter: blur(12px); white-space: nowrap; max-width: 90vw;
}
.vip-toast.show { opacity: 1; transform: translateX(-50%) translateY(0); pointer-events: auto; }
.toast-vip-link { color: #f59e0b; font-weight: 700; text-decoration: underline; margin: 0 2px; }
</style>

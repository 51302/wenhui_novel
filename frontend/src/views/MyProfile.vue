<template>
  <div class="profile-page">
    <div class="profile-header">
      <div class="avatar-big">{{ (profile.username || '?')[0] }}</div>
      <h2>{{ profile.username }}</h2>
      <span class="vip-badge" v-if="profile.is_vip">👑 VIP</span>
      <span class="vip-expire" v-if="profile.vip_expire_at">到期 {{ profile.vip_expire_at }}</span>
    </div>

    <!-- 数据统计 -->
    <div class="stats-row">
      <div class="stat-item"><strong>{{ stats.bookshelf }}</strong><span>书架</span></div>
      <div class="stat-item"><strong>{{ stats.followers }}</strong><span>粉丝</span></div>
      <div class="stat-item"><strong>{{ stats.following }}</strong><span>关注</span></div>
      <div class="stat-item"><strong>{{ stats.likes }}</strong><span>点赞</span></div>
    </div>

    <div v-if="loading" class="loading">
      <span class="spinner"></span> 加载中...
    </div>

    <div v-else>
      <!-- 关注列表 -->
      <div class="section" v-if="profile.following?.length">
        <h3>➕ 我关注的人 <span class="count">({{ profile.following.length }})</span></h3>
        <div class="user-list">
          <div v-for="u in profile.following" :key="u.user_id" class="user-tag">
            <span class="user-avatar">{{ (u.username || '?')[0] }}</span>
            <span>{{ u.username }}</span>
          </div>
        </div>
      </div>

      <!-- 收藏列表 -->
      <div class="section" v-if="profile.bookmarks?.length">
        <h3>🔖 我收藏的作品 <span class="count">({{ profile.bookmarks.length }})</span></h3>
        <div class="book-mini-list">
          <div v-for="b in profile.bookmarks" :key="b.novel_unique_id" class="book-mini" @click="goReader(b.novel_unique_id)">
            <img v-if="b.cover_image" :src="b.cover_image" class="mini-cover" />
            <div v-else class="mini-cover placeholder">📖</div>
            <div class="mini-info">
              <strong>{{ b.title }}</strong>
              <span>{{ b.author_name }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 点赞列表 -->
      <div class="section" v-if="profile.likes?.length">
        <h3>❤️ 我点赞的作品 <span class="count">({{ profile.likes.length }})</span></h3>
        <div class="book-mini-list">
          <div v-for="b in profile.likes" :key="b.novel_unique_id" class="book-mini" @click="goReader(b.novel_unique_id)">
            <img v-if="b.cover_image" :src="b.cover_image" class="mini-cover" />
            <div v-else class="mini-cover placeholder">📖</div>
            <div class="mini-info">
              <strong>{{ b.title }}</strong>
              <span>{{ b.author_name }}</span>
            </div>
          </div>
        </div>
      </div>

      <div v-if="!profile.following?.length && !profile.bookmarks?.length && !profile.likes?.length" class="empty">
        <p>还没有任何互动</p>
        <span>去作品圈逛逛，发现喜欢的作品吧</span>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import api from '../api'

export default {
  name: 'MyProfile',
  setup() {
    const router = useRouter()
    const profile = reactive({})
    const stats = reactive({ bookshelf: 0, followers: 0, following: 0, likes: 0 })
    const loading = ref(true)

    const fetchProfile = async () => {
      try {
        const res = await api.get('/auth/my-profile')
        if (res.状态码 === 200) {
          const d = res.数据
          Object.assign(profile, d)
          if (d.stats) Object.assign(stats, d.stats)
        }
      } catch (e) { } finally { loading.value = false }
    }

    const goReader = (nid) => router.push(`/reader/${nid}`)

    onMounted(() => fetchProfile())

    return { profile, stats, loading, goReader }
  }
}
</script>

<style scoped>
.profile-page { max-width: 800px; margin: 0 auto; padding: 20px; }

.profile-header { text-align: center; margin-bottom: 24px; }
.avatar-big {
  width: 72px; height: 72px; border-radius: 50%; margin: 0 auto 12px;
  background: var(--brand-gradient); display: flex; align-items: center; justify-content: center;
  font-size: 32px; font-weight: 700; color: #fff;
}
.profile-header h2 { font-size: 22px; color: var(--text-primary); margin-bottom: 4px; }
.vip-badge { font-size: 13px; color: #fbbf24; font-weight: 600; }
.vip-expire { font-size: 11px; color: var(--text-muted); margin-left: 8px; }

.stats-row { display: flex; justify-content: center; gap: 32px; margin-bottom: 28px; }
.stat-item { text-align: center; }
.stat-item strong { display: block; font-size: 22px; color: var(--accent); }
.stat-item span { font-size: 12px; color: var(--text-muted); }

.loading { display: flex; align-items: center; justify-content: center; gap: 10px; padding: 60px 0; color: var(--text-secondary); }
.spinner { width: 20px; height: 20px; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; display: inline-block; }
@keyframes spin { to { transform: rotate(360deg) } }

.section { margin-bottom: 24px; }
.section h3 { font-size: 16px; color: var(--text-primary); margin-bottom: 12px; }
.count { font-size: 13px; color: var(--text-muted); }

.user-list { display: flex; flex-wrap: wrap; gap: 8px; }
.user-tag {
  display: flex; align-items: center; gap: 8px;
  background: var(--bg-card); border: 1px solid var(--border);
  padding: 8px 14px; border-radius: 10px; font-size: 13px; color: var(--text-primary);
}
.user-avatar {
  width: 26px; height: 26px; border-radius: 50%; flex-shrink: 0;
  background: var(--brand-gradient); display: flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 700; color: #fff;
}

.book-mini-list { display: flex; flex-direction: column; gap: 8px; }
.book-mini {
  display: flex; gap: 10px; align-items: center; padding: 10px 14px;
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 10px; cursor: pointer; transition: all 0.3s;
}
.book-mini:hover { border-color: var(--border-hover); }
.mini-cover { width: 36px; height: 48px; border-radius: 4px; object-fit: cover; flex-shrink: 0; }
.mini-cover.placeholder { display: flex; align-items: center; justify-content: center; background: var(--btn-bg); font-size: 18px; }
.mini-info strong { display: block; font-size: 14px; color: var(--text-primary); }
.mini-info span { font-size: 12px; color: var(--text-muted); }

.empty { text-align: center; padding: 60px 0; color: var(--text-muted); font-size: 15px; }
</style>

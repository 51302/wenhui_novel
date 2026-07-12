<template>
  <div class="logs-page">
    <div class="page-hero">
      <h1>📋 系统日志</h1>
      <p>实时监控系统运行状态 · 日志保留 7 天自动清理</p>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <select v-model="filter.level" @change="resetAndFetch">
        <option value="">全级</option>
        <option value="INFO">INFO</option>
        <option value="WARNING">WARNING</option>
        <option value="ERROR">ERROR</option>
      </select>
      <select v-model="filter.source" @change="resetAndFetch">
        <option value="">全部来源</option>
        <option value="api">API请求</option>
        <option value="system">系统</option>
        <option value="user">用户</option>
      </select>
      <input v-model="filter.keyword" placeholder="搜索关键词..." @keyup.enter="resetAndFetch" />
      <button @click="resetAndFetch">🔍 搜索</button>
      <span class="poll-indicator" :class="{ active: polling }">
        {{ polling ? '🔄 轮询中...' : '⏸ 已暂停' }}
      </span>
      <button class="btn-clean" @click="manualCleanup">🗑 清理7天前</button>
    </div>

    <!-- 日志列表 -->
    <div class="log-list">
      <div v-if="logs.length === 0" class="empty">暂无日志</div>
      <div v-for="log in logs" :key="log.id" class="log-item" :class="'level-' + log.level.toLowerCase()">
        <div class="log-left">
          <span class="log-level" :class="'badge-' + log.level.toLowerCase()">{{ log.level }}</span>
          <span class="log-time">{{ formatTime(log.created_at) }}</span>
          <span class="log-source">{{ log.source }}</span>
          <span v-if="log.method" class="log-method">{{ log.method }}</span>
        </div>
        <div class="log-right">
          <span class="log-msg">{{ log.message }}</span>
          <span v-if="log.path" class="log-path">{{ log.path }}</span>
        </div>
      </div>
    </div>

    <!-- 分页 -->
    <div class="pagination" v-if="total > 0">
      <button :disabled="page <= 1" @click="page--; fetchLogs()">上一页</button>
      <span>第 {{ page }} / {{ totalPages }} 页 (共 {{ total }} 条)</span>
      <button :disabled="page >= totalPages" @click="page++; fetchLogs()">下一页</button>
    </div>
  </div>
</template>

<script>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import api from '../api'

export default {
  name: 'Logs',
  setup() {
    const logs = ref([])
    const page = ref(1)
    const total = ref(0)
    const pageSize = ref(50)
    const polling = ref(false)
    let pollTimer = null

    const totalPages = computed(() => Math.ceil(total.value / pageSize.value) || 1)

    const filter = reactive({ level: '', source: '', keyword: '' })

    const fetchLogs = async (sinceId = 0) => {
      try {
        const params = { page: page.value, page_size: pageSize.value }
        if (filter.level) params.level = filter.level
        if (filter.source) params.source = filter.source
        if (filter.keyword) params.keyword = filter.keyword
        if (sinceId > 0) {
          params.since_id = sinceId
          params.page = 1
        }
        const res = await api.get('/logs/list', { params })
        if (res.状态码 === 200 && res.数据) {
          const data = res.数据
          if (sinceId > 0 && data.items.length > 0) {
            logs.value = [...data.items, ...logs.value].slice(0, 200)
          } else if (sinceId === 0) {
            logs.value = data.items
          }
          total.value = data.total
        }
        return res.数据?.max_id || 0
      } catch (e) {
        console.error('获取日志失败', e)
        return 0
      }
    }

    let lastMaxId = 0

    const startPolling = () => {
      polling.value = true
      pollTimer = setInterval(async () => {
        if (lastMaxId === 0) {
          const res = await api.get('/logs/max-id')
          lastMaxId = res.max_id || 0
        }
        const newMax = await fetchLogs(lastMaxId)
        if (newMax > lastMaxId) {
          lastMaxId = newMax
        }
      }, 3000)
    }

    const stopPolling = () => {
      polling.value = false
      if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
    }

    const resetAndFetch = () => {
      page.value = 1
      lastMaxId = 0
      fetchLogs()
    }

    const manualCleanup = async () => {
      if (!confirm('确定清理 7 天前的日志？')) return
      try {
        const res = await api.post('/logs/cleanup?days=7')
        alert(res.message || (res.deleted + ' 条已清理'))
        resetAndFetch()
      } catch (e) { alert('清理失败') }
    }

    const formatTime = (t) => {
      if (!t) return '-'
      const d = new Date(t)
      return d.toLocaleString('zh-CN', { hour12: false })
    }

    onMounted(() => {
      fetchLogs()
      startPolling()
    })

    onUnmounted(() => {
      stopPolling()
    })

    return { logs, page, total, pageSize, totalPages, filter, polling,
             fetchLogs, resetAndFetch, manualCleanup, formatTime }
  }
}
</script>

<style scoped>
.logs-page { max-width: 1100px; margin: 0 auto; }

.page-hero { text-align: center; margin-bottom: 24px; padding: 30px 0 10px; }
.page-hero h1 { font-size: 26px; color: var(--text-primary); margin-bottom: 6px; }
.page-hero p { color: var(--text-secondary); font-size: 14px; }

/* 筛选栏 */
.filter-bar {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 12px; padding: 14px 18px; margin-bottom: 16px;
  box-shadow: var(--card-shadow);
}
.filter-bar select, .filter-bar input {
  padding: 7px 12px; border-radius: 6px; border: 1px solid var(--border);
  background: rgba(15,15,40,0.5); color: var(--text-primary); font-size: 13px;
}
.filter-bar select:focus, .filter-bar input:focus { outline: none; border-color: var(--border-hover); }
.filter-bar button {
  padding: 7px 16px; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 600;
  background: var(--btn-bg); color: var(--btn-text); border: 1px solid var(--btn-border);
  transition: all 0.3s;
}
.filter-bar button:hover { box-shadow: 0 2px 12px var(--accent-glow); }
.btn-clean { background: rgba(239,68,68,0.12) !important; border-color: rgba(239,68,68,0.25) !important; color: #f87171 !important; }
.btn-clean:hover { background: rgba(239,68,68,0.22) !important; }

.poll-indicator { font-size: 12px; color: var(--text-muted); margin-left: auto; }
.poll-indicator.active { color: #34d399; }

/* 日志列表 */
.log-list {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 12px; overflow: hidden; box-shadow: var(--card-shadow);
  max-height: 65vh; overflow-y: auto;
}
.empty { text-align: center; padding: 60px 0; color: var(--text-muted); font-size: 14px; }

.log-item {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 18px; border-bottom: 1px solid var(--border);
  transition: background 0.2s; font-size: 13px; gap: 12px;
}
.log-item:hover { background: var(--bg-card-hover); }
.log-item.level-error { border-left: 3px solid #ef4444; }
.log-item.level-warning { border-left: 3px solid #f59e0b; }
.log-item.level-info { border-left: 3px solid #06b6d4; }

.log-left { display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
.log-right { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.log-level { padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; }
.badge-info { background: rgba(6,182,212,0.15); color: #06b6d4; }
.badge-warning { background: rgba(245,158,11,0.15); color: #f59e0b; }
.badge-error { background: rgba(239,68,68,0.15); color: #ef4444; }
.log-time { color: var(--text-muted); font-size: 11px; white-space: nowrap; }
.log-source { color: var(--secondary); font-size: 11px; }
.log-method { color: var(--accent); font-size: 11px; font-weight: 600; }
.log-msg { color: var(--text-primary); word-break: break-all; }
.log-path { color: var(--text-muted); font-size: 11px; word-break: break-all; }

/* 分页 */
.pagination {
  display: flex; align-items: center; justify-content: center; gap: 16px;
  margin-top: 16px; padding: 12px;
}
.pagination button {
  padding: 8px 20px; border-radius: 8px; cursor: pointer; font-size: 13px;
  background: var(--btn-bg); color: var(--btn-text); border: 1px solid var(--btn-border);
}
.pagination button:disabled { opacity: 0.4; cursor: not-allowed; }
.pagination span { color: var(--text-secondary); font-size: 13px; }
</style>

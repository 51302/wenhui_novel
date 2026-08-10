<template>
  <div id="app-root">
    <!-- 星空背景 -->
    <div class="stars-layer"></div>
    <!-- 科技网格背景 -->
    <div class="tech-grid"></div>

    <!-- ===== Dashboard 侧边栏 ===== -->
    <aside v-if="!hideSidebar" class="sidebar" :class="{ collapsed: sidebarCollapsed }">
      <div class="sidebar-header">
        <router-link to="/" class="logo">
          <span class="logo-icon">✦</span>
          <span v-if="!sidebarCollapsed" class="logo-text">文辉小说</span>
        </router-link>
        <button class="sidebar-toggle" @click="sidebarCollapsed = !sidebarCollapsed">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="3" y1="12" x2="21" y2="12"/>
            <line x1="3" y1="6" x2="21" y2="6"/>
            <line x1="3" y1="18" x2="21" y2="18"/>
          </svg>
        </button>
      </div>

      <nav class="sidebar-nav">
        <router-link v-if="user" to="/" class="nav-item">
          <span class="nav-icon">🏠</span>
          <span v-if="!sidebarCollapsed" class="nav-label">首页</span>
        </router-link>
        <router-link v-if="user" to="/circle" class="nav-item" :class="{ 'nav-disabled': !showAllWorks }">
          <span class="nav-icon">🌐</span>
          <span v-if="!sidebarCollapsed" class="nav-label">作品圈</span>
          <span v-if="!sidebarCollapsed && !showAllWorks" class="disabled-badge">内测</span>
        </router-link>
        <router-link v-if="user" to="/bookshelf" class="nav-item">
          <span class="nav-icon">📚</span>
          <span v-if="!sidebarCollapsed" class="nav-label">书架</span>
        </router-link>
        <router-link v-if="user" to="/creation" class="nav-item">
          <span class="nav-icon">✏️</span>
          <span v-if="!sidebarCollapsed" class="nav-label">创作中心</span>
        </router-link>
        <router-link v-if="user" to="/vip" class="nav-item">
          <span class="nav-icon">💎</span>
          <span v-if="!sidebarCollapsed" class="nav-label">开通会员</span>
        </router-link>
      </nav>

      <!-- 侧边栏底部：用户信息 -->
      <div v-if="user && !sidebarCollapsed" class="sidebar-footer">
        <router-link to="/my" class="user-card">
          <span class="user-avatar">{{ user.username[0] }}</span>
          <div class="user-detail">
            <span class="user-name">{{ user.username }}</span>
            <span v-if="user.vip_level >= 2" class="vip-tag svip-tag">SVIP</span>
            <span v-else-if="user.vip_level >= 1" class="vip-tag">VIP</span>
          </div>
        </router-link>
        <div class="footer-actions">
          <router-link to="/settings" class="icon-btn" title="设置">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          </router-link>
          <button class="icon-btn" @click="logout" title="退出">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
          </button>
        </div>
      </div>

      <!-- 折叠时的迷你用户头像 -->
      <div v-if="user && sidebarCollapsed" class="sidebar-footer collapsed-footer">
        <router-link to="/my" class="user-avatar-mini">{{ user.username[0] }}</router-link>
      </div>
    </aside>

    <!-- ===== 主内容区 ===== -->
    <div class="main-area" :class="{ expanded: sidebarCollapsed, 'no-sidebar': hideSidebar }">
      <!-- 顶部状态栏 -->
      <header class="topbar">
        <div class="topbar-left">
          <button class="mobile-menu-btn" @click="sidebarCollapsed = !sidebarCollapsed">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
          </button>
        </div>
        <div class="topbar-right">
          <template v-if="authChecking">
          </template>
          <template v-else-if="user">
            <router-link v-if="!user.vip_level || user.vip_level < 2" to="/vip" class="btn-vip pulse-glow">💎 {{ user.vip_level >= 1 ? '升级SVIP' : '开通会员' }}</router-link>
          </template>
          <template v-else>
            <router-link to="/login" class="btn-login">登 录</router-link>
            <router-link to="/register" class="btn-register">注 册</router-link>
          </template>
        </div>
      </header>

      <!-- 页面内容 -->
      <main class="app-main">
        <router-view @login-success="onLoginSuccess" />
      </main>
    </div>

    <!-- 底部科技装饰线 -->
    <div class="bottom-line"></div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from './api'

export default {
  name: 'App',
  setup() {
    const router = useRouter()
    const route = useRoute()
    const user = ref(null)
    const authChecking = ref(true)
    const showAllWorks = ref(true)
    const sidebarCollapsed = ref(false)
    const hideSidebar = computed(() => ['/login', '/register'].includes(route.path))

    const fetchConfig = async () => {
      try {
        const res = await api.get('/config/public')
        if (res.状态码 === 200) {
          showAllWorks.value = res.数据?.show_all_works !== false
        }
      } catch (e) { }
    }

    onMounted(async () => {
      // 先获取公开配置
      fetchConfig()
      // 登录/注册页不需要会话校验，避免旧 token 触发 /auth/me 返回 401
      if (['/login', '/register'].includes(route.path)) {
        user.value = null
        authChecking.value = false
        return
      }
      // 先检查 localStorage 是否有 token 存在的痕迹
      const stored = localStorage.getItem('novel_user')
      if (!stored) {
        // localStorage 里都没有，直接跳过验证
        authChecking.value = false
        return
      }
      // 有 localStorage，用 /auth/me 验证 token 是否仍有效
      try {
        const res = await api.get('/auth/me')
        if (res.状态码 === 200) {
          user.value = res.数据
          localStorage.setItem('novel_user', JSON.stringify(res.数据))
        }
      } catch (e) {
        user.value = null
        localStorage.removeItem('novel_user')
      } finally {
        authChecking.value = false
      }
    })

    const onLoginSuccess = (u) => {
      user.value = u
      localStorage.setItem('novel_user', JSON.stringify(u))
    }

    const logout = async () => {
      try { await api.post('/auth/logout') } catch (e) { /* ignore */ }
      user.value = null
      localStorage.removeItem('novel_user')
      router.push('/login')
    }

    return { user, authChecking, showAllWorks, sidebarCollapsed, hideSidebar, onLoginSuccess, logout }
  }
}
</script>

<style>
/* ===== 全局重置 ===== */
* { margin: 0; padding: 0; box-sizing: border-box; }
body { 
  font-family: 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
  background: var(--bg-deep);
  color: var(--text-primary);
  overflow-x: hidden;
}
a { text-decoration: none; color: inherit; }
input, textarea, select, button { font-family: inherit; }

/* ===== 星空背景 ===== */
.stars-layer {
  position: fixed; top: 0; left: 0; right: 0; bottom: 0; z-index: 0; pointer-events: none;
  background: 
    radial-gradient(ellipse at 20% 50%, var(--star-color-1) 0%, transparent 50%),
    radial-gradient(ellipse at 80% 20%, var(--star-color-2) 0%, transparent 50%),
    radial-gradient(ellipse at 50% 80%, var(--star-color-3) 0%, transparent 50%);
}

/* ===== 科技网格背景 ===== */
.tech-grid {
  position: fixed; top: 0; left: 0; right: 0; bottom: 0; z-index: 0; pointer-events: none;
  opacity: 0.03;
  background-image:
    linear-gradient(var(--border) 1px, transparent 1px),
    linear-gradient(90deg, var(--border) 1px, transparent 1px);
  background-size: 50px 50px;
}

/* ===== 底部科技装饰线 ===== */
.bottom-line {
  position: fixed; bottom: 0; left: 0; right: 0; height: 2px; z-index: 200;
  background: var(--brand-gradient);
  opacity: 0.3;
  animation: bottomPulse 4s ease-in-out infinite;
}
@keyframes bottomPulse {
  0%, 100% { opacity: 0.2; }
  50% { opacity: 0.5; }
}

/* ===== Dashboard 侧边栏 ===== */
.sidebar {
  position: fixed; top: 0; left: 0; bottom: 0; width: 240px; z-index: 100;
  background: var(--bg-nav);
  backdrop-filter: blur(20px);
  border-right: 1px solid var(--border);
  display: flex; flex-direction: column;
  transition: width 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 4px 0 30px rgba(0, 0, 0, 0.15);
}
.sidebar.collapsed { width: 72px; }

.sidebar-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 20px 20px 16px; min-height: 64px;
}
.logo { 
  display: flex; align-items: center; gap: 10px; 
  font-size: 20px; font-weight: 800;
  background: var(--brand-gradient);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}
.logo-icon { font-size: 24px; -webkit-text-fill-color: var(--accent); filter: drop-shadow(0 0 8px var(--accent-glow)); }
.logo-text { font-size: 20px; white-space: nowrap; }

.sidebar-toggle {
  background: transparent; border: 1px solid var(--border); border-radius: 8px;
  padding: 6px; cursor: pointer; color: var(--text-secondary);
  display: flex; align-items: center; justify-content: center;
  transition: all 0.3s;
}
.sidebar-toggle:hover { color: var(--accent); border-color: var(--border-hover); background: var(--btn-bg); }

.sidebar-nav {
  flex: 1; padding: 8px 12px; display: flex; flex-direction: column; gap: 4px;
}
.nav-item {
  display: flex; align-items: center; gap: 12px;
  padding: 12px 14px; border-radius: 10px;
  color: var(--text-secondary); font-size: 14px; font-weight: 500;
  transition: all 0.3s; position: relative;
}
.nav-item:hover { color: var(--accent); background: var(--btn-bg); }
.nav-item.router-link-active {
  color: var(--accent);
  background: var(--btn-bg);
  box-shadow: 0 0 20px var(--accent-glow);
}
.nav-icon { font-size: 18px; flex-shrink: 0; width: 24px; text-align: center; }
.nav-label { white-space: nowrap; }

.nav-disabled {
  opacity: 0.5 !important;
  cursor: not-allowed !important;
  pointer-events: none;
  filter: grayscale(0.6);
}
.disabled-badge {
  display: inline-block;
  margin-left: auto;
  padding: 2px 8px;
  font-size: 10px;
  font-weight: 600;
  color: var(--gold);
  background: var(--warning-bg);
  border: 1px solid var(--border-hover);
  border-radius: 10px;
}

/* 侧边栏底部用户信息 */
.sidebar-footer {
  padding: 16px 12px; border-top: 1px solid var(--border);
  display: flex; flex-direction: column; gap: 12px;
}
.user-card {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 10px; border-radius: 10px; transition: all 0.3s;
}
.user-card:hover { background: var(--btn-bg); }
.user-avatar {
  width: 36px; height: 36px; border-radius: 50%;
  background: var(--brand-gradient);
  display: flex; align-items: center; justify-content: center;
  font-size: 14px; font-weight: 700; color: #fff; flex-shrink: 0;
  box-shadow: 0 0 12px var(--accent-glow);
}
.user-detail { display: flex; flex-direction: column; gap: 2px; }
.user-name { font-size: 13px; color: var(--text-primary); font-weight: 600; }
.vip-tag {
  color: var(--gold); font-weight: 700; font-size: 11px;
  text-shadow: 0 0 6px var(--accent-glow);
}
.svip-tag { color: var(--gold); }

.footer-actions { display: flex; gap: 8px; }
.icon-btn {
  flex: 1; display: flex; align-items: center; justify-content: center;
  padding: 8px; border-radius: 8px; border: 1px solid var(--border);
  background: transparent; color: var(--text-secondary); cursor: pointer;
  transition: all 0.3s;
}
.icon-btn:hover { color: var(--accent); border-color: var(--border-hover); background: var(--btn-bg); }

/* 折叠时的迷你头像 */
.collapsed-footer { padding: 16px 0; border-top: 1px solid var(--border); display: flex; justify-content: center; }
.user-avatar-mini {
  width: 36px; height: 36px; border-radius: 50%;
  background: var(--brand-gradient);
  display: flex; align-items: center; justify-content: center;
  font-size: 14px; font-weight: 700; color: #fff;
  box-shadow: 0 0 12px var(--accent-glow);
}

/* ===== 主内容区 ===== */
.main-area {
  margin-left: 240px; min-height: 100vh;
  transition: margin-left 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  display: flex; flex-direction: column;
}
.main-area.expanded { margin-left: 72px; }
.main-area.no-sidebar { margin-left: 0; }

/* 顶部状态栏 */
.topbar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 24px; height: 56px; min-height: 56px;
  background: var(--bg-nav);
  backdrop-filter: blur(20px);
  border-bottom: 1px solid var(--border);
  position: sticky; top: 0; z-index: 90;
}
.topbar-left { display: flex; align-items: center; gap: 12px; }
.topbar-right { display: flex; align-items: center; gap: 12px; }

.mobile-menu-btn {
  display: none; background: transparent; border: none; cursor: pointer;
  color: var(--text-secondary); padding: 6px;
}

/* 按钮 */
.btn-login, .btn-register, .btn-vip {
  padding: 8px 20px; border-radius: 8px; font-size: 13px; cursor: pointer; border: none;
  font-weight: 600; transition: all 0.3s;
}
.btn-vip {
  background: var(--gold-gradient); color: #fff;
  box-shadow: 0 4px 16px var(--accent-glow); font-size: 12px;
}
.btn-vip:hover { transform: translateY(-1px); }
.btn-login { 
  background: transparent; color: var(--accent); border: 1px solid var(--border-hover); 
}
.btn-login:hover { background: var(--btn-bg); box-shadow: 0 0 15px var(--accent-glow); }
.btn-register { 
  background: var(--brand-gradient); color: #fff;
  box-shadow: 0 4px 20px var(--accent-glow);
}
.btn-register:hover { box-shadow: 0 4px 30px var(--accent-glow-strong); transform: translateY(-1px); }

.app-main { 
  flex: 1; padding: 24px; max-width: 1400px; margin: 0 auto; width: 100%;
  position: relative; z-index: 1;
}

/* ===== 响应式：移动端侧边栏变浮层 ===== */
@media (max-width: 768px) {
  .sidebar { width: 72px; }
  .sidebar .nav-label, .sidebar .logo-text, .sidebar .sidebar-footer:not(.collapsed-footer) { display: none; }
  .main-area { margin-left: 72px; }
  .main-area.expanded { margin-left: 72px; }
  .mobile-menu-btn { display: flex; }
  .app-main { padding: 16px; }
}
</style>

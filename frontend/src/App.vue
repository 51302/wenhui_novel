<template>
  <div id="app-root">
    <!-- 星空背景 -->
    <div class="stars-layer"></div>
    <!-- 科技网格背景 -->
    <div class="tech-grid"></div>

    <header class="app-header">
      <div class="header-left">
        <router-link to="/" class="logo">
          <span class="logo-icon">✦</span>
          <span class="logo-text">文辉小说</span>
        </router-link>
        <nav class="nav-links">
          <router-link v-if="user" to="/"><span class="nav-icon">🏠</span> 首页</router-link>
          <router-link v-if="user" to="/circle" :class="{ 'nav-disabled': !showAllWorks }">
            <span class="nav-icon">🌐</span> 作品圈
            <span v-if="!showAllWorks" class="disabled-badge">内测中</span>
          </router-link>
          <router-link v-if="user" to="/bookshelf"><span class="nav-icon">📚</span> 书架</router-link>
          <router-link v-if="user" to="/vip"><span class="nav-icon">💎</span> 开通会员</router-link>
          <router-link v-if="user" to="/creation"><span class="nav-icon">✏️</span> 创作中心</router-link>
        </nav>
      </div>
      <div class="header-right">
        <!-- 正在验证登录状态，不显示任何按钮避免闪烁 -->
        <template v-if="authChecking">
        </template>
        <template v-else-if="user">
          <span class="user-info">
            <span class="user-avatar">{{ user.username[0] }}</span>
            {{ user.username }}
            <span v-if="user.vip_level >= 2" class="vip-tag svip-tag" :title="'到期: ' + (user.vip_expire_at || '未知')">· SVIP</span>
            <span v-else-if="user.vip_level >= 1" class="vip-tag" :title="'到期: ' + (user.vip_expire_at || '未知')">· VIP</span>
          </span>
          <router-link v-if="!user.vip_level || user.vip_level < 2" to="/vip" class="btn-vip pulse-glow">💎 {{ user.vip_level >= 1 ? '升级SVIP' : '开通会员' }}</router-link>
          <router-link to="/my" class="btn-my">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
          </router-link>
          <router-link to="/settings" class="btn-settings" title="设置">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          </router-link>
          <button class="btn-logout" @click="logout">退出</button>
        </template>
        <template v-else>
          <router-link to="/login" class="btn-login">登 录</router-link>
          <router-link to="/register" class="btn-register">注 册</router-link>
        </template>
      </div>
    </header>

    <main class="app-main">
      <router-view @login-success="onLoginSuccess" />
    </main>

    <!-- 底部科技装饰线 -->
    <div class="bottom-line"></div>
  </div>
</template>

<script>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import api from './api'

export default {
  name: 'App',
  setup() {
    const router = useRouter()
    const user = ref(null)
    const authChecking = ref(true)
    const showAllWorks = ref(true)

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
      router.push('/')
    }

    return { user, authChecking, showAllWorks, onLoginSuccess, logout }
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

/* ===== 顶部导航 ===== */
.app-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 32px; height: 64px;
  background: var(--bg-nav);
  backdrop-filter: blur(20px);
  border-bottom: 1px solid var(--border);
  position: sticky; top: 0; z-index: 100;
  box-shadow: 0 4px 30px rgba(0, 0, 0, 0.3);
}
.header-left { display: flex; align-items: center; gap: 40px; }
.logo { 
  display: flex; align-items: center; gap: 8px; 
  font-size: 22px; font-weight: 800;
  background: var(--brand-gradient);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}
.logo-icon { font-size: 26px; -webkit-text-fill-color: var(--accent); filter: drop-shadow(0 0 8px var(--accent-glow)); }
.logo-text { font-size: 22px; }

.nav-links { display: flex; gap: 8px; }
.nav-links a { 
  color: var(--text-secondary); font-size: 14px; padding: 8px 16px; border-radius: 8px;
  transition: all 0.3s; position: relative; font-weight: 500;
}
.nav-links a:hover { color: var(--accent); background: rgba(6, 182, 212, 0.08); }
.nav-links .router-link-active { 
  color: var(--accent); 
  background: rgba(6, 182, 212, 0.1);
  box-shadow: 0 0 20px var(--accent-glow);
}
.nav-icon { margin-right: 4px; }

.nav-disabled {
  opacity: 0.5 !important;
  cursor: not-allowed !important;
  pointer-events: none;
  filter: grayscale(0.6);
}
.disabled-badge {
  display: inline-block;
  margin-left: 6px;
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 600;
  color: #f59e0b;
  background: rgba(245, 158, 11, 0.15);
  border: 1px solid rgba(245, 158, 11, 0.3);
  border-radius: 10px;
}

.header-right { display: flex; align-items: center; gap: 14px; }
.user-info { 
  display: flex; align-items: center; gap: 8px;
  font-size: 14px; color: var(--secondary); 
}
.user-avatar {
  width: 32px; height: 32px; border-radius: 50%;
  background: var(--brand-gradient);
  display: flex; align-items: center; justify-content: center;
  font-size: 14px; font-weight: 700; color: #fff;
  box-shadow: 0 0 12px var(--accent-glow);
}
.vip-tag {
  color: var(--gold); font-weight: 700; cursor: help;
  text-shadow: 0 0 6px rgba(245,158,11,0.4);
}

.btn-login, .btn-register, .btn-logout, .btn-vip, .btn-settings {
  padding: 8px 20px; border-radius: 8px; font-size: 13px; cursor: pointer; border: none;
  font-weight: 600; transition: all 0.3s;
}
.btn-vip {
  background: var(--gold-gradient); color: #fff;
  box-shadow: 0 4px 16px rgba(245,158,11,0.3); font-size: 12px;
}
.btn-vip:hover { transform: translateY(-1px); }
.btn-settings {
  background: transparent; color: var(--text-secondary); border: 1px solid var(--border);
  padding: 6px 10px; display: flex; align-items: center; justify-content: center;
}
.btn-settings:hover { color: var(--accent); border-color: var(--border-hover); box-shadow: 0 0 12px var(--accent-glow); }
.btn-login { 
  background: transparent; color: var(--accent); border: 1px solid var(--border-hover); 
}
.btn-login:hover { background: rgba(6, 182, 212, 0.1); box-shadow: 0 0 15px var(--accent-glow); }
.btn-register { 
  background: var(--brand-gradient); color: #fff;
  box-shadow: 0 4px 20px var(--accent-glow);
}
.btn-register:hover { box-shadow: 0 4px 30px var(--accent-glow-strong); transform: translateY(-1px); }
.btn-logout { 
  background: transparent; color: var(--text-secondary); border: 1px solid var(--border);
}
.btn-logout:hover { color: #f87171; border-color: rgba(248, 113, 113, 0.4); }

.app-main { 
  min-height: calc(100vh - 64px); padding: 32px; max-width: 1280px; margin: 0 auto; 
  position: relative; z-index: 1;
}
</style>

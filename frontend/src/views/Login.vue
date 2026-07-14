<template>
  <div class="login-page">
    <!-- 左侧：品牌宣传 -->
    <div class="hero-panel">
      <div class="hero-glow"></div>
      <div class="hero-content">
        <div class="hero-badge">✨ AI 赋能创作</div>
        <h1 class="hero-title">
          让创作<span class="highlight">更简单</span>
        </h1>
        <p class="hero-desc">
          输入你的灵感，AI 帮你完成故事。从世界观搭建到章节续写，<br/>每一步都有智能助手相伴。
        </p>

        <!-- 三大卖点 -->
        <div class="feature-list">
          <div class="feature-item">
            <span class="feature-icon">🤖</span>
            <div>
              <strong>AI 智能续写</strong>
              <p>基于你的故事设定，一键生成后续章节，灵感永不枯竭</p>
            </div>
          </div>
          <div class="feature-item">
            <span class="feature-icon">📖</span>
            <div>
              <strong>全部免费阅读</strong>
              <p>所有创作者的作品对读者完全免费，让好故事被更多人看到</p>
            </div>
          </div>
          <div class="feature-item">
            <span class="feature-icon">🌟</span>
            <div>
              <strong>作品圈互动</strong>
              <p>点赞、评论、关注你喜爱的作者，创作路上不再孤单</p>
            </div>
          </div>
        </div>

        <div class="hero-stats">
          <div class="stat"><strong>AI 驱动</strong><span>智能创作引擎</span></div>
          <div class="stat"><strong>免费阅读</strong><span>所有作品开放</span></div>
          <div class="stat"><strong>即时发布</strong><span>写即所享</span></div>
        </div>
      </div>
    </div>

    <!-- 右侧：登录卡片 -->
    <div class="login-panel">
      <div class="login-card">
        <div class="card-header">
          <div class="card-icon">✦</div>
          <h2>登录文辉小说</h2>
          <p class="card-sub">开启你的 AI 创作之旅</p>
        </div>

        <form @submit.prevent="handleLogin">
          <div class="input-group">
            <span class="input-icon">👤</span>
            <input v-model="form.username" placeholder="用户名" required />
          </div>
          <div class="input-group">
            <span class="input-icon">🔒</span>
            <input v-model="form.password" type="password" placeholder="密码" required />
          </div>

          <!-- 滑块验证码 -->
          <div class="captcha-section" v-if="showCaptcha">
            <p class="captcha-label">安全验证</p>
            <div class="captcha-track" ref="captchaTrack"
                 @mousedown="startDrag"
                 @touchstart.prevent="startDrag">
              <div class="track-fill" :style="{ width: sliderLeft + 36 + 'px' }"></div>
              <div class="captcha-btn" ref="captchaSlider" :style="{ left: sliderLeft + 'px' }" :class="{ done: verified }">
                <span v-if="!verified">⟫</span>
                <span v-else>✓</span>
              </div>
              <span class="track-text" v-if="!verified">向右滑动验证</span>
              <span class="track-text done-text" v-else>验证通过</span>
            </div>
            <p v-if="errMsg" class="captcha-error">{{ errMsg }}</p>
          </div>

          <p v-if="error" class="error">{{ error }}</p>
          <button type="submit" :disabled="loggingIn">
            <span v-if="loggingIn" class="login-spinner"></span>
            {{ loggingIn ? '登录中...' : '登 录' }}
          </button>
        </form>

        <p class="tip">没有账号？<router-link to="/register">立即注册 →</router-link></p>
      </div>
    </div>

    <!-- 背景装饰 -->
    <div class="bg-decor">
      <div class="decor-circle c1"></div>
      <div class="decor-circle c2"></div>
      <div class="decor-circle c3"></div>
      <div class="decor-line l1"></div>
    </div>
  </div>
</template>

<script>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import api from '../api'

export default {
  name: 'Login',
  emits: ['login-success'],
  setup(props, { emit }) {
    const router = useRouter()
    const form = reactive({ username: '', password: '' })
    const error = ref('')
    const loggingIn = ref(false)

    // 清除登录状态
    onMounted(() => {
      localStorage.removeItem('novel_user')
    })

    const showCaptcha = ref(false)
    const captchaId = ref('')
    const targetX = ref(0)
    const sliderLeft = ref(0)
    const verified = ref(false)
    const errMsg = ref('')
    const captchaTrack = ref(null)
    const captchaSlider = ref(null)

    const loadCaptcha = async () => {
      verified.value = false; sliderLeft.value = 0; errMsg.value = ''
      try {
        const res = await api.get('/auth/captcha')
        if (res.状态码 === 200) {
          captchaId.value = res.数据.captcha_id
          targetX.value = res.数据.target_x
        }
      } catch (e) { errMsg.value = '验证码加载失败' }
    }

    let dragging = false
    let startX = 0

    const startDrag = (e) => {
      if (verified.value) return
      dragging = true; errMsg.value = ''
      const track = captchaTrack.value
      const maxW = track.offsetWidth - 42
      startX = e.touches ? e.touches[0].clientX : e.clientX

      const move = (ev) => {
        if (!dragging) return
        const cx = ev.touches ? ev.touches[0].clientX : ev.clientX
        sliderLeft.value = Math.max(0, Math.min(cx - startX, maxW))
      }
      const end = () => {
        dragging = false
        document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', end)
        document.removeEventListener('touchmove', move); document.removeEventListener('touchend', end)
        if (sliderLeft.value >= maxW * 0.95) {
          verified.value = true; sliderLeft.value = maxW
        } else {
          errMsg.value = '请滑到最右端'
          sliderLeft.value = 0
        }
      }
      document.addEventListener('mousemove', move); document.addEventListener('mouseup', end)
      document.addEventListener('touchmove', move); document.addEventListener('touchend', end)
    }

    const handleLogin = async () => {
      error.value = ''
      if (!showCaptcha.value) { showCaptcha.value = true; setTimeout(loadCaptcha, 50); return }
      if (!verified.value) { error.value = '请先完成滑块验证'; return }
      loggingIn.value = true
      try {
        const res = await api.post('/auth/login', {
          username: form.username, password: form.password,
          captcha_id: captchaId.value, captcha_x: targetX.value
        })
        if (res.状态码 === 200) {
          localStorage.setItem('novel_user', JSON.stringify(res.数据))
          emit('login-success', res.数据); router.push('/')
        } else { error.value = res.消息; showCaptcha.value = false }
      } catch (e) { error.value = '登录失败，请重试'; showCaptcha.value = false }
      finally { loggingIn.value = false }
    }

    return { form, error, loggingIn, showCaptcha, sliderLeft, verified, errMsg, captchaTrack, captchaSlider, loadCaptcha, startDrag, handleLogin }
  }
}
</script>

<style scoped>
.login-page {
  display: flex; min-height: calc(100vh - 120px); position: relative; overflow: hidden;
  align-items: center;
}

/* ====== 左侧品牌区 ====== */
.hero-panel {
  flex: 1.2; display: flex; align-items: center; justify-content: center;
  padding: 40px 60px; position: relative; z-index: 2;
}
.hero-glow {
  position: absolute; width: 500px; height: 500px; border-radius: 50%;
  background: radial-gradient(circle, rgba(6,182,212,0.08) 0%, transparent 70%);
  top: 50%; left: 50%; transform: translate(-50%, -50%); pointer-events: none;
}
.hero-content { position: relative; z-index: 2; max-width: 520px; }

.hero-badge {
  display: inline-block; padding: 6px 16px; border-radius: 20px;
  background: rgba(6,182,212,0.1); border: 1px solid rgba(6,182,212,0.2);
  color: #06b6d4; font-size: 12px; font-weight: 600; margin-bottom: 20px;
}

.hero-title {
  font-size: 40px; font-weight: 800; color: #e8eaed; line-height: 1.2; margin-bottom: 16px;
  letter-spacing: 2px;
}
.highlight {
  background: linear-gradient(135deg, #06b6d4, #8b5cf6);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}

.hero-desc {
  font-size: 14px; color: #8892b0; line-height: 1.8; margin-bottom: 32px;
}

/* 三大卖点 */
.feature-list { display: flex; flex-direction: column; gap: 18px; margin-bottom: 32px; }
.feature-item { display: flex; gap: 14px; align-items: flex-start; }
.feature-icon {
  font-size: 28px; width: 48px; height: 48px; border-radius: 14px;
  background: rgba(15,15,40,0.8); border: 1px solid rgba(102,126,234,0.12);
  display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.feature-item strong { display: block; font-size: 14px; color: #e0e0e0; margin-bottom: 3px; }
.feature-item p { font-size: 12px; color: #5a6080; line-height: 1.5; margin: 0; }

/* 底部数据 */
.hero-stats { display: flex; gap: 40px; }
.stat strong { display: block; font-size: 18px; color: #e0e0e0; }
.stat span { font-size: 12px; color: #5a6080; }

/* ====== 右侧登录卡 ====== */
.login-panel {
  flex: 0.8; display: flex; align-items: center; justify-content: center;
  padding: 40px 20px; position: relative; z-index: 2;
}

.login-card {
  background: rgba(15,15,40,0.88); border: 1px solid rgba(102,126,234,0.12);
  border-radius: 20px; padding: 40px 36px; width: 400px; max-width: 100%;
  backdrop-filter: blur(24px); box-shadow: 0 20px 60px rgba(0,0,0,0.4),
              0 0 80px rgba(6,182,212,0.04);
}

.card-header { text-align: center; margin-bottom: 28px; }
.card-icon {
  font-size: 44px; margin-bottom: 8px;
  background: linear-gradient(135deg, #06b6d4, #8b5cf6);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  filter: drop-shadow(0 0 12px rgba(6,182,212,0.4));
}
.card-header h2 { font-size: 22px; color: #e0e0e0; margin-bottom: 6px; }
.card-sub { font-size: 13px; color: #5a6080; }

.input-group {
  display: flex; align-items: center; gap: 10px;
  padding: 0 14px; margin-bottom: 12px; border-radius: 10px;
  background: rgba(15,15,40,0.6); border: 1px solid rgba(102,126,234,0.15);
  transition: all 0.3s;
}
.input-group:focus-within { border-color: rgba(6,182,212,0.5); box-shadow: 0 0 16px rgba(6,182,212,0.08); }
.input-icon { font-size: 16px; opacity: 0.5; }
.input-group input { flex: 1; padding: 11px 0; background: none; border: none; color: #e0e0e0; font-size: 14px; outline: none; }
.input-group input::placeholder { color: #4a5080; }

/* ====== 滑块验证码 ====== */
.captcha-section { margin-bottom: 10px; }
.captcha-label { font-size: 12px; color: #8892b0; margin-bottom: 6px; }

.captcha-track {
  position: relative; height: 44px; border-radius: 22px;
  background: rgba(15,15,40,0.9); border: 1px solid rgba(102,126,234,0.2);
  overflow: hidden; user-select: none;
}
.track-fill {
  position: absolute; left: 0; top: 0; height: 100%;
  background: linear-gradient(90deg, rgba(6,182,212,0.2), rgba(139,92,246,0.25));
  border-radius: 22px 0 0 22px;
}
.track-text {
  position: absolute; width: 100%; text-align: center; line-height: 44px;
  font-size: 13px; color: #5a6080; pointer-events: none;
}
.done-text { color: #34d399; font-weight: 600; }

.captcha-btn {
  position: absolute; top: 4px; width: 36px; height: 36px;
  background: linear-gradient(135deg, #06b6d4, #8b5cf6);
  border-radius: 50%; cursor: grab; z-index: 2;
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-size: 16px; font-weight: bold;
  box-shadow: 0 2px 12px rgba(6,182,212,0.5), 0 0 20px rgba(6,182,212,0.2);
}
.captcha-btn:active { cursor: grabbing; transform: scale(1.05); }
.captcha-btn.done { background: linear-gradient(135deg, #22c55e, #16a34a); box-shadow: 0 2px 12px rgba(34,197,94,0.5); }

.captcha-error { color: #f87171; font-size: 12px; margin-top: 3px; }

.login-card > form > button {
  width: 100%; padding: 13px; background: linear-gradient(135deg, #06b6d4, #8b5cf6);
  color: #fff; border: none; border-radius: 10px; font-size: 15px; cursor: pointer;
  font-weight: 700; transition: all 0.3s; margin-top: 4px;
  box-shadow: 0 4px 20px rgba(6,182,212,0.3);
  display: flex; align-items: center; justify-content: center; gap: 8px;
}
.login-card > form > button:hover:not(:disabled) { box-shadow: 0 4px 35px rgba(139,92,246,0.45); transform: translateY(-1px); }
.login-card > form > button:disabled { opacity: 0.6; cursor: not-allowed; transform: none; }
.login-spinner { display: inline-block; width: 16px; height: 16px; border: 2px solid rgba(255,255,255,0.3); border-top-color: #fff; border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.error { color: #f87171; font-size: 13px; margin-bottom: 4px; text-align: center; }
.tip { text-align: center; margin-top: 16px; font-size: 13px; color: #5a6080; }
.tip a { color: #06b6d4; font-weight: 600; }

/* ====== 背景装饰 ====== */
.bg-decor { position: absolute; inset: 0; pointer-events: none; z-index: 1; }
.decor-circle {
  position: absolute; border-radius: 50%; border: 1px solid rgba(102,126,234,0.06);
}
.c1 { width: 600px; height: 600px; top: -200px; right: -200px; }
.c2 { width: 400px; height: 400px; bottom: -150px; left: -100px; border-color: rgba(6,182,212,0.04); }
.c3 { width: 300px; height: 300px; top: 40%; left: 30%; border-color: rgba(139,92,246,0.04); }

.decor-line {
  position: absolute; width: 1px; height: 200px;
  background: linear-gradient(to bottom, transparent, rgba(6,182,212,0.1), transparent);
}
.l1 { top: 20%; left: 25%; }

/* ====== 响应式 ====== */
@media (max-width: 900px) {
  .login-page { flex-direction: column; }
  .hero-panel { flex: none; padding: 30px 24px 10px; }
  .hero-title { font-size: 28px; }
  .hero-desc { font-size: 13px; margin-bottom: 20px; }
  .feature-list { gap: 12px; margin-bottom: 20px; }
  .feature-icon { width: 40px; height: 40px; font-size: 22px; }
  .hero-stats { gap: 20px; }
  .login-panel { flex: none; padding: 10px 16px 40px; }
  .login-card { padding: 30px 24px; }
}
</style>

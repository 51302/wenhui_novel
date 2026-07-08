<template>
  <div class="login-page">
    <div class="login-card">
      <div class="card-icon">✦</div>
      <h2>登录文辉小说</h2>
      <p class="card-sub">探索无尽的创作宇宙</p>
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
      <p class="tip">没有账号？<router-link to="/register">去注册 →</router-link></p>
    </div>
    <div class="bg-text">文 辉 小 说</div>
  </div>
</template>

<script>
import { ref, reactive } from 'vue'
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
.login-page { display: flex; justify-content: center; align-items: center; min-height: 80vh; position: relative; overflow: hidden; }
.login-card { 
  background: rgba(15,15,40,0.85); border: 1px solid rgba(102,126,234,0.15); 
  border-radius: 18px; padding: 40px; width: 420px;
  backdrop-filter: blur(20px); box-shadow: 0 20px 60px rgba(0,0,0,0.4);
  position: relative; z-index: 2;
}
.card-icon { font-size: 48px; text-align: center; margin-bottom: 6px; background: linear-gradient(135deg, #06b6d4, #8b5cf6); -webkit-background-clip: text; -webkit-text-fill-color: transparent; filter: drop-shadow(0 0 12px rgba(6,182,212,0.4)); }
.login-card h2 { text-align: center; margin-bottom: 4px; font-size: 22px; color: #e0e0e0; }
.card-sub { text-align: center; margin-bottom: 24px; font-size: 13px; color: #5a6080; }

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
  width: 100%; padding: 12px; background: linear-gradient(135deg, #06b6d4, #8b5cf6); 
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
.bg-text { position: absolute; font-size: 180px; font-weight: 900; color: rgba(255,255,255,0.03); white-space: nowrap; z-index: 1; user-select: none; pointer-events: none; }
</style>

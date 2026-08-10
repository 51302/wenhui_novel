<template>
  <div class="login-page">
    <div class="login-card">
      <div class="card-icon">✦</div>
      <h2>注册文辉小说</h2>
      <p class="card-sub">开启你的创作之旅</p>
      <form @submit.prevent="handleRegister">
        <!-- 用户名 -->
        <div class="input-group">
          <span class="input-icon">👤</span>
          <input v-model="form.username" type="text" placeholder="用户名" autocomplete="username" required />
        </div>

        <!-- 密码 -->
        <div class="input-group">
          <span class="input-icon">🔒</span>
          <input v-model="form.password" type="password" placeholder="密码(至少8位)" autocomplete="new-password" required />
        </div>

        <!-- 邮箱 + 发送验证码 -->
        <div class="input-group">
          <span class="input-icon">📧</span>
          <input v-model="form.email" type="email" placeholder="邮箱(必填)" autocomplete="email" required />
        </div>
        <div class="code-row">
          <div class="input-group flex-1">
            <span class="input-icon">✉️</span>
            <input v-model="form.email_code" placeholder="邮箱验证码" autocomplete="one-time-code" required maxlength="6" />
          </div>
          <button type="button" class="btn-send" :disabled="emailCountdown > 0" @click="sendEmailCode">
            {{ emailCountdown > 0 ? emailCountdown + 's 后重发' : '发送验证码' }}
          </button>
        </div>

        <!-- 手机号（选填，仅格式校验） -->
        <div class="input-group">
          <span class="input-icon">📱</span>
          <input v-model="form.phone" placeholder="手机号(选填)" autocomplete="tel" maxlength="11" />
        </div>

        <p v-if="error" class="error">{{ error }}</p>
        <p v-if="tip" class="tip-info">{{ tip }}</p>
        <button type="submit" :disabled="submitting">
          {{ submitting ? '注册中...' : '注 册' }}
        </button>
      </form>

      <p class="tip">已有账号？<router-link to="/login">去登录 →</router-link></p>
    </div>
  </div>
</template>

<script>
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import api from '../api'

export default {
  name: 'Register',
  emits: ['login-success'],
  setup(props, { emit }) {
    const router = useRouter()
    const form = reactive({
      username: '', password: '',
      email: '', phone: '',
      email_code: ''
    })
    const error = ref('')
    const tip = ref('')
    const submitting = ref(false)
    const emailCountdown = ref(0)

    const startCountdown = (which) => {
      const refTarget = which === 'email' ? emailCountdown : phoneCountdown
      refTarget.value = 60
      const timer = setInterval(() => {
        refTarget.value--
        if (refTarget.value <= 0) clearInterval(timer)
      }, 1000)
    }

    const sendEmailCode = async () => {
      error.value = ''; tip.value = ''
      if (!form.email) { error.value = '请先输入邮箱'; return }
      try {
        const res = await api.post('/auth/send-email-code', { target: form.email })
        if (res.状态码 === 200) {
          startCountdown('email')
          tip.value = '验证码已发送至 ' + form.email + '，请查看收件箱（含垃圾箱）'
        } else error.value = res.消息
      } catch (e) { error.value = '发送失败，请重试' }
    }

    const handleRegister = async () => {
      error.value = ''; tip.value = ''
      if (form.password.length < 8) { error.value = '密码必须超过8位数'; return }
      if (!form.email) { error.value = '请输入邮箱'; return }
      if (!form.email_code) { error.value = '请输入邮箱验证码'; return }

      submitting.value = true
      try {
        const res = await api.post('/auth/register', {
          username: form.username,
          password: form.password,
          email: form.email,
          phone: form.phone || undefined,
          email_code: form.email_code
        })
        if (res.状态码 === 200) {
          localStorage.setItem('novel_user', JSON.stringify(res.数据))
          emit('login-success', res.数据)
          router.push('/')
        } else {
          // 针对不同错误给出更友好的提示
          if (res.消息 && res.消息.includes('邮箱')) {
            error.value = res.消息
          } else if (res.消息 && res.消息.includes('用户名')) {
            error.value = res.消息
          } else {
            error.value = res.消息 || '注册失败，请重试'
          }
        }
      } catch (e) { error.value = '注册失败，请重试' }
      finally { submitting.value = false }
    }

    return { form, error, tip, submitting, emailCountdown, sendEmailCode, handleRegister }
  }
}
</script>

<style scoped>
.login-page { display: flex; justify-content: center; align-items: center; min-height: 80vh; }
.login-card {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 18px; padding: 40px; width: 460px;
  backdrop-filter: blur(20px); box-shadow: var(--card-shadow), 0 0 60px var(--accent-glow);
}
.card-icon { font-size: 48px; text-align: center; margin-bottom: 6px; background: linear-gradient(135deg, #06b6d4, #8b5cf6); -webkit-background-clip: text; -webkit-text-fill-color: transparent; filter: drop-shadow(0 0 12px rgba(6,182,212,0.4)); }
.login-card h2 { text-align: center; margin-bottom: 4px; font-size: 22px; color: var(--text-primary); }
.card-sub { text-align: center; margin-bottom: 24px; font-size: 13px; color: var(--text-muted); }

.input-group {
  display: flex; align-items: center; gap: 10px;
  padding: 0 14px; margin-bottom: 12px; border-radius: 10px;
  background: var(--bg-card-hover); border: 1px solid var(--border);
  transition: border-color 0.3s;
}
.input-group:focus-within { border-color: var(--border-focus); box-shadow: 0 0 16px var(--accent-glow); }
.input-icon { font-size: 16px; opacity: 0.5; flex-shrink: 0; }
.input-group input { flex: 1; padding: 12px 0; background: none; border: none; color: var(--text-primary); font-size: 14px; outline: none; }
.input-group input::placeholder { color: var(--text-muted); }

.code-row { display: flex; gap: 10px; margin-bottom: 12px; align-items: stretch; }
.code-row .input-group { margin-bottom: 0; }
.flex-1 { flex: 1; }

.btn-send {
  flex-shrink: 0; padding: 0 16px; border-radius: 10px;
  border: 1px solid var(--border-hover); cursor: pointer;
  font-size: 13px; font-weight: 600; color: var(--accent);
  background: transparent; white-space: nowrap;
  transition: all 0.3s;
}
.btn-send:hover:not(:disabled) { background: var(--btn-bg); }
.btn-send:disabled { opacity: 0.5; cursor: not-allowed; }

.login-card button[type="submit"] {
  width: 100%; padding: 13px; margin-top: 6px;
  background: var(--brand-gradient); color: #fff; border: none;
  border-radius: 10px; font-size: 15px; cursor: pointer; font-weight: 700;
  transition: all 0.3s; box-shadow: 0 4px 20px var(--accent-glow);
}
.login-card button[type="submit"]:hover:not(:disabled) { box-shadow: 0 4px 35px var(--accent-glow-strong); transform: translateY(-1px); }
.login-card button[type="submit"]:disabled { opacity: 0.6; cursor: not-allowed; transform: none; }

.error { color: var(--error-text); font-size: 13px; margin-bottom: 6px; text-align: center; }
.tip-info { color: var(--success); font-size: 13px; margin-bottom: 6px; text-align: center; }

.tip { text-align: center; margin-top: 20px; font-size: 13px; color: var(--text-muted); }
.tip a { color: var(--accent); font-weight: 600; }
</style>

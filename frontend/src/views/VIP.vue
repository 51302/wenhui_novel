<template>
  <div class="vip-page">
    <div class="vip-hero">
      <div class="hero-glow"></div>
      <h1>💎 开通 VIP 会员</h1>
      <p class="hero-sub">解锁全部功能，畅享 AI 创作体验</p>
    </div>

    <div v-if="!loading && isVip" class="vip-card already-vip">
      <div class="vip-badge">✨ 已开通</div>
      <h2>您已是 VIP 会员</h2>
      <p v-if="vipExpireAt">到期时间：{{ vipExpireAt }}</p>
      <p>享受无限 AI 创作、发布作品等全部特权</p>
    </div>

    <div v-if="!loading && !isVip" class="vip-cards">
      <div class="price-card" @click="handlePay('monthly')">
        <h3>月度会员</h3>
        <div class="price"><span class="symbol">¥</span><span class="amount">59</span><span class="period">/月</span></div>
        <ul class="features">
          <li>✨ 无限 AI 生成</li><li>📚 创建并发布作品</li><li>🌐 作品圈互动</li><li>🎨 高级排版</li><li>⚡ 优先队列</li>
        </ul>
        <button class="btn-pay" :disabled="paying">
          <span v-if="paying && currentPlan === 'monthly'" class="spinner-white"></span>
          {{ paying && currentPlan === 'monthly' ? '获取中...' : '¥59 立即开通' }}
        </button>
      </div>

      <div class="price-card highlight">
        <div class="card-ribbon">🔥 推荐</div>
        <h3>季度会员</h3>
        <div class="price"><span class="symbol">¥</span><span class="amount">149</span><span class="period">/季</span></div>
        <div class="save-tag">省 ¥28 · 约 ¥49.67/月</div>
        <ul class="features">
          <li>✨ 月度全部特权</li><li>📚 无限制发布</li><li>🌐 优先曝光</li><li>🎨 高级排版</li><li>⚡ 极速队列</li>
        </ul>
        <button class="btn-pay btn-highlight" @click="handlePay('quarterly')" :disabled="paying">
          <span v-if="paying && currentPlan === 'quarterly'" class="spinner-white"></span>
          {{ paying && currentPlan === 'quarterly' ? '获取中...' : '¥149 立即开通' }}
        </button>
      </div>

      <div class="price-card" @click="handlePay('yearly')">
        <h3>年度会员</h3>
        <div class="price"><span class="symbol">¥</span><span class="amount">499</span><span class="period">/年</span></div>
        <div class="save-tag">省 ¥209 · 约 ¥41.58/月</div>
        <ul class="features">
          <li>✨ 全年全部特权</li><li>📚 无限创作</li><li>🌐 首页推荐</li><li>🎨 年度徽章</li><li>⚡ 超优先级</li>
        </ul>
        <button class="btn-pay" :disabled="paying">
          <span v-if="paying && currentPlan === 'yearly'" class="spinner-white"></span>
          {{ paying && currentPlan === 'yearly' ? '获取中...' : '¥499 立即开通' }}
        </button>
      </div>
    </div>

    <div v-if="loading" class="loading"><span class="spinner"></span> 加载中...</div>

    <div v-if="!loading && errorMsg" class="vip-card" style="text-align:center;padding:40px">
      <p style="color:#f87171;margin-bottom:12px">{{ errorMsg }}</p>
      <a href="/login" style="color:#06b6d4;font-size:14px">请先登录</a>
    </div>
  </div>
</template>

<script>
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import api from '../api'

export default {
  name: 'VIP',
  setup() {
    const router = useRouter()
    const route = useRoute()
    const isVip = ref(false)
    const vipExpireAt = ref(null)
    const loading = ref(true)
    const paying = ref(false)
    const currentPlan = ref('')
    const errorMsg = ref('')

    const checkStatus = async () => {
      loading.value = true; errorMsg.value = ''
      try {
        const res = await api.get('/vip/status')
        if (res.状态码 === 200) { isVip.value = res.数据.is_vip; vipExpireAt.value = res.数据.vip_expire_at }
        else errorMsg.value = res.消息 || '获取状态失败'
      } catch (e) { errorMsg.value = '请先登录'; if (e.response?.status === 401) window.location.href = '/login' }
      finally { loading.value = false }
    }

    const handlePay = async (planType) => {
      paying.value = true; currentPlan.value = planType
      try {
        const res = await api.post('/vip/create-order', { plan_type: planType })
        if (res.状态码 === 200 && res.数据.pay_url) {
          window.location.href = res.数据.pay_url
        } else alert(res.消息 || '创建订单失败')
      } catch (e) { alert('网络错误，请重试') }
      finally { paying.value = false }
    }

    // 支付宝支付完成后同步跳回时，URL 会带 out_trade_no 参数
    const confirmFromUrl = async () => {
      const outTradeNo = route.query.out_trade_no
      if (!outTradeNo) return
      try {
        const res = await api.post(`/vip/confirm/${outTradeNo}`)
        if (res.状态码 === 200) {
          // 1. 刷新 VIP 状态
          await checkStatus()
          // 2. 刷新 localStorage 中的用户信息（同步 VIP 状态到全站）
          try {
            const meRes = await api.get('/auth/me')
            if (meRes.状态码 === 200) {
              localStorage.setItem('novel_user', JSON.stringify(meRes.数据))
              // 派发事件让其他页面感知
              window.dispatchEvent(new Event('user-info-changed'))
            }
          } catch {}
        }
      } catch (e) { }
    }

    onMounted(async () => {
      if (!localStorage.getItem('novel_user')) { loading.value = false; errorMsg.value = '请先登录'; return }
      // 先确认URL参数（支付宝同步回调），再查状态
      await confirmFromUrl()
      if (!isVip.value) await checkStatus()
    })

    return { isVip, vipExpireAt, loading, paying, currentPlan, errorMsg, handlePay, checkStatus }
  }
}
</script>

<style scoped>
.vip-page { max-width: 1100px; margin: 0 auto }
.vip-hero { text-align: center; margin-bottom: 36px; position: relative; padding: 40px 0 20px }
.hero-glow { position: absolute; top: -40px; left: 50%; transform: translateX(-50%); width: 300px; height: 300px; background: radial-gradient(circle, var(--accent-glow), transparent); pointer-events: none }
.vip-hero h1 { font-size: 28px; color: var(--text-primary); position: relative; z-index: 1; margin-bottom: 8px }
.hero-sub { color: var(--text-secondary); font-size: 14px }

.loading { display: flex; gap: 10px; align-items: center; justify-content: center; padding: 80px 0; color: var(--text-secondary) }
.spinner { width: 20px; height: 20px; border: 2px solid rgba(6,182,212,0.2); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; display: inline-block }
@keyframes spin { to { transform: rotate(360deg) } }

.vip-card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 18px; padding: 40px 48px; backdrop-filter: blur(20px); box-shadow: var(--card-shadow) }
.already-vip { text-align: center; padding: 60px 48px }
.already-vip h2 { color: var(--accent); font-size: 22px; margin-bottom: 8px }
.already-vip p { color: var(--text-secondary); font-size: 14px; margin-bottom: 4px }
.vip-badge { display: inline-block; padding: 6px 20px; border-radius: 20px; background: linear-gradient(135deg, rgba(6,182,212,0.2), rgba(139,92,246,0.2)); color: var(--accent); font-size: 13px; font-weight: 600; margin-bottom: 16px; border: 1px solid var(--accent-glow) }

.vip-cards { display: flex; gap: 20px; justify-content: center; align-items: stretch }
.price-card { flex: 1; max-width: 340px; background: var(--bg-card); border: 1px solid var(--border); border-radius: 18px; padding: 28px 22px; backdrop-filter: blur(20px); text-align: center; position: relative; overflow: hidden; cursor: pointer; box-shadow: var(--card-shadow); transition: all 0.3s; display: flex; flex-direction: column }
.price-card:hover { border-color: var(--border-hover); transform: translateY(-4px); box-shadow: var(--card-shadow-hover) }
.price-card.highlight { border-color: var(--border-focus); box-shadow: var(--card-shadow), 0 0 50px var(--accent-glow); transform: scale(1.03) }
.price-card.highlight:hover { transform: scale(1.03) translateY(-4px) }

.card-ribbon { position: absolute; top: 12px; right: -28px; transform: rotate(45deg); background: var(--gold-gradient); color: #fff; padding: 3px 36px; font-size: 10px; font-weight: 700 }
.price-card h3 { font-size: 15px; color: var(--text-primary); margin: 0 0 10px; font-weight: 600 }
.price { margin-bottom: 6px }
.symbol { font-size: 18px; color: var(--accent); vertical-align: top; font-weight: 600 }
.amount { font-size: 40px; color: var(--text-primary); font-weight: 800; line-height: 1 }
.period { font-size: 13px; color: var(--text-muted) }
.save-tag { font-size: 11px; color: var(--gold); background: rgba(245,158,11,0.1); padding: 2px 10px; border-radius: 10px; display: inline-block; margin-bottom: 14px }
.features { list-style: none; padding: 0; margin: 0 0 20px; text-align: left; flex: 1 }
.features li { padding: 5px 0; color: var(--text-secondary); font-size: 12px }

.btn-pay { width: 100%; padding: 10px; border-radius: 8px; border: none; cursor: pointer; font-size: 14px; font-weight: 700; color: var(--btn-text); background: var(--btn-bg); border: 1px solid var(--btn-border); transition: all 0.3s; display: flex; align-items: center; justify-content: center; gap: 8px }
.btn-pay:hover:not(:disabled) { background: rgba(6,182,212,0.15) }
.btn-highlight { background: var(--brand-gradient); color: #fff; border: none; box-shadow: 0 4px 24px var(--accent-glow) }
.btn-pay:disabled { opacity: 0.6; cursor: not-allowed }
.spinner-white { width: 14px; height: 14px; border: 2px solid rgba(255,255,255,0.3); border-top-color: #fff; border-radius: 50%; animation: spin 0.8s linear infinite; display: inline-block }
</style>

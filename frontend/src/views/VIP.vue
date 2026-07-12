<template>
  <div class="vip-page">
    <div class="vip-hero">
      <div class="hero-glow"></div>
      <h1>💎 开通会员</h1>
      <p class="hero-sub">解锁全部功能，畅享 AI 创作体验</p>
    </div>

    <!-- 已开通会员 -->
    <div v-if="!loading && isVip" class="vip-card already-vip">
      <div class="vip-badge" :class="isSvip ? 'svip-badge' : ''">{{ isSvip ? '👑 已开通' : '✨ 已开通' }}</div>
      <h2>您已是 {{ isSvip ? 'SVIP' : 'VIP' }} 会员</h2>
      <p v-if="vipExpireAt">到期时间：{{ vipExpireAt }}</p>
      <p>{{ isSvip ? '每日可生成 50 章，畅享极致创作体验' : '每日可生成 10 章，享受 AI 创作特权' }}</p>
      <p v-if="!isSvip" class="upgrade-hint" @click="scrollToSvip">💡 升级 SVIP · 每日 50 章 →</p>
    </div>

    <!-- 套餐卡片 -->
    <div v-if="!loading && !isVip">
      <!-- VIP 专区 -->
      <div class="plan-section">
        <h2 class="section-title">🌟 VIP 会员 · 每日 10 章</h2>
        <div class="vip-cards">
          <div class="price-card" @click="handlePay('vip_monthly')">
            <h3>VIP 月度</h3>
            <div class="price"><span class="symbol">¥</span><span class="amount">59</span><span class="period">/月</span></div>
            <ul class="features">
              <li>✨ 10章/天 AI生成</li><li>📚 创建并发布作品</li><li>🌐 作品圈互动</li><li>🎨 高级排版</li><li>⚡ 优先队列</li>
            </ul>
            <button class="btn-pay" :disabled="paying">
              {{ paying && currentPlan === 'vip_monthly' ? '获取中...' : '¥59 开通' }}
            </button>
          </div>
          <div class="price-card highlight">
            <div class="card-ribbon">🔥 推荐</div>
            <h3>VIP 季度</h3>
            <div class="price"><span class="symbol">¥</span><span class="amount">79</span><span class="period">/季</span></div>
            <div class="save-tag">省 ¥8 · 约 ¥26.33/月</div>
            <ul class="features">
              <li>✨ 月度全部特权</li><li>📚 无限制发布</li><li>🌐 优先曝光</li><li>🎨 高级排版</li><li>⚡ 极速队列</li>
            </ul>
            <button class="btn-pay btn-highlight" @click="handlePay('vip_quarterly')" :disabled="paying">
              {{ paying && currentPlan === 'vip_quarterly' ? '获取中...' : '¥79 开通' }}
            </button>
          </div>
          <div class="price-card" @click="handlePay('vip_yearly')">
            <h3>VIP 年度</h3>
            <div class="price"><span class="symbol">¥</span><span class="amount">259</span><span class="period">/年</span></div>
            <div class="save-tag">省 ¥89 · 约 ¥21.58/月</div>
            <ul class="features">
              <li>✨ 全年全部特权</li><li>📚 无限创作</li><li>🌐 首页推荐</li><li>🎨 年度徽章</li><li>⚡ 超优先级</li>
            </ul>
            <button class="btn-pay" :disabled="paying">
              {{ paying && currentPlan === 'vip_yearly' ? '获取中...' : '¥259 开通' }}
            </button>
          </div>
        </div>
      </div>

      <!-- SVIP 专区 -->
      <div class="plan-section" id="svip-section">
        <h2 class="section-title svip-title">👑 SVIP 会员 · 每日 50 章</h2>
        <div class="vip-cards">
          <div class="price-card svip-card" @click="handlePay('svip_monthly')">
            <h3>SVIP 月度</h3>
            <div class="price"><span class="symbol">¥</span><span class="amount">79</span><span class="period">/月</span></div>
            <ul class="features">
              <li>👑 50章/天 AI生成</li><li>📚 无限创作发布</li><li>🌐 首页推荐曝光</li><li>🎨 专属徽章</li><li>⚡ 极速优先队列</li>
            </ul>
            <button class="btn-pay btn-svip" :disabled="paying">
              {{ paying && currentPlan === 'svip_monthly' ? '获取中...' : '¥79 开通' }}
            </button>
          </div>
          <div class="price-card svip-card highlight-svip" @click="handlePay('svip_quarterly')">
            <div class="card-ribbon ribbon-svip">👑 超值</div>
            <h3>SVIP 季度</h3>
            <div class="price"><span class="symbol">¥</span><span class="amount">149</span><span class="period">/季</span></div>
            <div class="save-tag">省 ¥28 · 约 ¥49.67/月</div>
            <ul class="features">
              <li>👑 月度全特权</li><li>📚 无限制创作</li><li>🌐 优先推荐</li><li>🎨 专属徽章</li><li>⚡ 闪电队列</li>
            </ul>
            <button class="btn-pay btn-svip-highlight" @click="handlePay('svip_quarterly')" :disabled="paying">
              {{ paying && currentPlan === 'svip_quarterly' ? '获取中...' : '¥149 开通' }}
            </button>
          </div>
          <div class="price-card svip-card" @click="handlePay('svip_yearly')">
            <h3>SVIP 年度</h3>
            <div class="price"><span class="symbol">¥</span><span class="amount">499</span><span class="period">/年</span></div>
            <div class="save-tag">省 ¥209 · 约 ¥41.58/月</div>
            <ul class="features">
              <li>👑 全年全特权</li><li>📚 无限创作</li><li>🌐 首页推荐</li><li>🎨 年度专属徽章</li><li>⚡ 至尊队列</li>
            </ul>
            <button class="btn-pay btn-svip" :disabled="paying">
              {{ paying && currentPlan === 'svip_yearly' ? '获取中...' : '¥499 开通' }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 已有VIP但可升级SVIP -->
    <div v-if="!loading && isVip && !isSvip" class="plan-section" id="svip-section">
      <h2 class="section-title svip-title">👑 升级 SVIP · 每日 50 章</h2>
      <div class="vip-cards">
        <div class="price-card svip-card" @click="handlePay('svip_monthly')">
          <h3>SVIP 月度</h3>
          <div class="price"><span class="symbol">¥</span><span class="amount">79</span><span class="period">/月</span></div>
          <ul class="features"><li>👑 50章/天</li><li>📚 无限创作</li><li>🌐 首页推荐</li><li>🎨 专属徽章</li><li>⚡ 极速队列</li></ul>
          <button class="btn-pay btn-svip" :disabled="paying">{{ paying && currentPlan === 'svip_monthly' ? '获取中...' : '¥79 升级' }}</button>
        </div>
        <div class="price-card svip-card highlight-svip" @click="handlePay('svip_quarterly')">
          <div class="card-ribbon ribbon-svip">👑 超值</div>
          <h3>SVIP 季度</h3>
          <div class="price"><span class="symbol">¥</span><span class="amount">149</span><span class="period">/季</span></div>
          <ul class="features"><li>👑 50章/天</li><li>📚 无限创作</li><li>🌐 优先推荐</li><li>🎨 专属徽章</li><li>⚡ 闪电队列</li></ul>
          <button class="btn-pay btn-svip-highlight" :disabled="paying">{{ paying && currentPlan === 'svip_quarterly' ? '获取中...' : '¥149 升级' }}</button>
        </div>
        <div class="price-card svip-card" @click="handlePay('svip_yearly')">
          <h3>SVIP 年度</h3>
          <div class="price"><span class="symbol">¥</span><span class="amount">499</span><span class="period">/年</span></div>
          <ul class="features"><li>👑 50章/天</li><li>📚 无限创作</li><li>🌐 首页推荐</li><li>🎨 专属徽章</li><li>⚡ 至尊队列</li></ul>
          <button class="btn-pay btn-svip" :disabled="paying">{{ paying && currentPlan === 'svip_yearly' ? '获取中...' : '¥499 升级' }}</button>
        </div>
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
    const isSvip = ref(false)
    const vipExpireAt = ref(null)
    const loading = ref(true)
    const paying = ref(false)
    const currentPlan = ref('')
    const errorMsg = ref('')

    const checkStatus = async () => {
      loading.value = true; errorMsg.value = ''
      try {
        const res = await api.get('/vip/status')
        if (res.状态码 === 200) {
          isVip.value = res.数据.is_vip
          isSvip.value = res.数据.is_svip
          vipExpireAt.value = res.数据.vip_expire_at
        } else errorMsg.value = res.消息 || '获取状态失败'
      } catch (e) {
        errorMsg.value = '请先登录'
        if (e.response?.status === 401) window.location.href = '/login'
      } finally { loading.value = false }
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

    const scrollToSvip = () => {
      const el = document.getElementById('svip-section')
      if (el) el.scrollIntoView({ behavior: 'smooth' })
    }

    const confirmFromUrl = async () => {
      const outTradeNo = route.query.out_trade_no
      if (!outTradeNo) return
      try {
        const res = await api.post(`/vip/confirm/${outTradeNo}`)
        if (res.状态码 === 200) {
          await checkStatus()
          try {
            const meRes = await api.get('/auth/me')
            if (meRes.状态码 === 200) {
              localStorage.setItem('novel_user', JSON.stringify(meRes.数据))
              window.dispatchEvent(new Event('user-info-changed'))
            }
          } catch {}
        }
      } catch (e) { }
    }

    onMounted(async () => {
      if (!localStorage.getItem('novel_user')) { loading.value = false; errorMsg.value = '请先登录'; return }
      await confirmFromUrl()
      if (!isVip.value) await checkStatus()
    })

    return { isVip, isSvip, vipExpireAt, loading, paying, currentPlan, errorMsg, handlePay, checkStatus, scrollToSvip }
  }
}
</script>

<style scoped>
.vip-page { max-width: 1100px; margin: 0 auto }
.vip-hero { text-align: center; margin-bottom: 36px; position: relative; padding: 40px 0 20px }
.hero-glow { position: absolute; top: -40px; left: 50%; transform: translateX(-50%); width: 300px; height: 300px; background: radial-gradient(circle, var(--accent-glow), transparent); pointer-events: none }
.vip-hero h1 { font-size: 28px; color: var(--text-primary); position: relative; z-index: 1; margin-bottom: 8px }
.hero-sub { color: var(--text-secondary); font-size: 14px }

.plan-section { margin-bottom: 48px }
.section-title { text-align: center; font-size: 20px; color: var(--text-primary); margin-bottom: 20px; font-weight: 700 }
.svip-title { color: #f59e0b }

.loading { display: flex; gap: 10px; align-items: center; justify-content: center; padding: 80px 0; color: var(--text-secondary) }
.spinner { width: 20px; height: 20px; border: 2px solid rgba(6,182,212,0.2); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; display: inline-block }
@keyframes spin { to { transform: rotate(360deg) } }

.vip-card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 18px; padding: 40px 48px; backdrop-filter: blur(20px); box-shadow: var(--card-shadow) }
.already-vip { text-align: center; padding: 60px 48px }
.already-vip h2 { color: var(--accent); font-size: 22px; margin-bottom: 8px }
.already-vip p { color: var(--text-secondary); font-size: 14px; margin-bottom: 4px }
.vip-badge { display: inline-block; padding: 6px 20px; border-radius: 20px; background: linear-gradient(135deg, rgba(6,182,212,0.2), rgba(139,92,246,0.2)); color: var(--accent); font-size: 13px; font-weight: 600; margin-bottom: 16px; border: 1px solid var(--accent-glow) }
.svip-badge { background: linear-gradient(135deg, rgba(245,158,11,0.2), rgba(239,68,68,0.2)); color: #f59e0b; border: 1px solid rgba(245,158,11,0.3) }
.upgrade-hint { color: #f59e0b; cursor: pointer; font-size: 14px; margin-top: 12px; text-decoration: underline; transition: color 0.2s }
.upgrade-hint:hover { color: #fbbf24 }

.vip-cards { display: flex; gap: 20px; justify-content: center; align-items: stretch }
.price-card { flex: 1; max-width: 340px; background: var(--bg-card); border: 1px solid var(--border); border-radius: 18px; padding: 28px 22px; backdrop-filter: blur(20px); text-align: center; position: relative; overflow: hidden; cursor: pointer; box-shadow: var(--card-shadow); transition: all 0.3s; display: flex; flex-direction: column }
.price-card:hover { border-color: var(--border-hover); transform: translateY(-4px); box-shadow: var(--card-shadow-hover) }
.price-card.highlight { border-color: var(--border-focus); box-shadow: var(--card-shadow), 0 0 50px var(--accent-glow); transform: scale(1.03) }
.price-card.highlight:hover { transform: scale(1.03) translateY(-4px) }

/* SVIP card styles */
.svip-card { border-color: rgba(245,158,11,0.25); background: linear-gradient(180deg, rgba(245,158,11,0.04), var(--bg-card)) }
.svip-card:hover { border-color: rgba(245,158,11,0.5); box-shadow: 0 0 40px rgba(245,158,11,0.15) }
.highlight-svip { border-color: rgba(245,158,11,0.5); box-shadow: var(--card-shadow), 0 0 60px rgba(245,158,11,0.2); transform: scale(1.03); background: linear-gradient(180deg, rgba(245,158,11,0.08), var(--bg-card)) }
.highlight-svip:hover { transform: scale(1.03) translateY(-4px); box-shadow: 0 0 70px rgba(245,158,11,0.3) }

.card-ribbon { position: absolute; top: 12px; right: -28px; transform: rotate(45deg); background: var(--gold-gradient); color: #fff; padding: 3px 36px; font-size: 10px; font-weight: 700 }
.ribbon-svip { background: linear-gradient(135deg, #f59e0b, #ef4444) }
.price-card h3 { font-size: 15px; color: var(--text-primary); margin: 0 0 10px; font-weight: 600 }
.price { margin-bottom: 6px }
.symbol { font-size: 18px; color: var(--accent); vertical-align: top; font-weight: 600 }
.amount { font-size: 40px; color: var(--text-primary); font-weight: 800; line-height: 1 }
.period { font-size: 13px; color: var(--text-muted) }
.save-tag { font-size: 11px; color: var(--gold); background: rgba(245,158,11,0.1); padding: 2px 10px; border-radius: 10px; display: inline-block; margin-bottom: 14px }
.features { list-style: none; padding: 0; margin: 0 0 20px; text-align: left; flex: 1 }
.features li { padding: 5px 0; color: var(--text-secondary); font-size: 12px }

.btn-pay { width: 100%; padding: 10px; border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: 700; color: var(--btn-text); background: var(--btn-bg); border: 1px solid var(--btn-border); transition: all 0.3s; display: flex; align-items: center; justify-content: center; gap: 8px }
.btn-pay:hover:not(:disabled) { background: rgba(6,182,212,0.15) }
.btn-highlight { background: var(--brand-gradient); color: #fff; border: none; box-shadow: 0 4px 24px var(--accent-glow) }
.btn-pay:disabled { opacity: 0.6; cursor: not-allowed }

/* SVIP buttons */
.btn-svip { background: linear-gradient(135deg, rgba(245,158,11,0.15), rgba(239,68,68,0.1)); border: 1px solid rgba(245,158,11,0.35); color: #f59e0b }
.btn-svip:hover:not(:disabled) { background: linear-gradient(135deg, rgba(245,158,11,0.25), rgba(239,68,68,0.2)) }
.btn-svip-highlight { background: linear-gradient(135deg, #f59e0b, #ef4444); color: #fff; border: none; box-shadow: 0 4px 24px rgba(245,158,11,0.4) }
.btn-svip-highlight:hover:not(:disabled) { box-shadow: 0 4px 30px rgba(245,158,11,0.5) }
</style>

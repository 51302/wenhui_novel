<template>
  <div class="vip-page">
    <div class="vip-hero">
      <div class="hero-glow"></div>
      <h1>💎 开通会员</h1>
      <p class="hero-sub">解锁全部功能，畅享 AI 创作体验</p>
    </div>

    <div v-if="loading" class="loading"><span class="spinner"></span> 加载中...</div>
    <div v-if="!loading && errorMsg" class="vip-card" style="text-align:center;padding:40px">
      <p style="color:#f87171;margin-bottom:12px">{{ errorMsg }}</p>
      <a href="/login" style="color:#06b6d4;font-size:14px">请先登录</a>
    </div>

    <!-- ============================================ -->
    <!-- 已开通会员状态卡片                                -->
    <!-- ============================================ -->
    <div v-if="!loading && !errorMsg && vipLevel >= 1" class="vip-card already-vip" :class="{ 'svip-card-bg': vipLevel >= 2 }">
      <div class="vip-badge" :class="{ 'svip-badge': vipLevel >= 2 }">
        {{ vipLevel >= 2 ? '👑 SVIP 会员' : '✨ VIP 会员' }}
      </div>
      <h2 :style="vipLevel >= 2 ? 'color:#f59e0b' : ''">{{ statusTitle }}</h2>
      <p v-if="vipExpireAt">到期时间：{{ vipExpireAt }}</p>
      <p v-if="vipLevel >= 2">每日可生成 <b>50</b> 章，畅享极致创作体验</p>
      <p v-else>每日可生成 <b>10</b> 章，享受 AI 创作特权</p>
    </div>

    <!-- ============================================ -->
    <!-- VIP 套餐区（有可见套餐时才显示）                  -->
    <!-- ============================================ -->
    <div v-if="!loading && !errorMsg && showVipPlans.length > 0" class="plan-section">
      <h2 class="section-title">🌟 VIP 会员 · 每日 10 章</h2>
      <div class="vip-cards">
        <div v-for="p in showVipPlans" :key="p.key" class="price-card" :class="{ highlight: p.key === 'vip_quarterly' && vipLevel === 0 }" @click="handlePay(p.key)">
          <div v-if="p.key === 'vip_quarterly' && vipLevel === 0" class="card-ribbon">🔥 推荐</div>
          <h3>{{ p.name }}</h3>
          <div class="price"><span class="symbol">¥</span><span class="amount">{{ p.priceNum }}</span><span class="period">{{ p.period }}</span></div>
          <div v-if="p.save" class="save-tag">{{ p.save }}</div>
          <ul class="features">
            <li v-for="f in p.features" :key="f">{{ f }}</li>
          </ul>
          <button class="btn-pay" :class="p.key === 'vip_quarterly' && vipLevel === 0 ? 'btn-highlight' : ''" :disabled="paying">
            {{ paying && currentPlan === p.key ? '获取中...' : '¥' + p.priceNum + ' ' + (vipLevel >= 1 ? '升级' : '开通') }}
          </button>
        </div>
      </div>
    </div>

    <!-- ============================================ -->
    <!-- SVIP 套餐区（有可见套餐时才显示）               -->
    <!-- ============================================ -->
    <div v-if="!loading && !errorMsg && showSvipPlans.length > 0" class="plan-section">
      <h2 class="section-title svip-title">👑 SVIP 会员 · 每日 50 章</h2>
      <div class="vip-cards">
        <div v-for="p in showSvipPlans" :key="p.key" class="price-card svip-card" :class="{ 'highlight-svip': p.key === 'svip_quarterly' }" @click="handlePay(p.key)">
          <div v-if="p.key === 'svip_quarterly'" class="card-ribbon ribbon-svip">👑 超值</div>
          <h3>{{ p.name }}</h3>
          <div class="price"><span class="symbol">¥</span><span class="amount">{{ p.priceNum }}</span><span class="period">{{ p.period }}</span></div>
          <div v-if="p.save" class="save-tag">{{ p.save }}</div>
          <ul class="features">
            <li v-for="f in p.features" :key="f">{{ f }}</li>
          </ul>
          <button class="btn-pay" :class="p.key === 'svip_quarterly' ? 'btn-svip-highlight' : 'btn-svip'" :disabled="paying">
            {{ paying && currentPlan === p.key ? '获取中...' : '¥' + p.priceNum + ' ' + (vipLevel >= 1 ? '升级' : '开通') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import api from '../api'

// 所有套餐定义
const ALL_PLANS = {
  vip_monthly:   { key: 'vip_monthly',   name: 'VIP 月度', price: '59.00',  priceNum: 59,  period: '/月', save: '',                 features: ['✨ 10章/天 AI生成','📚 创建并发布作品','🌐 作品圈互动','🎨 高级排版','⚡ 优先队列'] },
  vip_quarterly: { key: 'vip_quarterly', name: 'VIP 季度', price: '149.00', priceNum: 149, period: '/季', save: '省 ¥28 · 约 ¥49.67/月', features: ['✨ 月度全部特权','📚 无限制发布','🌐 优先曝光','🎨 高级排版','⚡ 极速队列'] },
  vip_yearly:    { key: 'vip_yearly',    name: 'VIP 年度', price: '499.00', priceNum: 499, period: '/年', save: '省 ¥209 · 约 ¥41.58/月', features: ['✨ 全年全部特权','📚 无限创作','🌐 首页推荐','🎨 年度徽章','⚡ 超优先级'] },
  svip_monthly:   { key: 'svip_monthly',   name: 'SVIP 月度', price: '79.00',  priceNum: 79,  period: '/月', save: '',                 features: ['👑 50章/天 AI生成','📚 无限创作发布','🌐 首页推荐','🎨 专属徽章','⚡ 极速队列'] },
  svip_quarterly: { key: 'svip_quarterly', name: 'SVIP 季度', price: '199.00', priceNum: 199, period: '/季', save: '省 ¥38 · 约 ¥66.33/月', features: ['👑 月度全特权','📚 无限制创作','🌐 优先推荐','🎨 专属徽章','⚡ 闪电队列'] },
  svip_yearly:    { key: 'svip_yearly',    name: 'SVIP 年度', price: '699.00', priceNum: 699, period: '/年', save: '省 ¥249 · 约 ¥58.25/月', features: ['👑 全年全特权','📚 无限创作','🌐 首页推荐','🎨 年度专属徽章','⚡ 至尊队列'] },
}

// 套餐排序 rank
const PLAN_RANK = { vip_monthly: 0, vip_quarterly: 1, vip_yearly: 2, svip_monthly: 3, svip_quarterly: 4, svip_yearly: 5 }
const VIP_KEYS = ['vip_monthly', 'vip_quarterly', 'vip_yearly']
const SVIP_KEYS = ['svip_monthly', 'svip_quarterly', 'svip_yearly']

export default {
  name: 'VIP',
  setup() {
    const route = useRoute()
    const vipLevel = ref(0)
    const isVip = ref(false)
    const isSvip = ref(false)
    const vipExpireAt = ref(null)
    const planType = ref('')
    const loading = ref(true)
    const paying = ref(false)
    const currentPlan = ref('')
    const errorMsg = ref('')

    // 当前套餐的 rank
    const currentRank = computed(() => PLAN_RANK[planType.value] ?? -1)

    // 状态标题
    const statusTitle = computed(() => {
      const map = {
        vip_monthly: '您已是 月度VIP 会员',
        vip_quarterly: '您已是 季度VIP 会员',
        vip_yearly: '您已是 年度VIP 会员',
        svip_monthly: '您已是 月度SVIP 会员',
        svip_quarterly: '您已是 季度SVIP 会员',
        svip_yearly: '您已是 年度SVIP 会员',
      }
      return map[planType.value] || (vipLevel.value >= 2 ? '您已是 SVIP 会员' : '您已是 VIP 会员')
    })

    // 可见的 VIP 套餐（只显示比当前更高的）
    const showVipPlans = computed(() => {
      if (vipLevel.value >= 2) return []  // SVIP 不显示VIP套餐
      return VIP_KEYS
        .filter(k => PLAN_RANK[k] > currentRank.value)
        .map(k => ALL_PLANS[k])
    })

    // 可见的 SVIP 套餐
    const showSvipPlans = computed(() => {
      if (vipLevel.value === 0) {
        // 免费用户：显示全部 SVIP
        return SVIP_KEYS.map(k => ALL_PLANS[k])
      }
      if (vipLevel.value === 1) {
        // VIP 用户：显示全部 SVIP
        return SVIP_KEYS.map(k => ALL_PLANS[k])
      }
      // SVIP 用户：只显示比当前更高的 SVIP
      return SVIP_KEYS
        .filter(k => PLAN_RANK[k] > currentRank.value)
        .map(k => ALL_PLANS[k])
    })

    const checkStatus = async () => {
      loading.value = true; errorMsg.value = ''
      try {
        const res = await api.get('/vip/status')
        if (res.状态码 === 200) {
          vipLevel.value = res.数据.vip_level ?? 0
          isVip.value = res.数据.is_vip
          isSvip.value = res.数据.is_svip
          vipExpireAt.value = res.数据.vip_expire_at
          planType.value = res.数据.plan_type || ''
        } else errorMsg.value = res.消息 || '获取状态失败'
      } catch (e) {
        // 401/网络错误由 axios 拦截器统一处理跳转登录页
        if (e.response?.status !== 401) {
          errorMsg.value = '网络错误，请稍后重试'
        }
      } finally { loading.value = false }
    }

    const handlePay = async (key) => {
      paying.value = true; currentPlan.value = key
      try {
        const res = await api.post('/vip/create-order', { plan_type: key })
        if (res.状态码 === 200 && res.数据.pay_url) {
          window.location.href = res.数据.pay_url
        } else alert(res.消息 || '创建订单失败')
      } catch (e) { alert('网络错误，请重试') }
      finally { paying.value = false }
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
      await checkStatus()
      await confirmFromUrl()
    })

    return { vipLevel, isVip, isSvip, vipExpireAt, planType, loading, paying, currentPlan, errorMsg, statusTitle, showVipPlans, showSvipPlans, handlePay }
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
.svip-title { color: var(--gold) }
.loading { display: flex; gap: 10px; align-items: center; justify-content: center; padding: 80px 0; color: var(--text-secondary) }
.spinner { width: 20px; height: 20px; border: 2px solid var(--accent-bg); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; display: inline-block }
@keyframes spin { to { transform: rotate(360deg) } }
.vip-card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 18px; padding: 40px 48px; backdrop-filter: blur(20px); box-shadow: var(--card-shadow) }
.already-vip { text-align: center; padding: 60px 48px; margin-bottom: 36px }
.already-vip h2 { color: var(--accent); font-size: 22px; margin-bottom: 8px }
.already-vip p { color: var(--text-secondary); font-size: 14px; margin-bottom: 4px }
.already-vip p b { color: #e0e0e0 }
.svip-card-bg { border-color: var(--gold); background: linear-gradient(180deg, rgba(245,158,11,0.05), var(--bg-card)) }
.vip-badge { display: inline-block; padding: 6px 20px; border-radius: 20px; background: linear-gradient(135deg, rgba(6,182,212,0.2), rgba(139,92,246,0.2)); color: var(--accent); font-size: 13px; font-weight: 600; margin-bottom: 16px; border: 1px solid var(--accent-glow) }
.svip-badge { background: linear-gradient(135deg, rgba(245,158,11,0.2), rgba(239,68,68,0.2)); color: var(--gold); border: 1px solid var(--gold) }

.vip-cards { display: flex; gap: 20px; justify-content: center; align-items: stretch; flex-wrap: wrap }
.price-card { flex: 1; min-width: 280px; max-width: 340px; background: var(--bg-card); border: 1px solid var(--border); border-radius: 18px; padding: 28px 22px; backdrop-filter: blur(20px); text-align: center; position: relative; overflow: hidden; cursor: pointer; box-shadow: var(--card-shadow); transition: all 0.3s; display: flex; flex-direction: column }
.price-card:hover { border-color: var(--border-hover); transform: translateY(-4px); box-shadow: var(--card-shadow-hover) }
.price-card.highlight { border-color: var(--border-focus); box-shadow: var(--card-shadow), 0 0 50px var(--accent-glow); transform: scale(1.03) }
.price-card.highlight:hover { transform: scale(1.03) translateY(-4px) }
.svip-card { border-color: var(--gold); background: linear-gradient(180deg, rgba(245,158,11,0.04), var(--bg-card)) }
.svip-card:hover { border-color: var(--gold); box-shadow: 0 0 40px rgba(245,158,11,0.15) }
.highlight-svip { border-color: var(--gold); box-shadow: var(--card-shadow), 0 0 60px rgba(245,158,11,0.2); transform: scale(1.03); background: linear-gradient(180deg, rgba(245,158,11,0.08), var(--bg-card)) }
.highlight-svip:hover { transform: scale(1.03) translateY(-4px); box-shadow: 0 0 70px rgba(245,158,11,0.3) }
.card-ribbon { position: absolute; top: 12px; right: -28px; transform: rotate(45deg); background: var(--gold-gradient); color: #fff; padding: 3px 36px; font-size: 10px; font-weight: 700 }
.ribbon-svip { background: linear-gradient(135deg, #f59e0b, #ef4444) }
.price-card h3 { font-size: 15px; color: var(--text-primary); margin: 0 0 10px; font-weight: 600 }
.price { margin-bottom: 6px }
.symbol { font-size: 18px; color: var(--accent); vertical-align: top; font-weight: 600 }
.svip-card .symbol { color: var(--gold) }
.amount { font-size: 40px; color: var(--text-primary); font-weight: 800; line-height: 1 }
.period { font-size: 13px; color: var(--text-muted) }
.save-tag { font-size: 11px; color: var(--gold); background: var(--warning-bg); padding: 2px 10px; border-radius: 10px; display: inline-block; margin-bottom: 14px }
.features { list-style: none; padding: 0; margin: 0 0 20px; text-align: left; flex: 1 }
.features li { padding: 5px 0; color: var(--text-secondary); font-size: 12px }
.btn-pay { width: 100%; padding: 10px; border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: 700; color: var(--btn-text); background: var(--btn-bg); border: 1px solid var(--btn-border); transition: all 0.3s; display: flex; align-items: center; justify-content: center; gap: 8px }
.btn-pay:hover:not(:disabled) { background: var(--accent-bg) }
.btn-highlight { background: var(--brand-gradient); color: #fff; border: none; box-shadow: 0 4px 24px var(--accent-glow) }
.btn-pay:disabled { opacity: 0.6; cursor: not-allowed }
.btn-svip { background: linear-gradient(135deg, rgba(245,158,11,0.15), rgba(239,68,68,0.1)); border: 1px solid var(--gold); color: var(--gold) }
.btn-svip:hover:not(:disabled) { background: linear-gradient(135deg, rgba(245,158,11,0.25), rgba(239,68,68,0.2)) }
.btn-svip-highlight { background: linear-gradient(135deg, #f59e0b, #ef4444); color: #fff; border: none; box-shadow: 0 4px 24px rgba(245,158,11,0.4) }
.btn-svip-highlight:hover:not(:disabled) { box-shadow: 0 4px 30px rgba(245,158,11,0.5) }
</style>
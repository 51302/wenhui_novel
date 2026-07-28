/**
 * 主题 Store — localStorage 持久化的全局主题管理
 * 用法: import { useTheme } from '../stores/themeStore'
 *       const { theme, setTheme } = useTheme()
 */
import { ref, watch } from 'vue'

const THEMES = [
  { key: 'purple', label: '星空紫',   desc: '青紫渐变·深邃科技' },
  { key: 'blue',   label: '蓝白科技', desc: '蓝白渐变·极简未来' },
  { key: 'light',  label: '极光白',   desc: '白底蓝调·清爽明亮' },
  { key: 'warm',   label: '暖阳橙',   desc: '暖橙白底·元气活力' },
  { key: 'mint',   label: '薄荷绿',   desc: '清新绿白·自然治愈' },
  { key: 'sakura', label: '樱粉白',   desc: '樱花粉白·温柔甜美' },
  { key: 'green',  label: '蓝绿科技', desc: '青绿渐变·赛博自然' },
  { key: 'gold',   label: '暗夜金',   desc: '琥珀金渐变·低调奢华' },
  { key: 'pink',   label: '赛博粉',   desc: '粉紫渐变·霓虹朋克' },
  { key: 'orange', label: '日落橙',   desc: '橙红渐变·温暖燃烧' },
]

// 全局共享的响应式状态
const currentTheme = ref(loadTheme())

function loadTheme() {
  const saved = localStorage.getItem('novel_theme')
  if (saved && THEMES.find(t => t.key === saved)) return saved
  return 'mint'
}

function setTheme(key) {
  if (!THEMES.find(t => t.key === key)) return
  currentTheme.value = key
  localStorage.setItem('novel_theme', key)
  document.documentElement.setAttribute('data-theme', key)
}

// 初始化
document.documentElement.setAttribute('data-theme', currentTheme.value)

export function useTheme() {
  return {
    theme: currentTheme,
    themes: THEMES,
    setTheme,
  }
}

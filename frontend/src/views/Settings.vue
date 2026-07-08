<template>
  <div class="settings-page">
    <div class="page-hero">
      <h1>⚙️ 系统设置</h1>
      <p>自定义界面外观及其他偏好</p>
    </div>

    <!-- ===== 主题色调 ===== -->
    <section class="settings-section scan-line">
      <div class="section-header">
        <div class="section-icon">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
        </div>
        <div>
          <h2>主题色调</h2>
          <span class="section-desc">选择你喜欢的界面配色方案</span>
        </div>
      </div>

      <div class="theme-grid">
        <div
          v-for="t in themes"
          :key="t.key"
          class="theme-card"
          :class="{ active: theme === t.key }"
          @click="setTheme(t.key)"
        >
          <!-- 预览色块 -->
          <div class="theme-preview" :class="'preview-' + t.key">
            <div class="preview-bar"></div>
            <div class="preview-body">
              <div class="preview-block" v-for="i in 3" :key="i"></div>
            </div>
          </div>

          <div class="theme-info">
            <h3>{{ t.label }}</h3>
            <p>{{ t.desc }}</p>
          </div>

          <div class="theme-check" v-if="theme === t.key">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>
          </div>
        </div>
      </div>
    </section>

    <!-- ===== 当前配色预览 ===== -->
    <section class="settings-section">
      <div class="section-header">
        <div class="section-icon" style="background:var(--brand-gradient)">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/></svg>
        </div>
        <div>
          <h2>当前配色方案预览</h2>
          <span class="section-desc">实时查看选中主题的视觉效果</span>
        </div>
      </div>

      <div class="color-palette">
        <div class="color-item">
          <div class="color-dot" :style="{ background: 'var(--brand-gradient)' }"></div>
          <span>品牌渐变</span>
        </div>
        <div class="color-item">
          <div class="color-dot" :style="{ background: 'var(--accent)' }"></div>
          <span>强调色</span>
        </div>
        <div class="color-item">
          <div class="color-dot" :style="{ background: 'var(--secondary)' }"></div>
          <span>辅助色</span>
        </div>
        <div class="color-item">
          <div class="color-dot" :style="{ background: 'var(--bg-card)' }"></div>
          <span>卡片背景</span>
        </div>
        <div class="color-item">
          <div class="color-dot" :style="{ background: 'var(--text-primary)' }"></div>
          <span>主文字</span>
        </div>
      </div>

      <!-- 按钮预览 -->
      <div class="preview-buttons">
        <button class="preview-btn-primary">主要按钮</button>
        <button class="preview-btn-outline">次要按钮</button>
        <div class="preview-tag">标签</div>
      </div>
    </section>

    <!-- ===== 视觉效果开关 ===== -->
    <section class="settings-section">
      <div class="section-header">
        <div class="section-icon">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
        </div>
        <div>
          <h2>视觉效果</h2>
          <span class="section-desc">控制页面动画和装饰效果</span>
        </div>
      </div>

      <div class="toggle-list">
        <div class="toggle-item">
          <div class="toggle-info">
            <span class="toggle-label">星空粒子背景</span>
            <span class="toggle-desc">页面背景动态星云装饰</span>
          </div>
          <label class="switch">
            <input type="checkbox" v-model="effects.stars" checked>
            <span class="slider"></span>
          </label>
        </div>
        <div class="toggle-item">
          <div class="toggle-info">
            <span class="toggle-label">科技网格背景</span>
            <span class="toggle-desc">底层网格科技感纹理</span>
          </div>
          <label class="switch">
            <input type="checkbox" v-model="effects.grid" checked>
            <span class="slider"></span>
          </label>
        </div>
        <div class="toggle-item">
          <div class="toggle-info">
            <span class="toggle-label">底部呼吸灯</span>
            <span class="toggle-desc">页面底部渐变装饰线</span>
          </div>
          <label class="switch">
            <input type="checkbox" v-model="effects.bottomLine" checked>
            <span class="slider"></span>
          </label>
        </div>
      </div>
    </section>
  </div>
</template>

<script>
import { ref } from 'vue'
import { useTheme } from '../stores/themeStore'

export default {
  name: 'Settings',
  setup() {
    const { theme, themes, setTheme } = useTheme()

    const effects = ref({
      stars: true,
      grid: true,
      bottomLine: true,
    })

    return { theme, themes, setTheme, effects }
  }
}
</script>

<style scoped>
.settings-page { max-width: 800px; margin: 0 auto; }

.page-hero {
  text-align: center; margin-bottom: 40px; padding: 30px 0 10px;
  position: relative;
}
.page-hero h1 { font-size: 26px; color: var(--text-primary); margin-bottom: 6px; }
.page-hero p { color: var(--text-secondary); font-size: 14px; }

/* ===== Section ===== */
.settings-section {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 18px; padding: 32px; margin-bottom: 24px;
  box-shadow: var(--card-shadow); backdrop-filter: blur(20px);
}
.section-header {
  display: flex; align-items: center; gap: 16px; margin-bottom: 24px;
}
.section-icon {
  width: 42px; height: 42px; border-radius: 12px;
  background: var(--btn-bg); border: 1px solid var(--border);
  display: flex; align-items: center; justify-content: center;
  color: var(--accent); flex-shrink: 0;
}
.section-header h2 { font-size: 17px; color: var(--text-primary); margin-bottom: 2px; }
.section-desc { font-size: 12px; color: var(--text-muted); }

/* ===== 主题卡片 ===== */
.theme-grid { display: flex; gap: 16px; }
.theme-card {
  flex: 1; background: var(--bg-card-hover); border: 2px solid var(--border);
  border-radius: 16px; padding: 20px; cursor: pointer;
  position: relative; overflow: hidden;
  transition: all 0.35s;
}
.theme-card:hover { border-color: var(--border-hover); box-shadow: var(--card-shadow-hover); }
.theme-card.active {
  border-color: var(--accent); box-shadow: 0 0 30px var(--accent-glow);
}

.theme-preview {
  width: 100%; height: 80px; border-radius: 10px; margin-bottom: 14px;
  overflow: hidden; display: flex; flex-direction: column;
}
.preview-purple {
  background: linear-gradient(135deg, #0a0a1a, #1a1040);
}
.preview-purple .preview-bar { background: linear-gradient(135deg, #06b6d4, #8b5cf6); }
.preview-purple .preview-block { background: rgba(6,182,212,0.15); }

.preview-blue {
  background: linear-gradient(135deg, #060a18, #101830);
}
.preview-blue .preview-bar { background: linear-gradient(135deg, #3b82f6, #60a5fa); }
.preview-blue .preview-block { background: rgba(59,130,246,0.15); }

.preview-green {
  background: linear-gradient(135deg, #050f14, #08181c);
}
.preview-green .preview-bar { background: linear-gradient(135deg, #06b6d4, #10b981); }
.preview-green .preview-block { background: rgba(16,185,129,0.15); }

.preview-gold {
  background: linear-gradient(135deg, #0d0b08, #1a1206);
}
.preview-gold .preview-bar { background: linear-gradient(135deg, #f59e0b, #d97706); }
.preview-gold .preview-block { background: rgba(245,158,11,0.15); }

.preview-pink {
  background: linear-gradient(135deg, #0f0518, #1a0830);
}
.preview-pink .preview-bar { background: linear-gradient(135deg, #ec4899, #a855f7); }
.preview-pink .preview-block { background: rgba(236,72,153,0.15); }

.preview-orange {
  background: linear-gradient(135deg, #0f0806, #1a0a06);
}
.preview-orange .preview-bar { background: linear-gradient(135deg, #f97316, #ef4444); }
.preview-orange .preview-block { background: rgba(249,115,22,0.15); }

.preview-bar { height: 12px; }
.preview-body { flex: 1; display: flex; gap: 6px; padding: 10px; }
.preview-block { flex: 1; border-radius: 4px; }

.theme-info h3 { font-size: 14px; color: var(--text-primary); margin-bottom: 2px; }
.theme-info p { font-size: 11px; color: var(--text-muted); }

.theme-check {
  position: absolute; top: 12px; right: 12px;
  width: 28px; height: 28px; border-radius: 50%;
  background: var(--success-gradient); color: #fff;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 0 12px rgba(16,185,129,0.4);
}

/* ===== 色板 ===== */
.color-palette { display: flex; gap: 20px; flex-wrap: wrap; margin-bottom: 24px; }
.color-item { display: flex; align-items: center; gap: 10px; }
.color-dot { width: 36px; height: 36px; border-radius: 10px; border: 2px solid var(--border); }
.color-item span { font-size: 13px; color: var(--text-secondary); }

.preview-buttons { display: flex; align-items: center; gap: 12px; }
.preview-btn-primary {
  padding: 10px 24px; border-radius: 8px; border: none; cursor: pointer;
  font-size: 13px; font-weight: 700; color: #fff;
  background: var(--brand-gradient); box-shadow: 0 4px 16px var(--accent-glow);
}
.preview-btn-outline {
  padding: 10px 24px; border-radius: 8px; cursor: pointer;
  font-size: 13px; font-weight: 700; color: var(--accent);
  background: transparent; border: 1px solid var(--border-hover);
}
.preview-tag {
  padding: 6px 16px; border-radius: 8px; font-size: 12px; font-weight: 700;
  background: var(--btn-bg); color: var(--accent); border: 1px solid var(--border);
}

/* ===== Toggle 开关 ===== */
.toggle-list { display: flex; flex-direction: column; gap: 16px; }
.toggle-item {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 16px; background: var(--bg-card-hover); border-radius: 12px;
  border: 1px solid var(--border);
}
.toggle-label { font-size: 14px; color: var(--text-primary); display: block; font-weight: 600; }
.toggle-desc { font-size: 12px; color: var(--text-muted); margin-top: 2px; display: block; }

.switch { position: relative; width: 48px; height: 28px; display: inline-block; }
.switch input { opacity: 0; width: 0; height: 0; }
.slider {
  position: absolute; cursor: pointer; inset: 0;
  background: rgba(100,100,150,0.3); border-radius: 14px;
  transition: all 0.3s;
}
.slider::before {
  content: ''; position: absolute; width: 22px; height: 22px;
  left: 3px; bottom: 3px; background: #fff; border-radius: 50%;
  transition: all 0.3s;
}
.switch input:checked + .slider {
  background: var(--brand-gradient);
}
.switch input:checked + .slider::before {
  transform: translateX(20px);
}
</style>

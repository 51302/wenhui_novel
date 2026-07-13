<template>
  <div class="creation-page">
    <h2 class="page-title">创作中心</h2>

    <!-- 会员等级 & 今日发布统计 -->
    <div :class="['quota-banner', 'level-' + vipLevel]">
      <div class="quota-level">
        <span class="level-badge">{{ levelLabel }}</span>
        <span class="level-desc">{{ levelDesc }}</span>
      </div>
      <div class="quota-progress">
        <div class="quota-bar-bg">
          <div class="quota-bar-fill" :style="{ width: quotaPercent + '%' }"></div>
        </div>
        <span class="quota-text">📝 今日已发布 <b>{{ publishedToday }}</b>/<b>{{ maxDailyQuota }}</b> 章{{ quotaRemaining > 0 ? ' · 还可发布 ' + quotaRemaining + ' 章' : ' · 已用完' }}</span>
      </div>
      <router-link v-if="vipLevel === 0" to="/vip" class="quota-action">✨ 升级VIP · 10章/天</router-link>
      <router-link v-if="vipLevel === 1" to="/vip" class="quota-action gold">👑 升级SVIP · 50章/天</router-link>
    </div>

    <!-- Tab 切换 -->
    <div class="tabs">
      <span :class="{ active: tab === 'create' }" @click="tab = 'create'">新建作品</span>
      <span :class="{ active: tab === 'my' }" @click="fetchMyNovels(); tab = 'my'">我的作品</span>
      <span :class="{ active: tab === 'drafts' }" @click="fetchDrafts(); tab = 'drafts'">草稿列表</span>
    </div>

    <!-- ==================== 新建作品 ==================== -->
    <div v-if="tab === 'create'" class="tab-content">
      <form class="create-form" @submit.prevent="handleCreateNovel">
        <div class="form-row">
          <label>作品名称</label><input v-model="novelForm.title" required />
        </div>
        <div class="form-row">
          <label>封面图片</label>
          <div class="image-upload">
            <div v-if="novelForm.cover_image" class="preview">
              <img :src="novelForm.cover_image" alt="封面预览" @error="novelForm.cover_image = ''" />
              <button type="button" class="btn-remove" @click="removeCover">删除</button>
            </div>
            <input v-else type="file" accept="image/*" @change="handleCoverUpload" />
          </div>
        </div>
        <div class="form-row">
          <label>目标读者</label>
          <select v-model="novelForm.target_reader" required>
            <option value="">请选择</option><option value="男频">男频</option><option value="女频">女频</option>
          </select>
        </div>
        <div class="form-row">
          <label>标签/题材</label>
          <div class="genre-select">
            <div v-for="genre in genreOptions" :key="genre" 
                 :class="['genre-tag', { active: selectedGenres.includes(genre) }]"
                 @click="toggleGenre(genre)">
              {{ genre }}
            </div>
          </div>
        </div>
        <div class="form-row">
          <label>作品简介 <span class="char-count" :class="{ over: novelForm.description.length > 600 }">{{ novelForm.description.length }}/600</span></label>
          <textarea v-model="novelForm.description" rows="4" :class="{ over: novelForm.description.length > 600 }" placeholder="不超过600字" />
          <p v-if="novelForm.description.length > 600" class="field-error">作品简介不能超过600字</p>
        </div>
        <div class="form-row">
          <label>故事背景</label><textarea v-model="novelForm.story_background" rows="3" />
        </div>
        <div class="form-row">
          <label>世界观设定</label><textarea v-model="novelForm.world_setting" rows="3" />
        </div>
        <div class="form-row">
          <label>境界设定</label>
          <div class="realm-list">
            <div v-for="(realm, ri) in novelForm.realms" :key="ri" class="realm-item">
              <input v-model="realm.name" placeholder="体系名称(如：A体系)" />
              <textarea v-model="realm.value" placeholder="该体系的境界设定" rows="2" />
              <button type="button" class="btn-remove" @click="novelForm.realms.splice(ri, 1)">删除</button>
            </div>
            <button type="button" class="btn-add" @click="novelForm.realms.push({ name: '', value: '' })">+ 添加境界体系</button>
          </div>
        </div>

        <!-- 角色管理 -->
        <div class="form-row">
          <label>角色设定</label>
          <div class="char-list">
            <div v-for="(ch, ci) in novelForm.characters" :key="ci" class="char-card">
              <div class="char-header"><strong>角色{{ String.fromCharCode(65+ci) }}</strong><button type="button" class="btn-remove" @click="novelForm.characters.splice(ci, 1)">删除</button></div>
              <div class="char-fields">
                <div class="half"><label>角色名称</label><input v-model="ch.name" /></div>
                <div class="half"><label>性别</label><select v-model="ch.gender"><option value="">请选择</option><option value="男">男</option><option value="女">女</option></select></div>
                <div class="full"><label>角色定位</label><input v-model="ch.position" placeholder="男主，天云宗圣子" /></div>
                <div class="full"><label>角色性格</label><input v-model="ch.personality" /></div>
                <div class="full"><label>角色简介</label><textarea v-model="ch.intro" rows="2" /></div>
                <div class="half"><label>伴侣</label><input v-model="ch.partner" /></div>
                <div class="half"><label>子女</label><input v-model="ch.children" /></div>
                <div class="half"><label>亲人</label><input v-model="ch.relatives" /></div>
                <div class="half"><label>朋友</label><input v-model="ch.friends" /></div>
                <div class="full"><label>弟子</label><input v-model="ch.disciples" /></div>
              </div>
            </div>
            <button type="button" class="btn-add" @click="novelForm.characters.push({ name: '', gender: '', position: '', personality: '', intro: '', partner: '', children: '', relatives: '', friends: '', disciples: '' })">+ 添加角色</button>
          </div>
        </div>

        <p v-if="createError" class="error">{{ createError }}</p>
        <p v-if="createSuccess" class="success">{{ createSuccess }}</p>
        <button type="submit" :disabled="novelForm.description.length > 600">创建作品</button>
      </form>
    </div>

    <!-- ==================== 我的作品 ==================== -->
    <div v-if="tab === 'my'" class="tab-content">
      <div v-if="myNovels.length === 0" class="empty">暂无作品</div>
      <div v-for="novel in myNovels" :key="novel.novel_unique_id" class="my-novel-card">
        <div class="my-novel-cover">
          <img v-if="novel.cover_image" :src="novel.cover_image" alt="封面" @error="novel.cover_image = ''" />
          <span v-if="!novel.cover_image" class="placeholder">文辉小说</span>
        </div>
        <div class="my-novel-info">
          <h3>{{ novel.title }}</h3>
          <p>{{ novel.target_reader }} {{ novel.genre ? "· " + novel.genre : "" }}</p>
          <p class="my-novel-desc">{{ novel.description }}</p>
        </div>
        <div class="my-novel-actions">
          <button @click="openChapterModal(novel)">编辑章节</button>
          <button @click="openEditModal(novel)">编辑作品</button>
          <button class="btn-danger" @click="deleteNovel(novel)">删除作品</button>
        </div>
      </div>

      <!-- 章节管理弹窗 -->
      <div v-if="showChapterModal" class="modal-overlay" @click.self="showChapterModal = false">
        <div class="modal-content chapter-modal">
          <button class="modal-close" @click="showChapterModal = false">&times;</button>
          <h2>{{ chapterNovel.title }} - 章节管理</h2>
          <div class="chapter-form">
            <h3>{{ chapterMode === 'new' ? '新建章节' : '编辑章节' }}</h3>
            <input v-model="chapterForm.chapter_name" placeholder="章节名称" />
            <input v-model="chapterForm.characters_involved" placeholder="涉及人物" />
            <input v-model="chapterForm.organizations" placeholder="涉及组织" />
            <input v-model="chapterForm.locations" placeholder="涉及地点" />
            <input v-model="chapterForm.skills" placeholder="涉及技能" />
            <input v-model.number="chapterForm.word_count" type="number" placeholder="章节字数" />
            <input v-model="chapterForm.chapter_summary" placeholder="本章概要(如：偷袭天道教宗)" />
            <div class="chapter-btns">
              <button class="btn-ai" @click="generateChapter" :disabled="generating">
                <span v-if="generating" class="spinner"></span>
                {{ generating ? '正在生成中...' : '一键AI生成' }}
              </button>
            </div>
          </div>
          <div class="existing-chapters">
            <h3>已有章节</h3>
            <div v-if="novelChapters.length === 0" class="empty">暂无章节</div>
            <div v-for="(ch, idx) in novelChapters" :key="ch.chapter_unique_id" class="chapter-item">
              <span>第{{ idx + 1 }}章 - {{ ch.chapter_name }} ({{ ch.word_count }}字)</span>
              <span class="chapter-status">{{ ch.is_published ? '✓ 已发布' : '草稿' }}</span>
              <button class="btn-delete-chapter" @click="deleteChapter(ch)" title="删除章节">✕ 删除</button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ==================== 编辑作品弹窗 ==================== -->
    <div v-if="showEditModal" class="modal-overlay" @click.self="showEditModal = false">
      <div class="modal-content edit-modal">
        <button class="modal-close" @click="showEditModal = false">&times;</button>
        <h2>编辑作品</h2>
        <form @submit.prevent="handleUpdateNovel">
          <div class="form-row">
            <label>作品名称</label><input v-model="editForm.title" required />
          </div>
          <div class="form-row">
            <label>封面图片</label>
            <div class="image-upload">
              <div v-if="editForm.cover_image" class="preview">
                <img :src="editForm.cover_image" alt="封面预览" @error="editForm.cover_image = ''" />
                <button type="button" class="btn-remove" @click="editForm.cover_image = ''">删除</button>
              </div>
              <input v-else type="file" accept="image/*" @change="handleEditCoverUpload" />
            </div>
          </div>
          <div class="form-row">
            <label>目标读者</label>
            <select v-model="editForm.target_reader" required>
              <option value="">请选择</option><option value="男频">男频</option><option value="女频">女频</option>
            </select>
          </div>
          <div class="form-row">
            <label>标签/题材</label>
            <div class="genre-select">
              <div v-for="genre in genreOptions" :key="genre" 
                   :class="['genre-tag', { active: editSelectedGenres.includes(genre) }]"
                   @click="toggleEditGenre(genre)">
                {{ genre }}
              </div>
            </div>
          </div>
          <div class="form-row">
            <label>作品简介 <span class="char-count" :class="{ over: editForm.description.length > 600 }">{{ editForm.description.length }}/600</span></label>
            <textarea v-model="editForm.description" rows="4" :class="{ over: editForm.description.length > 600 }" placeholder="不超过600字" />
            <p v-if="editForm.description.length > 600" class="field-error">作品简介不能超过600字</p>
          </div>
          <div class="form-row">
            <label>故事背景</label><textarea v-model="editForm.story_background" rows="3" />
          </div>
          <div class="form-row">
            <label>世界观设定</label><textarea v-model="editForm.world_setting" rows="3" />
          </div>
          <p v-if="editError" class="error">{{ editError }}</p>
          <p v-if="editSuccess" class="success">{{ editSuccess }}</p>
          <button type="submit">保存修改</button>
        </form>
      </div>
    </div>

    <!-- ==================== 草稿列表 ==================== -->
    <div v-if="tab === 'drafts'" class="tab-content">
      <div v-if="drafts.length === 0" class="empty">暂无草稿</div>
      <div v-for="d in drafts" :key="d.chapter_unique_id" class="draft-card">
        <div class="draft-header">
          <h3>{{ d.chapter_name }}</h3>
          <span>{{ d.word_count }}字 | {{ formatTime(d.created_at) }}</span>
        </div>
        <div class="draft-content">
          <textarea v-model="d.content" rows="10" />
        </div>
        <!-- AI提取信息面板 -->
        <div class="draft-info-panel">
          <button class="btn-extract" @click="extractDraftInfo(d)" :disabled="extracting[d.chapter_unique_id]">
            <span v-if="extracting[d.chapter_unique_id]" class="spinner"></span>
            {{ extracting[d.chapter_unique_id] ? '正在提取...' : (d._info ? '重新提取信息' : '🔍 AI提取关键信息') }}
          </button>
          <div v-if="d._info" class="info-grid">
            <div class="info-cell" v-if="d._info.人物 || extracting[d.chapter_unique_id]"><label>人物</label><input v-model="d._info.人物" /></div>
            <div class="info-cell" v-if="d._info.组织 || extracting[d.chapter_unique_id]"><label>组织</label><input v-model="d._info.组织" /></div>
            <div class="info-cell" v-if="d._info.功法技能 || extracting[d.chapter_unique_id]"><label>功法技能</label><input v-model="d._info.功法技能" /></div>
            <div class="info-cell" v-if="d._info.关键事件 || extracting[d.chapter_unique_id]"><label>关键事件</label><input v-model="d._info.关键事件" /></div>
            <div class="info-cell" v-if="d._info.地点 || extracting[d.chapter_unique_id]"><label>地点</label><input v-model="d._info.地点" /></div>
            <div class="info-cell" v-if="d._info.时间 || extracting[d.chapter_unique_id]"><label>时间</label><input v-model="d._info.时间" /></div>
            <div class="info-cell" v-if="d._info.关键物品 || extracting[d.chapter_unique_id]"><label>关键物品</label><input v-model="d._info.关键物品" /></div>
            <div class="info-cell" v-if="d._info.实力变化 || extracting[d.chapter_unique_id]"><label>实力变化</label><input v-model="d._info.实力变化" /></div>
            <div class="info-cell" v-if="d._info.伏笔 || extracting[d.chapter_unique_id]"><label>伏笔</label><input v-model="d._info.伏笔" /></div>
          </div>
        </div>
        <div class="draft-actions">
          <button @click="continueChapter(d)" :disabled="continuing[d.chapter_unique_id]">
            <span v-if="continuing[d.chapter_unique_id]" class="spinner"></span>
            {{ continuing[d.chapter_unique_id] ? '正在续写...' : '🤖 AI续写' }}
          </button>
          <button @click="publishChapter(d)">发布章节</button>
          <button class="btn-danger" @click="deleteDraft(d)">删除</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import api from '../api'

export default {
  name: 'Creation',
  setup() {
    const tab = ref('create')

    const user = reactive(JSON.parse(localStorage.getItem('novel_user') || '{}'))
    const isVip = computed(() => !!user.is_vip)
    const isSvip = computed(() => !!user.is_svip)
    const vipLevel = computed(() => user.vip_level ?? 0)
    const freeQuota = computed(() => user.free_generate_quota ?? 0)

    // 今日发布统计
    const publishedToday = ref(0)
    const maxDailyQuota = computed(() => {
      if (vipLevel.value >= 2) return 50
      if (vipLevel.value >= 1) return 10
      return 6
    })
    const quotaRemaining = computed(() => Math.max(0, maxDailyQuota.value - publishedToday.value))
    const quotaPercent = computed(() => Math.min(100, (publishedToday.value / maxDailyQuota.value) * 100))

    const levelLabel = computed(() => {
      if (vipLevel.value >= 2) return '👑 SVIP会员'
      if (vipLevel.value >= 1) return '🌟 VIP会员'
      return '💎 普通用户'
    })
    const levelDesc = computed(() => {
      if (vipLevel.value >= 2) return '每日最多50章'
      if (vipLevel.value >= 1) return '每日最多10章'
      return '免费体验6章/天'
    })

    const fetchTodayPublished = async () => {
      try {
        const res = await api.get('/chapters/today-published-count')
        if (res.状态码 === 200) {
          publishedToday.value = res.数据.published_today
        }
      } catch {}
    }

    // 新建作品
    const novelForm = reactive({
      title: '', target_reader: '', genre: '', description: '',
      story_background: '', world_setting: '', cover_image: '',
      realms: [{ name: '', value: '' }],
      characters: []
    })
    const createError = ref('')
    const createSuccess = ref('')
    
    // 标签选项
    const genreOptions = ['玄幻', '修仙', '都市', '科幻', '历史', '武侠', '悬疑', '游戏', '军事', '竞技', '轻小说', '奇幻', '灵异', '无限流', '末世', '古言', '现言', '穿越', '重生', '总裁', '纯爱', '种田', '宫斗', '宅斗', '女强', '幻想', '清穿', '穿书']
    const selectedGenres = ref([])
    
    // 切换标签选中状态
    const toggleGenre = (genre) => {
      const index = selectedGenres.value.indexOf(genre)
      if (index > -1) {
        selectedGenres.value.splice(index, 1)
      } else {
        selectedGenres.value.push(genre)
      }
      // 更新 novelForm.genre 为逗号分隔的字符串
      novelForm.genre = selectedGenres.value.join(',')
    }

    // 封面图片上传
    const handleCoverUpload = async (event) => {
      const file = event.target.files[0]
      if (!file) return
      if (!file.type.startsWith('image/')) { alert('请选择图片文件'); return }
      if (file.size > 10 * 1024 * 1024) { alert('图片大小不能超过 10MB'); return }

      const formData = new FormData()
      formData.append('file', file)

      try {
        const res = await api.post('/upload/image', formData)
        console.log('[上传响应]', res)
        // 兼容两种返回格式: {success, url} 或 {状态码:200, 数据:{url}}
        const url = res.url || res.数据?.url
        if (url) {
          novelForm.cover_image = url
          console.log('[封面已设置]', url)
        } else {
          alert('上传失败: 未获取到图片地址')
        }
      } catch (e) {
        console.error('[上传失败]', e)
        alert('上传失败: ' + (e.response?.data?.detail || e.message || '网络错误'))
      }
    }

    // 删除封面图片
    const removeCover = () => {
      novelForm.cover_image = ''
    }

    // 编辑作品相关
    const showEditModal = ref(false)
    const editForm = reactive({
      novel_unique_id: '',
      title: '',
      target_reader: '',
      genre: '',
      description: '',
      story_background: '',
      world_setting: '',
      cover_image: ''
    })
    const editSelectedGenres = ref([])
    const editError = ref('')
    const editSuccess = ref('')

    const openEditModal = async (novel) => {
      try {
        const res = await api.get(`/novels/detail/${novel.novel_unique_id}`)
        if (res.状态码 === 200) {
          const data = res.数据
          Object.assign(editForm, {
            novel_unique_id: data.novel_unique_id,
            title: data.title,
            target_reader: data.target_reader,
            genre: data.genre || '',
            description: data.description || '',
            story_background: data.story_background || '',
            world_setting: data.world_setting || '',
            cover_image: data.cover_image || ''
          })
          // 解析标签
          editSelectedGenres.value = data.genre ? data.genre.split(',') : []
          showEditModal.value = true
        }
      } catch (e) {
        alert('获取作品信息失败')
      }
    }

    const toggleEditGenre = (genre) => {
      const index = editSelectedGenres.value.indexOf(genre)
      if (index > -1) {
        editSelectedGenres.value.splice(index, 1)
      } else {
        editSelectedGenres.value.push(genre)
      }
      editForm.genre = editSelectedGenres.value.join(',')
    }

    const handleEditCoverUpload = async (event) => {
      const file = event.target.files[0]
      if (!file) return
      if (!file.type.startsWith('image/')) { alert('请选择图片文件'); return }
      if (file.size > 10 * 1024 * 1024) { alert('图片大小不能超过 10MB'); return }

      const formData = new FormData()
      formData.append('file', file)

      try {
        const res = await api.post('/upload/image', formData)
        console.log('[上传响应-编辑]', res)
        const url = res.url || res.数据?.url
        if (url) {
          editForm.cover_image = url
          console.log('[封面已设置-编辑]', url)
        } else {
          alert('上传失败: 未获取到图片地址')
        }
      } catch (e) {
        console.error('[上传失败-编辑]', e)
        alert('上传失败: ' + (e.response?.data?.detail || e.message || '网络错误'))
      }
    }

    const handleUpdateNovel = async () => {
      editError.value = ''; editSuccess.value = ''
      if (editForm.description.length > 600) {
        editError.value = '作品简介不能超过600字'
        return
      }
      
      try {
        const params = {
          title: editForm.title,
          target_reader: editForm.target_reader,
          genre: editForm.genre,
          description: editForm.description,
          story_background: editForm.story_background,
          world_setting: editForm.world_setting,
          cover_image: editForm.cover_image
        }
        const res = await api.put(`/novels/update/${editForm.novel_unique_id}`, null, { params })
        if (res.状态码 === 200) {
          editSuccess.value = '作品更新成功！'
          fetchMyNovels()
          setTimeout(() => {
            showEditModal.value = false
          }, 1500)
        } else {
          editError.value = res.消息
        }
      } catch (e) {
        editError.value = '更新失败'
      }
    }

    const handleCreateNovel = async () => {
      createError.value = ''; createSuccess.value = ''
      if (novelForm.description.length > 600) {
        createError.value = '作品简介不能超过600字'
        return
      }
      const realmsJson = novelForm.realms.filter(r => r.name).map(r => `${r.name}体系：${r.value}`).join('\n')
      const charsJson = JSON.stringify(novelForm.characters.filter(c => c.name))
      try {
        const params = {
          title: novelForm.title, target_reader: novelForm.target_reader,
          genre: novelForm.genre, description: novelForm.description,
          story_background: novelForm.story_background, world_setting: novelForm.world_setting,
          cover_image: novelForm.cover_image,
          realm_setting: realmsJson || null, characters: charsJson
        }
        const res = await api.post('/novels/create', null, { params })
        if (res.状态码 === 200) {
          createSuccess.value = '作品创建成功！'
          Object.assign(novelForm, { title: '', target_reader: '', genre: '', description: '', story_background: '', world_setting: '', cover_image: '', realms: [{ name: '', value: '' }], characters: [] })
          selectedGenres.value = []
        } else {
          createError.value = res.消息
        }
      } catch (e) { createError.value = '创建失败' }
    }

    // 我的作品
    const myNovels = ref([])
    const fetchMyNovels = async () => {
      try {
        const res = await api.get('/novels/my')
        if (res.状态码 === 200) myNovels.value = res.数据
      } catch (e) { }
    }

    // 章节管理
    const showChapterModal = ref(false)
    const chapterNovel = ref({})
    const chapterMode = ref('new')
    const novelChapters = ref([])
    const generating = ref(false)
    const chapterForm = reactive({
      chapter_name: '', characters_involved: '', organizations: '',
      locations: '', skills: '', word_count: 2000, chapter_summary: ''
    })

    const openChapterModal = async (novel) => {
      chapterNovel.value = novel
      showChapterModal.value = true
      chapterMode.value = 'new'
      Object.assign(chapterForm, { chapter_name: '', characters_involved: '', organizations: '', locations: '', skills: '', word_count: 2000, chapter_summary: '' })
      try {
        const res = await api.get(`/chapters/novel/${novel.novel_unique_id}`)
        if (res.状态码 === 200) novelChapters.value = res.数据
      } catch { novelChapters.value = [] }
    }

    const generateChapter = async () => {
      if (!chapterForm.chapter_name) return alert('请输入章节名称')
      // 非VIP且次数用完的前端拦截
      if (!isVip.value && freeQuota.value <= 0) {
        alert('免费生成次数已用完，请开通VIP继续使用')
        router.push('/vip')
        return
      }
      generating.value = true
      try {
        const res = await api.post('/chapters/generate', null, {
          params: {
            novel_unique_id: chapterNovel.value.novel_unique_id,
            chapter_name: chapterForm.chapter_name,
            characters_involved: chapterForm.characters_involved,
            organizations: chapterForm.organizations,
            locations: chapterForm.locations,
            skills: chapterForm.skills,
            word_count: chapterForm.word_count,
            chapter_summary: chapterForm.chapter_summary
          }
        })
        if (res.状态码 === 200) {
          // 刷新用户信息（更新免费次数）
          try { const mu = await api.get('/auth/me'); if (mu.状态码===200) { Object.assign(user, mu.数据); localStorage.setItem('novel_user', JSON.stringify(user)) } } catch {}
          alert(res.消息)
          tab.value = 'drafts'
          fetchDrafts()
        } else {
          alert('生成失败: ' + res.消息)
        }
      } catch (e) {
        const msg = e.response ? (e.response.数据 || e.response.消息 || JSON.stringify(e.response.data)) : (e.message || '网络错误，请检查后端是否启动')
        alert('AI生成失败: ' + msg)
      } finally {
        generating.value = false
      }
    }

    // 草稿
    const drafts = ref([])
    const continuing = reactive({})
    const extracting = reactive({})
    const fetchDrafts = async () => {
      try {
        const res = await api.get('/chapters/drafts')
        if (res.状态码 === 200) drafts.value = res.数据
      } catch (e) { }
    }

    const extractDraftInfo = async (d) => {
      if (!d.content || d.content.trim() === '') {
        alert('章节内容为空，无法提取')
        return
      }
      extracting[d.chapter_unique_id] = true
      try {
        const res = await api.post('/chapters/extract-info', { content: d.content, chapter_name: d.chapter_name, novel_unique_id: d.novel_unique_id })
        console.log('[提取信息] 响应:', JSON.stringify(res, null, 2))
        if (res.状态码 === 200 && res.数据) {
          // 用 $set 或重新赋值确保响应式
          const idx = drafts.value.findIndex(item => item.chapter_unique_id === d.chapter_unique_id)
          if (idx !== -1) {
            drafts.value[idx] = { ...drafts.value[idx], _info: res.数据 }
          }
        } else {
          alert('提取失败: ' + (res.消息 || JSON.stringify(res)))
        }
      } catch (e) {
        console.error('[提取信息] 异常:', e)
        const detail = e.response?.data?.detail || e.response?.data?.消息 || e.message
        alert('提取失败: ' + detail)
      } finally {
        extracting[d.chapter_unique_id] = false
      }
    }

    const publishChapter = async (d) => {
      if (!d.content || d.content.trim() === '') {
        alert('章节内容为空，无法发布')
        return
      }
      if (!confirm(`确定发布章节「${d.chapter_name}」到作品圈？`)) return
      try {
        const body = { content: d.content }
        // 附带 AI 提取的信息
        if (d._info) {
          body.characters_involved = d._info.人物 || ''
          body.organizations = d._info.组织 || ''
          body.skills = d._info.功法技能 || ''
          body.locations = d._info.地点 || ''
          body.events = d._info.关键事件 || ''
          body.time_info = d._info.时间 || ''
          body.key_items = d._info.关键物品 || ''
          body.power_changes = d._info.实力变化 || ''
          body.foreshadowing = d._info.伏笔 || ''
        }
        const res = await api.post(`/chapters/publish/${d.chapter_unique_id}`, body)
        if (res.状态码 === 200) {
          alert(res.消息)
          fetchDrafts()
          fetchTodayPublished()
        } else alert(res.消息)
      } catch (e) {
        alert('发布失败: ' + (e.response?.data?.detail || e.message))
      }
    }

    const deleteDraft = async (d) => {
      if (!confirm('确定删除该草稿？')) return
      try {
        const res = await api.delete(`/chapters/delete/${d.chapter_unique_id}`)
        if (res.状态码 === 200) {
          alert('删除成功')
          fetchDrafts()
        } else alert(res.消息)
      } catch (e) { alert('删除失败') }
    }

    const deleteChapter = async (ch) => {
      if (!confirm(`确定删除章节「${ch.chapter_name}」？此操作不可恢复。`)) return
      try {
        const res = await api.delete(`/chapters/delete/${ch.chapter_unique_id}`)
        if (res.状态码 === 200) {
          alert('删除成功')
          // 重新加载章节列表
          const r2 = await api.get(`/chapters/novel/${chapterNovel.value.novel_unique_id}`)
          if (r2.状态码 === 200) novelChapters.value = r2.数据
          fetchTodayPublished()
        } else alert(res.消息)
      } catch (e) { alert('删除失败') }
    }

    const continueChapter = async (d) => {
      // 非VIP且次数用完的前端拦截
      if (!isVip.value && freeQuota.value <= 0) {
        alert('免费生成次数已用完，请开通VIP继续使用')
        router.push('/vip')
        return
      }
      continuing[d.chapter_unique_id] = true
      try {
        const res = await api.post(`/chapters/continue/${d.chapter_unique_id}`, null, { params: { word_count: 800 } })
        if (res.状态码 === 200) {
          // 续写完成后刷新草稿列表，确保内容正确显示
          await fetchDrafts()
          alert(`续写成功！新增 ${res.数据?.word_count || '?'} 字`)
        } else {
          alert(res.消息)
        }
      } catch (e) { alert('续写失败') }
      finally { continuing[d.chapter_unique_id] = false }
    }

    const deleteNovel = async (novel) => {
      if (!confirm(`确定删除作品「${novel.title}」？\n\n此操作将同时删除该作品的所有章节和设定文件，不可恢复！`)) return
      try {
        const res = await api.delete(`/novels/delete/${novel.novel_unique_id}`)
        if (res.状态码 === 200) {
          alert('作品已删除')
          fetchMyNovels()
        } else alert(res.消息)
      } catch (e) { alert('删除失败') }
    }

    const formatTime = (t) => t ? new Date(t).toLocaleString('zh-CN') : ''

    const syncUserFromServer = async () => {
      try {
        const meRes = await api.get('/auth/me')
        if (meRes.状态码 === 200) {
          Object.assign(user, meRes.数据)
          localStorage.setItem('novel_user', JSON.stringify(user))
        }
      } catch {}
    }

    const onUserChanged = () => {
      const stored = localStorage.getItem('novel_user')
      if (stored) {
        try { Object.assign(user, JSON.parse(stored)) } catch {}
      }
      fetchTodayPublished()
    }

    onMounted(() => {
      // 页面挂载时拉取最新用户状态（VIP开通后回来是最新）
      syncUserFromServer().then(() => fetchTodayPublished())
      window.addEventListener('user-info-changed', onUserChanged)
      fetchMyNovels()
    })

    onUnmounted(() => {
      window.removeEventListener('user-info-changed', onUserChanged)
    })

    return { tab, isVip, isSvip, vipLevel, freeQuota, publishedToday, maxDailyQuota, quotaRemaining, quotaPercent, levelLabel, levelDesc, fetchTodayPublished, novelForm, createError, createSuccess, handleCreateNovel,
      myNovels, fetchMyNovels,
      showChapterModal, chapterNovel, chapterMode, novelChapters, chapterForm, generating,
      openChapterModal, generateChapter,
      drafts, fetchDrafts, publishChapter, deleteDraft, deleteChapter, continueChapter, continuing, deleteNovel, formatTime,
      extracting, extractDraftInfo,
      genreOptions, selectedGenres, toggleGenre, handleCoverUpload, removeCover,
      showEditModal, editForm, editSelectedGenres, editError, editSuccess,
      openEditModal, toggleEditGenre, handleEditCoverUpload, handleUpdateNovel
    }
  }
}
</script>

<style scoped>
.page-title { font-size: 24px; margin-bottom: 20px; color: #e0e0e0; font-weight: 700; }

/* 配额横幅 */
.quota-banner {
  background: rgba(15,15,40,0.8); border: 1px solid rgba(102,126,234,0.15);
  border-radius: 14px; padding: 18px 24px; margin-bottom: 20px;
  display: flex; align-items: center; gap: 20px; flex-wrap: wrap;
  backdrop-filter: blur(10px);
}
.quota-banner.level-0 { border-color: rgba(16,185,129,0.25); background: linear-gradient(135deg, rgba(16,185,129,0.08), rgba(15,15,40,0.8)); }
.quota-banner.level-1 { border-color: rgba(6,182,212,0.3); background: linear-gradient(135deg, rgba(6,182,212,0.08), rgba(15,15,40,0.8)); }
.quota-banner.level-2 { border-color: rgba(245,158,11,0.3); background: linear-gradient(135deg, rgba(245,158,11,0.08), rgba(15,15,40,0.8)); }

.quota-level { display: flex; align-items: center; gap: 10px; }
.level-badge {
  padding: 4px 14px; border-radius: 20px; font-size: 13px; font-weight: 700;
  white-space: nowrap;
}
.level-0 .level-badge { background: rgba(16,185,129,0.15); color: #34d399; border: 1px solid rgba(16,185,129,0.3); }
.level-1 .level-badge { background: rgba(6,182,212,0.15); color: #06b6d4; border: 1px solid rgba(6,182,212,0.3); }
.level-2 .level-badge { background: linear-gradient(135deg, rgba(245,158,11,0.2), rgba(239,68,68,0.15)); color: #f59e0b; border: 1px solid rgba(245,158,11,0.3); }
.level-desc { font-size: 13px; color: #8892b0; }

.quota-progress { flex: 1; min-width: 200px; }
.quota-bar-bg { height: 6px; background: rgba(15,15,40,0.6); border-radius: 3px; margin-bottom: 6px; overflow: hidden; }
.quota-bar-fill { height: 100%; border-radius: 3px; transition: width 0.5s ease; }
.level-0 .quota-bar-fill { background: linear-gradient(90deg, #10b981, #34d399); }
.level-1 .quota-bar-fill { background: linear-gradient(90deg, #06b6d4, #38bdf8); }
.level-2 .quota-bar-fill { background: linear-gradient(90deg, #f59e0b, #fbbf24); }
.quota-text { font-size: 13px; color: #8892b0; }
.quota-text b { color: #e0e0e0; }

.quota-action {
  padding: 8px 20px; border-radius: 8px; font-size: 13px; font-weight: 600;
  text-decoration: none; white-space: nowrap; transition: all 0.3s;
  background: linear-gradient(135deg, #06b6d4, #8b5cf6); color: #fff;
  box-shadow: 0 2px 12px rgba(6,182,212,0.3);
}
.quota-action:hover { box-shadow: 0 4px 20px rgba(139,92,246,0.4); transform: translateY(-1px); }
.quota-action.gold { background: linear-gradient(135deg, #f59e0b, #ef4444); box-shadow: 0 2px 12px rgba(245,158,11,0.3); }
.quota-action.gold:hover { box-shadow: 0 4px 20px rgba(245,158,11,0.5); }

/* Tabs */
.tabs { display: flex; gap: 4px; margin-bottom: 28px; }
.tabs span { 
  padding: 10px 24px; cursor: pointer; font-size: 14px; font-weight: 600;
  color: #5a6080; border-radius: 10px; transition: all 0.3s;
  background: rgba(15, 15, 40, 0.6); border: 1px solid rgba(102, 126, 234, 0.1);
}
.tabs span:hover { color: #06b6d4; border-color: rgba(6, 182, 212, 0.3); }
.tabs span.active { 
  color: #06b6d4; background: linear-gradient(135deg, rgba(6,182,212,0.15), rgba(139,92,246,0.15));
  border-color: rgba(6, 182, 212, 0.5); box-shadow: 0 0 20px rgba(6, 182, 212, 0.1);
}
.tab-content { min-height: 400px; }
.no-permission { text-align: center; padding: 80px; background: rgba(15,15,40,0.7); border: 1px solid rgba(102,126,234,0.12); border-radius: 14px; color: #6b7280; font-size: 15px; }
.no-permission p { margin: 0; }
.link-vip { color: #f59e0b; font-weight: 700; text-decoration: underline; }

/* 免费体验 banner */
.free-banner {
  text-align: center; padding: 16px 24px; background: linear-gradient(135deg, rgba(16,185,129,0.1), rgba(5,150,105,0.08));
  border: 1px solid rgba(16,185,129,0.25); border-radius: 12px; color: #a7f3d0; font-size: 14px;
  margin-bottom: 20px; display: flex; align-items: center; justify-content: center; gap: 16px; flex-wrap: wrap;
}
.free-banner b { color: #34d399; font-size: 18px; }
.btn-upgrade {
  display: inline-block; padding: 6px 16px; background: linear-gradient(135deg, #f59e0b, #d97706);
  color: #fff; border-radius: 8px; font-size: 13px; font-weight: 600; text-decoration: none;
  transition: all 0.2s;
}
.btn-upgrade:hover { box-shadow: 0 4px 16px rgba(245,158,11,0.4); }

/* Form */
.create-form { background: rgba(15,15,40,0.7); border: 1px solid rgba(102,126,234,0.12); border-radius: 14px; padding: 28px; max-width: 800px; backdrop-filter: blur(10px); }
.form-row { margin-bottom: 18px; }
.form-row > label { display: block; margin-bottom: 6px; font-weight: 600; font-size: 13px; color: #8892b0; }
.form-row input, .form-row select, .form-row textarea { 
  width: 100%; padding: 10px 14px; border: 1px solid rgba(102, 126, 234, 0.2); 
  border-radius: 8px; font-size: 14px; background: rgba(15,15,40,0.5); color: #e0e0e0;
  transition: border-color 0.3s;
}
.form-row input:focus, .form-row select:focus, .form-row textarea:focus { outline: none; border-color: rgba(6,182,212,0.5); box-shadow: 0 0 12px rgba(6,182,212,0.1); }
.form-row textarea { resize: vertical; }
.form-row textarea.over { border-color: #f87171; }
.form-row select { cursor: pointer; color: #e0e0e0; }
.form-row select option { background: #111133; color: #e0e0e0; }
.char-count { font-weight: normal; font-size: 12px; color: #5a6080; }
.char-count.over { color: #f87171; }
.field-error { color: #f87171; font-size: 12px; margin-top: 4px; }

/* Image upload */
.image-upload { width: 100%; }
.image-upload .preview { position: relative; display: inline-block; }
.image-upload .preview img { max-width: 200px; max-height: 200px; border-radius: 10px; border: 1px solid rgba(102,126,234,0.2); }
.image-upload .preview .btn-remove { position: absolute; top: -8px; right: -8px; background: #f87171; color: #fff; border: none; border-radius: 50%; width: 24px; height: 24px; cursor: pointer; font-size: 12px; }
.image-upload input[type="file"] { width: 100%; padding: 10px; border: 1px dashed rgba(102,126,234,0.3); border-radius: 8px; cursor: pointer; color: #8892b0; background: rgba(15,15,40,0.5); }

/* Edit modal */
.edit-modal { max-width: 700px; max-height: 80vh; overflow-y: auto; }
.edit-modal form { padding: 20px 0; }
.edit-modal button[type="submit"] { width: 100%; padding: 12px; background: linear-gradient(135deg, #06b6d4, #8b5cf6); color: #fff; border: none; border-radius: 8px; cursor: pointer; font-size: 15px; font-weight: 600; transition: all 0.3s; }
.edit-modal button[type="submit"]:hover { box-shadow: 0 4px 24px rgba(6,182,212,0.4); }

/* Genre tags */
.genre-select { display: flex; flex-wrap: wrap; gap: 8px; }
.genre-tag { padding: 6px 16px; border: 1px solid rgba(102,126,234,0.2); border-radius: 20px; cursor: pointer; font-size: 13px; color: #6b7280; background: rgba(15,15,40,0.5); transition: all 0.2s; }
.genre-tag:hover { border-color: rgba(6,182,212,0.5); color: #06b6d4; }
.genre-tag.active { background: linear-gradient(135deg, rgba(6,182,212,0.2), rgba(139,92,246,0.2)); color: #06b6d4; border-color: rgba(6,182,212,0.6); box-shadow: 0 0 12px rgba(6,182,212,0.1); }

/* Realm */
.realm-item { display: flex; flex-direction: column; gap: 6px; margin-bottom: 8px; padding: 12px; background: rgba(15,15,40,0.4); border: 1px solid rgba(102,126,234,0.1); border-radius: 8px; }
.realm-item input { width: 60% !important; }

/* Character card */
.char-card { border: 1px solid rgba(102,126,234,0.12); border-radius: 10px; padding: 16px; margin-bottom: 12px; background: rgba(15,15,40,0.4); }
.char-header { display: flex; justify-content: space-between; margin-bottom: 10px; color: #c0c8e0; }
.char-fields { display: flex; flex-wrap: wrap; gap: 10px; }
.char-fields .half { width: calc(50% - 5px); }
.char-fields .full { width: 100%; }
.char-fields label { display: block; font-size: 12px; color: #6b7280; margin-bottom: 3px; }
.char-fields input, .char-fields select, .char-fields textarea { width: 100%; padding: 8px 10px; border: 1px solid rgba(102,126,234,0.15); border-radius: 6px; font-size: 13px; background: rgba(15,15,40,0.5); color: #e0e0e0; }
.char-fields textarea { resize: vertical; }

.btn-add { padding: 8px 18px; background: rgba(6,182,212,0.1); color: #06b6d4; border: 1px solid rgba(6,182,212,0.3); border-radius: 8px; cursor: pointer; font-size: 13px; margin-top: 8px; transition: all 0.3s; }
.btn-add:hover { background: rgba(6,182,212,0.2); }
.btn-remove { padding: 4px 12px; color: #f87171; border: 1px solid rgba(248,113,113,0.4); border-radius: 6px; cursor: pointer; font-size: 12px; background: transparent; transition: all 0.3s; }
.btn-remove:hover { background: rgba(248,113,113,0.1); }

.error { color: #f87171; margin: 12px 0; font-size: 13px; }
.success { color: #34d399; margin: 12px 0; font-size: 13px; }
.create-form > button { padding: 12px 32px; background: linear-gradient(135deg, #06b6d4, #8b5cf6); color: #fff; border: none; border-radius: 8px; font-size: 15px; cursor: pointer; font-weight: 600; transition: all 0.3s; box-shadow: 0 4px 20px rgba(6,182,212,0.25); }
.create-form > button:hover { box-shadow: 0 4px 30px rgba(139,92,246,0.4); transform: translateY(-1px); }
.create-form > button:disabled { opacity: 0.4; cursor: not-allowed; transform: none; box-shadow: none; }

/* My novels */
.my-novel-card { 
  background: rgba(15,15,40,0.7); border: 1px solid rgba(102,126,234,0.12); 
  border-radius: 14px; padding: 20px; margin-bottom: 12px;
  display: flex; gap: 18px; align-items: center; backdrop-filter: blur(10px);
  transition: all 0.3s;
}
.my-novel-card:hover { border-color: rgba(6,182,212,0.25); box-shadow: 0 4px 20px rgba(6,182,212,0.08); }
.my-novel-cover { width: 80px; height: 110px; flex-shrink: 0; border-radius: 8px; overflow: hidden; background: linear-gradient(135deg, #111133, #0d1b3e); }
.my-novel-cover img { width: 100%; height: 100%; object-fit: cover; }
.my-novel-cover .placeholder { display: flex; align-items: center; justify-content: center; width: 100%; height: 100%; background: linear-gradient(135deg, #06b6d4, #8b5cf6); color: #fff; font-size: 12px; font-weight: 600; }
.my-novel-info { flex: 1; }
.my-novel-info h3 { margin: 0 0 6px 0; font-size: 16px; color: #e0e0e0; font-weight: 600; }
.my-novel-info p { margin: 0 0 4px 0; font-size: 13px; color: #6b7280; }
.my-novel-desc { color: #5a6080 !important; font-size: 12px !important; }
.my-novel-actions { display: flex; gap: 8px; }
.my-novel-actions button { padding: 8px 16px; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 500; transition: all 0.3s; border: none; }
.my-novel-actions button:first-child { background: rgba(6,182,212,0.12); color: #06b6d4; border: 1px solid rgba(6,182,212,0.25); }
.my-novel-actions button:nth-child(2) { background: rgba(139,92,246,0.12); color: #8b5cf6; border: 1px solid rgba(139,92,246,0.25); }
.my-novel-actions button:first-child:hover, .my-novel-actions button:nth-child(2):hover { opacity: 0.85; }

/* Modal */
.modal-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); backdrop-filter: blur(4px); display: flex; align-items: center; justify-content: center; z-index: 200; }
.modal-content { 
  background: #0f0f2a; border: 1px solid rgba(102,126,234,0.2); border-radius: 16px; 
  padding: 32px; max-width: 700px; width: 90%; max-height: 80vh; overflow-y: auto; 
  position: relative; box-shadow: 0 20px 60px rgba(0,0,0,0.5), 0 0 40px rgba(6,182,212,0.1);
}
.modal-close { position: absolute; top: 14px; right: 20px; font-size: 24px; background: none; border: none; cursor: pointer; color: #5a6080; transition: color 0.2s; }
.modal-close:hover { color: #f87171; }
.chapter-modal h2 { margin-bottom: 20px; color: #e0e0e0; }
.chapter-form { margin-bottom: 20px; padding: 20px; background: rgba(15,15,40,0.5); border: 1px solid rgba(102,126,234,0.1); border-radius: 12px; }
.chapter-form h3 { margin-bottom: 14px; font-size: 15px; color: #8892b0; }
.chapter-form input { width: 100%; padding: 10px 14px; margin-bottom: 10px; border: 1px solid rgba(102,126,234,0.2); border-radius: 8px; font-size: 14px; background: rgba(15,15,40,0.5); color: #e0e0e0; }
.chapter-form input:focus { outline: none; border-color: rgba(6,182,212,0.5); }
.chapter-btns { display: flex; gap: 10px; margin-top: 4px; }
.chapter-btns button { flex: 1; padding: 11px; border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: 600; transition: all 0.3s; }
.chapter-btns button:first-child { background: rgba(15,15,40,0.8); color: #8892b0; border: 1px solid rgba(102,126,234,0.2); }
.btn-ai { background: linear-gradient(135deg, #06b6d4, #8b5cf6) !important; color: #fff !important; border: none !important; box-shadow: 0 4px 16px rgba(6,182,212,0.3); }
.btn-ai:hover { box-shadow: 0 4px 28px rgba(139,92,246,0.4); }
.btn-ai:disabled { opacity: 0.6; cursor: not-allowed; }
.spinner { display: inline-block; width: 16px; height: 16px; border: 2px solid rgba(255,255,255,0.3); border-top-color: #fff; border-radius: 50%; animation: spin 0.8s linear infinite; vertical-align: middle; margin-right: 6px; }
@keyframes spin { to { transform: rotate(360deg); } }

.existing-chapters { margin-top: 20px; }
.existing-chapters h3 { margin-bottom: 12px; font-size: 15px; color: #8892b0; }
.chapter-item { padding: 10px 14px; background: rgba(15,15,40,0.4); border: 1px solid rgba(102,126,234,0.1); border-radius: 8px; margin-bottom: 6px; display: flex; justify-content: space-between; font-size: 13px; color: #b0b8d0; }
.chapter-status { color: #34d399; font-size: 12px; font-weight: 600; }
.btn-delete-chapter {
  background: rgba(239, 68, 68, 0.12); border: 1px solid rgba(239, 68, 68, 0.25);
  color: #f87171; cursor: pointer; font-size: 11px; font-weight: 600;
  padding: 4px 12px; border-radius: 6px; transition: all 0.2s;
  white-space: nowrap;
}
.btn-delete-chapter:hover {
  background: rgba(239, 68, 68, 0.22); border-color: #ef4444;
  color: #fca5a5; box-shadow: 0 2px 12px rgba(239, 68, 68, 0.2);
}

/* Draft */
.draft-card { background: rgba(15,15,40,0.7); border: 1px solid rgba(102,126,234,0.12); border-radius: 14px; padding: 20px; margin-bottom: 16px; backdrop-filter: blur(10px); }
.draft-header { display: flex; justify-content: space-between; margin-bottom: 12px; }
.draft-header h3 { font-size: 16px; color: #e0e0e0; font-weight: 600; }
.draft-header span { font-size: 12px; color: #5a6080; }
.draft-content textarea { width: 100%; padding: 14px; border: 1px solid rgba(102,126,234,0.15); border-radius: 10px; font-size: 14px; resize: vertical; line-height: 1.8; background: rgba(15,15,40,0.5); color: #e0e0e0; }
.draft-content textarea:focus { outline: none; border-color: rgba(6,182,212,0.4); }
.draft-actions { display: flex; gap: 10px; margin-top: 12px; }
.draft-actions button { padding: 9px 22px; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 500; transition: all 0.3s; }
.draft-actions button:first-child { background: linear-gradient(135deg, #06b6d4, #8b5cf6); color: #fff; border: none; }
.draft-actions button:first-child:hover { box-shadow: 0 4px 20px rgba(6,182,212,0.4); }
.btn-danger { background: transparent !important; color: #f87171 !important; border: 1px solid rgba(248,113,113,0.4) !important; }
.btn-danger:hover { background: rgba(248,113,113,0.1) !important; }
.empty { text-align: center; padding: 60px 0; color: #5a6080; font-size: 14px; }

/* Draft Info Panel */
.draft-info-panel { margin-top: 12px; }
.btn-extract { padding: 8px 18px; border-radius: 8px; cursor: pointer; font-size: 12px; font-weight: 500; background: rgba(6,182,212,0.15); color: #06b6d4; border: 1px solid rgba(6,182,212,0.3); transition: all 0.3s; }
.btn-extract:hover { background: rgba(6,182,212,0.25); box-shadow: 0 2px 12px rgba(6,182,212,0.2); }
.btn-extract:disabled { opacity: 0.6; cursor: not-allowed; }
.info-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 10px; }
.info-cell { display: flex; flex-direction: column; }
.info-cell label { font-size: 11px; color: #667eea; margin-bottom: 4px; font-weight: 500; }
.info-cell input { padding: 8px 10px; border: 1px solid rgba(102,126,234,0.2); border-radius: 6px; font-size: 12px; background: rgba(15,15,40,0.5); color: #e0e0e0; transition: border-color 0.3s; }
.info-cell input:focus { outline: none; border-color: rgba(6,182,212,0.5); }
@media (max-width: 768px) { .info-grid { grid-template-columns: repeat(2, 1fr); } }
</style>

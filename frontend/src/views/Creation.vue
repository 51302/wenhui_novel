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
      <span :class="{ active: tab === 'outline' }" @click="tab = 'outline'">章节概要</span>
      <span :class="{ active: tab === 'drafts' }" @click="fetchDrafts(); tab = 'drafts'">草稿列表</span>
      <span :class="{ active: tab === 'screenplay' }" @click="initScreenplay(); tab = 'screenplay'">剧本创作</span>
    </div>

    <!-- ==================== 新建作品 ==================== -->
    <div v-if="tab === 'create'" class="tab-content">
      <form class="create-form creation-canvas" @submit.prevent="handleCreateNovel">
        <div class="canvas-intro">
          <div>
            <span class="eyebrow">NEW STORY / 03</span>
            <h1>把灵感铺成一张作品地图</h1>
            <p>从标题、气质到人物关系，逐格搭建属于你的世界。</p>
          </div>
          <div class="canvas-progress"><strong>{{ creationCompleted }}/5</strong><span>模块已完成</span><i><b :style="{ width: creationProgress + '%' }"></b></i></div>
        </div>

        <section class="canvas-card card-identity" :class="{ collapsed: !creationSections.identity }">
          <button type="button" class="card-heading" @click="creationSections.identity = !creationSections.identity">
            <span class="card-index">01</span><span class="section-icon">📖</span><span class="card-title"><strong>作品身份</strong><small>先让故事有一个清晰的名字与气质</small></span><span class="card-state">{{ creationIdentitySummary }}</span><span class="card-toggle">{{ creationSections.identity ? '收起' : '展开' }}</span>
          </button>
          <div v-show="creationSections.identity" class="card-body">
            <div class="identity-layout">
              <div class="identity-fields">
                <div class="form-row"><label>作品名称</label><input v-model="novelForm.title" required placeholder="请输入作品名称" /></div>
                <div class="field-grid">
                  <div class="form-row"><label>目标读者</label><select v-model="novelForm.target_reader" required><option value="">请选择</option><option value="男频">男频</option><option value="女频">女频</option></select></div>
                  <div class="form-row"><label>签约类型</label><select v-model="novelForm.sign_type" required><option value="non_exclusive">非独家（作品可在作品圈和首页展示）</option><option value="exclusive">独家（仅自己可见）</option></select></div>
                </div>
                <div class="form-row"><label>标签/题材</label><div class="genre-select"><div v-for="genre in genreOptions" :key="genre" :class="['genre-tag', { active: selectedGenres.includes(genre) }]" @click="toggleGenre(genre)">{{ genre }}</div></div></div>
                <div class="form-row"><label>写作风格（作家）<span class="multi-tip">（可选，选定后本作品后续章节默认按此风格写）</span></label><select v-model="novelForm.writing_style_id"><option value="">不指定（默认，按题材自动写）</option><option v-for="s in authorStyles" :key="s.id" :value="s.id">{{ s.name }}{{ s.brief ? ' · ' + s.brief : '' }}</option></select></div>
              </div>
              <div class="cover-stage"><span class="stage-label">COVER ART</span><div class="image-upload"><div v-if="novelForm.cover_image" class="preview"><img :src="novelForm.cover_image" alt="封面预览" @error="novelForm.cover_image = ''" /><button type="button" class="btn-remove" @click="novelForm.cover_image = ''">删除</button></div><template v-else><div class="upload-placeholder"><span>✦</span><b>上传封面</b><small>建议使用竖版图片 · 10MB以内</small><input type="file" accept="image/*" @change="handleCoverUpload" /></div></template></div></div>
            </div>
          </div>
        </section>

        <section class="canvas-card card-summary" :class="{ collapsed: !creationSections.summary }">
          <button type="button" class="card-heading" @click="creationSections.summary = !creationSections.summary"><span class="card-index">02</span><span class="section-icon">📝</span><span class="card-title"><strong>故事序章</strong><small>用一段简介留下第一枚钩子</small></span><span class="card-state">{{ novelForm.description ? novelForm.description.length + ' / 600 字' : '待填写' }}</span><span class="card-toggle">{{ creationSections.summary ? '收起' : '展开' }}</span></button>
          <div v-show="creationSections.summary" class="card-body"><div class="form-row"><textarea v-model="novelForm.description" rows="5" :class="{ over: novelForm.description.length > 600 }" placeholder="不超过600字，写下故事最想被看见的那一刻" /><div class="form-row-meta"><span class="char-count" :class="{ over: novelForm.description.length > 600 }">{{ novelForm.description.length }}/600</span><span v-if="novelForm.description.length > 600" class="field-error">作品简介不能超过600字</span></div></div></div>
        </section>

        <section class="canvas-card card-world" :class="{ collapsed: !creationSections.world }">
          <button type="button" class="card-heading" @click="creationSections.world = !creationSections.world"><span class="card-index">03</span><span class="section-icon">🌍</span><span class="card-title"><strong>世界底稿</strong><small>故事发生在哪里，规则又是什么</small></span><span class="card-state">{{ creationWorldSummary }}</span><span class="card-toggle">{{ creationSections.world ? '收起' : '展开' }}</span></button>
          <div v-show="creationSections.world" class="card-body"><div class="field-grid"><div class="form-row"><label>故事背景</label><textarea v-model="novelForm.story_background" rows="5" placeholder="描述故事的时代背景、地点等" /></div><div class="form-row"><label>世界观设定</label><textarea v-model="novelForm.world_setting" rows="5" placeholder="描述世界观体系，如修炼体系、社会结构等" /></div></div></div>
        </section>

        <section class="canvas-card card-realm" :class="{ collapsed: !creationSections.realm }">
          <button type="button" class="card-heading" @click="creationSections.realm = !creationSections.realm"><span class="card-index">04</span><span class="section-icon">⚡</span><span class="card-title"><strong>力量坐标</strong><small>定义角色如何成长、突破与冒险</small></span><span class="card-state">{{ creationRealmSummary }}</span><span class="card-toggle">{{ creationSections.realm ? '收起' : '展开' }}</span></button>
          <div v-show="creationSections.realm" class="card-body"><div class="realm-list"><div v-for="(realm, ri) in novelForm.realms" :key="ri" class="realm-item"><div class="realm-number">{{ String(ri + 1).padStart(2, '0') }}</div><div class="realm-fields"><input v-model="realm.name" placeholder="体系名称(如：A体系)" /><textarea v-model="realm.value" placeholder="该体系的境界设定" rows="2" /></div><button type="button" class="btn-remove" @click="novelForm.realms.splice(ri, 1)">删除</button></div><button type="button" class="btn-add" @click="novelForm.realms.push({ name: '', value: '' })">+ 添加境界体系</button></div></div>
        </section>

        <section class="canvas-card card-characters" :class="{ collapsed: !creationSections.characters }">
          <button type="button" class="card-heading" @click="creationSections.characters = !creationSections.characters"><span class="card-index">05</span><span class="section-icon">👥</span><span class="card-title"><strong>关系群像</strong><small>把角色放进故事，让世界开始呼吸</small></span><span class="card-state">{{ creationCharacterSummary }}</span><span class="card-toggle">{{ creationSections.characters ? '收起' : '展开' }}</span></button>
          <div v-show="creationSections.characters" class="card-body"><div class="char-list"><div v-for="(ch, ci) in novelForm.characters" :key="ci" class="char-card"><div class="char-header"><strong>角色{{ String.fromCharCode(65+ci) }}</strong><button type="button" class="btn-remove" @click="novelForm.characters.splice(ci, 1)">删除</button></div><div class="char-fields"><div class="half"><label>角色名称</label><input v-model="ch.name" /></div><div class="half"><label>性别</label><select v-model="ch.gender"><option value="">请选择</option><option value="男">男</option><option value="女">女</option></select></div><div class="full"><label>角色定位</label><input v-model="ch.position" placeholder="男主，天云宗圣子" /></div><div class="full"><label>角色性格</label><input v-model="ch.personality" /></div><div class="full"><label>角色简介</label><textarea v-model="ch.intro" rows="2" /></div><div class="half"><label>伴侣</label><input v-model="ch.partner" /></div><div class="half"><label>子女</label><input v-model="ch.children" /></div><div class="half"><label>亲人</label><input v-model="ch.relatives" /></div><div class="half"><label>朋友</label><input v-model="ch.friends" /></div><div class="full"><label>弟子</label><input v-model="ch.disciples" /></div></div></div><button type="button" class="btn-add" @click="novelForm.characters.push({ name: '', gender: '', position: '', personality: '', intro: '', partner: '', children: '', relatives: '', friends: '', disciples: '' })">+ 添加角色</button></div></div>
        </section>

        <div class="form-footer canvas-footer"><p v-if="createError" class="error">{{ createError }}</p><p v-if="createSuccess" class="success">{{ createSuccess }}</p><button type="submit" class="btn-create" :disabled="novelForm.description.length > 600">创建作品 <span>→</span></button></div>
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
          <button class="btn-download" @click="downloadNovel(novel)">⬇ 下载作品</button>
          <button class="btn-danger" @click="deleteNovel(novel)">删除作品</button>
        </div>
      </div>

      <!-- 章节管理弹窗 -->
      <div v-if="showChapterModal" class="modal-overlay">
        <div class="modal-content chapter-modal">
          <button class="modal-close" @click="showChapterModal = false">&times;</button>
          <h2>{{ chapterNovel.title }} - 章节管理</h2>
          <div class="chapter-form">
            <section class="canvas-card" aria-labelledby="generation-settings-title">
              <div class="card-heading"><span class="card-index">01</span><div class="card-title"><h3 id="generation-settings-title">生成设置</h3><small>确定章节名称、篇幅与故事要素</small></div></div>
              <div class="card-body">
                <div class="field-grid">
                  <div class="form-row"><label for="generate-chapter_name">章节名称</label><input id="generate-chapter_name" v-model="chapterForm.chapter_name" placeholder="章节名称" /></div>
                  <div class="form-row"><label for="generate-word_count">章节字数</label><input id="generate-word_count" v-model.number="chapterForm.word_count" type="number" placeholder="章节字数" /></div>
                  <div class="form-row"><label for="generate-characters_involved">涉及人物</label><input id="generate-characters_involved" v-model="chapterForm.characters_involved" placeholder="涉及人物" /></div>
                  <div class="form-row"><label for="generate-organizations">涉及组织</label><input id="generate-organizations" v-model="chapterForm.organizations" placeholder="涉及组织" /></div>
                  <div class="form-row"><label for="generate-locations">涉及地点</label><input id="generate-locations" v-model="chapterForm.locations" placeholder="涉及地点" /></div>
                  <div class="form-row"><label for="generate-skills">涉及技能</label><input id="generate-skills" v-model="chapterForm.skills" placeholder="涉及技能" /></div>
                </div>
                <label class="anti-ai-toggle">
                  <input type="checkbox" v-model="chapterForm.use_anti_ai" />
                  <span><strong>反AI检测去味</strong><small>默认开启，生成后自动按项目反AI规则降低AI味</small></span>
                </label>
              </div>
            </section>
            <section class="canvas-card chapter-style-card" aria-labelledby="generation-style-title">
              <div class="card-heading"><span class="card-index">02</span><div class="card-title"><h3 id="generation-style-title">风格模板</h3><small>搭配作家风格与章节模板，确定叙事气质</small></div></div>
              <div class="card-body">
                <div class="form-row"><label>作家风格<span class="multi-tip">（可多选，最多4个）</span></label>
                  <div class="multi-select" :class="{ open: msStyleOpen }">
                    <button type="button" class="multi-select-trigger" @click="msStyleOpen = !msStyleOpen">
                      <span class="ms-trigger-label">{{ selAuthorStyles.length ? '已选 ' + selAuthorStyles.length + ' 个作家风格' : '点击选择作家风格' }}</span>
                      <span class="ms-trigger-arrow" :class="{ up: msStyleOpen }">▾</span>
                    </button>
                    <div v-if="msStyleOpen" class="multi-select-panel">
                      <div v-for="s in authorStyles" :key="s.id" class="ms-item"
                           :class="{ checked: selAuthorStyles.includes(s.id), disabled: !selAuthorStyles.includes(s.id) && selAuthorStyles.length >= 4 }"
                           @click="toggleMulti(selAuthorStyles, s.id)">
                        <span class="ms-name">{{ s.name }}</span>
                        <small class="ms-brief">{{ s.brief }}</small>
                        <span v-if="selAuthorStyles.includes(s.id)" class="ms-check">✓</span>
                      </div>
                      <div class="ms-panel-hint">最多可选 4 个{{ selAuthorStyles.length >= 4 ? '（已达上限，取消勾选后可换选）' : '，选中后置灰' }}</div>
                    </div>
                  </div></div>
                <div class="form-row"><label>章节模板<span class="multi-tip">（可多选，最多4个，不选则跟随主角性格）</span></label>
                  <div class="multi-select" :class="{ open: msTemplateOpen }">
                    <button type="button" class="multi-select-trigger" @click="msTemplateOpen = !msTemplateOpen">
                      <span class="ms-trigger-label">{{ selChapterTemplates.length ? '已选 ' + selChapterTemplates.length + ' 个章节模板' : '点击选择章节模板' }}</span>
                      <span class="ms-trigger-arrow" :class="{ up: msTemplateOpen }">▾</span>
                    </button>
                    <div v-if="msTemplateOpen" class="multi-select-panel">
                      <template v-for="g in chapterTemplateGroups" :key="g.category">
                        <div class="ms-group">{{ g.category }}</div>
                        <div v-for="t in g.items" :key="t.id" class="ms-item"
                             :class="{ checked: selChapterTemplates.includes(t.id), disabled: !selChapterTemplates.includes(t.id) && selChapterTemplates.length >= 4 }"
                             @click="toggleMulti(selChapterTemplates, t.id)">
                          <span class="ms-name">{{ t.name }}</span>
                          <span v-if="selChapterTemplates.includes(t.id)" class="ms-check">✓</span>
                        </div>
                      </template>
                      <div class="ms-panel-hint">最多可选 4 个{{ selChapterTemplates.length >= 4 ? '（已达上限，取消勾选后可换选）' : '，选中后置灰' }}</div>
                    </div>
                  </div></div>
              </div>
            </section>
            <section class="canvas-card" aria-labelledby="generation-summary-title">
              <div class="card-heading"><span class="card-index">03</span><div class="card-title"><h3 id="generation-summary-title">章节概要</h3><small>串联关键情节，为本章写下剧情发展路线</small></div></div>
              <div class="card-body">
                <div class="form-row">
                  <label for="generate-summary">剧情发展路线</label>
                  <textarea id="generate-summary" v-model="chapterForm.chapter_summary" class="wide-textarea" placeholder="剧情发展路线(如：主角偷袭天道教宗→夺取镇教之宝→被追杀→坠崖获机缘)" rows="4"></textarea>
                </div>
              </div>
            </section>
            <div class="chapter-btns">
              <button class="btn-ai" @click="generateChapter" :disabled="generating">
                <span v-if="generating" class="spinner"></span>
                {{ generating ? '正在生成中...' : '一键AI生成' }}
              </button>
            </div>
          </div>
          <div class="existing-chapters">
            <h3>已有章节
              <span class="chapter-count-hint">共 {{ novelChapters.length }} 章</span>
            </h3>
            <div v-if="novelChapters.length === 0" class="empty">暂无章节</div>
            <div v-for="ch in chapterPaged" :key="ch.chapter_unique_id" class="chapter-item">
              <div class="chapter-main">
                <span>第{{ ch.chapter_number || (novelChapters.indexOf(ch) + 1) }}章 - {{ ch.chapter_name }} ({{ ch.word_count }}字)</span>
                <span class="chapter-status">{{ ch.is_published ? '✓ 已发布' : '草稿' }}</span>
              </div>
              <div class="chapter-actions">
                <button class="btn-edit-chapter" @click="editChapter(ch)" title="编辑章节">✎ 编辑</button>
                <button class="btn-delete-chapter" @click="deleteChapter(ch)" title="删除章节">✕ 删除</button>
              </div>
            </div>
            <div v-if="chapterPageCount > 1" class="pagination">
              <button class="page-btn" :disabled="chapterPage <= 1" @click="chapterPage--">上一页</button>
              <template v-for="(p, i) in chapterPageNums" :key="'cp-' + i">
                <span v-if="p === '...'" class="page-ellipsis">…</span>
                <button v-else class="page-btn" :class="{ active: p === chapterPage }" @click="chapterPage = p">{{ p }}</button>
              </template>
              <button class="page-btn" :disabled="chapterPage >= chapterPageCount" @click="chapterPage++">下一页</button>
            </div>
          </div>
        </div>
      </div>

      <!-- 章节编辑独立弹窗 -->
      <div v-if="showChapterEditModal" class="modal-overlay">
        <div class="modal-content chapter-edit-modal">
          <button class="modal-close" @click="showChapterEditModal = false">&times;</button>
          <h2>编辑章节：{{ editChapterForm.chapter_name }}</h2>
          <div v-if="chapterEditIssue" class="chapter-edit-issue" role="alert">{{ chapterEditIssue }}</div>
          <div class="edit-row"><label>章节名称</label><input v-model="editChapterForm.chapter_name" /></div>
          <div class="edit-row"><label>剧情发展路线</label>
            <textarea v-model="editChapterForm.chapter_summary" class="wide-textarea" rows="4" style="width: 580px; height: 71px;" placeholder="剧情发展路线(如：主角偷袭天道教宗→夺取镇教之宝→被追杀→坠崖获机缘)"></textarea></div>
          <div class="edit-row"><label>作家风格<span class="multi-tip">（可多选，最多4个）</span></label>
            <div class="multi-select" :class="{ open: msEditStyleOpen }">
              <button type="button" class="multi-select-trigger" @click="msEditStyleOpen = !msEditStyleOpen">
                <span class="ms-trigger-label">{{ selEditAuthorStyles.length ? '已选 ' + selEditAuthorStyles.length + ' 个作家风格' : '点击选择作家风格' }}</span>
                <span class="ms-trigger-arrow" :class="{ up: msEditStyleOpen }">▾</span>
              </button>
              <div v-if="msEditStyleOpen" class="multi-select-panel">
                <div v-for="s in authorStyles" :key="s.id" class="ms-item"
                     :class="{ checked: selEditAuthorStyles.includes(s.id), disabled: !selEditAuthorStyles.includes(s.id) && selEditAuthorStyles.length >= 4 }"
                     @click="toggleMulti(selEditAuthorStyles, s.id)">
                  <span class="ms-name">{{ s.name }}</span>
                  <small class="ms-brief">{{ s.brief }}</small>
                  <span v-if="selEditAuthorStyles.includes(s.id)" class="ms-check">✓</span>
                </div>
                <div class="ms-panel-hint">最多可选 4 个{{ selEditAuthorStyles.length >= 4 ? '（已达上限，取消勾选后可换选）' : '，选中后置灰' }}</div>
              </div>
            </div></div>
          <div class="edit-row"><label>章节模板<span class="multi-tip">（可多选，最多4个，不选则跟随主角性格）</span></label>
            <div class="multi-select" :class="{ open: msEditTemplateOpen }">
              <button type="button" class="multi-select-trigger" @click="msEditTemplateOpen = !msEditTemplateOpen">
                <span class="ms-trigger-label">{{ selEditChapterTemplates.length ? '已选 ' + selEditChapterTemplates.length + ' 个章节模板' : '点击选择章节模板' }}</span>
                <span class="ms-trigger-arrow" :class="{ up: msEditTemplateOpen }">▾</span>
              </button>
              <div v-if="msEditTemplateOpen" class="multi-select-panel">
                <template v-for="g in chapterTemplateGroups" :key="g.category">
                  <div class="ms-group">{{ g.category }}</div>
                  <div v-for="t in g.items" :key="t.id" class="ms-item"
                       :class="{ checked: selEditChapterTemplates.includes(t.id), disabled: !selEditChapterTemplates.includes(t.id) && selEditChapterTemplates.length >= 4 }"
                       @click="toggleMulti(selEditChapterTemplates, t.id)">
                    <span class="ms-name">{{ t.name }}</span>
                    <span v-if="selEditChapterTemplates.includes(t.id)" class="ms-check">✓</span>
                  </div>
                </template>
                <div class="ms-panel-hint">最多可选 4 个{{ selEditChapterTemplates.length >= 4 ? '（已达上限，取消勾选后可换选）' : '，选中后置灰' }}</div>
              </div>
            </div></div>
          <div class="edit-row"><label>章节正文</label><button class="btn-copy-content" @click="copyChapterContent" title="复制正文内容">📋</button>
            <textarea v-model="editChapterForm.content" :readonly="regenerating" rows="16" placeholder="章节正文内容"></textarea></div>
          <div class="edit-actions">
            <button class="btn-save" @click="saveChapterEdit" :disabled="saving || regenerating">💾 {{ saving ? '保存中...' : '保存修改' }}</button>
            <button class="btn-regenerate" :class="{ 'btn-svip-only': !isSvip }" @click="isSvip ? regenerateChapter() : null" :disabled="regenerating || !isSvip" :title="isSvip ? 'AI重新生成本章节内容' : '仅SVIP可使用此功能'">🔄 {{ regenerating ? '重新生成中...' : 'AI重新生成' }}</button>
            <button class="btn-cancel" @click="showChapterEditModal = false">取消</button>
          </div>
        </div>
      </div>
    </div>

    <!-- ==================== 编辑作品弹窗 ==================== -->
    <div v-if="showEditModal" class="modal-overlay">
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
              <template v-else>
                <input type="file" accept="image/*" @change="handleEditCoverUpload" />
              </template>
            </div>
          </div>
          <div class="form-row">
            <label>目标读者</label>
            <select v-model="editForm.target_reader" required>
              <option value="">请选择</option><option value="男频">男频</option><option value="女频">女频</option>
            </select>
          </div>
          <div class="form-row">
            <label>签约类型</label>
            <select v-model="editForm.sign_type">
              <option value="non_exclusive">非独家（作品可在作品圈和首页展示）</option>
              <option value="exclusive">独家（作品仅自己可见，不在作品圈和首页展示）</option>
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
            <label>写作风格（作家）</label>
            <select v-model="editForm.writing_style_id">
              <option value="">不指定（默认，按题材自动写）</option>
              <option v-for="s in authorStyles" :key="s.id" :value="s.id">{{ s.name }}{{ s.brief ? ' · ' + s.brief : '' }}</option>
            </select>
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
      <section v-if="generationStatus" class="draft-card generation-card" aria-label="生成预览">
        <div class="draft-header">
          <h3>{{ generationTitle.novel }} · {{ generationTitle.chapter }}</h3>
          <span>生成预览</span>
        </div>
        <div v-if="generating" class="generating-waiting-bar" role="status">
          <span class="generating-waiting-spinner"></span>
          <span>{{ generationStatus === 'waiting' ? '等待生成正文...' : generationStatus === 'refreshing' ? '生成完成，正在刷新草稿...' : '正在流式生成正文...' }}</span>
        </div>
        <p v-if="generationStatus === 'failed'" class="error" role="alert">{{ generationError }}。已收到的正文保留如下。</p>
        <pre v-if="generationPreview" class="generation-preview">{{ generationPreview }}</pre>
      </section>
      <div v-if="drafts.length === 0 && !generationStatus" class="empty">暂无草稿</div>
      <div v-for="d in drafts" :key="d.chapter_unique_id" class="draft-card">
        <div class="draft-header">
          <h3>{{ d.chapter_name }}</h3>
          <span>{{ d.word_count }}字 | {{ formatTime(d.created_at) }}</span>
        </div>
        <div class="draft-content">
          <textarea v-model="d.content" :readonly="continuing[d.chapter_unique_id]" rows="10" />
        </div>
        <div v-if="continuing[d.chapter_unique_id] || continuationPreviews[d.chapter_unique_id]">
          <p>{{ continuing[d.chapter_unique_id] ? '正在续写，以下为实时预览，最终内容以保存结果为准' : '续写预览，成功后正文已刷新为保存结果' }}</p>
          <pre v-if="continuationPreviews[d.chapter_unique_id]" class="generation-preview">{{ continuationPreviews[d.chapter_unique_id] }}</pre>
        </div>
        <div class="draft-actions">
          <button @click="continueChapter(d)" :disabled="continuing[d.chapter_unique_id]">
            <span v-if="continuing[d.chapter_unique_id]" class="spinner"></span>
            {{ continuing[d.chapter_unique_id] ? '正在续写...' : '🤖 AI续写' }}
          </button>
          <button @click="publishChapter(d)" :disabled="publishing[d.chapter_unique_id] || continuing[d.chapter_unique_id]">
            <span v-if="publishing[d.chapter_unique_id]" class="spinner"></span>
            {{ publishing[d.chapter_unique_id] ? '发布中...' : '发布章节' }}
          </button>
          <button class="btn-danger" @click="deleteDraft(d)" :disabled="continuing[d.chapter_unique_id]">删除</button>
        </div>
      </div>
    </div>

    <!-- ==================== 剧本创作 ==================== -->
    <div v-if="tab === 'screenplay'" class="tab-content">
      <div class="screenplay-section">
        <div class="form-row">
          <label>选择作品</label>
          <select v-model="spNovelId" @change="spLoadChapters" class="sp-novel-select">
            <option value="">-- 请选择作品 --</option>
            <option v-for="n in myNovels" :key="n.novel_unique_id" :value="n.novel_unique_id">
              {{ n.title }}
            </option>
          </select>
        </div>

        <div v-if="spNovelId" class="sp-chapter-list">
          <div class="sp-chapter-header">
            <label class="sp-check-all">
              <input type="checkbox" :checked="spAllSelected" @change="spToggleAll" />
              全选
            </label>
            <span class="sp-selected-count">已选 {{ spSelectedIds.length }} 章</span>
            <button class="btn-generate" @click="spGenerate" :disabled="spGenerating || spSelectedIds.length === 0">
              <span v-if="spGenerating" class="spinner"></span>
              {{ spGenerating ? '生成中...' : '🎬 生成剧本' }}
            </button>
          </div>
          <div v-if="spChapters.length === 0" class="empty">暂无章节</div>
          <div v-for="ch in spChapters" :key="ch.chapter_unique_id" class="sp-chapter-item">
            <label class="sp-chk-label">
              <input type="checkbox" :value="ch.chapter_unique_id" v-model="spSelectedIds" />
              <span class="sp-ch-name">{{ ch.chapter_name }}</span>
              <span class="sp-ch-words">{{ ch.word_count || 0 }}字</span>
              <span v-if="ch.is_published" class="sp-ch-status">已发布</span>
              <span v-else class="sp-ch-status draft">草稿</span>
            </label>
          </div>
        </div>

        <div v-if="!spNovelId" class="empty sp-hint">请先在上方选择一个作品</div>
      </div>

      <!-- 剧本结果 - 弹窗 -->
      <div v-if="spResult" class="modal-overlay" @click.self="spResult = null">
        <div class="sp-modal">
          <div class="sp-modal-header">
            <h3>🎬 剧本：{{ spResult.novel_title }}（{{ spResult.chapter_range }}）</h3>
            <div class="sp-modal-actions">
              <span class="sp-word-count">{{ spResult.word_count }} 字</span>
              <button class="btn-copy" @click="spCopyResult">📋 复制剧本</button>
              <button class="btn-close-result" @click="spResult = null">✕</button>
            </div>
          </div>
          <div class="sp-modal-body" ref="spResultRef">{{ spResult.content }}</div>
        </div>
      </div>
    </div>

    <!-- ==================== 章节概要规划 ==================== -->
    <div v-if="tab === 'outline'" class="tab-content">
      <div class="screenplay-section">
        <div class="form-row">
          <label>选择作品</label>
          <select v-model="outlineNovelId" class="sp-novel-select" @change="onOutlineNovelChange">
            <option value="">-- 请选择作品 --</option>
            <option v-for="n in myNovels" :key="n.novel_unique_id" :value="n.novel_unique_id">
              {{ n.title }}
            </option>
          </select>
        </div>

        <div v-if="outlineNovelId" class="sp-chapter-list">
          <div class="sp-chapter-header">
            <label class="sp-check-all">后续剧情大框</label>
            <span class="sp-selected-count">概要缓存 24 小时，点「生成正文」随章节落库</span>
            <button
              class="btn-generate"
              :class="{ 'btn-generate-disabled': outlineResult.length > 0 }"
              @click="outlineGenerate"
              :disabled="outlineGenerating || !outlineDirection.trim()"
              :aria-disabled="outlineResult.length > 0"
              :title="outlineResult.length > 0 ? '请先清空章节概要列表后，再生成章节概要' : ''"
            >
              <span v-if="outlineGenerating" class="spinner"></span>
              {{ outlineGenerating ? '生成中...' : '📝 生成章节概要' }}
            </button>
          </div>

          <div class="form-row">
            <textarea v-model="outlineDirection" class="wide-textarea" rows="4"
              style="width: 100%; height: 90px;"
              placeholder="描述后续剧情的整体走向，例如：主角被逐出宗门后流落落空城，意外结识青姨，逐步觉醒血脉之力，同时躲避天道教宗的追杀，为三年后的宗门大比埋下伏笔……"></textarea>
          </div>

          <div class="form-row">
            <label>生成章数</label>
            <input v-model.number="outlineCount" type="number" min="1" max="15" style="width: 120px;" />
            <span class="outline-hint">建议 5-15 章，最多 15 章</span>
          </div>

          <div v-if="outlineGenerating" class="empty">⏳ AI 正在根据已有章节概要规划后续剧情，请稍候…（约 30-90 秒）</div>

          <!-- 概要列表：只展示 Redis 缓存概要（MySQL 章节概要仅作为生成输入，不在此展示） -->
          <div class="outline-result">
            <div class="outline-result-title">
              📖 章节概要列表
              <span v-if="outlineLoading" class="outline-loading">加载中…</span>
            </div>
            <div class="outline-batch-toolbar">
              <label class="outline-select-all">
                <input
                  type="checkbox"
                  :checked="outlineAllSelected"
                  :disabled="outlineLoading || outlineGenerating || !outlineResult.length"
                  @change="toggleOutlineSelectAll"
                />
                <span>全选</span>
              </label>
              <span class="outline-selected-count">已选 {{ outlineSelectedCount }} 条</span>
              <button
                class="btn-outline-batch-delete"
                :disabled="outlineLoading || outlineSaving || outlineGenerating || !outlineSelectedCount"
                @click="outlineDeleteSelected"
              >
                {{ outlineBatchDeleting ? '删除中...' : '删除选中' }}
              </button>
              <button
                class="btn-outline-export"
                :disabled="outlineLoading || outlineGenerating || !outlineResult.length"
                @click="exportOutlines"
                title="将所有章节概要导出为TXT文件"
              >
                📥 导出概要
              </button>
            </div>

            <!-- 临时缓存概要（Redis，24h，不落库） -->
            <template v-if="outlineResult.length">
              <div class="outline-group-title">🕐 章节概要（24小时内有效，共 {{ outlineResult.length }} 章）</div>
              <div v-for="(o, i) in outlineResult" :key="'preview-' + i" class="outline-item">
                <div class="outline-item-head">
                  <input
                    v-model="outlineSelectedNumbers"
                    class="outline-item-checkbox"
                    type="checkbox"
                    :value="o.chapter_number"
                    :disabled="outlineLoading || outlineGenerating || outlineBatchDeleting"
                    aria-label="选择章节概要"
                  />
                  <span class="outline-item-num">第{{ o.chapter_number }}章</span>
                  <span class="outline-item-name">{{ outlineEditNum === o.chapter_number ? outlineEditName : o.chapter_name }}</span>
                  <span class="outline-tag pending">临时缓存</span>
                </div>
                <!-- 编辑态 -->
                <template v-if="outlineEditNum === o.chapter_number">
                  <div class="form-row">
                    <label>章节名</label>
                    <input v-model="outlineEditName" class="outline-edit-input" placeholder="请输入章节名" />
                  </div>
                  <div class="form-row">
                    <label>概要内容</label>
                    <textarea v-model="outlineEditSummary" class="outline-edit-textarea" rows="4"></textarea>
                    <div class="outline-char-count" :class="{ 'char-warn': isOutlineTooShort(outlineEditSummary) }">{{ getOutlineCharCount(outlineEditSummary) }} 字 {{ isOutlineTooShort(outlineEditSummary) ? '（不足170字）' : '' }}</div>
                  </div>
                  <div class="outline-item-actions">
                    <button class="btn-outline-save" @click="outlineUpdateOne(o)" :disabled="outlineSaving">
                      {{ outlineSaving ? '保存中...' : '✅ 保存修改' }}
                    </button>
                    <button class="btn-outline-cancel" @click="cancelOutlineEditOne">取消</button>
                  </div>
                </template>
                <!-- 查看态 -->
                <template v-else>
                  <div class="outline-item-summary">{{ o.chapter_summary }}</div>
                  <div class="outline-char-count" :class="{ 'char-warn': isOutlineTooShort(o.chapter_summary) }">{{ getOutlineCharCount(o.chapter_summary) }} 字 {{ isOutlineTooShort(o.chapter_summary) ? '（不足170字）' : '' }}</div>
                  <div class="outline-item-actions">
                    <button class="btn-outline-save" @click="outlineGenerateChapter(o)" :disabled="generating || outlineLoading || outlineBatchDeleting">
                      📝 生成正文
                    </button>
                    <button class="btn-outline-edit" @click="startOutlineEditOne(o)" :disabled="outlineLoading || outlineBatchDeleting">✏️ 修改</button>
                    <button class="btn-outline-cancel" @click="outlineDeleteOne(o)" :disabled="outlineSaving || outlineLoading || outlineBatchDeleting">
                      🗑 删除
                    </button>
                  </div>
                </template>
              </div>
            </template>

            <div v-if="!outlineLoading && !outlineResult.length" class="empty">
              暂无章节概要，输入剧情大框点击生成即可（概要临时缓存，生成正文后落库）
            </div>
          </div>
        </div>

        <div v-if="!outlineNovelId" class="empty sp-hint">请先在上方选择一个作品</div>
      </div>
    </div>

    <!-- 发布加载遮罩 -->
    <div v-if="publishOverlay.visible" class="modal-overlay publish-overlay">
      <div class="publish-modal">
        <div class="publish-spinner"></div>
        <h3>正在发布章节「{{ publishOverlay.name }}」</h3>
        <div class="publish-steps">
          <div class="step" :class="{ done: publishOverlay.step >= 1, active: publishOverlay.step === 1 }">
            <span class="step-icon">{{ publishOverlay.step > 1 ? '✅' : publishOverlay.step === 1 ? '⏳' : '○' }}</span>
            <span>保存章节文本文件</span>
          </div>
          <div class="step" :class="{ done: publishOverlay.step >= 2, active: publishOverlay.step === 2 }">
            <span class="step-icon">{{ publishOverlay.step > 2 ? '✅' : publishOverlay.step === 2 ? '⏳' : '○' }}</span>
            <span>写入章节数据库</span>
          </div>
          <div class="step" :class="{ done: publishOverlay.step >= 3, active: publishOverlay.step === 3 }">
            <span class="step-icon">{{ publishOverlay.step > 3 ? '✅' : publishOverlay.step === 3 ? '⏳' : '○' }}</span>
            <span>同步记忆体 & 作品圈</span>
          </div>
        </div>
        <p class="publish-hint">请耐心等候，数据正在录入中…</p>
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

    // 生成分页页码数组（含省略号）：如 [1, '...', 4, 5, 6, '...', 20]
    const buildPageNums = (page, count) => {
      if (count <= 7) return Array.from({ length: count }, (_, i) => i + 1)
      const set = new Set([1, count, page - 2, page - 1, page, page + 1, page + 2].filter(p => p >= 1 && p <= count))
      const sorted = [...set].sort((a, b) => a - b)
      const out = []
      let prev = 0
      for (const p of sorted) {
        if (p - prev > 1) out.push('...')
        out.push(p)
        prev = p
      }
      return out
    }
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
      writing_style_id: '',
      realms: [{ name: '', value: '' }],
      characters: [],
      sign_type: 'non_exclusive'
    })
    const createError = ref('')
    const createSuccess = ref('')
    const creationSections = reactive({ identity: true, summary: true, world: true, realm: true, characters: true })
    const creationIdentitySummary = computed(() => novelForm.title ? `${novelForm.title}${novelForm.target_reader ? ' · ' + novelForm.target_reader : ''}` : '待填写')
    const creationWorldSummary = computed(() => novelForm.story_background || novelForm.world_setting ? '设定已铺开' : '待填写')
    const creationRealmSummary = computed(() => {
      const count = novelForm.realms.filter(realm => realm.name || realm.value).length
      return count ? `${count} 个体系` : '待填写'
    })
    const creationCharacterSummary = computed(() => {
      const count = novelForm.characters.filter(character => character.name).length
      return count ? `${count} 位角色` : '尚未登场'
    })
    const creationCompleted = computed(() => [
      !!(novelForm.title && novelForm.target_reader),
      !!novelForm.description,
      !!(novelForm.story_background || novelForm.world_setting),
      novelForm.realms.some(realm => realm.name || realm.value),
      novelForm.characters.some(character => character.name)
    ].filter(Boolean).length)
    const creationProgress = computed(() => creationCompleted.value * 20)
    
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

    // 删除封面图片（已内联处理，保留空函数避免引用错误）
    const removeCover = () => { novelForm.cover_image = '' }

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
      cover_image: '',
      writing_style_id: '',
      sign_type: 'non_exclusive'
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
            cover_image: data.cover_image || '',
            writing_style_id: data.writing_style_id || '',
            sign_type: data.sign_type || 'non_exclusive'
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
          cover_image: editForm.cover_image,
          writing_style_id: editForm.writing_style_id,
          sign_type: editForm.sign_type
        }
        const res = await api.put(`/novels/update/${editForm.novel_unique_id}`, params)
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
          realm_setting: realmsJson || null, characters: charsJson,
          writing_style_id: novelForm.writing_style_id,
          sign_type: novelForm.sign_type
        }
        const res = await api.post('/novels/create', params)
        if (res.状态码 === 200) {
          createSuccess.value = '作品创建成功！'
          Object.assign(novelForm, { title: '', target_reader: '', genre: '', description: '', story_background: '', world_setting: '', cover_image: '', writing_style_id: '', realms: [{ name: '', value: '' }], characters: [], sign_type: 'non_exclusive' })
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
    const novelChapters = ref([])
    const generating = ref(false)
    const generationPreview = ref('')
    const generationStatus = ref('')
    const generationTitle = ref({ novel: '', chapter: '' })
    const generationError = ref('')
    const continuationPreviews = reactive({})
    const saving = ref(false)
    const regenerating = ref(false)
    const chapterEditIssue = ref('')
    const showChapterEditModal = ref(false)
    // 已有章节列表分页
    const chapterPage = ref(1)
    const chapterPageSize = ref(10)
    const chapterPageCount = computed(() => Math.max(1, Math.ceil(novelChapters.value.length / chapterPageSize.value)))
    const chapterPaged = computed(() => {
      if (chapterPage.value > chapterPageCount.value) chapterPage.value = chapterPageCount.value
      const s = (chapterPage.value - 1) * chapterPageSize.value
      // 章节号由大到小展示
      const sorted = [...novelChapters.value].sort((a, b) => (b.chapter_number || 0) - (a.chapter_number || 0))
      return sorted.slice(s, s + chapterPageSize.value)
    })
    const chapterPageNums = computed(() => buildPageNums(chapterPage.value, chapterPageCount.value))
    const authorStyles = ref([])
    const fetchAuthorStyles = async () => {
      try {
        const res = await api.get('/chapters/author-styles')
        if (res.状态码 === 200 && Array.isArray(res.数据)) authorStyles.value = res.数据
      } catch (e) { authorStyles.value = [] }
    }
    const chapterTemplates = ref([])
    const fetchChapterTemplates = async () => {
      try {
        const res = await api.get('/chapters/chapter-templates')
        if (res.状态码 === 200 && Array.isArray(res.数据)) chapterTemplates.value = res.数据
      } catch (e) { chapterTemplates.value = [] }
    }
    const chapterTemplateGroups = computed(() => {
      const groups = {}
      for (const t of chapterTemplates.value) {
        if (!groups[t.category]) groups[t.category] = { category: t.category, items: [] }
        groups[t.category].items.push(t)
      }
      return Object.values(groups)
    })
    const chapterForm = reactive({
      chapter_name: '', characters_involved: '', organizations: '',
      locations: '', skills: '', word_count: 2500, chapter_summary: '', content: '', author_style: '', chapter_template: '', use_anti_ai: true
    })
    const editChapterForm = reactive({
      chapter_name: '', chapter_summary: '', content: '', author_style: '', chapter_template: ''
    })
    const editingChapterId = ref(null)
    // 多选：作家风格 / 章节模板
    const selAuthorStyles = ref([])
    const selChapterTemplates = ref([])
    const selEditAuthorStyles = ref([])
    const selEditChapterTemplates = ref([])
    // 多选下拉展开状态
    const msStyleOpen = ref(false)
    const msTemplateOpen = ref(false)
    const msEditStyleOpen = ref(false)
    const msEditTemplateOpen = ref(false)
    // 多选切换：已选则取消，未选且未达上限(4个)则选中
    // 注意：模板中 ref 自动解包，此处接收的是数组本身（非 ref）
    const toggleMulti = (arr, id) => {
      const i = arr.indexOf(id)
      if (i > -1) arr.splice(i, 1)
      else if (arr.length < 4) arr.push(id)
    }

    const openChapterModal = async (novel) => {
      chapterNovel.value = novel
      showChapterModal.value = true
      editingChapterId.value = null
      selAuthorStyles.value = []
      selChapterTemplates.value = []
      msStyleOpen.value = false
      msTemplateOpen.value = false
      Object.assign(chapterForm, { chapter_name: '', characters_involved: '', organizations: '', locations: '', skills: '', word_count: 2500, chapter_summary: '', content: '', author_style: '', chapter_template: '', use_anti_ai: true })
      try {
        const res = await api.get(`/chapters/novel/${novel.novel_unique_id}`)
        if (res.状态码 === 200) { novelChapters.value = res.数据; chapterPage.value = 1 }
      } catch { novelChapters.value = [] }
    }

    const generateChapter = async () => {
      if (generating.value) return
      if (!chapterForm.chapter_name.trim()) return alert('请输入章节名称')
      if (chapterForm.word_count > 3000) {
        if (!confirm(`章节字数超过3000字上限（当前${chapterForm.word_count}字），将自动调整为3000字。是否继续？`)) return
        chapterForm.word_count = 3000
      }
      generating.value = true
      generationPreview.value = ''
      const novelId = chapterNovel.value.novel_unique_id
      generationTitle.value = { novel: chapterNovel.value.title, chapter: chapterForm.chapter_name }
      generationStatus.value = 'waiting'
      generationError.value = ''
      showChapterModal.value = false
      tab.value = 'drafts'
      try {
        const res = await api.post('/chapters/generate', {
          novel_unique_id: novelId,
          chapter_name: chapterForm.chapter_name,
          characters_involved: chapterForm.characters_involved,
          organizations: chapterForm.organizations,
          locations: chapterForm.locations,
          skills: chapterForm.skills,
          word_count: chapterForm.word_count,
          chapter_summary: chapterForm.chapter_summary,
          author_style: selAuthorStyles.value.join(','),
          chapter_template: selChapterTemplates.value.join(','),
          use_anti_ai: chapterForm.use_anti_ai
        })
        if (res.状态码 === 200 && res.数据 && res.数据.task_id) {
          // 刷新用户信息（更新免费次数）
          try { const mu = await api.get('/auth/me'); if (mu.状态码===200) { Object.assign(user, mu.数据); localStorage.setItem('novel_user', JSON.stringify(user)) } } catch {}
          const taskId = res.数据.task_id
          const task = await streamTask(taskId, chunk => {
            if (!chunk) return
            generationStatus.value = 'streaming'
            generationPreview.value += chunk
          })
          if (task.status !== 'done') throw new Error(task.error || 'AI生成失败')
          generationPreview.value = task.result?.content ?? generationPreview.value
          generationStatus.value = 'refreshing'
          if (!await fetchDrafts()) throw new Error('正文已生成，但草稿刷新失败，请稍后刷新草稿列表')
          generationStatus.value = ''
          generationPreview.value = ''
          try {
            const chapters = await api.get(`/chapters/novel/${novelId}`)
            if (chapters.状态码 === 200 && chapterNovel.value.novel_unique_id === novelId) {
              novelChapters.value = chapters.数据
            }
          } catch {}
        } else {
          throw new Error(res.消息 || '提交失败')
        }
      } catch (e) {
        const data = e.response?.data || e.response || {}
        const msg = data.数据 || data.消息 || data.detail || e.message || '网络错误，请检查后端是否启动'
        generationStatus.value = 'failed'
        generationError.value = '生成失败: ' + (typeof msg === 'string' ? msg : JSON.stringify(msg))
      } finally {
        generating.value = false
      }
    }

    // 章节概要规划
    const outlineNovelId = ref('')
    const outlineDirection = ref('')
    const outlineCount = ref(5)
    const outlineGenerating = ref(false)
    const outlineResult = ref([])        // Redis 缓存概要（24h，不落库）
    const outlineLoading = ref(false)
    const outlineSaving = ref(false)
    const outlineBatchDeleting = ref(false)
    const outlineSelectedNumbers = ref([])
    const outlineSelectedCount = computed(() => outlineSelectedNumbers.value.length)
    const outlineAllSelected = computed(() => (
      outlineResult.value.length > 0 && outlineResult.value.every(o => outlineSelectedNumbers.value.includes(o.chapter_number))
    ))
    const getOutlineCharCount = (text) => String(text || '').length
    const isOutlineTooShort = (text) => getOutlineCharCount(text) < 170
    const toggleOutlineSelectAll = (event) => {
      outlineSelectedNumbers.value = event.target.checked
        ? outlineResult.value.map(o => o.chapter_number)
        : []
    }
    const outlineEditNum = ref(null)     // 正在编辑的缓存概要章节号
    const outlineEditName = ref('')
    const outlineEditSummary = ref('')

    // 加载：只展示 Redis 缓存概要（MySQL 章节概要仅作为生成输入，不在此展示）
    const loadOutlineList = async () => {
      if (!outlineNovelId.value) { outlineResult.value = []; return }
      outlineLoading.value = true
      try {
        const cacheRes = await api.get('/chapters/outline/cache?novel_unique_id=' + outlineNovelId.value)
        if (cacheRes.状态码 === 200 && cacheRes.数据 && Array.isArray(cacheRes.数据.chapters)) {
          outlineResult.value = cacheRes.数据.chapters.slice().sort((a, b) => (a.chapter_number || 0) - (b.chapter_number || 0))
        } else {
          outlineResult.value = []
        }
        outlineSelectedNumbers.value = outlineSelectedNumbers.value.filter(number =>
          outlineResult.value.some(o => o.chapter_number === number)
        )
      } catch (e) {
        console.error('[加载章节概要失败]', e)
        outlineResult.value = []
      } finally {
        outlineLoading.value = false
      }
    }

    // 切换作品：清空缓存预览并加载该作品概要
    const onOutlineNovelChange = () => {
      outlineResult.value = []
      outlineSelectedNumbers.value = []
      loadOutlineList()
    }

    const outlineGenerate = async () => {
      if (outlineResult.value.length > 0) {
        alert('请先清空章节概要列表后，再生成章节概要')
        return
      }
      if (!outlineNovelId.value) return alert('请先选择作品')
      if (!outlineDirection.value.trim()) return alert('请输入后续剧情大框')
      outlineGenerating.value = true
      outlineResult.value = []
      outlineSelectedNumbers.value = []
      try {
        const res = await api.post('/chapters/outline/generate', {
          novel_unique_id: outlineNovelId.value,
          story_direction: outlineDirection.value,
          chapter_count: outlineCount.value
        })
        if (res.状态码 === 200 && res.数据 && res.数据.task_id) {
          const taskId = res.数据.task_id
          const task = await waitForTask(taskId, 150000, 3000)
          if (task.status === 'done') {
            await loadOutlineList()
          } else if (task.status === 'failed') {
            alert(task.error || '概要生成失败')
            return
          } else {
            alert('概要生成超时，请稍后重试')
          }
        } else {
          alert('提交失败: ' + (res.消息 || '未知错误'))
        }
      } catch (e) {
        const msg = e.response ? (e.response.数据 || e.response.消息 || JSON.stringify(e.response.data)) : (e.message || '网络错误')
        alert('概要生成失败: ' + msg)
      } finally {
        outlineGenerating.value = false
      }
    }

    // 从缓存概要一键生成正文：预填章节管理弹窗表单
    const outlineGenerateChapter = async (o) => {
      const novel = myNovels.value.find(n => n.novel_unique_id === outlineNovelId.value)
      if (!novel) return alert('作品不存在，请刷新后重试')
      await openChapterModal(novel)
      Object.assign(chapterForm, {
        chapter_name: o.chapter_name || '',
        chapter_summary: o.chapter_summary || ''
      })
      tab.value = 'my'
    }

    // 批量删除临时缓存概要：逐条调用现有删除接口，全部完成后刷新列表
    const outlineDeleteSelected = async () => {
      if (!outlineSelectedCount.value || outlineBatchDeleting.value) return
      if (!confirm(`确定删除选中的 ${outlineSelectedCount.value} 条章节概要吗？此操作不可恢复。`)) return
      outlineBatchDeleting.value = true
      try {
        const selected = outlineResult.value.filter(o => outlineSelectedNumbers.value.includes(o.chapter_number))
        let failedCount = 0
        for (const o of selected) {
          try {
            const res = await api.delete('/chapters/outline/cache', {
              data: { novel_unique_id: outlineNovelId.value, chapter_number: o.chapter_number }
            })
            if (res.状态码 !== 200) failedCount++
          } catch (e) {
            failedCount++
          }
        }
        alert(failedCount ? `删除完成，${failedCount} 条概要删除失败，请稍后重试` : '选中概要已删除')
        await loadOutlineList()
      } catch (e) {
        const msg = e.response ? (e.response.数据 || e.response.消息 || JSON.stringify(e.response.data)) : (e.message || '网络错误')
        alert('批量删除失败: ' + msg)
        await loadOutlineList()
      } finally {
        outlineBatchDeleting.value = false
      }
    }

    // 导出所有章节概要为TXT文件
    const exportOutlines = () => {
      if (!outlineResult.value.length) return
      const lines = outlineResult.value.map(o => {
        return `第${o.chapter_number}章 ${o.chapter_name}\n${'─'.repeat(40)}\n${o.chapter_summary}\n`
      })
      const content = `章节概要导出\n${'═'.repeat(50)}\n共 ${outlineResult.value.length} 章\n${'═'.repeat(50)}\n\n${lines.join('\n')}`
      const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `章节概要_${new Date().toISOString().slice(0, 10)}.txt`
      a.click()
      URL.revokeObjectURL(url)
    }

    // 删除单条临时缓存概要（不落库，直接丢弃）
    const outlineDeleteOne = async (o) => {
      if (!confirm(`确定删除第${o.chapter_number}章《${o.chapter_name}》的缓存概要吗？`)) return
      outlineSaving.value = true
      try {
        const res = await api.delete('/chapters/outline/cache', {
          data: { novel_unique_id: outlineNovelId.value, chapter_number: o.chapter_number }
        })
        if (res.状态码 === 200) {
          await loadOutlineList()
          alert(res.消息 || '已删除')
        } else {
          alert(res.消息 || '删除失败')
        }
      } catch (e) {
        const msg = e.response ? (e.response.数据 || e.response.消息 || JSON.stringify(e.response.data)) : (e.message || '网络错误')
        alert('删除失败: ' + msg)
      } finally {
        outlineSaving.value = false
      }
    }

    // 进入缓存概要编辑态
    const startOutlineEditOne = (o) => {
      outlineEditNum.value = o.chapter_number
      outlineEditName.value = o.chapter_name || ''
      outlineEditSummary.value = o.chapter_summary || ''
    }
    const cancelOutlineEditOne = () => { outlineEditNum.value = null }

    // 保存缓存概要的修改（更新 Redis，不落库）
    const outlineUpdateOne = async (o) => {
      if (!outlineEditName.value.trim()) { alert('章节名不能为空'); return }
      outlineSaving.value = true
      try {
        const res = await api.put('/chapters/outline/cache', {
          novel_unique_id: outlineNovelId.value,
          chapter_number: o.chapter_number,
          chapter_name: outlineEditName.value.trim(),
          chapter_summary: outlineEditSummary.value.trim()
        })
        if (res.状态码 === 200) {
          outlineEditNum.value = null
          await loadOutlineList()
          alert(res.消息 || '概要已更新')
        } else {
          alert(res.消息 || '更新失败')
        }
      } catch (e) {
        const msg = e.response ? (e.response.数据 || e.response.消息 || JSON.stringify(e.response.data)) : (e.message || '网络错误')
        alert('更新失败: ' + msg)
      } finally {
        outlineSaving.value = false
      }
    }

    // 草稿
    const drafts = ref([])
    const continuing = reactive({})
    const publishing = reactive({})
    const publishOverlay = reactive({ visible: false, name: '', step: 0 })

    const streamTask = (taskId, onChunk) => new Promise((resolve, reject) => {
      const source = new EventSource('/api/chapters/tasks/' + taskId + '/stream')
      let settled = false
      const finish = (callback, value) => {
        if (settled) return
        settled = true
        source.close()
        callback(value)
      }
      source.onmessage = event => {
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'chunk') onChunk(data.content || '')
          if (data.type === 'done') finish(resolve, { status: 'done', result: data.result || null })
          if (data.type === 'error') finish(reject, new Error(data.error || '任务执行失败'))
        } catch (error) {
          finish(reject, error)
        }
      }
      source.onerror = () => finish(reject, new Error('流式连接中断'))
    })

    const waitForTask = async (taskId, maxWait = 120000, pollInterval = 3000) => {
      let waited = 0
      let consecutiveFailures = 0
      while (waited < maxWait) {
        await new Promise(r => setTimeout(r, pollInterval))
        waited += pollInterval
        try {
          const statusRes = await api.get('/chapters/tasks/' + taskId)
          if (statusRes.状态码 === 200 && statusRes.数据) {
            consecutiveFailures = 0
            const task = statusRes.数据
            if (task.status === 'done') return { status: 'done', result: task.result?.data || null }
            if (task.status === 'failed') return { status: 'failed', error: task.error || '任务执行失败' }
          } else {
            consecutiveFailures++
          }
        } catch (e) {
          consecutiveFailures++
          console.warn(`[任务轮询] 第${consecutiveFailures}次失败`, e)
        }
        if (consecutiveFailures >= 5) {
          return { status: 'failed', error: '任务状态连续5次查询失败，请稍后重试' }
        }
      }
      return { status: 'timeout', result: null }
    }

    const fetchDrafts = async () => {
      try {
        const res = await api.get('/chapters/drafts')
        if (res.状态码 === 200) {
          drafts.value = (res.数据 || []).slice().reverse()
          return true
        }
        console.error('获取草稿列表失败:', res)
      } catch (e) { console.error('获取草稿列表异常:', e) }
      return false
    }

    const publishChapter = async (d) => {
      if (!d.content || d.content.trim() === '') {
        alert('章节内容为空，无法发布')
        return
      }
      if (!confirm(`确定发布章节「${d.chapter_name}」到作品圈？`)) return

      // 检查今日发布配额，达到上限提示并拦截
      if (quotaRemaining.value <= 0) {
        if (vipLevel.value === 0) {
          alert(`今日免费发布已用完(6次/天)，开通VIP会员可获得10次/天`)
        } else if (vipLevel.value === 1) {
          alert(`今日VIP发布已用完(10次/天)，升级SVIP会员可获得50次/天`)
        } else if (vipLevel.value >= 2) {
          alert(`今日SVIP发布已用完(50次/天)，请明天再来`)
        }
        return
      }

      publishing[d.chapter_unique_id] = true
      publishOverlay.visible = true
      publishOverlay.name = d.chapter_name
      publishOverlay.step = 1

      try {
        const body = { content: d.content }

        // 阶段2：调用后端 API（后端内部三阶段验证：txt→MySQL→ChromaDB）
        publishOverlay.step = 2
        const res = await api.post(`/chapters/publish/${d.chapter_unique_id}`, body)

        // 阶段3：后端返回成功 = 三阶段全部验证通过
        publishOverlay.step = 3
        if (res.状态码 === 200) {
          await new Promise(r => setTimeout(r, 400)) // 短暂停留让用户看到全绿
          publishOverlay.visible = false
          alert(res.消息)
          drafts.value = drafts.value.filter(draft => draft.chapter_unique_id !== d.chapter_unique_id)
          await fetchDrafts()
          await fetchTodayPublished()
          // 概要已随发布自动转入 MySQL 章节概要：刷新概要缓存列表
          if (outlineNovelId.value && outlineNovelId.value === d.novel_unique_id) await loadOutlineList()
        } else {
          publishOverlay.visible = false
          alert(res.消息)
        }
      } catch (e) {
        publishOverlay.visible = false
        alert('发布失败: ' + (e.response?.data?.detail || e.message))
      } finally {
        publishing[d.chapter_unique_id] = false
        publishOverlay.visible = false
        publishOverlay.step = 0
      }
    }

    const deleteDraft = async (d) => {
      if (!confirm('确定删除该草稿？')) return
      try {
        const res = await api.delete(`/chapters/delete/${d.chapter_unique_id}`)
        if (res.状态码 === 200) {
          alert('删除成功')
          await fetchDrafts()
        } else alert(res.消息)
      } catch (e) { alert('删除失败') }
    }

    const deleteChapter = async (ch) => {
      if (!confirm(`确定删除章节「${ch.chapter_name}」？此操作不可恢复。`)) return
      try {
        const res = await api.delete(`/chapters/delete/${ch.chapter_unique_id}`)
        if (res.状态码 === 200) {
          alert('删除成功')
          const r2 = await api.get(`/chapters/novel/${chapterNovel.value.novel_unique_id}`)
          if (r2.状态码 === 200) { novelChapters.value = r2.数据; chapterPage.value = 1 }
          fetchTodayPublished()
        } else alert(res.消息)
      } catch (e) { alert('删除失败') }
    }

    const editChapter = (ch) => {
      editingChapterId.value = ch.chapter_unique_id
      Object.assign(editChapterForm, {
        chapter_name: ch.chapter_name || '',
        chapter_summary: ch.chapter_summary || '',
        content: ch.content || '',
        author_style: ch.author_style || '',
        chapter_template: ch.chapter_template || ''
      })
      // 多选回填（逗号分隔字符串 → 数组）
      selEditAuthorStyles.value = (ch.author_style || '').split(',').map(s => s.trim()).filter(Boolean)
      selEditChapterTemplates.value = (ch.chapter_template || '').split(',').map(s => s.trim()).filter(Boolean)
      msEditStyleOpen.value = false
      msEditTemplateOpen.value = false
      chapterEditIssue.value = ''
      showChapterEditModal.value = true
    }

    const copyChapterContent = () => {
      const text = editChapterForm.content
      if (!text) return alert('正文内容为空')
      // 优先使用 Clipboard API（HTTPS 环境）
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => {
          alert('✅ 复制成功')
        }).catch(() => {
          fallbackCopy(text)
        })
      } else {
        fallbackCopy(text)
      }
    }

    const fallbackCopy = (text) => {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.left = '-9999px'
      ta.style.top = '-9999px'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.focus()
      ta.select()
      ta.setSelectionRange(0, text.length)
      let ok = false
      try {
        ok = document.execCommand('copy')
      } catch (e) { /* ignore */ }
      document.body.removeChild(ta)
      if (ok) {
        alert('✅ 复制成功')
      } else {
        // 终极兜底：弹出提示框让用户手动复制
        prompt('复制失败，请手动复制以下内容（Ctrl+C）：', text)
      }
    }

    const saveChapterEdit = async () => {
      if (!editChapterForm.chapter_name) {
        chapterEditIssue.value = '保存失败：请输入章节名称'
        return
      }
      chapterEditIssue.value = ''
      saving.value = true
      try {
        const res = await api.put(`/chapters/update/${editingChapterId.value}`, {
          content: editChapterForm.content,
          chapter_name: editChapterForm.chapter_name,
          chapter_summary: editChapterForm.chapter_summary
        })
        if (res.状态码 === 200) {
          alert('章节修改成功')
          const r2 = await api.get(`/chapters/novel/${chapterNovel.value.novel_unique_id}`)
          if (r2.状态码 === 200) { novelChapters.value = r2.数据; chapterPage.value = 1 }
          showChapterEditModal.value = false
        } else {
          chapterEditIssue.value = '保存失败：' + (res.消息 || '服务器未能保存章节')
          alert(res.消息)
        }
      } catch (e) {
        const msg = e.response?.data?.消息 || e.response?.data?.detail || e.message || '网络错误'
        chapterEditIssue.value = '保存失败：' + msg
        alert('修改失败: ' + msg)
      } finally { saving.value = false }
    }

    const regenerateChapter = async () => {
      if (!editChapterForm.chapter_name) {
        chapterEditIssue.value = '重新生成失败：请输入章节名称'
        return
      }
      if (!confirm('AI重新生成将覆盖当前章节内容，确定继续？')) return
      if (regenerating.value) return
      chapterEditIssue.value = ''
      regenerating.value = true
      try {
        const res = await api.post(`/chapters/regenerate/${editingChapterId.value}`, {
          chapter_summary: editChapterForm.chapter_summary,
          word_count: chapterForm.word_count,
          author_style: selEditAuthorStyles.value.join(','),
          chapter_template: selEditChapterTemplates.value.join(','),
          use_anti_ai: chapterForm.use_anti_ai
        })
        if (res.状态码 === 200 && res.数据 && res.数据.task_id) {
          // 异步任务：轮询结果（重新生成耗时可达数分钟，同步请求会被公网隧道/浏览器掐断）
          const taskId = res.数据.task_id
          let preview = ''
          const task = await streamTask(taskId, chunk => {
            preview += chunk
            editChapterForm.content = preview
          })
          if (task.status === 'done') {
            const newContent = task.result?.content ?? preview
            if (newContent) {
              editChapterForm.content = newContent
              chapterEditIssue.value = ''
              await fetchDrafts()
              const chapters = await api.get(`/chapters/novel/${chapterNovel.value.novel_unique_id}`)
              if (chapters.状态码 === 200) novelChapters.value = chapters.数据
              alert('重新生成成功，内容已更新到编辑区')
            } else {
              chapterEditIssue.value = '重新生成失败：任务完成但没有返回章节正文'
              alert('重新生成成功，但未能获取内容')
            }
          } else if (task.status === 'failed') {
            chapterEditIssue.value = '重新生成失败：' + (task.error || '任务执行失败')
            alert('AI重新生成失败: ' + task.error)
          } else {
            chapterEditIssue.value = '重新生成失败：任务超时，请稍后重试'
            alert('AI重新生成超时，请稍后查看章节内容')
          }
        } else {
          chapterEditIssue.value = '重新生成失败：' + (res.消息 || '提交失败')
          alert('重新生成失败: ' + (res.消息 || '提交失败'))
        }
      } catch (e) {
        const msg = e.response?.data?.消息 || e.response?.data?.detail || e.message || '网络错误'
        chapterEditIssue.value = '重新生成失败：' + msg
        alert('AI重新生成失败: ' + msg)
      } finally {
        regenerating.value = false
      }
    }

    const continueChapter = async (d) => {
      // 非VIP且次数用完的前端拦截
      if (!isVip.value && freeQuota.value <= 0) {
        alert('免费生成次数已用完，请开通VIP继续使用')
        router.push('/vip')
        return
      }
      if (continuing[d.chapter_unique_id]) return
      continuing[d.chapter_unique_id] = true
      continuationPreviews[d.chapter_unique_id] = ''
      try {
        const res = await api.post(`/chapters/continue/${d.chapter_unique_id}`, null, { params: { word_count: 800, use_anti_ai: chapterForm.use_anti_ai } })
        if (res.状态码 === 200 && res.数据?.task_id) {
          // 异步任务：轮询续写结果
          const taskId = res.数据.task_id
          const task = await streamTask(taskId, chunk => {
            continuationPreviews[d.chapter_unique_id] += chunk
          })
          if (task.status === 'done') {
            const result = task.result
            continuationPreviews[d.chapter_unique_id] = result?.continued_text ?? continuationPreviews[d.chapter_unique_id]
            await fetchDrafts()
            const added = Array.from(continuationPreviews[d.chapter_unique_id]).length
            alert(`续写成功！新增 ${added} 字`)
          } else if (task.status === 'failed') {
            alert('AI续写失败: ' + task.error)
          } else {
            alert('AI续写超时，请稍后查看章节内容')
          }
        } else {
          alert(res.消息 || '提交失败')
        }
      } catch (e) {
        const data = e.response?.data || e.response || {}
        const msg = data.数据 || data.消息 || data.detail || e.message || '网络错误，请检查后端是否启动'
        alert('续写失败: ' + (typeof msg === 'string' ? msg : JSON.stringify(msg)))
      }
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

    // ============================================================
    // 剧本创作
    // ============================================================
    const spNovelId = ref('')
    const spChapters = ref([])
    const spSelectedIds = ref([])
    const spGenerating = ref(false)
    const spResult = ref(null)
    const spResultRef = ref(null)
    let spPollTimer = null

    const spAllSelected = computed(() =>
      spChapters.value.length > 0 && spSelectedIds.value.length === spChapters.value.length
    )

    const initScreenplay = () => {
      fetchMyNovels()
      spNovelId.value = ''
      spChapters.value = []
      spSelectedIds.value = []
      spResult.value = null
    }

    const spLoadChapters = async () => {
      spChapters.value = []
      spSelectedIds.value = []
      spResult.value = null
      if (!spNovelId.value) return
      try {
        const res = await api.get(`/chapters/novel/${spNovelId.value}`)
        if (res.状态码 === 200) {
          spChapters.value = res.数据 || []
        }
      } catch (e) {
        alert('获取章节列表失败')
      }
    }

    const spToggleAll = () => {
      if (spAllSelected.value) {
        spSelectedIds.value = []
      } else {
        spSelectedIds.value = spChapters.value.map(c => c.chapter_unique_id)
      }
    }

    const spGenerate = async () => {
      if (spSelectedIds.value.length === 0) return
      spGenerating.value = true
      spResult.value = null
      try {
        const res = await api.post('/screenplay/generate', {
          novel_unique_id: spNovelId.value,
          chapter_ids: spSelectedIds.value,
        })
        if (res.状态码 === 200) {
          const taskId = res.数据.task_id
          spPollTimer = setInterval(async () => {
            try {
              const pollRes = await api.get(`/screenplay/tasks/${taskId}`)
              const status = pollRes.数据
              if (status.status === 'done') {
                clearInterval(spPollTimer)
                spPollTimer = null
                spGenerating.value = false
                if (status.result && status.result.success) {
                  spResult.value = status.result.data
                } else {
                  alert('剧本生成失败: ' + (status.result?.error || '未知错误'))
                }
              } else if (status.status === 'failed') {
                clearInterval(spPollTimer)
                spPollTimer = null
                spGenerating.value = false
                alert('剧本生成失败: ' + (status.error || '未知错误'))
              }
            } catch (e) {
              // 轮询出错时忽略，继续重试
            }
          }, 3000)
        } else {
          spGenerating.value = false
          alert(res.消息 || '提交失败')
        }
      } catch (e) {
        spGenerating.value = false
        alert('提交失败: ' + (e.message || ''))
      }
    }

    const spCopyResult = () => {
      if (!spResult.value?.content) return
      const text = spResult.value.content
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => {
          alert('✅ 复制成功')
        }).catch(() => {
          fallbackCopy(text)
        })
      } else {
        fallbackCopy(text)
      }
    }

    const downloadNovel = async (novel) => {
      try {
        const blob = await api.get(`/chapters/download/${novel.novel_unique_id}`, { responseType: 'blob' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `${novel.title || '作品'}.zip`
        a.click()
        URL.revokeObjectURL(url)
      } catch (e) {
        alert('下载失败: ' + (e.response?.data?.detail || e.message))
      }
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

    // 点击下拉外部时收起所有多选下拉
    const closeAllMultiSelect = (e) => {
      if (!e.target.closest('.multi-select')) {
        msStyleOpen.value = false
        msTemplateOpen.value = false
        msEditStyleOpen.value = false
        msEditTemplateOpen.value = false
      }
    }

    onMounted(() => {
      // 页面挂载时拉取最新用户状态（VIP开通后回来是最新）
      syncUserFromServer().then(() => fetchTodayPublished())
      window.addEventListener('user-info-changed', onUserChanged)
      document.addEventListener('click', closeAllMultiSelect)
      fetchMyNovels()
      fetchAuthorStyles()
      fetchChapterTemplates()
    })

    onUnmounted(() => {
      window.removeEventListener('user-info-changed', onUserChanged)
      document.removeEventListener('click', closeAllMultiSelect)
    })

    return { tab, isVip, isSvip, vipLevel, freeQuota, publishedToday, maxDailyQuota, quotaRemaining, quotaPercent, levelLabel, levelDesc, fetchTodayPublished, novelForm, createError, createSuccess, handleCreateNovel,
      myNovels, fetchMyNovels,
      creationSections, creationIdentitySummary, creationWorldSummary, creationRealmSummary, creationCharacterSummary, creationCompleted, creationProgress,
      showChapterModal, chapterNovel, novelChapters, chapterForm, generating, generationPreview, generationStatus, generationTitle, generationError, continuationPreviews,
      openChapterModal, generateChapter, authorStyles, fetchAuthorStyles,
      chapterTemplates, fetchChapterTemplates, chapterTemplateGroups,
      selAuthorStyles, selChapterTemplates, selEditAuthorStyles, selEditChapterTemplates,
      msStyleOpen, msTemplateOpen, msEditStyleOpen, msEditTemplateOpen, toggleMulti,
      chapterPage, chapterPageSize, chapterPaged, chapterPageCount, chapterPageNums,
      drafts, fetchDrafts, publishChapter, deleteDraft, deleteChapter, editChapter, saveChapterEdit, regenerateChapter, continueChapter, continuing, deleteNovel, downloadNovel, formatTime, saving, regenerating, chapterEditIssue, showChapterEditModal, editChapterForm,
      publishing, publishOverlay,
      genreOptions, selectedGenres, toggleGenre, handleCoverUpload,
      showEditModal, editForm, editSelectedGenres, editError, editSuccess,
      openEditModal, toggleEditGenre, handleEditCoverUpload, handleUpdateNovel,
      spNovelId, spChapters, spSelectedIds, spGenerating, spResult, spResultRef,
      spAllSelected, initScreenplay, spLoadChapters, spToggleAll, spGenerate, spCopyResult,
      outlineNovelId, outlineDirection, outlineCount, outlineGenerating, outlineResult,
      outlineLoading, outlineSaving,
      outlineSelectedNumbers, outlineSelectedCount, outlineAllSelected, outlineBatchDeleting,
      getOutlineCharCount, isOutlineTooShort, toggleOutlineSelectAll, outlineDeleteSelected, exportOutlines,
      outlineEditNum, outlineEditName, outlineEditSummary,
      startOutlineEditOne, cancelOutlineEditOne, outlineUpdateOne,
      loadOutlineList, onOutlineNovelChange, outlineGenerate, outlineGenerateChapter, outlineDeleteOne,
      copyChapterContent, fallbackCopy,
    }
  }
}
</script>

<style scoped>
.page-title { font-size: 24px; margin-bottom: 20px; color: var(--text-primary); font-weight: 700; }

/* 配额横幅 */
.quota-banner {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 14px; padding: 18px 24px; margin-bottom: 20px;
  display: flex; align-items: center; gap: 20px; flex-wrap: wrap;
  backdrop-filter: blur(10px);
}
.quota-banner.level-0 { border-color: var(--border-hover); background: linear-gradient(135deg, var(--border), var(--bg-card)); }
.quota-banner.level-1 { border-color: var(--border-hover); background: linear-gradient(135deg, var(--border), var(--bg-card)); }
.quota-banner.level-2 { border-color: var(--border-hover); background: linear-gradient(135deg, var(--border), var(--bg-card)); }

.quota-level { display: flex; align-items: center; gap: 10px; }
.level-badge {
  padding: 4px 14px; border-radius: 20px; font-size: 13px; font-weight: 700;
  white-space: nowrap;
}
.level-0 .level-badge { background: var(--btn-bg); color: var(--success-text); border: 1px solid var(--border-hover); }
.level-1 .level-badge { background: var(--btn-bg); color: var(--accent-text); border: 1px solid var(--border-hover); }
.level-2 .level-badge { background: linear-gradient(135deg, var(--btn-bg), rgba(239,68,68,0.15)); color: var(--gold); border: 1px solid var(--border-hover); }
.level-desc { font-size: 13px; color: var(--text-secondary); }

.quota-progress { flex: 1; min-width: 200px; }
.quota-bar-bg { height: 6px; background: var(--bg-card); border-radius: 3px; margin-bottom: 6px; overflow: hidden; }
.quota-bar-fill { height: 100%; border-radius: 3px; transition: width 0.5s ease; }
.level-0 .quota-bar-fill { background: linear-gradient(90deg, #10b981, #34d399); }
.level-1 .quota-bar-fill { background: linear-gradient(90deg, #06b6d4, #38bdf8); }
.level-2 .quota-bar-fill { background: linear-gradient(90deg, #f59e0b, #fbbf24); }
.quota-text { font-size: 13px; color: var(--text-secondary); }
.quota-text b { color: var(--text-primary); }

.quota-action {
  padding: 8px 20px; border-radius: 8px; font-size: 13px; font-weight: 600;
  text-decoration: none; white-space: nowrap; transition: all 0.3s;
  background: linear-gradient(135deg, #06b6d4, #8b5cf6); color: #fff;
  box-shadow: 0 2px 12px var(--border-hover);
}
.quota-action:hover { box-shadow: 0 4px 20px var(--border-hover); transform: translateY(-1px); }
.quota-action.gold { background: linear-gradient(135deg, #f59e0b, #ef4444); box-shadow: 0 2px 12px var(--border-hover); }
.quota-action.gold:hover { box-shadow: 0 4px 20px var(--border-hover); }

/* Tabs */
.tabs { display: flex; gap: 4px; margin-bottom: 28px; }
.tabs span { 
  padding: 10px 24px; cursor: pointer; font-size: 14px; font-weight: 600;
  color: var(--text-muted); border-radius: 10px; transition: all 0.3s;
  background: var(--bg-card); border: 1px solid var(--border);
}
.tabs span:hover { color: var(--accent-text); border-color: var(--border-hover); }
.tabs span.active { 
  color: var(--accent-text); background: linear-gradient(135deg, var(--btn-bg), var(--btn-bg));
  border-color: var(--border-focus); box-shadow: 0 0 20px var(--btn-bg);
}
.tab-content { min-height: 400px; }
.no-permission { text-align: center; padding: 80px; background: var(--bg-card); border: 1px solid var(--border); border-radius: 14px; color: var(--text-muted); font-size: 15px; }
.no-permission p { margin: 0; }
.link-vip { color: var(--gold); font-weight: 700; text-decoration: underline; }

/* 免费体验 banner */
.free-banner {
  text-align: center; padding: 16px 24px; background: linear-gradient(135deg, var(--btn-bg), rgba(5,150,105,0.08));
  border: 1px solid var(--border-hover); border-radius: 12px; color: var(--success-text); font-size: 14px;
  margin-bottom: 20px; display: flex; align-items: center; justify-content: center; gap: 16px; flex-wrap: wrap;
}
.free-banner b { color: var(--success-text); font-size: 18px; }
.btn-upgrade {
  display: inline-block; padding: 6px 16px; background: linear-gradient(135deg, #f59e0b, #d97706);
  color: #fff; border-radius: 8px; font-size: 13px; font-weight: 600; text-decoration: none;
  transition: all 0.2s;
}
.btn-upgrade:hover { box-shadow: 0 4px 16px var(--border-hover); }

/* Form */
.create-form { max-width: 960px; display: flex; flex-direction: column; gap: 16px; }
.creation-canvas { max-width: 1040px; gap: 14px; }
.canvas-intro { display: flex; justify-content: space-between; align-items: flex-end; gap: 24px; padding: 10px 4px 18px; }
.eyebrow { display: block; color: var(--accent-text); font-size: 11px; letter-spacing: .18em; font-weight: 800; margin-bottom: 10px; }
.canvas-intro h1 { margin: 0; color: var(--text-primary); font-size: clamp(24px, 4vw, 38px); letter-spacing: -.04em; line-height: 1.15; }
.canvas-intro p { margin: 10px 0 0; color: var(--text-muted); font-size: 14px; }
.canvas-progress { min-width: 150px; display: flex; flex-direction: column; gap: 6px; color: var(--text-muted); font-size: 12px; text-align: right; }
.canvas-progress strong { color: var(--text-primary); font-size: 26px; line-height: 1; }
.canvas-progress i { display: block; width: 150px; height: 5px; overflow: hidden; background: var(--bg-input); border-radius: 10px; }
.canvas-progress b { display: block; height: 100%; background: var(--brand-gradient); border-radius: inherit; transition: width .35s ease; }
.canvas-card { position: relative; overflow: hidden; background: color-mix(in srgb, var(--bg-card) 94%, #fff 6%); border: 1px solid var(--border); border-radius: 18px; box-shadow: 0 16px 36px rgba(0, 0, 0, .08); transition: border-color .25s, box-shadow .25s; }
.canvas-card:hover { border-color: var(--border-hover); box-shadow: 0 18px 42px rgba(0, 0, 0, .12); }
.canvas-card::after { content: ''; position: absolute; top: 0; right: 0; width: 36%; height: 1px; background: var(--brand-gradient); opacity: .7; }
.card-heading { width: 100%; display: flex; align-items: center; gap: 12px; padding: 20px 24px; border: 0; background: transparent; color: var(--text-primary); text-align: left; cursor: pointer; }
.card-index { color: var(--accent-text); font: 800 12px/1 'Courier New', monospace; letter-spacing: .08em; }
.card-heading .section-icon { font-size: 20px; }
.card-title { display: flex; flex: 1; flex-direction: column; gap: 4px; }
.card-title strong { font-size: 16px; }
.card-title small { color: var(--text-muted); font-size: 12px; font-weight: 400; }
.card-state { max-width: 180px; overflow: hidden; color: var(--accent-text); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.card-toggle { min-width: 34px; color: var(--text-muted); font-size: 12px; text-align: right; }
.card-body { padding: 0 24px 26px; animation: canvasReveal .25s ease; }
.canvas-card.collapsed .card-heading { padding-bottom: 20px; }
@keyframes canvasReveal { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: translateY(0); } }
.identity-layout { display: grid; grid-template-columns: minmax(0, 1fr) 220px; gap: 28px; }
.identity-fields { min-width: 0; }
.field-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.cover-stage { min-height: 270px; display: flex; flex-direction: column; justify-content: center; align-items: center; padding: 16px; border: 1px dashed var(--border-hover); border-radius: 14px; background: linear-gradient(145deg, var(--bg-input), var(--bg-card)); }
.stage-label { align-self: flex-start; color: var(--text-muted); font: 10px/1 'Courier New', monospace; letter-spacing: .16em; }
.upload-placeholder { position: relative; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; min-height: 190px; color: var(--text-muted); text-align: center; }
.upload-placeholder span { color: var(--accent-text); font-size: 32px; }
.upload-placeholder b { color: var(--text-primary); font-size: 15px; }
.upload-placeholder small { font-size: 11px; }
.upload-placeholder input { position: absolute; inset: 0; width: 100%; height: 100%; cursor: pointer; opacity: 0; }
.cover-stage .image-upload .preview img { max-width: 170px; max-height: 230px; }
.canvas-footer { padding: 8px 0 18px; }
.canvas-footer .btn-create { max-width: 360px; }
.canvas-footer .btn-create span { margin-left: 12px; font-size: 18px; }
.realm-item { display: grid; grid-template-columns: 34px 1fr auto; align-items: start; gap: 12px; }
.realm-number { padding-top: 10px; color: var(--accent-text); font: 700 12px/1 'Courier New', monospace; }
.realm-fields { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.form-section {
  background: var(--bg-card); border: 1px solid var(--border); border-radius: 14px;
  padding: 22px 24px; backdrop-filter: blur(10px);
}
.section-title {
  display: flex; align-items: center; gap: 8px;
  font-size: 15px; font-weight: 700; color: var(--text-primary);
  margin-bottom: 18px; padding-bottom: 12px;
  border-bottom: 1px solid var(--border);
}
.section-icon { font-size: 18px; }
.form-row { margin-bottom: 16px; }
.form-row:last-child { margin-bottom: 0; }
.form-row > label { display: block; margin-bottom: 6px; font-weight: 600; font-size: 13px; color: var(--text-secondary); }
.form-row input, .form-row select, .form-row textarea { 
  width: 100%; padding: 10px 14px; border: 1px solid var(--border); 
  border-radius: 8px; font-size: 14px; background: var(--bg-input); color: var(--text-primary);
  transition: border-color 0.3s;
}
.form-row input:focus, .form-row select:focus, .form-row textarea:focus { outline: none; border-color: var(--border-focus); box-shadow: 0 0 12px var(--btn-bg); }
.form-row textarea { resize: vertical; }
.form-row textarea.over { border-color: #f87171; }
.form-row select { cursor: pointer; color: var(--text-primary); }
.form-row select option { background: var(--bg-deep); color: var(--text-primary); }

/* Two column layout */
.form-two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
.form-two-col .col-left, .form-two-col .col-right { display: flex; flex-direction: column; gap: 4px; }

.form-row-meta { display: flex; justify-content: space-between; align-items: center; margin-top: 6px; }
.char-count { font-weight: normal; font-size: 12px; color: var(--text-muted); }
.char-count.over { color: #f87171; }
.field-error { color: #f87171; font-size: 12px; }

/* Form footer */
.form-footer { margin-top: 8px; text-align: center; }
.form-footer .error { color: #f87171; margin-bottom: 10px; }
.form-footer .success { color: #10b981; margin-bottom: 10px; }
.btn-create {
  width: 100%; max-width: 320px; padding: 12px 32px; border: none; border-radius: 10px;
  font-size: 15px; font-weight: 700; cursor: pointer;
  background: linear-gradient(135deg, #06b6d4, #8b5cf6); color: #fff;
  box-shadow: 0 4px 20px var(--border-hover); transition: all 0.3s;
}
.btn-create:hover:not(:disabled) { box-shadow: 0 6px 28px var(--border-hover); transform: translateY(-2px); }
.btn-create:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }

@media (max-width: 720px) {
  .form-two-col { grid-template-columns: 1fr; }
  .create-form { max-width: 100%; }
  .canvas-intro { align-items: flex-start; flex-direction: column; }
  .canvas-progress { width: 100%; text-align: left; }
  .canvas-progress i { width: 100%; }
  .identity-layout, .field-grid { grid-template-columns: 1fr; }
  .card-heading, .card-body { padding-left: 16px; padding-right: 16px; }
  .card-state { display: none; }
}

/* Image upload */
.image-upload { width: 100%; }
.image-upload .preview { position: relative; display: inline-block; }
.image-upload .preview img { max-width: 180px; max-height: 180px; border-radius: 10px; border: 1px solid var(--border); }
.image-upload .preview .btn-remove { position: absolute; top: -8px; right: -8px; background: var(--error-text); color: #fff; border: none; border-radius: 50%; width: 24px; height: 24px; cursor: pointer; font-size: 12px; }
.image-upload input[type="file"] { width: 100%; padding: 10px; border: 1px dashed var(--border-hover); border-radius: 8px; cursor: pointer; color: var(--text-secondary); background: var(--bg-input); }

/* Edit modal */
.edit-modal { max-width: 700px; max-height: 80vh; overflow-y: auto; }
.edit-modal form { padding: 20px 0; }
.edit-modal button[type="submit"] { width: 100%; padding: 12px; background: linear-gradient(135deg, #06b6d4, #8b5cf6); color: #fff; border: none; border-radius: 8px; cursor: pointer; font-size: 15px; font-weight: 600; transition: all 0.3s; }
.edit-modal button[type="submit"]:hover { box-shadow: 0 4px 24px var(--border-hover); }

/* Genre tags */
.anti-ai-toggle { display: flex; align-items: center; gap: 8px; margin: 10px 0; font-size: 13px; color: var(--text-muted); cursor: pointer; }
.anti-ai-toggle input { width: auto; cursor: pointer; }
.genre-select { display: flex; flex-wrap: wrap; gap: 8px; }.genre-tag { padding: 6px 16px; border: 1px solid var(--border); border-radius: 20px; cursor: pointer; font-size: 13px; color: var(--text-muted); background: var(--bg-input); transition: all 0.2s; }
.genre-tag:hover { border-color: var(--border-focus); color: var(--accent-text); }
.genre-tag.active { background: linear-gradient(135deg, var(--border), var(--border-hover)); color: var(--accent-text); border-color: rgba(6,182,212,0.6); box-shadow: 0 0 12px var(--btn-bg); }

/* Realm */
.realm-item { display: flex; flex-direction: column; gap: 6px; margin-bottom: 8px; padding: 12px; background: var(--bg-input); border: 1px solid var(--border); border-radius: 8px; }
.card-realm .realm-fields { width: 100%; }
.card-realm .realm-fields input { width: 680px; max-width: 100%; box-sizing: border-box; }
.card-realm .realm-fields textarea { width: 100%; max-width: 100%; height: 220px; min-height: 220px; max-height: 220px; box-sizing: border-box; resize: none; }

/* Character card */
.char-card { border: 1px solid var(--border); border-radius: 10px; padding: 16px; margin-bottom: 12px; background: var(--bg-input); }
.char-header { display: flex; justify-content: space-between; margin-bottom: 10px; color: var(--text-primary); }
.char-fields { display: flex; flex-wrap: wrap; gap: 10px; }
.char-fields .half { width: calc(50% - 5px); }
.char-fields .full { width: 100%; }
.char-fields label { display: block; font-size: 12px; color: var(--text-muted); margin-bottom: 3px; }
.char-fields input, .char-fields select, .char-fields textarea { width: 100%; padding: 8px 10px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; background: var(--bg-input); color: var(--text-primary); }
.char-fields textarea { resize: vertical; }

.btn-add { padding: 8px 18px; background: var(--btn-bg); color: var(--accent-text); border: 1px solid var(--border-hover); border-radius: 8px; cursor: pointer; font-size: 13px; margin-top: 8px; transition: all 0.3s; }
.btn-add:hover { background: var(--border); }
.btn-remove { padding: 4px 12px; color: var(--error-text); border: 1px solid rgba(248,113,113,0.4); border-radius: 6px; cursor: pointer; font-size: 12px; background: transparent; transition: all 0.3s; }
.btn-remove:hover { background: var(--error-bg); }

.error { color: var(--error-text); margin: 12px 0; font-size: 13px; }
.success { color: var(--success-text); margin: 12px 0; font-size: 13px; }
.create-form > button { padding: 12px 32px; background: linear-gradient(135deg, #06b6d4, #8b5cf6); color: #fff; border: none; border-radius: 8px; font-size: 15px; cursor: pointer; font-weight: 600; transition: all 0.3s; box-shadow: 0 4px 20px var(--border-hover); }
.create-form > button:hover { box-shadow: 0 4px 30px var(--border-hover); transform: translateY(-1px); }
.create-form > button:disabled { opacity: 0.4; cursor: not-allowed; transform: none; box-shadow: none; }

/* My novels */
.my-novel-card { 
  background: var(--bg-card); border: 1px solid var(--border); 
  border-radius: 14px; padding: 20px; margin-bottom: 12px;
  display: flex; gap: 18px; align-items: center; backdrop-filter: blur(10px);
  transition: all 0.3s;
}
.my-novel-card:hover { border-color: var(--border-hover); box-shadow: 0 4px 20px var(--border); }
.my-novel-cover { width: 80px; height: 110px; flex-shrink: 0; border-radius: 8px; overflow: hidden; background: linear-gradient(135deg, var(--bg-deep), var(--bg-deep)); position: relative; }
.my-novel-cover img { width: 100%; height: 100%; object-fit: cover; }
.my-novel-cover .placeholder { display: flex; align-items: center; justify-content: center; width: 100%; height: 100%; background: linear-gradient(135deg, #06b6d4, #8b5cf6); color: #fff; font-size: 12px; font-weight: 600; }

.my-novel-info { flex: 1; }
.my-novel-info h3 { margin: 0 0 6px 0; font-size: 16px; color: var(--text-primary); font-weight: 600; }
.my-novel-info p { margin: 0 0 4px 0; font-size: 13px; color: var(--text-muted); }
.my-novel-desc { color: var(--text-muted) !important; font-size: 12px !important; }
.my-novel-actions { display: flex; gap: 8px; }
.my-novel-actions button { padding: 8px 16px; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 500; transition: all 0.3s; border: none; }
.my-novel-actions button:first-child { background: var(--btn-bg); color: var(--accent-text); border: 1px solid var(--border-hover); }
.my-novel-actions button:nth-child(2) { background: var(--btn-bg); color: var(--accent-text); border: 1px solid var(--border-hover); }
.my-novel-actions button:first-child:hover, .my-novel-actions button:nth-child(2):hover { opacity: 0.85; }

/* Modal */
.modal-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); backdrop-filter: blur(4px); display: flex; align-items: center; justify-content: center; z-index: 200; }
.modal-content { 
  background: var(--bg-card); border: 1px solid var(--border); border-radius: 16px; 
  padding: 32px; max-width: 700px; width: 90%; max-height: 80vh; overflow-y: auto; 
  position: relative; box-shadow: 0 20px 60px rgba(0,0,0,0.5), 0 0 40px var(--btn-bg);
}
.modal-close { position: absolute; top: 14px; right: 20px; font-size: 24px; background: none; border: none; cursor: pointer; color: var(--text-muted); transition: color 0.2s; }
.modal-close:hover { color: #f87171; }
.chapter-modal h2 { margin-bottom: 20px; color: var(--text-primary); }
.chapter-modal { max-width: 860px; }
.chapter-modal h2 { padding-right: 24px; overflow-wrap: anywhere; }
.chapter-form { display: flex; flex-direction: column; gap: 14px; margin-bottom: 20px; }
.chapter-form .card-heading { cursor: default; }
.chapter-form .card-title h3 { margin: 0; font-size: 16px; color: var(--text-primary); }
.chapter-form .field-grid .form-row { min-width: 0; margin-bottom: 0; }
.chapter-form .form-row input:not([type="checkbox"]), .chapter-form .form-row textarea { box-sizing: border-box; }
.chapter-form .form-row textarea { display: block; min-height: 128px; max-width: 100%; line-height: 1.7; font-family: inherit; }
.chapter-form .anti-ai-toggle { align-items: flex-start; gap: 10px; margin: 18px 0 0; padding: 14px; border: 1px solid var(--border); border-radius: 10px; background: var(--bg-input); line-height: 1.6; }
.chapter-form .anti-ai-toggle input[type="checkbox"] { flex: 0 0 16px; width: 16px; height: 16px; margin: 3px 0 0; padding: 0; accent-color: var(--accent-text); }
.chapter-form .anti-ai-toggle input:focus-visible { outline: 2px solid var(--border-focus); outline-offset: 3px; }
.chapter-form .anti-ai-toggle span { min-width: 0; }
.chapter-form .anti-ai-toggle strong { display: block; color: var(--text-secondary); font-weight: 600; }
.chapter-form .anti-ai-toggle small { display: block; font-size: 12px; }
.chapter-style-card { overflow: visible; z-index: 1; }
@media (max-width: 720px) {
  .chapter-modal { padding: 24px 16px; width: calc(100% - 24px); box-sizing: border-box; }
  .chapter-item { align-items: flex-start; flex-direction: column; gap: 8px; }
  .chapter-main { width: 100%; }
  .chapter-actions { width: 100%; justify-content: flex-end; }
}
.author-style-select { width: 100%; padding: 10px 14px; margin-bottom: 10px; border: 1px solid var(--border); border-radius: 8px; font-size: 14px; background: var(--bg-input); color: var(--text-primary); }
.edit-row .author-style-select { width: 580px; margin-bottom: 0; }
.chapter-btns { display: flex; gap: 10px; margin-top: 4px; }
.chapter-btns button { flex: 1; padding: 11px; border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: 600; transition: all 0.3s; }
.chapter-btns button:first-child { background: var(--bg-card); color: var(--text-secondary); border: 1px solid var(--border); }
.btn-ai { background: linear-gradient(135deg, #06b6d4, #8b5cf6) !important; color: #fff !important; border: none !important; box-shadow: 0 4px 16px var(--border-hover); }
.btn-ai:hover { box-shadow: 0 4px 28px var(--border-hover); }
.btn-ai:disabled { opacity: 0.6; cursor: not-allowed; }
.spinner { display: inline-block; width: 16px; height: 16px; border: 2px solid rgba(255,255,255,0.3); border-top-color: #fff; border-radius: 50%; animation: spin 0.8s linear infinite; vertical-align: middle; margin-right: 6px; }
@keyframes spin { to { transform: rotate(360deg); } }

.existing-chapters { margin-top: 20px; }
.existing-chapters h3 { margin-bottom: 12px; font-size: 15px; color: var(--text-secondary); }
.chapter-item { padding: 10px 14px; background: var(--bg-input); border: 1px solid var(--border); border-radius: 8px; margin-bottom: 6px; display: flex; align-items: center; justify-content: space-between; gap: 16px; font-size: 13px; color: var(--text-secondary); }
.chapter-main { min-width: 0; display: flex; align-items: center; gap: 14px; flex: 1; }
.chapter-main > span:first-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chapter-status { flex: 0 0 auto; color: var(--success-text); font-size: 12px; font-weight: 600; }
.chapter-actions { display: flex; align-items: center; gap: 8px; flex: 0 0 auto; }
.btn-delete-chapter {
  background: rgba(239, 68, 68, 0.12); border: 1px solid rgba(239, 68, 68, 0.25);
  color: var(--error-text); cursor: pointer; font-size: 11px; font-weight: 600;
  padding: 4px 12px; border-radius: 6px; transition: all 0.2s;
  white-space: nowrap;
}
.btn-delete-chapter:hover {
  background: rgba(239, 68, 68, 0.22); border-color: #ef4444;
  color: var(--error-text); box-shadow: 0 2px 12px rgba(239, 68, 68, 0.2);
}
.btn-edit-chapter {
  background: var(--btn-bg); border: 1px solid var(--border-hover);
  color: var(--accent-text); cursor: pointer; font-size: 11px; font-weight: 600;
  padding: 4px 12px; border-radius: 6px; transition: all 0.2s;
  white-space: nowrap;
}
.btn-edit-chapter:hover {
  background: rgba(6, 182, 212, 0.22); border-color: #06b6d4;
  color: var(--accent-hover); box-shadow: 0 2px 12px var(--border);
}
.btn-save {
  background: var(--brand-gradient); color: #fff; border: none;
  cursor: pointer; font-size: 13px; font-weight: 700;
  padding: 8px 20px; border-radius: 8px; transition: all 0.2s;
}
.btn-save:hover { opacity: 0.9 }
.btn-save:disabled { opacity: 0.5; cursor: not-allowed }
.btn-regenerate {
  background: rgba(249, 115, 22, 0.15); border: 1px solid rgba(249, 115, 22, 0.35);
  color: var(--warning-text); cursor: pointer; font-size: 13px; font-weight: 700;
  padding: 8px 20px; border-radius: 8px; transition: all 0.2s;
}
.btn-regenerate:hover { background: rgba(249, 115, 22, 0.25); border-color: #f97316; color: #fdba74; }

.btn-regenerate:disabled { opacity: 0.5; cursor: not-allowed }
.btn-svip-only { opacity: 0.4; cursor: not-allowed; filter: grayscale(0.8); pointer-events: none; }
.btn-cancel {
  background: transparent; color: var(--text-secondary); border: 1px solid var(--border);
  cursor: pointer; font-size: 13px; font-weight: 600;
  padding: 8px 20px; border-radius: 8px; transition: all 0.2s;
}
.btn-cancel:hover { color: var(--error-text); border-color: rgba(248, 113, 113, 0.4); }

/* 章节编辑独立弹窗 */
.chapter-edit-modal { max-width: 700px; }
.chapter-edit-modal h2 { margin-bottom: 20px; color: var(--text-primary); font-size: 18px; }
.chapter-edit-issue {
  margin: -8px 0 16px;
  padding: 10px 12px;
  border-left: 3px solid #ef4444;
  background: rgba(239, 68, 68, 0.1);
  color: #f87171;
  font-size: 13px;
  line-height: 1.5;
  white-space: pre-wrap;
}
.edit-row { margin-bottom: 14px; }
.edit-row label { display: block; font-size: 13px; color: var(--text-secondary); margin-bottom: 6px; }
.edit-row input, .edit-row textarea {
  width: 100%; padding: 10px 14px; background: var(--bg-input);
  border: 1px solid var(--border); border-radius: 8px;
  color: var(--text-primary); font-size: 14px; font-family: inherit; resize: vertical;
}
.edit-row textarea.wide-textarea {
  width: 580px;
  height: 71px;
}
.edit-row input:focus, .edit-row textarea:focus { outline: none; border-color: var(--border-focus); }

/* 多选下拉：作家风格 / 章节模板 */
.multi-tip { font-size: 11px; color: var(--text-muted); font-weight: 400; margin-left: 6px; }
.multi-select { position: relative; }
.multi-select-trigger {
  width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding: 10px 14px; border: 1px solid var(--border); border-radius: 8px;
  background: var(--bg-input); color: var(--text-secondary); font-size: 14px;
  cursor: pointer; transition: border-color 0.2s;
}
.multi-select-trigger:hover, .multi-select.open .multi-select-trigger { border-color: var(--border-focus); }
.ms-trigger-label { flex: 1; text-align: left; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ms-trigger-arrow { font-size: 12px; color: var(--text-muted); transition: transform 0.2s; }
.ms-trigger-arrow.up { transform: rotate(180deg); }
.multi-select-panel {
  position: absolute; left: 0; right: 0; top: calc(100% + 4px); z-index: 50;
  max-height: 260px; overflow-y: auto; padding: 6px;
  background: var(--bg-card); border: 1px solid var(--border-hover); border-radius: 10px;
  box-shadow: 0 8px 30px rgba(0,0,0,0.35);
}
.ms-group {
  font-size: 12px; font-weight: 600; color: var(--text-secondary);
  padding: 6px 8px 4px; margin-top: 4px;
}
.ms-group:first-child { margin-top: 0; }
.ms-item {
  display: flex; align-items: center; gap: 8px;
  padding: 7px 10px; border-radius: 7px; cursor: pointer;
  font-size: 13px; color: var(--text-primary); transition: background 0.15s;
}
.ms-item:hover:not(.disabled) { background: var(--bg-input); }
.ms-item.checked {
  background: rgba(107, 114, 128, 0.35);
  color: var(--text-muted);
  cursor: default;
  text-decoration: line-through;
}
.ms-item.checked .ms-check { color: #22c55e; font-weight: 700; margin-left: auto; }
.ms-item.disabled { opacity: 0.45; cursor: not-allowed; }
.ms-name { flex: 1; }
.ms-brief { font-size: 11px; color: var(--text-muted); max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ms-panel-hint { font-size: 11px; color: var(--text-muted); padding: 6px 8px 2px; border-top: 1px dashed var(--border); margin-top: 4px; }
.btn-copy-content {
  display: inline-block;
  margin-left: 8px;
  padding: 2px 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg-input);
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  vertical-align: middle;
  transition: all 0.2s;
  line-height: 1.6;
}
.btn-copy-content:hover { border-color: var(--accent-text); color: var(--accent-text); }
.edit-actions { display: flex; gap: 10px; margin-top: 20px; }

/* Draft */
.draft-card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 14px; padding: 20px; margin-bottom: 16px; backdrop-filter: blur(10px); }
.draft-header { display: flex; justify-content: space-between; margin-bottom: 12px; }
.draft-header h3 { font-size: 16px; color: var(--text-primary); font-weight: 600; }
.draft-header span { font-size: 12px; color: var(--text-muted); }
.draft-content textarea { width: 100%; padding: 14px; border: 1px solid var(--border); border-radius: 10px; font-size: 14px; resize: vertical; line-height: 1.8; background: var(--bg-input); color: var(--text-primary); }
.draft-content textarea:focus { outline: none; border-color: var(--border-hover); }
.draft-actions { display: flex; gap: 10px; margin-top: 12px; }
.draft-actions button { padding: 9px 22px; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 500; transition: all 0.3s; }
.draft-actions button:first-child { background: linear-gradient(135deg, #06b6d4, #8b5cf6); color: #fff; border: none; }
.draft-actions button:first-child:hover { box-shadow: 0 4px 20px var(--border-hover); }
.btn-danger { background: transparent !important; color: var(--error-text) !important; border: 1px solid rgba(248,113,113,0.4) !important; }
.btn-download { background: transparent !important; color: var(--success-text) !important; border: 1px solid rgba(16, 185, 129, 0.4) !important; }
.btn-download:hover { opacity: 0.85; }
.btn-danger:hover { background: rgba(248,113,113,0.1) !important; }
.empty { text-align: center; padding: 60px 0; color: var(--text-muted); font-size: 14px; }

/* Draft Info Panel */

/* 发布加载遮罩 */
.publish-overlay { z-index: 300; }
.publish-modal {
  background: var(--bg-card);
  backdrop-filter: blur(20px);
  border: 1px solid var(--border-hover);
  border-radius: 20px;
  padding: 40px 48px;
  text-align: center;
  min-width: 400px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5), 0 0 80px var(--border);
}
.publish-spinner {
  width: 56px; height: 56px;
  border: 4px solid var(--border);
  border-top-color: var(--info-text);
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin: 0 auto 24px;
}
.publish-modal h3 {
  font-size: 18px; color: var(--text-primary);
  margin: 0 0 28px; font-weight: 600;
}
.publish-steps {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-bottom: 24px;
}
.step {
  display: flex; align-items: center; gap: 12px;
  font-size: 14px; color: var(--text-muted);
  padding: 10px 16px;
  background: var(--bg-input);
  border-radius: 10px;
  border: 1px solid var(--border);
  transition: all 0.4s;
}
.step.done {
  color: var(--success-text);
  border-color: rgba(74, 222, 128, 0.25);
  background: rgba(74, 222, 128, 0.06);
}
.step.active {
  color: var(--text-primary);
  border-color: var(--border-hover);
  background: var(--btn-bg);
  box-shadow: 0 0 20px var(--btn-bg);
}
.step-icon { font-size: 18px; width: 28px; text-align: center; }
.publish-hint {
  font-size: 13px; color: var(--text-muted);
  margin: 0;
  animation: pulse 2s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 1; }
}

/* 生成等待条 */
.generation-card .draft-header { flex-wrap: wrap; gap: 8px; }
.generation-card h3, .generation-card .error { overflow-wrap: anywhere; }
.generation-preview {
  overflow-wrap: anywhere;
  max-height: 260px;
  overflow: auto;
  white-space: pre-wrap;
  padding: 12px;
  margin: 10px 0;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-input);
  color: var(--text-primary);
  font: inherit;
}
.generating-waiting-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  margin-top: 12px;
  background: linear-gradient(135deg, var(--bg-card), var(--bg-card));
  border: 1px solid var(--error-text);
  border-radius: 8px;
  color: var(--error-text);
  font-size: 14px;
  animation: pulse-border 1.5s ease-in-out infinite;
}
.generating-waiting-spinner {
  width: 18px;
  height: 18px;
  border: 2px solid rgba(233, 69, 96, 0.3);
  border-top-color: var(--error-text);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  flex-shrink: 0;
}
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes pulse-border {
  0%, 100% { border-color: #e94560; }
  50% { border-color: #ff6b81; }
}

/* ============================================================ */
/* 剧本创作
/* ============================================================ */
.screenplay-section {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 24px;
}
.sp-novel-select {
  flex: 1;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-input);
  color: var(--text-primary);
  font-size: 14px;
  outline: none;
  max-width: 400px;
}
.sp-novel-select:focus { border-color: var(--accent-text); }

.sp-chapter-list { margin-top: 20px; }
.sp-chapter-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 10px 14px;
  background: var(--bg-input);
  border-radius: 8px;
  margin-bottom: 12px;
}
.sp-check-all {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-secondary);
  cursor: pointer;
  white-space: nowrap;
}
.sp-check-all input { cursor: pointer; }
.sp-selected-count { font-size: 12px; color: var(--text-muted); }
.btn-generate {
  margin-left: auto;
  padding: 8px 20px;
  border: none;
  border-radius: 8px;
  background: linear-gradient(135deg, var(--accent-text), #8b5cf6);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  gap: 6px;
}
.btn-generate:hover { opacity: 0.9; transform: translateY(-1px); }
.btn-generate:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }

.sp-chapter-item {
  padding: 8px 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 4px;
  transition: all 0.15s;
}
.sp-chapter-item:hover { border-color: var(--accent-text); background: var(--accent-bg); }
.sp-chk-label {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  font-size: 13px;
}
.sp-chk-label input { cursor: pointer; }
.sp-ch-name { flex: 1; color: var(--text-primary); }
.sp-ch-words { font-size: 11px; color: var(--text-muted); white-space: nowrap; }
.sp-ch-status {
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 4px;
  background: rgba(74, 222, 128, 0.12);
  color: var(--success-text);
  white-space: nowrap;
}
.sp-ch-status.draft {
  background: rgba(251, 191, 36, 0.12);
  color: #f59e0b;
}

.sp-hint { padding: 60px 0; font-size: 14px; color: var(--text-muted); }

/* ==================== 章节概要规划 ==================== */
.outline-hint { font-size: 12px; color: var(--text-muted); margin-left: 10px; }
.outline-result { margin-top: 20px; padding: 16px; background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; }
.outline-result-title { font-size: 15px; font-weight: 600; margin-bottom: 12px; color: #22c55e; }
.outline-batch-toolbar {
  display: flex; align-items: center; gap: 14px; margin: 0 0 12px; padding: 9px 10px;
  background: var(--bg-input); border: 1px solid var(--border); border-radius: 8px;
}
.outline-select-all { display: inline-flex; align-items: center; gap: 7px; color: var(--text-secondary); font-size: 13px; cursor: pointer; }
.outline-select-all input, .outline-item-checkbox { accent-color: #22c55e; cursor: pointer; }
.outline-select-all input:disabled, .outline-item-checkbox:disabled { cursor: not-allowed; }
.outline-selected-count { font-size: 12px; color: var(--text-muted); }
.btn-outline-batch-delete {
  margin-left: auto; padding: 5px 12px; border: 1px solid rgba(248,113,113,.55); border-radius: 6px;
  background: transparent; color: #f87171; font-size: 12px; cursor: pointer; transition: all .15s;
}
.btn-outline-batch-delete:hover:not(:disabled) { background: rgba(248,113,113,.12); }
.btn-outline-batch-delete:disabled { opacity: .45; cursor: not-allowed; }
.btn-outline-export {
  margin-left: 8px; padding: 5px 12px; border: 1px solid rgba(96,165,250,.55); border-radius: 6px;
  background: transparent; color: #60a5fa; font-size: 12px; cursor: pointer; transition: all .15s;
}
.btn-outline-export:hover:not(:disabled) { background: rgba(96,165,250,.12); }
.btn-outline-export:disabled { opacity: .45; cursor: not-allowed; }
.outline-item-checkbox { flex: 0 0 auto; margin: 0 2px 0 0; }
.outline-char-count { margin-top: 5px; text-align: right; color: var(--text-muted); font-size: 12px; }
.outline-char-count.char-warn { color: #ef4444; font-weight: 600; }
.outline-loading { font-size: 12px; font-weight: 400; color: var(--text-muted); margin-left: 10px; }
.outline-group-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  margin: 8px 0 4px;
  padding: 6px 10px;
  background: var(--bg-input);
  border-radius: 6px;
}
.outline-item { padding: 12px 0; border-bottom: 1px dashed var(--border); }
.outline-item:last-child { border-bottom: none; }
.outline-item-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 6px; }
.outline-item-num { font-size: 13px; font-weight: 600; color: var(--text-primary); background: var(--bg-input); padding: 2px 8px; border-radius: 6px; white-space: nowrap; }
.outline-item-name { font-size: 15px; font-weight: 600; color: var(--text-primary); }
.outline-item-summary { font-size: 13px; line-height: 1.7; color: var(--text-secondary); }
.outline-tag { font-size: 11px; padding: 2px 8px; border-radius: 4px; white-space: nowrap; }
.outline-tag.pending { background: rgba(251, 191, 36, 0.12); color: #f59e0b; }
.outline-tag.saved { background: rgba(74, 222, 128, 0.12); color: var(--success-text); }
.outline-item-actions { display: flex; gap: 8px; margin-top: 8px; }
.btn-outline-save, .btn-outline-edit {
  padding: 5px 14px;
  font-size: 13px;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
  background: linear-gradient(135deg, #22c55e, #16a34a);
  color: #fff;
}
.btn-outline-save:hover, .btn-outline-edit:hover { opacity: 0.9; transform: translateY(-1px); }
.btn-outline-save:disabled, .btn-outline-edit:disabled, .btn-outline-cancel:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
.btn-outline-save:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
.btn-outline-edit { background: linear-gradient(135deg, #3b82f6, #2563eb); }
.btn-outline-cancel {
  padding: 5px 14px;
  font-size: 13px;
  border: 1px solid var(--border);
  border-radius: 6px;
  cursor: pointer;
  color: var(--text-secondary);
  background: transparent;
  transition: all 0.15s;
}
.btn-outline-cancel:hover { border-color: var(--accent-text); color: var(--text-primary); }
.outline-edit-input { width: 100%; max-width: 480px; }
.outline-edit-textarea { width: 100%; resize: vertical; min-height: 80px; }

/* ==================== 分页 ==================== */
.pagination { display: flex; align-items: center; gap: 6px; margin-top: 12px; flex-wrap: wrap; }
.page-btn {
  min-width: 30px; height: 30px; padding: 0 8px;
  font-size: 13px; color: var(--text-secondary);
  background: var(--bg-input); border: 1px solid var(--border);
  border-radius: 6px; cursor: pointer; transition: all 0.15s;
}
.page-btn:hover:not(:disabled) { color: var(--accent-text); border-color: var(--border-hover); }
.page-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.page-btn.active { background: linear-gradient(135deg, #06b6d4, #8b5cf6); color: #fff; border-color: transparent; }
.page-ellipsis { color: var(--text-muted); padding: 0 2px; font-size: 13px; }
.chapter-count-hint { font-size: 12px; font-weight: 400; color: var(--text-muted); margin-left: 8px; }

/* 剧本结果 - 弹窗 */
.sp-modal {
  background: var(--bg-card);
  border-radius: 16px;
  width: 90vw;
  max-width: 960px;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 20px 60px rgba(0,0,0,0.3);
  animation: spModalIn 0.25s ease-out;
}
@keyframes spModalIn {
  from { opacity: 0; transform: scale(0.92) translateY(20px); }
  to   { opacity: 1; transform: scale(1) translateY(0); }
}
.sp-modal-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 18px 24px;
  background: var(--accent-bg);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.sp-modal-header h3 {
  margin: 0;
  font-size: 16px;
  color: var(--text-primary);
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sp-modal-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}
.sp-word-count { font-size: 12px; color: var(--text-muted); }
.btn-copy {
  padding: 8px 18px;
  border: 1px solid var(--accent-text);
  border-radius: 8px;
  background: transparent;
  color: var(--accent-text);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}
.btn-copy:hover { background: var(--accent-text); color: #fff; }
.btn-close-result {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 50%;
  background: var(--bg-input);
  color: var(--text-muted);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  transition: all 0.2s;
}
.btn-close-result:hover { background: rgba(239,68,68,0.15); color: #ef4444; }
.sp-modal-body {
  padding: 24px;
  flex: 1;
  overflow-y: auto;
  font-size: 14px;
  line-height: 1.8;
  color: var(--text-secondary);
  white-space: pre-wrap;
  font-family: 'Courier New', Courier, monospace;
}
.sp-modal-body::-webkit-scrollbar { width: 6px; }
.sp-modal-body::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }


</style>

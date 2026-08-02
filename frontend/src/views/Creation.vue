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
      <form class="create-form" @submit.prevent="handleCreateNovel">

        <div class="form-section">
          <div class="section-title"><span class="section-icon">📖</span>基本信息</div>
          <div class="form-two-col">
            <div class="col-left">
              <div class="form-row">
                <label>作品名称</label><input v-model="novelForm.title" required placeholder="请输入作品名称" />
              </div>
              <div class="form-row">
                <label>目标读者</label>
                <select v-model="novelForm.target_reader" required>
                  <option value="">请选择</option><option value="男频">男频</option><option value="女频">女频</option>
                </select>
              </div>
              <div class="form-row">
                <label>签约类型</label>
                <select v-model="novelForm.sign_type" required>
                  <option value="non_exclusive">非独家（作品可在作品圈和首页展示）</option>
                  <option value="exclusive">独家（仅自己可见）</option>
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
            </div>
            <div class="col-right">
              <div class="form-row">
                <label>封面图片</label>
                <div class="image-upload">
                  <div v-if="novelForm.cover_image" class="preview">
                    <img :src="novelForm.cover_image" alt="封面预览" @error="novelForm.cover_image = ''" />
                    <button type="button" class="btn-remove" @click="novelForm.cover_image = ''">删除</button>
                  </div>
                  <template v-else>
                    <input type="file" accept="image/*" @change="handleCoverUpload" />
                  </template>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="form-section">
          <div class="section-title"><span class="section-icon">📝</span>作品简介</div>
          <div class="form-row">
            <textarea v-model="novelForm.description" rows="4" :class="{ over: novelForm.description.length > 600 }" placeholder="不超过600字" />
            <div class="form-row-meta">
              <span class="char-count" :class="{ over: novelForm.description.length > 600 }">{{ novelForm.description.length }}/600</span>
              <span v-if="novelForm.description.length > 600" class="field-error">作品简介不能超过600字</span>
            </div>
          </div>
        </div>

        <div class="form-section">
          <div class="section-title"><span class="section-icon">🌍</span>作品设定</div>
          <div class="form-two-col">
            <div class="col-left">
              <div class="form-row">
                <label>故事背景</label><textarea v-model="novelForm.story_background" rows="4" placeholder="描述故事的时代背景、地点等" />
              </div>
            </div>
            <div class="col-right">
              <div class="form-row">
                <label>世界观设定</label><textarea v-model="novelForm.world_setting" rows="4" placeholder="描述世界观体系，如修炼体系、社会结构等" />
              </div>
            </div>
          </div>
        </div>

        <div class="form-section">
          <div class="section-title"><span class="section-icon">⚡</span>境界体系</div>
          <div class="form-row">
            <div class="realm-list">
              <div v-for="(realm, ri) in novelForm.realms" :key="ri" class="realm-item">
                <input v-model="realm.name" placeholder="体系名称(如：A体系)" />
                <textarea v-model="realm.value" placeholder="该体系的境界设定" rows="2" />
                <button type="button" class="btn-remove" @click="novelForm.realms.splice(ri, 1)">删除</button>
              </div>
              <button type="button" class="btn-add" @click="novelForm.realms.push({ name: '', value: '' })">+ 添加境界体系</button>
            </div>
          </div>
        </div>

        <div class="form-section">
          <div class="section-title"><span class="section-icon">👥</span>角色设定</div>
          <div class="form-row">
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
        </div>

        <div class="form-footer">
          <p v-if="createError" class="error">{{ createError }}</p>
          <p v-if="createSuccess" class="success">{{ createSuccess }}</p>
          <button type="submit" class="btn-create" :disabled="novelForm.description.length > 600">创建作品</button>
        </div>
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
            <h3>新建章节</h3>
            <input v-model="chapterForm.chapter_name" placeholder="章节名称" />
            <input v-model="chapterForm.characters_involved" placeholder="涉及人物" />
            <input v-model="chapterForm.organizations" placeholder="涉及组织" />
            <input v-model="chapterForm.locations" placeholder="涉及地点" />
            <input v-model="chapterForm.skills" placeholder="涉及技能" />
            <input v-model.number="chapterForm.word_count" type="number" placeholder="章节字数" />
            <select v-model="chapterForm.author_style" class="author-style-select">
              <option value="">默认（不指定作家风格）</option>
              <option v-for="s in authorStyles" :key="s.id" :value="s.id">{{ s.name }} - {{ s.brief }}</option>
            </select>
            <select v-model="chapterForm.chapter_template" class="author-style-select">
              <option value="">默认（不指定章节模板）</option>
              <optgroup v-for="g in chapterTemplateGroups" :key="g.category" :label="g.category">
                <option v-for="t in g.items" :key="t.id" :value="t.id">{{ t.name }}</option>
              </optgroup>
            </select>
            <textarea v-model="chapterForm.chapter_summary" class="wide-textarea" style="width: 580px; height: 71px;" placeholder="剧情发展路线(如：主角偷袭天道教宗→夺取镇教之宝→被追杀→坠崖获机缘)" rows="4"></textarea>
            <div class="chapter-btns">
              <button class="btn-ai" @click="generateChapter" :disabled="generating">
                <span v-if="generating" class="spinner"></span>
                {{ generating ? '正在生成中...' : '一键AI生成' }}
              </button>
            </div>
          <!-- AI生成中等待提示 -->
          <div v-if="generating" class="generating-waiting-bar">
            <span class="generating-waiting-spinner"></span>
            <span>AI生成中，预计30-60秒，请稍候...</span>
          </div>
          </div>
          <div class="existing-chapters">
            <h3>已有章节
              <span class="chapter-count-hint">共 {{ novelChapters.length }} 章</span>
            </h3>
            <div v-if="novelChapters.length === 0" class="empty">暂无章节</div>
            <div v-for="ch in chapterPaged" :key="ch.chapter_unique_id" class="chapter-item">
              <span>第{{ ch.chapter_number || (novelChapters.indexOf(ch) + 1) }}章 - {{ ch.chapter_name }} ({{ ch.word_count }}字)</span>
              <span class="chapter-status">{{ ch.is_published ? '✓ 已发布' : '草稿' }}</span>
              <button class="btn-edit-chapter" @click="editChapter(ch)" title="编辑章节">✎ 编辑</button>
              <button class="btn-delete-chapter" @click="deleteChapter(ch)" title="删除章节">✕ 删除</button>
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
          <div class="edit-row"><label>章节名称</label><input v-model="editChapterForm.chapter_name" /></div>
          <div class="edit-row"><label>剧情发展路线</label>
            <textarea v-model="editChapterForm.chapter_summary" class="wide-textarea" rows="4" style="width: 580px; height: 71px;" placeholder="剧情发展路线(如：主角偷袭天道教宗→夺取镇教之宝→被追杀→坠崖获机缘)"></textarea></div>
          <div class="edit-row"><label>作家风格</label>
            <select v-model="editChapterForm.author_style" class="author-style-select">
              <option value="">默认（不指定作家风格）</option>
              <option v-for="s in authorStyles" :key="s.id" :value="s.id">{{ s.name }} - {{ s.brief }}</option>
            </select></div>
          <div class="edit-row"><label>章节模板</label>
            <select v-model="editChapterForm.chapter_template" class="author-style-select">
              <option value="">默认（不指定章节模板）</option>
              <optgroup v-for="g in chapterTemplateGroups" :key="g.category" :label="g.category">
                <option v-for="t in g.items" :key="t.id" :value="t.id">{{ t.name }}</option>
              </optgroup>
            </select></div>
          <div class="edit-row"><label>章节正文</label><button class="btn-copy-content" @click="copyChapterContent" title="复制正文内容">📋</button>
            <textarea v-model="editChapterForm.content" rows="16" placeholder="章节正文内容"></textarea></div>
          <div class="edit-actions">
            <button class="btn-save" @click="saveChapterEdit" :disabled="saving">💾 {{ saving ? '保存中...' : '保存修改' }}</button>
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
          <button @click="publishChapter(d)" :disabled="publishing[d.chapter_unique_id]">
            <span v-if="publishing[d.chapter_unique_id]" class="spinner"></span>
            {{ publishing[d.chapter_unique_id] ? '发布中...' : '发布章节' }}
          </button>
          <button class="btn-danger" @click="deleteDraft(d)">删除</button>
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
            <button class="btn-generate" @click="outlineGenerate" :disabled="outlineGenerating || !outlineDirection.trim()">
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

            <!-- 临时缓存概要（Redis，24h，不落库） -->
            <template v-if="outlineResult.length">
              <div class="outline-group-title">🕐 章节概要（24小时内有效，共 {{ outlineResult.length }} 章）</div>
              <div v-for="(o, i) in outlineResult" :key="'preview-' + i" class="outline-item">
                <div class="outline-item-head">
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
                  <div class="outline-item-actions">
                    <button class="btn-outline-save" @click="outlineGenerateChapter(o)" :disabled="generating">
                      📝 生成正文
                    </button>
                    <button class="btn-outline-edit" @click="startOutlineEditOne(o)">✏️ 修改</button>
                    <button class="btn-outline-cancel" @click="outlineDeleteOne(o)" :disabled="outlineSaving">
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
      realms: [{ name: '', value: '' }],
      characters: [],
      sign_type: 'non_exclusive'
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
          sign_type: editForm.sign_type
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
          realm_setting: realmsJson || null, characters: charsJson,
          sign_type: novelForm.sign_type
        }
        const res = await api.post('/novels/create', null, { params })
        if (res.状态码 === 200) {
          createSuccess.value = '作品创建成功！'
          Object.assign(novelForm, { title: '', target_reader: '', genre: '', description: '', story_background: '', world_setting: '', cover_image: '', realms: [{ name: '', value: '' }], characters: [], sign_type: 'non_exclusive' })
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
    const saving = ref(false)
    const regenerating = ref(false)
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
      locations: '', skills: '', word_count: 2500, chapter_summary: '', content: '', author_style: '', chapter_template: ''
    })
    const editChapterForm = reactive({
      chapter_name: '', chapter_summary: '', content: '', author_style: '', chapter_template: ''
    })
    const editingChapterId = ref(null)

    const openChapterModal = async (novel) => {
      chapterNovel.value = novel
      showChapterModal.value = true
      editingChapterId.value = null
      Object.assign(chapterForm, { chapter_name: '', characters_involved: '', organizations: '', locations: '', skills: '', word_count: 2500, chapter_summary: '', content: '', author_style: '', chapter_template: '' })
      try {
        const res = await api.get(`/chapters/novel/${novel.novel_unique_id}`)
        if (res.状态码 === 200) { novelChapters.value = res.数据; chapterPage.value = 1 }
      } catch { novelChapters.value = [] }
    }

        const generateChapter = async () => {
      if (!chapterForm.chapter_name) return alert('请输入章节名称')
      if (chapterForm.word_count > 2500) {
        if (!confirm(`章节字数超过2500字上限（当前${chapterForm.word_count}字），将自动调整为2500字。是否继续？`)) return
        chapterForm.word_count = 2500
      }
      generating.value = true
      try {
        const res = await api.post('/chapters/generate', {
          novel_unique_id: chapterNovel.value.novel_unique_id,
          chapter_name: chapterForm.chapter_name,
          characters_involved: chapterForm.characters_involved,
          organizations: chapterForm.organizations,
          locations: chapterForm.locations,
          skills: chapterForm.skills,
          word_count: chapterForm.word_count,
          chapter_summary: chapterForm.chapter_summary,
          author_style: chapterForm.author_style,
          chapter_template: chapterForm.chapter_template
        })
        if (res.状态码 === 200 && res.数据 && res.数据.task_id) {
          // 刷新用户信息（更新免费次数）
          try { const mu = await api.get('/auth/me'); if (mu.状态码===200) { Object.assign(user, mu.数据); localStorage.setItem('novel_user', JSON.stringify(user)) } } catch {}
          // 轮询任务状态，直到完成
          const taskId = res.数据.task_id
          const maxWait = 120000
          const pollInterval = 3000
          let waited = 0
          let done = false
          while (waited < maxWait) {
            await new Promise(r => setTimeout(r, pollInterval))
            waited += pollInterval
            try {
              const statusRes = await api.get('/chapters/tasks/' + taskId)
              if (statusRes.状态码 === 200 && statusRes.数据) {
                const taskStatus = statusRes.数据.status
                if (taskStatus === 'done') {
                  done = true
                  break
                } else if (taskStatus === 'failed') {
                  alert(statusRes.数据.error || 'AI生成失败')
                  return
                }
              }
            } catch { /* ignore polling errors */ }
          }
          if (done) {
            // 概要缓存保留到发布成功后才自动消费（发布时转入 MySQL 并移除缓存），此处不删除
            tab.value = 'drafts'
            await fetchDrafts()
          } else {
            alert('AI生成超时，请稍后到草稿箱查看')
            tab.value = 'drafts'
            fetchDrafts()
          }
        } else {
          alert('生成失败: ' + (res.消息 || '提交失败'))
        }
      } catch (e) {
        const msg = e.response ? (e.response.数据 || e.response.消息 || JSON.stringify(e.response.data)) : (e.message || '网络错误，请检查后端是否启动')
        alert('AI生成失败: ' + msg)
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
      loadOutlineList()
    }

    const outlineGenerate = async () => {
      if (!outlineNovelId.value) return alert('请先选择作品')
      if (!outlineDirection.value.trim()) return alert('请输入后续剧情大框')
      outlineGenerating.value = true
      outlineResult.value = []
      try {
        const res = await api.post('/chapters/outline/generate', {
          novel_unique_id: outlineNovelId.value,
          story_direction: outlineDirection.value,
          chapter_count: outlineCount.value
        })
        if (res.状态码 === 200 && res.数据 && res.数据.task_id) {
          const taskId = res.数据.task_id
          const maxWait = 150000
          const pollInterval = 3000
          let waited = 0
          let done = false
          while (waited < maxWait) {
            await new Promise(r => setTimeout(r, pollInterval))
            waited += pollInterval
            try {
              const statusRes = await api.get('/chapters/tasks/' + taskId)
              if (statusRes.状态码 === 200 && statusRes.数据) {
                const taskStatus = statusRes.数据.status
                if (taskStatus === 'done') {
                  await loadOutlineList()
                  done = true
                  break
                } else if (taskStatus === 'failed') {
                  alert(statusRes.数据.error || '概要生成失败')
                  return
                }
              }
            } catch { /* ignore polling errors */ }
          }
          if (!done) alert('概要生成超时，请稍后重试')
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
    const extracting = reactive({})
    const publishing = reactive({})
    const publishOverlay = reactive({ visible: false, name: '', step: 0 })

    // 判断提取结果是否包含有效维度数据（排除空串/无）
    const hasMemoryFields = (info) => {
      if (!info) return false
      const keys = ['人物', '组织', '功法技能', '关键事件', '地点', '时间', '关键物品', '实力变化', '伏笔']
      return keys.some(k => info[k] && String(info[k]).trim() && String(info[k]).trim() !== '无')
    }

    // 轮询异步提取/生成任务，返回任务结果 data（失败或超时返回 null）
    const pollExtractResult = async (taskId, maxWait = 120000, pollInterval = 3000) => {
      let waited = 0
      while (waited < maxWait) {
        await new Promise(r => setTimeout(r, pollInterval))
        waited += pollInterval
        try {
          const statusRes = await api.get('/chapters/tasks/' + taskId)
          if (statusRes.状态码 === 200 && statusRes.数据) {
            const st = statusRes.数据.status
            if (st === 'done') return statusRes.数据.result?.data || null
            if (st === 'failed') return null
          }
        } catch { /* ignore polling errors */ }
      }
      return null
    }
    const fetchDrafts = async () => {
      try {
        const res = await api.get('/chapters/drafts')
        if (res.状态码 === 200) drafts.value = (res.数据 || []).slice().reverse()  // 倒序展示：最新草稿在最上方
        else console.error('获取草稿列表失败:', res)
      } catch (e) { console.error('获取草稿列表异常:', e) }
    }

    const extractDraftInfo = async (d) => {
      if (!d.content || d.content.trim() === '') {
        alert('章节内容为空，无法提取')
        return
      }
      extracting[d.chapter_unique_id] = true
      try {
        const res = await api.post('/chapters/extract-info', { content: d.content, chapter_name: d.chapter_name, novel_unique_id: d.novel_unique_id })
        if (res.状态码 === 200 && res.数据 && res.数据.task_id) {
          // 接口为异步任务，轮询等待真实提取结果
          const info = await pollExtractResult(res.数据.task_id, 120000, 3000)
          if (info && hasMemoryFields(info)) {
            const idx = drafts.value.findIndex(item => item.chapter_unique_id === d.chapter_unique_id)
            if (idx !== -1) {
              drafts.value[idx] = { ...drafts.value[idx], _info: info }
            }
          } else {
            alert('提取失败或超时，请稍后重试')
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
        // 附带 AI 提取的信息（未提取或无有效数据时自动提取，确保记忆体同步保存成功）
        let info = d._info
        if (!hasMemoryFields(info)) {
          try {
            const extRes = await api.post('/chapters/extract-info', { content: d.content, chapter_name: d.chapter_name, novel_unique_id: d.novel_unique_id })
            if (extRes.状态码 === 200 && extRes.数据 && extRes.数据.task_id) {
              info = await pollExtractResult(extRes.数据.task_id, 120000, 3000)
            }
          } catch (e) {
            console.error('[发布-自动提取] 异常:', e)
            info = null
          }
          if (!hasMemoryFields(info)) {
            publishOverlay.visible = false
            alert('AI 提取章节关键信息失败，无法保证记忆体保存成功，请稍后重试发布')
            return
          }
        }
        if (info) {
          body.characters_involved = info.人物 || ''
          body.organizations = info.组织 || ''
          body.skills = info.功法技能 || ''
          body.locations = info.地点 || ''
          body.events = info.关键事件 || ''
          body.time_info = info.时间 || ''
          body.key_items = info.关键物品 || ''
          body.power_changes = info.实力变化 || ''
          body.foreshadowing = info.伏笔 || ''
        }

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
      if (!editChapterForm.chapter_name) return alert('请输入章节名称')
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
        } else alert(res.消息)
      } catch (e) { alert('修改失败: ' + (e.response?.data?.detail || e.message)) }
      finally { saving.value = false }
    }

    const regenerateChapter = async () => {
      if (!editChapterForm.chapter_name) return alert('请输入章节名称')
      if (!confirm('AI重新生成将覆盖当前章节内容，确定继续？')) return
      regenerating.value = true
      try {
        const res = await api.post(`/chapters/regenerate/${editingChapterId.value}`, {
          chapter_summary: editChapterForm.chapter_summary,
          word_count: 2500,
          author_style: editChapterForm.author_style,
          chapter_template: editChapterForm.chapter_template
        })
        if (res.状态码 === 200) {
          const newContent = res.数据?.content
          if (newContent) {
            editChapterForm.content = newContent
            alert('重新生成成功，内容已更新到编辑区')
          } else {
            alert('重新生成成功，但未能获取内容')
          }
        } else {
          alert('重新生成失败: ' + res.消息)
        }
      } catch (e) {
        const msg = e.response?.data?.detail || e.message || '网络错误'
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

    onMounted(() => {
      // 页面挂载时拉取最新用户状态（VIP开通后回来是最新）
      syncUserFromServer().then(() => fetchTodayPublished())
      window.addEventListener('user-info-changed', onUserChanged)
      fetchMyNovels()
      fetchAuthorStyles()
      fetchChapterTemplates()
    })

    onUnmounted(() => {
      window.removeEventListener('user-info-changed', onUserChanged)
    })

    return { tab, isVip, isSvip, vipLevel, freeQuota, publishedToday, maxDailyQuota, quotaRemaining, quotaPercent, levelLabel, levelDesc, fetchTodayPublished, novelForm, createError, createSuccess, handleCreateNovel,
      myNovels, fetchMyNovels,
      showChapterModal, chapterNovel, novelChapters, chapterForm, generating,
      openChapterModal, generateChapter, authorStyles, fetchAuthorStyles,
      chapterTemplates, fetchChapterTemplates, chapterTemplateGroups,
      chapterPage, chapterPageSize, chapterPaged, chapterPageCount, chapterPageNums,
      drafts, fetchDrafts, publishChapter, deleteDraft, deleteChapter, editChapter, saveChapterEdit, regenerateChapter, continueChapter, continuing, deleteNovel, downloadNovel, formatTime, saving, regenerating, showChapterEditModal, editChapterForm,
      extracting, extractDraftInfo, publishing, publishOverlay,
      genreOptions, selectedGenres, toggleGenre, handleCoverUpload,
      showEditModal, editForm, editSelectedGenres, editError, editSuccess,
      openEditModal, toggleEditGenre, handleEditCoverUpload, handleUpdateNovel,
      spNovelId, spChapters, spSelectedIds, spGenerating, spResult, spResultRef,
      spAllSelected, initScreenplay, spLoadChapters, spToggleAll, spGenerate, spCopyResult,
      outlineNovelId, outlineDirection, outlineCount, outlineGenerating, outlineResult,
      outlineLoading, outlineSaving,
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
.genre-select { display: flex; flex-wrap: wrap; gap: 8px; }
.genre-tag { padding: 6px 16px; border: 1px solid var(--border); border-radius: 20px; cursor: pointer; font-size: 13px; color: var(--text-muted); background: var(--bg-input); transition: all 0.2s; }
.genre-tag:hover { border-color: var(--border-focus); color: var(--accent-text); }
.genre-tag.active { background: linear-gradient(135deg, var(--border), var(--border-hover)); color: var(--accent-text); border-color: rgba(6,182,212,0.6); box-shadow: 0 0 12px var(--btn-bg); }

/* Realm */
.realm-item { display: flex; flex-direction: column; gap: 6px; margin-bottom: 8px; padding: 12px; background: var(--bg-input); border: 1px solid var(--border); border-radius: 8px; }
.realm-item input { width: 60% !important; }

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
.chapter-form { margin-bottom: 20px; padding: 20px; background: var(--bg-input); border: 1px solid var(--border); border-radius: 12px; }
.chapter-form h3 { margin-bottom: 14px; font-size: 15px; color: var(--text-secondary); }
.chapter-form input { width: 100%; padding: 10px 14px; margin-bottom: 10px; border: 1px solid var(--border); border-radius: 8px; font-size: 14px; background: var(--bg-input); color: var(--text-primary); }
.chapter-form input:focus { outline: none; border-color: var(--border-focus); }
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
.chapter-item { padding: 10px 14px; background: var(--bg-input); border: 1px solid var(--border); border-radius: 8px; margin-bottom: 6px; display: flex; justify-content: space-between; font-size: 13px; color: var(--text-secondary); }
.chapter-status { color: var(--success-text); font-size: 12px; font-weight: 600; }
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
.draft-info-panel { margin-top: 12px; }
.btn-extract { padding: 8px 18px; border-radius: 8px; cursor: pointer; font-size: 12px; font-weight: 500; background: var(--btn-bg); color: var(--accent-text); border: 1px solid var(--border-hover); transition: all 0.3s; }
.btn-extract:hover { background: var(--border); box-shadow: 0 2px 12px var(--border); }
.btn-extract:disabled { opacity: 0.6; cursor: not-allowed; }
.info-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 10px; }
.info-cell { display: flex; flex-direction: column; }
.info-cell label { font-size: 11px; color: var(--info-text); margin-bottom: 4px; font-weight: 500; }
.info-cell input { padding: 8px 10px; border: 1px solid var(--border); border-radius: 6px; font-size: 12px; background: var(--bg-input); color: var(--text-primary); transition: border-color 0.3s; }
.info-cell input:focus { outline: none; border-color: var(--border-focus); }
@media (max-width: 768px) { .info-grid { grid-template-columns: repeat(2, 1fr); } }

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

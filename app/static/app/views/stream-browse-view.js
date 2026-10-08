/*
 * stream-browse-view.js — 登录态 B 流浏览视图（US-14 / AC-14.1~14.3 / AC-21.1）
 *
 * 消费既有契约 GET /api/stream/b（技术书 §3）：
 * - 常规条目按 relevance 降序（阈值过滤服务端已做，仅约束常规条目）；
 * - 穿插条目（band=low_interleaved）真实分数展示 + "穿插"徽标（AC-14.2
 *   不伪装语义）；
 * - 探索条目（flag="explore"）徽标 + 真实低相关分（AC-14.3）；
 * - 未评分条目（unscored 数组，flag="unscored"）"暂未评分"标注（AC-21.1
 *   故障隔离呈现面）；
 * - 评分理由展开（score_reason 字段 reason）；
 * - 分类 Tab：抓取新闻（/api/stream/b）× AI 文章（/api/articles，AC-15.2
 *   作者筛选前端位）。
 */
import { api } from "../api.js";

export default {
  name: "StreamBrowseView",
  data() {
    return {
      tab: "news",
      loading: false,
      error: "",
      // B 流数据面
      items: [],
      unscored: [],
      interleaveMeta: null,
      exploreMeta: null,
      expandedIds: [],
      // C 流（AI 文章 Tab）数据面
      articles: [],
      authorFilter: "",
      // 分页
      page: 1,
      pageSize: 24,
    };
  },
  computed: {
    tabOptions() {
      return [
        { value: "news", label: this.$t("stream.tabNews") },
        { value: "articles", label: this.$t("stream.tabArticles") },
      ];
    },
    authorOptions() {
      const ids = [...new Set(this.articles.map((a) => a.author_id))];
      return [
        { value: "", label: this.$t("stream.authorAll") },
        ...ids.map((id) => ({ value: String(id), label: `${this.$t("articles.authorColumn")} #${id}` })),
      ];
    },
    filteredArticles() {
      const filter = this.authorFilter;
      const base = filter
        ? this.articles.filter((a) => String(a.author_id) === filter)
        : this.articles;
      return base;
    },
    pagedItems() {
      const start = (this.page - 1) * this.pageSize;
      return this.items.slice(start, start + this.pageSize);
    },
    pages() {
      return Math.max(1, Math.ceil(this.items.length / this.pageSize));
    },
  },
  watch: {
    tab(value) {
      this.page = 1;
      if (value === "news") this.loadStream();
      else this.loadArticles();
    },
  },
  mounted() { this.loadStream(); },
  methods: {
    async loadStream() {
      this.loading = true;
      this.error = "";
      try {
        const data = await api.get("/api/stream/b?sort=score&limit=300");
        this.items = data.items || [];
        this.unscored = data.unscored || [];
        this.interleaveMeta = data.interleave || null;
        this.exploreMeta = data.explore || null;
      } catch (err) {
        this.error = err.message || this.$t("common.errorGeneric");
      } finally {
        this.loading = false;
      }
    },
    async loadArticles() {
      this.loading = true;
      this.error = "";
      try {
        this.articles = await api.get("/api/articles");
      } catch (err) {
        this.error = err.message || this.$t("common.errorGeneric");
      } finally {
        this.loading = false;
      }
    },
    toggleReason(id) {
      this.expandedIds = this.expandedIds.includes(id)
        ? this.expandedIds.filter((v) => v !== id)
        : [...this.expandedIds, id];
    },
    isExplore(item) { return item.flag === "explore"; },
    isInterleaved(item) { return item.band === "low_interleaved"; },
  },
  template: `
    <section>
      <div class="view-heading">
        <p class="eyebrow">{{ $t("stream.subtitle") }}</p>
        <div class="view-heading-row">
          <h1 class="page-serif-headline">{{ $t("stream.heading") }}</h1>
          <nw-tab-bar :tabs="tabOptions" v-model="tab"></nw-tab-bar>
        </div>
      </div>

      <nw-alert-bar v-if="error" tone="danger">{{ error }}</nw-alert-bar>

      <template v-if="tab === 'news'">
        <div class="view-toolbar" v-if="interleaveMeta || exploreMeta">
          <nw-badge v-if="interleaveMeta && interleaveMeta.inserted > 0" tone="warn">{{ $t("stream.interleaveBadge") }} ×{{ interleaveMeta.inserted }}</nw-badge>
          <nw-badge v-if="exploreMeta && exploreMeta.inserted > 0" tone="info">{{ $t("stream.exploreBadge") }} ×{{ exploreMeta.inserted }}</nw-badge>
          <span class="toolbar-spacer"></span>
          <nw-score-badge :label="$t('stream.scoreLabel')" :value="$t('stream.sortScore')"></nw-score-badge>
        </div>

        <div v-if="unscored.length" class="admin-section">
          <nw-alert-bar tone="warn">{{ $t("stream.unscoredNote") }}（{{ unscored.length }}）</nw-alert-bar>
          <div class="stream-list">
            <div v-for="entry in unscored" :key="'u' + entry.id" class="stream-row">
              <div>
                <h4 class="stream-row-title">{{ entry.title }}</h4>
                <p class="card-meta"><nw-badge tone="neutral">{{ entry.note || $t("stream.unscoredBadge") }}</nw-badge></p>
              </div>
              <a class="btn-pill btn-ghost btn-sm" :href="entry.url" target="_blank" rel="noopener noreferrer">{{ $t("stream.openOriginal") }}</a>
            </div>
          </div>
        </div>

        <nw-empty-state v-if="!loading && !pagedItems.length"
                        :title="$t('stream.emptyNews')" :hint="$t('common.emptyHint')"></nw-empty-state>

        <div class="stream-grid">
          <article v-for="item in pagedItems" :key="item.id" class="card-base stream-card">
            <p class="eyebrow">
              <nw-badge v-if="isExplore(item)" tone="info">{{ $t("stream.exploreBadge") }}</nw-badge>
              <nw-badge v-if="isInterleaved(item)" tone="warn">{{ $t("stream.interleaveBadge") }}</nw-badge>
              <span class="source-tag">#{{ item.source_id }}</span>
            </p>
            <h2 class="card-serif-title" style="font-size:20px;">
              <a :href="item.url" target="_blank" rel="noopener noreferrer nofollow">{{ item.title }}</a>
            </h2>
            <div class="card-meta">
              <nw-score-badge :label="$t('stream.scoreLabel')" :value="item.relevance"></nw-score-badge>
              <button type="button" class="reason-toggle" @click="toggleReason(item.id)">
                {{ expandedIds.includes(item.id) ? $t("common.collapse") : $t("common.expand") }}{{ $t("stream.reasonLabel") }}
              </button>
            </div>
            <p v-if="expandedIds.includes(item.id)" class="reason-block">{{ item.reason }}</p>
          </article>
        </div>

        <nw-pagination v-if="pages > 1" :page="page" :pages="pages"
                       @change="page = $event"></nw-pagination>
      </template>

      <template v-else>
        <div class="view-toolbar">
          <label class="muted-note" for="author-filter">{{ $t("stream.authorFilter") }}</label>
          <select id="author-filter" class="select-pill" v-model="authorFilter">
            <option v-for="opt in authorOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
          </select>
          <span class="toolbar-spacer"></span>
          <a class="btn-pill btn-ghost btn-sm" href="#/articles">{{ $t("articles.openDetail") }} →</a>
        </div>
        <nw-empty-state v-if="!loading && !filteredArticles.length"
                        :title="$t('stream.emptyArticles')" :hint="$t('common.emptyHint')"></nw-empty-state>
        <div class="stream-list">
          <div v-for="article in filteredArticles" :key="article.id" class="stream-row">
            <div>
              <h4 class="stream-row-title">
                <a :href="'#/articles/' + article.id" style="text-decoration:none;color:inherit;">{{ article.title }}</a>
              </h4>
              <p class="card-meta">
                <span>{{ $t("articles.authorColumn") }} #{{ article.author_id }}</span>
                <span>{{ $t("articles.citationsColumn") }} {{ article.citations }}</span>
              </p>
            </div>
            <nw-badge :tone="article.bookmarked ? 'danger' : 'neutral'">
              {{ article.bookmarked ? $t("articles.bookmarked") : $t("articles.unbookmarked") }}</nw-badge>
            <a class="btn-pill btn-ghost btn-sm" :href="'#/articles/' + article.id">{{ $t("articles.openDetail") }}</a>
          </div>
        </div>
      </template>
    </section>
  `,
};

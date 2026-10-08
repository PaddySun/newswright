/*
 * article-list-view.js — C 流文章列表视图（US-15 / AC-15.1/15.2）
 *
 * 消费既有契约 GET /api/articles（author_id/bookmarked 过滤在服务端）与
 * POST /api/articles/{id}/bookmark（幂等置位）。作者筛选以 author_id 维度
 * 提供契约内能力（作者名端点不在 W1 之外的契约面——缺口已呈报统筹）。
 */
import { api } from "../api.js";

export default {
  name: "ArticleListView",
  data() {
    return {
      loading: false,
      error: "",
      articles: [],
      authorFilter: "",
      bookmarkedOnly: false,
      busyId: null,
    };
  },
  computed: {
    authorOptions() {
      const ids = [...new Set(this.articles.map((a) => a.author_id))];
      return [
        { value: "", label: this.$t("stream.authorAll") },
        ...ids.map((id) => ({ value: String(id), label: `${this.$t("articles.authorColumn")} #${id}` })),
      ];
    },
    visibleArticles() {
      // 服务端过滤参数已生效；此处仅做前端二次呈现过滤（author 变更即时响应）
      return this.articles.filter((a) => {
        if (this.bookmarkedOnly && !a.bookmarked) return false;
        return true;
      });
    },
  },
  mounted() { this.load(); },
  methods: {
    async load() {
      this.loading = true;
      this.error = "";
      try {
        const params = new URLSearchParams();
        if (this.authorFilter) params.set("author_id", this.authorFilter);
        if (this.bookmarkedOnly) params.set("bookmarked", "true");
        const query = params.toString();
        this.articles = await api.get(`/api/articles${query ? "?" + query : ""}`);
      } catch (err) {
        this.error = err.message || this.$t("common.errorGeneric");
      } finally {
        this.loading = false;
      }
    },
    async bookmark(article) {
      this.busyId = article.id;
      try {
        await api.post(`/api/articles/${article.id}/bookmark`);
        article.bookmarked = true; // 幂等置位语义：本地状态与服务端收敛一致
      } catch (err) {
        this.error = err.message || this.$t("common.errorGeneric");
      } finally {
        this.busyId = null;
      }
    },
  },
  template: `
    <section>
      <div class="view-heading">
        <p class="eyebrow">ARTICLES / {{ $t("nav.articles") }}</p>
        <div class="view-heading-row">
          <h1 class="page-serif-headline">{{ $t("articles.heading") }}</h1>
        </div>
      </div>

      <nw-alert-bar v-if="error" tone="danger">{{ error }}</nw-alert-bar>

      <div class="view-toolbar">
        <label class="muted-note" for="list-author-filter">{{ $t("stream.authorFilter") }}</label>
        <select id="list-author-filter" class="select-pill" v-model="authorFilter" @change="load">
          <option v-for="opt in authorOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
        </select>
        <nw-toggle-pill :label="$t('articles.bookmarkedOnly')" :active="bookmarkedOnly"
                        @toggle="bookmarkedOnly = !bookmarkedOnly; load()"></nw-toggle-pill>
      </div>

      <nw-empty-state v-if="!loading && !visibleArticles.length"
                      :title="$t('stream.emptyArticles')" :hint="$t('common.emptyHint')"></nw-empty-state>

      <div class="stream-list">
        <div v-for="article in visibleArticles" :key="article.id" class="stream-row">
          <div>
            <h4 class="stream-row-title">
              <a :href="'#/articles/' + article.id" style="text-decoration:none;color:inherit;">{{ article.title }}</a>
            </h4>
            <p class="card-meta">
              <span>{{ $t("articles.authorColumn") }} #{{ article.author_id }}</span>
              <span>{{ $t("articles.citationsColumn") }} {{ article.citations }}</span>
            </p>
          </div>
          <button type="button" class="bookmark-btn" :disabled="busyId === article.id"
                  :aria-pressed="article.bookmarked"
                  :title="$t('stream.bookmark')" @click="bookmark(article)">✚</button>
          <a class="btn-pill btn-ghost btn-sm" :href="'#/articles/' + article.id">{{ $t("articles.openDetail") }}</a>
        </div>
      </div>
    </section>
  `,
};

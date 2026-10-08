/*
 * root-component.js — SPA 根组件（应用壳：顶栏导航 + 路由出口）
 *
 * 三栏导航（浏览/文章/后台）+ 后台子导航；文案一律 t("key")（裁定⑦）。
 * 路由出口渲染当前 hash 对应视图（router.js 提供 route/navigate 注入）。
 */
import { route, navigate } from "./router.js";
import { api } from "./api.js";
import { setSessionUser } from "./store.js";

export default {
  name: "RootComponent",
  data() {
    return { route, adminTab: this.isAdmin(route.path) ? route.path : "/admin/directions" };
  },
  computed: {
    isAdminPath() { return this.route.path.startsWith("/admin"); },
    adminNav() {
      return [
        { value: "/admin/directions", label: this.$t("nav.adminDirections") },
        { value: "/admin/authors", label: this.$t("nav.adminAuthors") },
        { value: "/admin/write", label: this.$t("nav.adminWrite") },
        { value: "/admin/system", label: this.$t("nav.adminSystem") },
      ];
    },
    mainNav() {
      return [
        { value: "/stream", label: this.$t("nav.browse") },
        { value: "/articles", label: this.$t("nav.articles") },
        { value: "/admin/directions", label: this.$t("nav.admin") },
      ];
    },
    activeMain() {
      if (this.route.path.startsWith("/admin")) return "/admin/directions";
      if (this.route.path.startsWith("/articles")) return "/articles";
      return "/stream";
    },
    avatarChar() {
      return "编"; // 站长单管理员体系（US-01）的头像占位字
    },
  },
  methods: {
    isAdmin(path) { return path.startsWith("/admin"); },
    go(value) {
      this.adminTab = value;
      navigate(value);
    },
  },
  async mounted() {
    // 会话身份拉取（登录态 SPA 入口自证）：401 由 api.js 统一跳登录
    try {
      const usage = await api.get("/api/settings/notify");
      if (usage && typeof usage === "object") setSessionUser("admin");
    } catch { /* 401 已跳转；其他错误不阻塞壳渲染 */ }
  },
  template: `
    <div class="app-shell">
      <header class="app-topbar">
        <div class="shell app-topbar-row">
          <span class="brand-logo">{{ $t("common.appName") }}</span>
          <nav class="pill-nav" aria-label="main">
            <a v-for="item in mainNav" :key="item.value" class="pill-item"
               :class="{ active: activeMain === item.value }" :href="'#' + item.value">
              {{ item.label }}</a>
          </nav>
          <div class="app-user-pill">
            <div class="app-user-avatar">{{ avatarChar }}</div>
            <span class="muted-note">admin</span>
          </div>
        </div>
      </header>

      <div class="shell app-subnav" v-if="isAdminPath">
        <nw-tab-bar :tabs="adminNav" :model-value="route.path"
                    @update:model-value="go"></nw-tab-bar>
      </div>

      <main class="shell app-main">
        <component :is="route.component"></component>
      </main>

      <footer class="site-footer">
        <div class="shell"><p>{{ $t("site.copyright") }}</p></div>
      </footer>
    </div>
  `,
};

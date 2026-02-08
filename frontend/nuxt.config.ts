// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  devtools: { enabled: true },

  modules: ["@nuxtjs/tailwindcss", "@nuxtjs/color-mode"],

  // Nuxt 4 compatibility
  future: {
    compatibilityVersion: 4,
  },

  compatibilityDate: "2024-11-01",

  // Color mode
  colorMode: {
    classSuffix: "",
  },

  // App configuration
  app: {
    head: {
      title: "ReadMatrix",
      meta: [
        {
          name: "description",
          content: "Local-first personal knowledge platform with grounded Q&A",
        },
      ],
      link: [{ rel: "icon", type: "image/svg+xml", href: "/favicon.svg" }],
    },
  },

  // Runtime config
  runtimeConfig: {
    public: {
      apiUrl: process.env.NUXT_PUBLIC_API_URL || "http://localhost:8000",
    },
  },

  // TypeScript
  typescript: {
    strict: true,
  },

  // Tailwind
  tailwindcss: {
    cssPath: "~/assets/css/tailwind.css",
    configPath: "tailwind.config.ts",
  },

  // Components auto-import
  components: {
    dirs: [
      { path: "~/components/ui", prefix: "Ui" },
      { path: "~/components", prefix: "" },
    ],
  },
});

// @ts-check
import { defineConfig } from "astro/config";
import sitemap from "@astrojs/sitemap";

export default defineConfig({
  site: "https://suisan-career.jp",
  integrations: [
    sitemap({
      filter: (page) => !page.includes("/draft/"),
    }),
  ],
  image: {
    domains: [],
  },
});

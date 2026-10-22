// @ts-check
import { defineConfig } from "astro/config";
import sitemap from "@astrojs/sitemap";

// Статичный сайт. Адрес и папку сборки задает воркер (P1-6) через окружение:
// SITE_URL - канонический адрес (по умолчанию добромир-крым.рф в punycode, без www),
// ASTRO_OUT_DIR - папка релиза releases/<время>/. Локально - значения по умолчанию.
const site = (
    process.env.SITE_URL || "https://xn----9sbirljdkbtdc7l.xn--p1ai"
).replace(/\/+$/, "");

export default defineConfig({
    site,
    outDir: process.env.ASTRO_OUT_DIR || "./dist",
    // Адреса со слэшем в конце, как у старого WordPress: старые ссылки совпадут.
    trailingSlash: "always",
    integrations: [sitemap()],
});

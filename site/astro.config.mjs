// @ts-check
import { defineConfig } from "astro/config";
import sitemap from "@astrojs/sitemap";
import { createReadStream, statSync } from "node:fs";
import { resolve, sep } from "node:path";

// Статичный сайт. Адрес и папку сборки задает воркер (P1-6) через окружение:
// SITE_URL - канонический адрес (по умолчанию добромир-крым.рф в punycode, без www),
// ASTRO_OUT_DIR - папка релиза releases/<время>/. Локально - значения по умолчанию.
const site = (
    process.env.SITE_URL || "https://xn----9sbirljdkbtdc7l.xn--p1ai"
).replace(/\/+$/, "");

// Только для сервера разработки: фото новостей из MEDIA_DIR (на хостинге их отдает
// ссылка media рядом с релизом, в сборку они не попадают). Без MEDIA_DIR - 404, как раньше.
/** @returns {import("vite").Plugin} */
function devMedia() {
    const root = process.env.MEDIA_DIR ? resolve(process.env.MEDIA_DIR) : "";
    return {
        name: "dobromir-dev-media",
        configureServer(server) {
            if (!root) return;
            server.middlewares.use("/media/", (req, res, next) => {
                const name = decodeURIComponent(
                    (req.url ?? "").split("?")[0],
                ).replace(/\/+$/, "");
                const file = resolve(root, `.${name}`);
                // Не выпускать за пределы каталога: ../ в адресе
                if (!file.startsWith(root + sep) || !file.endsWith(".webp"))
                    return next();
                try {
                    statSync(file);
                } catch {
                    return next();
                }
                res.setHeader("Content-Type", "image/webp");
                createReadStream(file).pipe(res);
            });
        },
    };
}

export default defineConfig({
    site,
    outDir: process.env.ASTRO_OUT_DIR || "./dist",
    // Адреса со слэшем в конце, как у старого WordPress: старые ссылки совпадут.
    trailingSlash: "always",
    integrations: [sitemap()],
    vite: { plugins: [devMedia()] },
});

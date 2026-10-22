// @ts-check
import { defineConfig } from "astro/config";

// Сайт полностью статичный (output по умолчанию - static), без i18n и без base:
// публикуется в корне dobromir.ru. Хост канонический, без www.
export default defineConfig({
    site: "https://dobromir.ru",
});

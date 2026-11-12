import { siteEnv, siteUrl, withBase } from "../lib/env";

// Тестовая копия закрыта целиком; боевая открыта, с картой сайта.
export function GET(): Response {
    const body =
        siteEnv() === "staging"
            ? "User-agent: *\nDisallow: /\n"
            : `User-agent: *\nAllow: /\n\nSitemap: ${siteUrl()}${withBase("/sitemap-index.xml")}\n`;
    return new Response(body, {
        headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
}

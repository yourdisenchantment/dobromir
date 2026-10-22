import rss from "@astrojs/rss";
import type { APIContext } from "astro";

import { displayTitle, loadNews, summary } from "../lib/news";

// Лента новостей. Удаленных постов в news.json нет - нет их и здесь.
export function GET(context: APIContext): Promise<Response> {
    return rss({
        title: "Новости центра «Добромир»",
        description:
            "Республиканский центр коррекционной педагогики «Добромир», Симферополь.",
        site: context.site ?? "",
        trailingSlash: true,
        customData: "<language>ru</language>",
        items: loadNews().map((post) => ({
            title: displayTitle(post),
            link: `/news/${post.slug}/`,
            pubDate: new Date(post.date),
            description: summary(post),
        })),
    });
}

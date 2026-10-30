// Чтение news.json, который пишет воркер. Формат - docs/content-contract.md; схема здесь
// и экспорт в pipeline/src/pipeline/export/news.py меняются вместе. Ошибка схемы валит
// сборку: лучше не выпустить релиз, чем выпустить сломанный.

import { readFileSync } from "node:fs";
import { z } from "zod";

import example from "../sample/news.example.json";

import { newsJsonPath, siteEnv } from "./env";
import { formatDate } from "./date";
import { restAfterTitle } from "./cardtext";
import { plainVkText } from "./vktext";

const Rendition = z.object({
    file: z.string().min(1),
    width: z.number().int().positive(),
    height: z.number().int().positive(),
});
// Полная копия (до 1600 px) - для окна и страницы новости, preview (до 800 px) - для
// карточки; у маленького фото preview - тот же файл.
const Photo = Rendition.extend({ preview: Rendition });
const Link = z.object({ url: z.string(), title: z.string() });
const Media = z.object({ kind: z.enum(["doc", "video"]), title: z.string() });
const Content = {
    text: z.string(),
    photos: z.array(Photo),
    links: z.array(Link),
    media: z.array(Media),
};
const Repost = z.object({
    source_name: z.string().nullable(),
    source_url: z.string(),
    date: z.string(),
    ...Content,
});
const Post = z.object({
    id: z.number().int(),
    slug: z.string().regex(/^\d{4}-\d{2}-\d{2}-vk\d+$/u),
    title: z.string(),
    date: z.string(),
    edited_date: z.string().nullable(),
    pinned: z.boolean(),
    tags: z.array(z.string()),
    source_url: z.string(),
    ...Content,
    repost: Repost.nullable(),
});
const News = z.object({
    version: z.literal(2),
    generated_at: z.string(),
    posts: z.array(Post),
});

export type NewsPost = z.infer<typeof Post>;
export type NewsPhoto = z.infer<typeof Photo>;

let cache: NewsPost[] | undefined;

/** Посты для сборки, новые первыми (так их отдает воркер). */
export function loadNews(): NewsPost[] {
    if (cache) return cache;
    const path = newsJsonPath();
    if (!path && siteEnv() === "production") {
        throw new Error(
            "NEWS_JSON не задана: боевую сборку нельзя делать на примерах",
        );
    }
    // Без NEWS_JSON (локальная разработка) - пример из src/sample, вшитый в сборку.
    const raw: unknown = path
        ? JSON.parse(readFileSync(path, "utf-8"))
        : example;
    const source = path ?? "src/sample/news.example.json";
    const parsed = News.safeParse(raw);
    if (!parsed.success) {
        const issues = parsed.error.issues
            .slice(0, 5)
            .map((i) => `${i.path.join(".")}: ${i.message}`);
        throw new Error(
            `news.json не прошел проверку (${source}):\n${issues.join("\n")}`,
        );
    }
    cache = parsed.data.posts;
    return cache;
}

/** Заголовок для показа: у поста без текста его нет - тогда по дате. */
export function displayTitle(post: NewsPost): string {
    return post.title || `Новость от ${formatDate(post.date)}`;
}

/** Краткое описание для meta description и RSS: первые ~160 символов текста. */
export function summary(post: NewsPost, max = 160): string {
    return (
        shorten(post.text || post.repost?.text || "", max) || displayTitle(post)
    );
}

/** Текст без разметки VK одной строкой, не длиннее max (обрезка по слову с «…»). */
function shorten(raw: string, max: number): string {
    const text = plainVkText(raw).replace(/\s+/gu, " ").trim();
    if (text.length <= max) return text;
    return `${text.slice(0, max).replace(/\s+\S*$/u, "")}…`;
}

export function mediaUrl(file: string): string {
    // Защита от path traversal: разрешаем только (photos/)?<имя>.webp без ".."
    if (
        file.includes("..") ||
        !/^(?:photos\/)?[a-zA-Z0-9._-]+\.webp$/u.test(file)
    ) {
        return "/media/";
    }
    return `/media/${file}`;
}

/** Новость как карточка (components/Card.astro): лента лендинга, архив, стайлбук. */
export function newsCard(post: NewsPost) {
    const cover = post.photos[0] ?? post.repost?.photos[0];
    return {
        title: displayTitle(post),
        subtitle: formatDate(post.date),
        datetime: post.date,
        // без повтора заголовка: под ним - продолжение текста (lib/cardtext.ts)
        text:
            shorten(
                restAfterTitle(
                    post.text || post.repost?.text || "",
                    post.title,
                ),
                140,
            ) || undefined,
        href: `/news/${post.slug}/`,
        modal: true,
        image: cover
            ? {
                  src: mediaUrl(cover.preview.file),
                  width: cover.preview.width,
                  height: cover.preview.height,
                  alt: "",
              }
            : undefined,
    };
}

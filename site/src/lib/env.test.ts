import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import { siteBase, withBase } from "./env.ts";

let originalBase: string | undefined;

// Каждый тест задает свое окружение и не оставляет SITE_BASE следующим тестам.
beforeEach(() => {
    originalBase = process.env.SITE_BASE;
    delete process.env.SITE_BASE;
});

afterEach(() => {
    if (originalBase === undefined) delete process.env.SITE_BASE;
    else process.env.SITE_BASE = originalBase;
});

test("без SITE_BASE внутренние абсолютные пути не меняются", () => {
    assert.equal(siteBase(), "");
    assert.equal(withBase("/news/example/"), "/news/example/");
    assert.equal(withBase("/"), "/");
});

test("SITE_BASE=/dobromir добавляет подпапку к внутренним путям", () => {
    process.env.SITE_BASE = "/dobromir";

    assert.equal(siteBase(), "/dobromir");
    assert.equal(withBase("/news/example/"), "/dobromir/news/example/");
    assert.equal(withBase("/#news"), "/dobromir/#news");
    assert.equal(withBase("/"), "/dobromir/");
});

test("хвостовые слэши в SITE_BASE убираются, корневая подпапка пуста", () => {
    process.env.SITE_BASE = "/dobromir///";
    assert.equal(siteBase(), "/dobromir");
    assert.equal(withBase("/media/photo.webp"), "/dobromir/media/photo.webp");

    process.env.SITE_BASE = "/";
    assert.equal(siteBase(), "");
    assert.equal(withBase("/news/"), "/news/");
});

test("внешние ссылки, телефон, якоря и относительные пути не меняются", () => {
    process.env.SITE_BASE = "/dobromir";
    const paths = [
        "https://vk.com/dobromir.crimea",
        "http://example.com/path",
        "tel:+79780000000",
        "#news",
        "news/example/",
    ];

    for (const path of paths) assert.equal(withBase(path), path);
});

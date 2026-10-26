import assert from "node:assert/strict";
import { test } from "node:test";

import { parseVkText, plainVkText, safeHref, type Segment } from "./vktext.ts";

function links(text: string): string[] {
    return parseVkText(text)
        .flat()
        .filter(
            (s): s is Extract<Segment, { type: "link" }> => s.type === "link",
        )
        .map((s) => s.href);
}

test("абзацы по пустой строке", () => {
    assert.equal(parseVkText("Первый\nвсе еще первый\n\nВторой").length, 2);
    assert.deepEqual(parseVkText("\n\n  \n"), []);
});

test("упоминания VK становятся ссылками на vk.com", () => {
    const [p] = parseVkText("Спасибо [club123|Добромиру] и [id45|Анне]!");
    assert.deepEqual(p, [
        { type: "text", value: "Спасибо " },
        { type: "link", href: "https://vk.com/club123", label: "Добромиру" },
        { type: "text", value: " и " },
        { type: "link", href: "https://vk.com/id45", label: "Анне" },
        { type: "text", value: "!" },
    ]);
});

test("адреса - ссылками, точка в конце не входит", () => {
    assert.deepEqual(links("См. https://ru.wikipedia.org/wiki/Антарктида."), [
        "https://ru.wikipedia.org/wiki/%D0%90%D0%BD%D1%82%D0%B0%D1%80%D0%BA%D1%82%D0%B8%D0%B4%D0%B0",
    ]);
});

test("хэштеги отдельными кусками", () => {
    const tags = parseVkText("Новости #тест #антарктика@dobromir")
        .flat()
        .filter((s) => s.type === "tag");
    assert.deepEqual(
        tags.map((s) => (s.type === "tag" ? s.value : "")),
        ["#тест", "#антарктика@dobromir"],
    );
});

test("XSS: только http(s) становится ссылкой", () => {
    assert.equal(safeHref("javascript:alert(1)"), null);
    assert.equal(safeHref("data:text/html,<script>alert(1)</script>"), null);
    assert.deepEqual(links("[javascript:alert(1)|жми]"), []);
    assert.deepEqual(links("javascript:alert(1)"), []);
    // разметка остается текстом - экранирует ее Astro при выводе
    const [p] = parseVkText(
        '<script>alert("x")</script> <img src=x onerror=alert(1)>',
    );
    assert.deepEqual(p, [
        {
            type: "text",
            value: '<script>alert("x")</script> <img src=x onerror=alert(1)>',
        },
    ]);
});

test("кавычки и скобки рядом с адресом", () => {
    assert.deepEqual(links("(подробнее: https://example.org/a)"), [
        "https://example.org/a",
    ]);
    assert.deepEqual(links("«https://example.org/b»"), [
        "https://example.org/b",
    ]);
});

test("текст без разметки VK: упоминания - только название", () => {
    assert.equal(
        plainVkText(
            "Ссылка на [club1|группу] и [https://example.org|сайт], #тег остается",
        ),
        "Ссылка на группу и сайт, #тег остается",
    );
    assert.equal(plainVkText("Без разметки"), "Без разметки");
});

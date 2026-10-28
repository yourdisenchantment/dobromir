import assert from "node:assert/strict";
import { test } from "node:test";

import { fixTexts, typography } from "./typography.ts";

test("лишние пробелы", () => {
    assert.equal(typography("  Центр   для\tдетей "), "Центр для детей");
});

test("дефис между словами - тире, внутри слова - нет", () => {
    assert.equal(typography("Добромир - это центр"), "Добромир — это центр");
    assert.equal(typography("Пн – Пт"), "Пн — Пт");
    assert.equal(typography("кто-то 9-18"), "кто-то 9-18");
    assert.equal(typography("- запуск речи;"), "— запуск речи;");
});

test("прямые кавычки - елочки, непарные не трогаем", () => {
    assert.equal(
        typography('Центр "Добромир" (программа "Шаг")'),
        "Центр «Добромир» (программа «Шаг»)",
    );
    assert.equal(typography('"Цитата"'), "«Цитата»");
    assert.equal(typography('рост 5"'), 'рост 5"');
});

test("правильный текст не меняется", () => {
    const s = "Центр «Добромир» — для детей и родителей.";
    assert.equal(typography(s), s);
});

test("ссылки, имена файлов и номера не трогаем", () => {
    const block = {
        type: "contacts",
        title: 'Как  нас найти - "просто"',
        map: "https://yandex.ru/maps/-/abc",
        phones: [{ label: "Запись", number: "+7 978 229 - 48 - 54" }],
        items: [{ photo: "ivanova  - 2.webp", href: "#contacts" }],
    };
    const { value, changes } = fixTexts(block);
    assert.deepEqual(value, {
        ...block,
        title: "Как нас найти — «просто»",
    });
    assert.deepEqual(
        changes.map((c) => c.path),
        ["title"],
    );
});

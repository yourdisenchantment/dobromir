import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

// Карта старых адресов (P2-5) живет в deploy/htaccess.example; здесь - что ее цели есть на
// сайте: редирект на несуществующего специалиста дал бы 404 вместо старой страницы.
const htaccess = readFileSync(
    new URL("../../../deploy/htaccess.example", import.meta.url),
    "utf-8",
);
const specialists = JSON.parse(
    readFileSync(
        new URL("../../content/blocks/specialists/block.json", import.meta.url),
        "utf-8",
    ),
) as { items: { slug: string }[] };
const page = JSON.parse(
    readFileSync(new URL("../../content/page.json", import.meta.url), "utf-8"),
) as { blocks: string[] };

const rules = [
    ...htaccess.matchAll(/^\s*RewriteRule\s+(\S+)\s+(\S+)\s+\[([^\]]+)\]/gmu),
].map((m) => ({ from: m[1], to: m[2], flags: m[3] }));

test("редиректы на специалистов ведут на существующие страницы", () => {
    const slugs = new Set(specialists.items.map((s) => s.slug));
    const targets = rules
        .map((r) => /^\/specialisty\/([^/]+)\/$/u.exec(r.to)?.[1])
        .filter((s): s is string => s !== undefined);
    assert.equal(targets.length, 16, "16 специалистов старого сайта");
    for (const slug of targets)
        assert.ok(slugs.has(slug), `нет специалиста ${slug}`);
});

test("редиректы на блоки лендинга ведут на существующие блоки", () => {
    const anchors = rules
        .map((r) => /^\/#([a-z-]+)$/u.exec(r.to)?.[1])
        .filter((s): s is string => s !== undefined);
    assert.deepEqual(anchors, ["about", "contacts", "specialists"]);
    for (const id of anchors)
        assert.ok(page.blocks.includes(id), `нет блока ${id}`);
});

test("все редиректы постоянные (301)", () => {
    assert.ok(rules.length > 0);
    for (const r of rules)
        if (r.to !== "-") assert.match(r.flags, /R=301/u, r.from);
});

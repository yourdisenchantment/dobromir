// Подготовка ручного содержимого перед сборкой (npm run build, решено 2026-10-28).
// У админа - доводит сама: фото из block.json переводит в WebP до 800 px без метаданных
// и вписывает новое имя, тексты правит по правилам типографики (src/lib/typography.ts).
// На сервере и в хуке (--check или CONTENT_CHECK_ONLY=1) ничего не меняет: если что-то
// не доведено, сообщает и завершается с ошибкой - файлы в клоне на сервере не правятся.
// Остальное (поля, типы, наличие файлов) проверяет сама сборка: src/lib/content.ts.

import {
    existsSync,
    readdirSync,
    readFileSync,
    renameSync,
    writeFileSync,
} from "node:fs";
import { extname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

import { format, resolveConfig } from "prettier";
import sharp from "sharp";

import { fixTexts } from "../src/lib/typography.ts";

const SITE = fileURLToPath(new URL("..", import.meta.url));
const BLOCKS = join(SITE, "content", "blocks");
/** Длинная сторона фото на сайте; больше не нужно ни карточке, ни странице специалиста. */
const MAX_SIDE = 800;
const QUALITY = 82;
const SOURCES = new Set([
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
    ".gif",
    ".avif",
    ".heic",
    ".heif",
]);

const checkOnly =
    process.argv.includes("--check") || process.env.CONTENT_CHECK_ONLY === "1";
const show = (p: string) => relative(join(SITE, ".."), p);

type Item = { photo?: unknown };

/** Готово ли фото для сайта: WebP, не больше MAX_SIDE, без EXIF/XMP/IPTC. */
async function ready(file: string): Promise<boolean> {
    if (extname(file).toLowerCase() !== ".webp") return false;
    const m = await sharp(file).metadata();
    return (
        (m.width ?? 0) <= MAX_SIDE &&
        (m.height ?? 0) <= MAX_SIDE &&
        !m.exif &&
        !m.xmp &&
        !m.iptc
    );
}

/** Поворот по EXIF, уменьшение, WebP; метаданные sharp не переносит. */
async function convert(from: string, to: string): Promise<void> {
    const input = readFileSync(from); // буфер: from и to могут быть одним файлом
    const tmp = `${to}.tmp`;
    try {
        await sharp(input)
            .rotate()
            .resize({
                width: MAX_SIDE,
                height: MAX_SIDE,
                fit: "inside",
                withoutEnlargement: true,
            })
            .webp({ quality: QUALITY })
            .toFile(tmp);
    } catch {
        const heic = /\.hei[cf]$/iu.test(from);
        throw new Error(
            heic
                ? `${show(from)}: формат HEIC (фото с iPhone) не читается - сохраните фото в JPEG и укажите его`
                : `${show(from)}: не удалось прочитать картинку - сохраните ее в JPEG или PNG`,
        );
    }
    renameSync(tmp, to);
}

type Report = { done: string[]; notes: string[]; problems: string[] };

async function prepare(
    block: string,
    { done, notes, problems }: Report,
): Promise<void> {
    const file = join(BLOCKS, block, "block.json");
    if (!existsSync(file)) return;
    let data: unknown;
    try {
        data = JSON.parse(readFileSync(file, "utf8"));
    } catch (e) {
        problems.push(
            `${show(file)}: JSON не читается (${(e as Error).message}) - проверьте запятые и кавычки`,
        );
        return;
    }
    let changed = false;

    const photos = join(BLOCKS, block, "photos");
    const items = (data as { items?: unknown }).items;
    if (existsSync(photos) && Array.isArray(items)) {
        const used = new Set<string>();
        for (const [n, item] of (items as Item[]).entries()) {
            if (typeof item?.photo !== "string") continue;
            const src = join(photos, item.photo);
            const ext = extname(item.photo).toLowerCase();
            const webp =
                item.photo.slice(0, item.photo.length - ext.length) + ".webp";
            used.add(webp);
            if (!existsSync(src) || (ext !== ".webp" && !SOURCES.has(ext)))
                continue; // скажет сборка
            if (await ready(src)) continue;
            if (checkOnly) {
                problems.push(
                    `${show(src)}: фото не обработано (нужен WebP до ${MAX_SIDE} px без метаданных) - запустите npm run build у себя`,
                );
                continue;
            }
            await convert(src, join(photos, webp));
            done.push(
                `${show(src)} -> ${webp} (WebP, до ${MAX_SIDE} px, без метаданных)`,
            );
            if (webp !== item.photo) {
                (items as Item[])[n] = { ...item, photo: webp };
                changed = true;
            }
        }
        const leftovers = readdirSync(photos).filter(
            (f) =>
                SOURCES.has(extname(f).toLowerCase()) ||
                (extname(f) === ".webp" && !used.has(f)),
        );
        if (leftovers.length && !checkOnly)
            notes.push(
                `в ${show(photos)} не используются: ${leftovers.join(", ")} - можно удалить (в git исходники не попадут)`,
            );
    }

    const { value, changes } = fixTexts(data);
    if (changes.length) {
        if (checkOnly) {
            for (const c of changes)
                problems.push(
                    `${show(file)}: ${c.path}: «${c.from}» надо «${c.to}» - запустите npm run build у себя`,
                );
        } else {
            for (const c of changes)
                done.push(`${show(file)}: ${c.path}: «${c.from}» -> «${c.to}»`);
            data = value;
            changed = true;
        }
    }

    if (changed && !checkOnly) {
        const options = { ...(await resolveConfig(file)), parser: "json" };
        writeFileSync(
            file,
            await format(JSON.stringify(data, null, 4), options),
        );
    }
}

const report: Report = { done: [], notes: [], problems: [] };
for (const block of readdirSync(BLOCKS).sort()) {
    try {
        await prepare(block, report);
    } catch (e) {
        report.problems.push((e as Error).message);
    }
}
const list = (lines: string[]) => lines.map((l) => `  - ${l}`).join("\n");
if (report.done.length)
    console.log(`Содержимое доведено:\n${list(report.done)}`);
if (report.notes.length) console.log(`Заметки:\n${list(report.notes)}`);
if (report.problems.length) {
    console.error(
        `Содержимое не готово:\n${list(report.problems)}\n` +
            "Что сборка правит сама - docs/HOWTO-add-content.md.",
    );
    process.exit(1);
}

// Ручное содержимое лендинга: site/content/blocks/<блок>/block.json и картинки рядом
// (решено 2026-10-25). Проверяется схемой при сборке: ошибка в JSON или нет файла фото -
// сборка падает с понятным сообщением по-русски, сломанный сайт не выходит.

import type { ImageMetadata } from "astro";
import { z } from "zod";

import specialistsJson from "../../content/blocks/specialists/block.json";

const specialistPhotos = import.meta.glob<ImageMetadata>(
    "../../content/blocks/specialists/photos/*",
    { eager: true, import: "default" },
);

const text = (what: string) =>
    z
        .string({ error: `${what}: нужен текст` })
        .trim()
        .min(1, `${what}: пусто`);

const SpecialistSchema = z.object({
    slug: z
        .string({ error: "slug: нужен адрес латиницей" })
        .regex(
            /^[a-z][a-z0-9-]*$/u,
            "slug: только латиница, цифры и дефис, например shepitko",
        ),
    name: text("name (имя)"),
    position: text("position (должность)"),
    short: text("short (кратко)").optional(),
    photo: text("photo (файл фото)"),
    description: z.array(text("description (абзац)"), {
        error: "description: нужен список абзацев",
    }),
});

const SpecialistsBlockSchema = z.object({
    type: z.literal("specialists"),
    title: text("title (заголовок блока)"),
    intro: text("intro (вводный абзац)").optional(),
    items: z
        .array(SpecialistSchema)
        .min(1, "items: нужен хотя бы один специалист"),
});

export type Specialist = z.infer<typeof SpecialistSchema> & {
    image: ImageMetadata;
};
export type SpecialistsBlock = Omit<
    z.infer<typeof SpecialistsBlockSchema>,
    "items"
> & {
    items: Specialist[];
};

/** Ошибка содержимого: какой файл, какое место, что не так. */
function fail(file: string, problems: string[]): never {
    throw new Error(
        `Ошибка в ${file}:\n${problems.map((p) => `  - ${p}`).join("\n")}\n` +
            "Формат блоков - docs/pages.md.",
    );
}

let specialistsCache: SpecialistsBlock | undefined;

export function loadSpecialists(): SpecialistsBlock {
    if (specialistsCache) return specialistsCache;
    const file = "site/content/blocks/specialists/block.json";
    const parsed = SpecialistsBlockSchema.safeParse(specialistsJson);
    if (!parsed.success) {
        fail(
            file,
            parsed.error.issues.map((i) => {
                const where = i.path.length ? `${i.path.join(".")}: ` : "";
                return `${where}${i.message}`;
            }),
        );
    }
    const block = parsed.data;
    const problems: string[] = [];
    const seen = new Set<string>();
    const items = block.items.map((item, n) => {
        if (seen.has(item.slug))
            problems.push(`items.${n}.slug: адрес ${item.slug} уже занят`);
        seen.add(item.slug);
        const image =
            specialistPhotos[
                `../../content/blocks/specialists/photos/${item.photo}`
            ];
        if (!image)
            problems.push(`items.${n}.photo: нет файла photos/${item.photo}`);
        return { ...item, image: image as ImageMetadata };
    });
    if (problems.length) fail(file, problems);
    specialistsCache = { ...block, items };
    return specialistsCache;
}

/** Специалист как карточка (components/Card.astro): фото в рамке 4:5 по лицу,
 *  имя, должность, «кратко»; открывается во всплывающем окне. */
export function specialistCard(person: Specialist) {
    return {
        title: person.name,
        subtitle: person.position,
        text: person.short,
        href: `/specialisty/${person.slug}/`,
        modal: true,
        ratio: "4/5" as const,
        focus: "50% 15%",
        image: {
            src: person.image.src,
            width: person.image.width,
            height: person.image.height,
            alt: "",
        },
    };
}

/** Абзацы описания: строки, начинающиеся с «— », собираются в список. */
export type DescriptionPart =
    { type: "p"; text: string } | { type: "list"; items: string[] };

export function descriptionParts(lines: string[]): DescriptionPart[] {
    const parts: DescriptionPart[] = [];
    for (const line of lines) {
        const item = /^[—-]\s+(.*)$/u.exec(line);
        const last = parts.at(-1);
        if (item) {
            if (last?.type === "list") last.items.push(item[1]);
            else parts.push({ type: "list", items: [item[1]] });
        } else {
            parts.push({ type: "p", text: line });
        }
    }
    return parts;
}

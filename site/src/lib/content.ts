// Ручное содержимое лендинга: site/content/blocks/<блок>/block.json и картинки рядом
// (решено 2026-10-25). Проверяется схемой при сборке: ошибка в JSON или нет файла фото -
// сборка падает с понятным сообщением по-русски, сломанный сайт не выходит.

import type { ImageMetadata } from "astro";
import { z } from "zod";

import { iconNames, icons } from "./icons";

import pageJson from "../../content/page.json";
import specialistsJson from "../../content/blocks/specialists/block.json";

const blockFiles = import.meta.glob<unknown>(
    "../../content/blocks/*/block.json",
    {
        eager: true,
        import: "default",
    },
);

const specialistPhotos = import.meta.glob<ImageMetadata>(
    "../../content/blocks/specialists/photos/*",
    { eager: true, import: "default" },
);

const text = (what: string) =>
    z
        .string({ error: `${what}: нужен текст` })
        .trim()
        .min(1, `${what}: пусто`);

/** Пункт меню в шапке: блок с этим полем попадает в меню, порядок - как в page.json. */
const menu = text("menu (пункт меню)").max(20, "menu: не длиннее 20 знаков");

const SpecialistSchema = z.strictObject({
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

const SpecialistsBlockSchema = z.strictObject({
    type: z.literal("specialists"),
    menu: menu.optional(),
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

// Остальные типы блоков лендинга (docs/pages.md). Специалисты - выше, у них свои фото.
const Action = z.strictObject({
    label: text("label (надпись)"),
    href: text("href (ссылка)"),
});
const HeroSchema = z.strictObject({
    type: z.literal("hero"),
    menu: menu.optional(),
    title: text("title (заголовок)"),
    lead: text("lead (подзаголовок)").optional(),
    actions: z
        .array(Action)
        .max(2, "actions: не больше двух кнопок")
        .default([]),
});
const TextSchema = z.strictObject({
    type: z.literal("text"),
    menu: menu.optional(),
    title: text("title (заголовок)"),
    quote: z
        .object({
            text: text("quote.text (цитата)"),
            author: text("quote.author (автор)").optional(),
        })
        .optional(),
    paragraphs: z.array(text("paragraphs (абзац)"), {
        error: "paragraphs: нужен список абзацев",
    }),
});
const CardsSchema = z.strictObject({
    type: z.literal("cards"),
    menu: menu.optional(),
    title: text("title (заголовок)"),
    intro: text("intro (вводный абзац)").optional(),
    items: z
        .array(
            z.strictObject({
                title: text("title (заголовок карточки)"),
                subtitle: text("subtitle (подзаголовок)").optional(),
                text: text("text (текст)").optional(),
                list: z.array(text("list (пункт)")).optional(),
            }),
        )
        .min(1, "items: нужна хотя бы одна карточка"),
});
const FactsSchema = z.strictObject({
    type: z.literal("facts"),
    menu: menu.optional(),
    title: text("title (заголовок)"),
    items: z
        .array(
            z.strictObject({
                icon: z
                    .string({ error: "icon: нужно имя иконки" })
                    .refine((n) => n in icons, {
                        error: `нет такой иконки; есть ${iconNames.join(", ")}`,
                    })
                    .optional(),
                value: text("value (число)"),
                label: text("label (подпись)"),
                source: z
                    .object({
                        title: text("source.title (источник)"),
                        url: z.url("source.url: нужна ссылка").optional(),
                    })
                    .optional(),
            }),
        )
        .min(1, "items: нужна хотя бы одна цифра"),
});
const NewsBlockSchema = z.strictObject({
    type: z.literal("news"),
    menu: menu.optional(),
    title: text("title (заголовок)"),
    count: z.number().int().min(1).max(30, "count: не больше 30").default(12),
});
const QuotesSchema = z.strictObject({
    type: z.literal("quotes"),
    menu: menu.optional(),
    title: text("title (заголовок)"),
    items: z
        .array(
            z.strictObject({
                text: text("text (отзыв)"),
                author: text("author (кто)").optional(),
            }),
        )
        .min(1, "items: нужен хотя бы один отзыв"),
});
const ContactsSchema = z.strictObject({
    type: z.literal("contacts"),
    menu: menu.optional(),
    title: text("title (заголовок)"),
    address: text("address (адрес)"),
    text: text("text (как добраться)").optional(),
    map: z.url("map: нужна ссылка на карту").optional(),
    phones: z
        .array(
            z.strictObject({
                label: text("label (подпись)"),
                number: text("number (номер)"),
            }),
        )
        .min(1, "phones: нужен хотя бы один телефон"),
    vk: z.url("vk: нужна ссылка").optional(),
});
// Только тип: остальное проверяет SpecialistsBlockSchema в loadSpecialists.
const SpecialistsRef = z.looseObject({
    type: z.literal("specialists"),
    menu: menu.optional(),
});

const BlockSchema = z.discriminatedUnion(
    "type",
    [
        HeroSchema,
        TextSchema,
        CardsSchema,
        FactsSchema,
        NewsBlockSchema,
        QuotesSchema,
        ContactsSchema,
        SpecialistsRef,
    ],
    {
        error: "неизвестный тип блока; есть hero, text, cards, facts, news, specialists, quotes, contacts",
    },
);
const PageSchema = z.strictObject({
    blocks: z
        .array(
            z
                .string()
                .regex(
                    /^[a-z][a-z0-9-]*$/u,
                    "blocks: имя папки блока латиницей, например services",
                ),
        )
        .min(1, "blocks: нужен хотя бы один блок"),
});

export type Block =
    | z.infer<typeof HeroSchema>
    | z.infer<typeof TextSchema>
    | z.infer<typeof CardsSchema>
    | z.infer<typeof FactsSchema>
    | z.infer<typeof NewsBlockSchema>
    | z.infer<typeof QuotesSchema>
    | z.infer<typeof ContactsSchema>
    | ({ type: "specialists" } & SpecialistsBlock);

/** Ошибка содержимого: какой файл, какое место, что не так. */
function fail(file: string, problems: string[]): never {
    throw new Error(
        `Ошибка в ${file}:\n${problems.map((p) => `  - ${p}`).join("\n")}\n` +
            "Формат блоков - docs/HOWTO-add-content.md.",
    );
}

function issues(error: z.ZodError): string[] {
    return error.issues.map((i) => {
        const where = i.path.length ? `${i.path.join(".")}: ` : "";
        // Опечатка в имени поля не должна теряться молча: такого поля нет в справочнике.
        if (i.code === "unrecognized_keys")
            return `${where}лишнее поле ${i.keys.join(", ")} - такого нет в docs/HOWTO-add-content.md`;
        return `${where}${i.message}`;
    });
}

/** Лендинг: блоки в порядке site/content/page.json; id блока - имя его папки (якорь меню). */
export function loadPage(): { id: string; block: Block }[] {
    const page = PageSchema.safeParse(pageJson);
    if (!page.success) fail("site/content/page.json", issues(page.error));
    const seen = new Set<string>();
    return page.data.blocks.map((id) => {
        if (seen.has(id))
            fail("site/content/page.json", [
                `blocks: блок ${id} указан дважды`,
            ]);
        seen.add(id);
        const file = `site/content/blocks/${id}/block.json`;
        const raw = blockFiles[`../../content/blocks/${id}/block.json`];
        if (raw === undefined)
            fail("site/content/page.json", [`blocks: нет файла ${file}`]);
        const parsed = BlockSchema.safeParse(raw);
        if (!parsed.success) fail(file, issues(parsed.error));
        if (parsed.data.type !== "specialists")
            return { id, block: parsed.data };
        if (id !== "specialists")
            fail(file, ["блок специалистов должен лежать в папке specialists"]);
        return {
            id,
            block: loadSpecialists(),
        };
    });
}

/** Пункты меню шапки: блоки с полем menu в порядке page.json. */
export function menuLinks(): { id: string; label: string }[] {
    return loadPage().flatMap(({ id, block }) =>
        block.menu ? [{ id, label: block.menu }] : [],
    );
}

/** Контакты для шапки, подвала и страниц: блок contacts лендинга - единственное место
 *  адреса и телефонов. Первый телефон блока - для записи. */
export function siteContacts() {
    const found = loadPage().find(({ block }) => block.type === "contacts");
    if (!found || found.block.type !== "contacts")
        fail("site/content/page.json", [
            "blocks: нужен блок типа contacts - из него шапка и подвал берут телефон",
        ]);
    const { address, phones, vk } = found.block;
    return { address, phones, vk, booking: phones[0] };
}

/** Ссылка tel: из номера в любом написании: «+7 978 229-48-54» -> tel:+79782294854. */
export function tel(number: string): string {
    return `tel:${number.replace(/[^+\d]/gu, "")}`;
}

let specialistsCache: SpecialistsBlock | undefined;

export function loadSpecialists(): SpecialistsBlock {
    if (specialistsCache) return specialistsCache;
    const file = "site/content/blocks/specialists/block.json";
    const parsed = SpecialistsBlockSchema.safeParse(specialistsJson);
    if (!parsed.success) {
        fail(file, issues(parsed.error));
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

/** Специалист как карточка (components/Card.astro): фото в квадратной рамке по лицу (было 4:5; ближе к квадрату - 2026-10-27),
 *  имя, должность, «кратко»; открывается во всплывающем окне. */
export function specialistCard(person: Specialist) {
    return {
        title: person.name,
        subtitle: person.position,
        text: person.short,
        href: `/specialisty/${person.slug}/`,
        modal: true,
        ratio: "1/1" as const,
        focus: "50% 20%",
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

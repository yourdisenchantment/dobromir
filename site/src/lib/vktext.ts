// Разбор текста поста VK в безопасные куски. HTML здесь не собирается: страница выводит
// куски обычными тегами Astro, а Astro экранирует текст сам. Поэтому «<script>» в посте
// так и останется текстом, а ссылкой станет только http(s)-адрес.

export type Segment =
    | { type: "text"; value: string }
    | { type: "link"; href: string; label: string }
    | { type: "tag"; value: string };

export type Paragraph = Segment[];

// [club123|Название], [public123|...], [id123|Имя], [https://...|текст]
const MENTION =
    /\[((?:club|public|event|id)\d+|https?:\/\/[^\]|\s]+)\|([^\]]+)\]/gu;
const URL_RE = /https?:\/\/[^\s<>"'«»]+/gu;
const HASHTAG = /#[\p{L}\p{N}_]+(?:@[\w.]+)?/gu;
const TRAILING_PUNCT = /[.,;:!?)\]]+$/u;

export function safeHref(raw: string): string | null {
    try {
        const url = new URL(raw);
        return url.protocol === "https:" || url.protocol === "http:"
            ? url.href
            : null;
    } catch {
        return null;
    }
}

function mentionHref(target: string): string | null {
    return /^(club|public|event|id)\d+$/u.test(target)
        ? `https://vk.com/${target}`
        : safeHref(target);
}

/** Текст без разметки VK: упоминание [club1|Название] -> «Название». Для анонсов,
 *  описаний и RSS, где ссылок нет, а служебный текст VK читателю не нужен. */
export function plainVkText(text: string): string {
    return text.replace(MENTION, (_m, _target: string, label: string) => label);
}

/** Текст поста -> абзацы (пустая строка - граница абзаца) из кусков. */
export function parseVkText(text: string): Paragraph[] {
    return text
        .replace(/\r\n?/gu, "\n")
        .split(/\n\s*\n/u)
        .map((block) => block.trim())
        .filter((block) => block.length > 0)
        .map(parseBlock);
}

function parseBlock(block: string): Paragraph {
    const out: Segment[] = [];
    let last = 0;
    for (const m of block.matchAll(MENTION)) {
        pushPlain(out, block.slice(last, m.index));
        const href = mentionHref(m[1] ?? "");
        const label = m[2] ?? "";
        out.push(
            href
                ? { type: "link", href, label }
                : { type: "text", value: label },
        );
        last = (m.index ?? 0) + m[0].length;
    }
    pushPlain(out, block.slice(last));
    return out;
}

/** Обычный текст: адреса - ссылками, хэштеги - отдельными кусками. */
function pushPlain(out: Segment[], text: string): void {
    const tokens: { start: number; end: number; seg: Segment }[] = [];
    for (const m of text.matchAll(URL_RE)) {
        const raw = m[0].replace(TRAILING_PUNCT, "");
        const href = safeHref(raw);
        if (href) {
            const start = m.index ?? 0;
            tokens.push({
                start,
                end: start + raw.length,
                seg: { type: "link", href, label: raw },
            });
        }
    }
    for (const m of text.matchAll(HASHTAG)) {
        const start = m.index ?? 0;
        if (!tokens.some((t) => start >= t.start && start < t.end)) {
            tokens.push({
                start,
                end: start + m[0].length,
                seg: { type: "tag", value: m[0] },
            });
        }
    }
    tokens.sort((a, b) => a.start - b.start);
    let pos = 0;
    for (const t of tokens) {
        if (t.start > pos) addText(out, text.slice(pos, t.start));
        out.push(t.seg);
        pos = t.end;
    }
    if (pos < text.length) addText(out, text.slice(pos));
}

function addText(out: Segment[], value: string): void {
    const prev = out[out.length - 1];
    if (prev?.type === "text") prev.value += value;
    else if (value) out.push({ type: "text", value });
}

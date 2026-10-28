// Текст карточки новости без повтора заголовка. Заголовок воркер берет из первой строки
// поста (pipeline/parse/posts.py: make_title), длинную строку обрезает по слову с «…».
// Если под заголовком снова показать начало текста, карточка повторяет одно и то же
// (замечено 2026-10-27), поэтому здесь - то, что идет после заголовка. Ссылки воркер
// из заголовка вырезает (title_line там же) - строка сравнивается так же, без них.

const URL = /https?:\/\/\S+/gu;

/** Как title_line в pipeline/parse/posts.py: строка без ссылок. Менять вместе. */
function titleLine(line: string): string {
    if (!line.match(URL)) return line.trim();
    return line
        .replace(URL, " ")
        .split(/\s+/u)
        .filter(Boolean)
        .join(" ")
        .replace(/[,.;:\- ]+$/u, "");
}

/** Текст поста после заголовка: остаток первой строки (с «…», если заголовок обрезан)
 *  и следующие строки. Если заголовок не из первой строки - текст целиком. */
export function restAfterTitle(text: string, title: string): string {
    const lines = text.split(/\r?\n/u);
    const first = lines.findIndex((l) => titleLine(l) !== "");
    if (first < 0 || !title) return text;
    const line = titleLine(lines[first]);
    const rest = lines.slice(first + 1).join("\n");
    if (line === title) return rest.trim();
    const cut = title.endsWith("…") ? title.slice(0, -1) : "";
    if (!cut || !line.startsWith(cut)) return text;
    // остаток обрезанной строки: без знаков, которые make_title срезал перед «…»
    const tail = line.slice(cut.length).replace(/^[\s,.;:-]+/u, "");
    return [tail && `…${tail}`, rest].filter(Boolean).join("\n").trim();
}

/** Строка не длиннее max: обрезка по слову с «…». Для <title> новости - поисковики
 *  показывают около 60-70 знаков, а заголовок поста бывает до 120 (2026-10-28). */
export function clip(raw: string, max: number): string {
    const text = raw.replace(/\s+/gu, " ").trim(); // в постах VK бывают двойные пробелы
    if (text.length <= max) return text;
    const head = text.slice(0, max - 1);
    const cut = head.replace(/\s+\S*$/u, "") || head;
    return `${cut.replace(/[\s,.;:—-]+$/u, "")}…`;
}

// Типографика ручного содержимого (site/content/): сборка у админа правит тексты сама
// (решено 2026-10-28), на сервере только проверяет. Правила простые и предсказуемые:
// лишние пробелы, тире вместо дефиса между словами, «елочки» вместо прямых кавычек.

/** Поля, которые не текст, а имена, ссылки и номера: их не трогаем. */
const RAW_KEYS = new Set([
    "type",
    "slug",
    "photo",
    "icon",
    "href",
    "url",
    "map",
    "vk",
    "number",
]);

/** Текст по правилам сайта; строку без нарушений возвращает как есть. */
export function typography(s: string): string {
    let out = s
        .replace(/[ \t]+/gu, " ")
        .trim()
        // Дефис или короткое тире между словами - длинное тире.
        .replace(/ [-–] /gu, " — ")
        // Пункт списка в начале строки: «- текст» -> «— текст».
        .replace(/^[-–] /u, "— ");
    // Прямые кавычки - только парами, иначе непонятно, где открывающая.
    if ((out.match(/"/gu) ?? []).length % 2 === 0)
        out = out.replace(/(^|[\s([{«—-])"/gu, "$1«").replace(/"/gu, "»");
    return out;
}

/** Обходит JSON блока и правит строки; список правок - для сообщения. */
export function fixTexts(
    value: unknown,
    path = "",
    changes: { path: string; from: string; to: string }[] = [],
): { value: unknown; changes: typeof changes } {
    if (typeof value === "string") {
        const key = path.split(".").pop() ?? "";
        const raw =
            RAW_KEYS.has(key) || /^(https?:|mailto:|tel:|#|\/)/u.test(value);
        const to = raw ? value : typography(value);
        if (to !== value) changes.push({ path, from: value, to });
        return { value: to, changes };
    }
    if (Array.isArray(value))
        return {
            value: value.map(
                (v, i) =>
                    fixTexts(v, path ? `${path}.${i}` : `${i}`, changes).value,
            ),
            changes,
        };
    if (value && typeof value === "object")
        return {
            value: Object.fromEntries(
                Object.entries(value).map(([k, v]) => [
                    k,
                    fixTexts(v, path ? `${path}.${k}` : k, changes).value,
                ]),
            ),
            changes,
        };
    return { value, changes };
}

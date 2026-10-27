// Иконки Material Symbols Rounded (Google, лицензия Apache 2.0 - src/assets/icons/LICENSE),
// скачаны 2026-10-27 и лежат в проекте: с серверов Google на сайте ничего не грузится
// (из Крыма они могут не открываться, и адрес посетителя уходил бы Google). В каждом
// файле один <path> - он и вставляется в разметку, цвет - currentColor.
// Новая иконка: положить <имя>.svg с fonts.google.com/icons (стиль Rounded) в src/assets/icons/.

const files = import.meta.glob<string>("../assets/icons/*.svg", {
    eager: true,
    query: "?raw",
    import: "default",
});

/** Имя иконки -> контур (атрибут d) и viewBox. */
export const icons: Record<string, { d: string; viewBox: string }> = {};
for (const [path, svg] of Object.entries(files)) {
    const name = path.replace(/^.*\/|\.svg$/gu, "");
    const d = /<path d="([^"]+)"/u.exec(svg)?.[1];
    const viewBox = /viewBox="([^"]+)"/u.exec(svg)?.[1];
    if (!d || !viewBox)
        throw new Error(
            `src/assets/icons/${name}.svg: нет <path d> или viewBox`,
        );
    icons[name] = { d, viewBox };
}

export const iconNames = Object.keys(icons).sort();

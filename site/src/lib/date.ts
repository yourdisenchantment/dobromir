// Даты на сайте - только абсолютные и только по Симферополю: «12 октября 2026».
// Пояс зашит в сборку, а не берется с компьютера посетителя.

export const TIME_ZONE = "Europe/Simferopol";

const DAY_MONTH_YEAR = new Intl.DateTimeFormat("ru-RU", {
    timeZone: TIME_ZONE,
    day: "numeric",
    month: "long",
    year: "numeric",
});

const ISO_DAY = new Intl.DateTimeFormat("en-CA", {
    timeZone: TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
});

/** «12 октября 2026» - без «г.», который добавляет ru-RU. */
export function formatDate(iso: string): string {
    const parts = DAY_MONTH_YEAR.formatToParts(new Date(iso));
    const pick = (type: Intl.DateTimeFormatPartTypes): string =>
        parts.find((p) => p.type === type)?.value ?? "";
    return `${pick("day")} ${pick("month")} ${pick("year")}`;
}

/** День публикации по Симферополю, «2026-10-12». */
export function localDay(iso: string): string {
    return ISO_DAY.format(new Date(iso));
}

/** «Обновлено» показываем, только если правка была в другой день, чем публикация. */
export function showUpdated(published: string, edited: string | null): boolean {
    return edited !== null && localDay(edited) !== localDay(published);
}

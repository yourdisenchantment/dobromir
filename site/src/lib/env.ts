// Настройки сборки из окружения. Задает их воркер (P1-6); при локальной разработке -
// значения по умолчанию. Читаются только здесь, чтобы не размазывать process.env по сайту.

const DEFAULT_SITE_URL = "https://xn----9sbirljdkbtdc7l.xn--p1ai";

export type SiteEnv = "production" | "staging";

export function siteEnv(): SiteEnv {
    const value = process.env.SITE_ENV ?? "staging";
    if (value !== "production" && value !== "staging") {
        throw new Error(
            `SITE_ENV должна быть production или staging, получено ${JSON.stringify(value)}`,
        );
    }
    return value;
}

export function siteUrl(): string {
    return (process.env.SITE_URL || DEFAULT_SITE_URL).replace(/\/+$/, "");
}

/** Подпапка публикации ("" для корня), без завершающих слэшей. */
export function siteBase(): string {
    return (process.env.SITE_BASE ?? "").replace(/\/+$/, "");
}

/** Добавляет подпапку только к внутреннему абсолютному пути. */
export function withBase(path: string): string {
    const base = siteBase();
    if (!base || !path.startsWith("/")) return path;
    return `${base}${path}`;
}

export function newsJsonPath(): string | undefined {
    return process.env.NEWS_JSON || undefined;
}

/** Подтверждение прав в Яндекс.Вебмастере и Google Search Console; пусто - тега нет. */
export function verification(): { yandex?: string; google?: string } {
    return {
        yandex: process.env.YANDEX_VERIFICATION || undefined,
        google: process.env.GOOGLE_VERIFICATION || undefined,
    };
}

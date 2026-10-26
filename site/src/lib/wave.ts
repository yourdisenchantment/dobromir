// Волна-разделитель секций со своими изгибами у каждой секции (решено 2026-10-26).
// Форма считается при сборке из имени секции: волны не повторяются, но одна и та же
// секция от сборки к сборке выглядит одинаково, и на странице нет ни строчки JS.

export const WAVE_WIDTH = 1440;
export const WAVE_HEIGHT = 80;
const TOP = 14; // самая высокая точка изгиба
const BOTTOM = 62; // самая низкая: ниже - полоса цвета секции

/** Детерминированный генератор псевдослучайных чисел (mulberry32) от строки. */
function random(seed: string): () => number {
    let h = 2166136261;
    for (let i = 0; i < seed.length; i++) {
        h = Math.imul(h ^ seed.charCodeAt(i), 16777619);
    }
    let a = h >>> 0;
    return () => {
        a = (a + 0x6d2b79f5) >>> 0;
        let t = a;
        t = Math.imul(t ^ (t >>> 15), t | 1);
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
}

const round = (n: number) => Math.round(n * 10) / 10;

/**
 * SVG-путь волны: 4-6 изгибов случайной высоты, сглаженных кривыми Безье
 * (Catmull-Rom), снизу закрыт прямоугольником цвета следующей секции.
 */
export function wavePath(seed: string): string {
    const rand = random(seed);
    const bends = 4 + Math.floor(rand() * 3);
    const points: [number, number][] = [];
    for (let i = 0; i <= bends; i++) {
        const jitter =
            i === 0 || i === bends
                ? 0
                : (rand() - 0.5) * (WAVE_WIDTH / bends) * 0.4;
        points.push([
            round((i * WAVE_WIDTH) / bends + jitter),
            round(TOP + rand() * (BOTTOM - TOP)),
        ]);
    }
    let d = `M${points[0][0]},${points[0][1]}`;
    for (let i = 0; i < points.length - 1; i++) {
        const p0 = points[Math.max(0, i - 1)];
        const [p1, p2] = [points[i], points[i + 1]];
        const p3 = points[Math.min(points.length - 1, i + 2)];
        const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
        const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
        d += ` C${round(c1[0])},${round(c1[1])} ${round(c2[0])},${round(c2[1])} ${p2[0]},${p2[1]}`;
    }
    return `${d} L${WAVE_WIDTH},${WAVE_HEIGHT} L0,${WAVE_HEIGHT} Z`;
}

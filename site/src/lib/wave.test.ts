import assert from "node:assert/strict";
import { test } from "node:test";

import { WAVE_HEIGHT, WAVE_WIDTH, wavePath } from "./wave.ts";

function numbers(d: string): number[][] {
    return [...d.matchAll(/(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/g)].map((m) => [
        Number(m[1]),
        Number(m[2]),
    ]);
}

test("одна и та же секция - одна и та же волна от сборки к сборке", () => {
    assert.equal(wavePath("news"), wavePath("news"));
});

test("у разных секций волны разные", () => {
    const paths = new Set(
        ["news", "services", "specialists", "about", "contacts", "facts"].map(
            wavePath,
        ),
    );
    assert.equal(paths.size, 6);
});

test("волна от левого края до правого и не выходит за рамку", () => {
    for (const seed of ["a", "b", "news", "очень длинное имя секции"]) {
        const d = wavePath(seed);
        assert.match(d, /^M0,/);
        assert.match(
            d,
            new RegExp(`L${WAVE_WIDTH},${WAVE_HEIGHT} L0,${WAVE_HEIGHT} Z$`),
        );
        for (const [x, y] of numbers(d)) {
            assert.ok(x >= 0 && x <= WAVE_WIDTH, `x=${x}`);
            assert.ok(y >= 0 && y <= WAVE_HEIGHT, `y=${y}`);
        }
    }
});

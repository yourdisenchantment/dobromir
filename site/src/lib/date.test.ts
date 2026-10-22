import assert from "node:assert/strict";
import { test } from "node:test";

import { formatDate, localDay, showUpdated } from "./date.ts";

test("дата словами, без «г.»", () => {
    assert.equal(formatDate("2026-10-12T10:00:00+03:00"), "12 октября 2026");
    assert.equal(formatDate("2026-01-01T00:00:00+03:00"), "1 января 2026");
});

test("сутки по Симферополю, а не по UTC", () => {
    // 23:30 по Симферополю - 20:30 UTC того же дня: дата не меняется
    assert.equal(formatDate("2026-10-12T23:30:00+03:00"), "12 октября 2026");
    // 00:30 по Симферополю - еще 21:30 UTC предыдущего дня, но дата уже новая
    assert.equal(formatDate("2026-10-12T21:30:00Z"), "13 октября 2026");
    assert.equal(localDay("2026-10-12T21:30:00Z"), "2026-10-13");
});

test("«Обновлено» только при правке в другой день", () => {
    const published = "2026-10-12T10:00:00+03:00";
    assert.equal(showUpdated(published, null), false);
    assert.equal(showUpdated(published, "2026-10-12T23:59:00+03:00"), false);
    assert.equal(showUpdated(published, "2026-10-13T00:01:00+03:00"), true);
});

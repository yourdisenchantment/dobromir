// @ts-check
import js from "@eslint/js";
import astro from "eslint-plugin-astro";
import tsParser from "@typescript-eslint/parser";

// Плоский конфиг ESLint: массив конфигов, применяются по порядку.
export default [
    // Генерируемое и сторонее не линтим.
    {
        ignores: ["dist/", ".astro/", "node_modules/"],
    },
    js.configs.recommended,
    // Разбор .astro и правила против ошибок шаблона и клиентских скриптов.
    ...astro.configs["flat/recommended"],
    // Правила доступности для .astro (нужен eslint-plugin-jsx-a11y).
    ...astro.configs["flat/jsx-a11y-recommended"],
    // TypeScript во фронтматтере .astro. Без type-aware линтинга: типы проверяет astro check.
    {
        files: ["**/*.astro"],
        languageOptions: {
            parserOptions: {
                parser: tsParser,
            },
        },
    },
    {
        files: ["**/*.ts"],
        languageOptions: {
            parser: tsParser,
        },
        // Необъявленные имена в TS ловит проверка типов (astro check); no-undef не знает
        // глобалов Node и веба (process, URL, Response) и только мешает - так советует
        // и typescript-eslint.
        rules: {
            "no-undef": "off",
        },
    },
    // Конфиг выполняется в Node при сборке: process там есть.
    {
        files: ["*.config.mjs"],
        languageOptions: {
            globals: { process: "readonly" },
        },
    },
];

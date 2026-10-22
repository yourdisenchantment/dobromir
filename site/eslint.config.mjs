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
    },
];

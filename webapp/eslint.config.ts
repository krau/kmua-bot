import js from "@eslint/js";
import prettierConfig from "@vue/eslint-config-prettier";
import { defineConfigWithVueTs, vueTsConfigs } from "@vue/eslint-config-typescript";
import type { Linter } from "eslint";
import vue from "eslint-plugin-vue";

// The return type is annotated explicitly: inferring it would name a type through a
// pnpm-internal path, which TypeScript rejects as non-portable (TS2742).
const config: Linter.Config[] = defineConfigWithVueTs(
  {
    name: "ignores",
    ignores: ["dist/**", "node_modules/**", "../kmua/webapp/dist/**"],
  },
  js.configs.recommended,
  vue.configs["flat/recommended"],
  vueTsConfigs.recommended,
  {
    name: "project-rules",
    rules: {
      // Single-word component filenames are intentional (App.vue); the rest of the
      // tree already uses multi-word names.
      "vue/multi-word-component-names": "off",
      // Attribute order is handled by prettier, and the plugin's ordering fights it.
      "vue/attributes-order": "off",
      // Optional props are typed `string | undefined` and read as "absent". Adding
      // `undefined` defaults just to satisfy the rule is noise, and a real default
      // would be a lie for things like an optional hint line.
      "vue/require-default-prop": "off",
      "@typescript-eslint/consistent-type-imports": [
        "error",
        { prefer: "type-imports", fixStyle: "inline-type-imports" },
      ],
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      "no-console": ["error", { allow: ["warn", "error"] }],
    },
  },
  prettierConfig,
) as Linter.Config[];

export default config;

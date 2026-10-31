import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import globals from 'globals'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['dist/**', 'coverage/**', 'src/shared/api/schema.d.ts'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...pluginVue.configs['flat/recommended'],
  {
    files: ['**/*.{ts,vue}'],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { parser: tseslint.parser },
    },
    rules: {
      'vue/multi-word-component-names': 'off',
      'vue/max-attributes-per-line': 'off',
      'vue/singleline-html-element-content-newline': 'off',
      'vue/html-self-closing': 'off',
      '@typescript-eslint/no-explicit-any': 'error',
      'no-restricted-properties': [
        'error',
        {
          object: 'crypto',
          property: 'randomUUID',
          message: "Use createUuid from '@/shared/uuid' so LAN HTTP remains supported.",
        },
      ],
      'no-restricted-syntax': [
        'error',
        {
          selector:
            "MemberExpression[object.type='MemberExpression'][object.object.name='globalThis'][object.property.name='crypto'][property.name='randomUUID']",
          message: "Use createUuid from '@/shared/uuid' so LAN HTTP remains supported.",
        },
        {
          selector:
            "MemberExpression[object.type='MemberExpression'][object.object.name='window'][object.property.name='crypto'][property.name='randomUUID']",
          message: "Use createUuid from '@/shared/uuid' so LAN HTTP remains supported.",
        },
      ],
    },
  },
  {
    files: ['scripts/**/*.mjs', '*.config.{js,ts}'],
    languageOptions: { globals: globals.node },
  },
)

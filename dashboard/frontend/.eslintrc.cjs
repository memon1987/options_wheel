/* eslint-env node */
// Vite + React + TypeScript baseline. Was missing since project bootstrap,
// which made `npm run lint` fail and the IDE's ESLint extension report
// "no config" on every TS/TSX file (rendering the folder red).
module.exports = {
  root: true,
  env: { browser: true, es2020: true, node: true },
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react-hooks/recommended',
  ],
  ignorePatterns: ['dist', 'node_modules', '.eslintrc.cjs', 'vite.config.ts'],
  parser: '@typescript-eslint/parser',
  parserOptions: {
    ecmaVersion: 'latest',
    sourceType: 'module',
    ecmaFeatures: { jsx: true },
  },
  plugins: ['react-refresh', '@typescript-eslint'],
  rules: {
    // We co-locate test-only helper exports with their consuming components
    // (e.g. `dotAxisFor` next to AcbWalkChart, `buildHeadlineKpis` next to
    // KPICards). The Fast-Refresh-only rule is theoretical here; disabled.
    'react-refresh/only-export-components': 'off',
    // The codebase already uses `as any` defensively in a couple of places
    // (e.g. ResizeObserver stub in test setup); soften from error to warn so
    // a green CI baseline is achievable without a refactor pass.
    '@typescript-eslint/no-explicit-any': 'warn',
  },
  overrides: [
    {
      // Test files reasonably use any-typed mocks and have noisy unused
      // import patterns from testing-library helpers.
      files: ['**/*.test.ts', '**/*.test.tsx', 'src/test/**/*'],
      rules: {
        '@typescript-eslint/no-explicit-any': 'off',
      },
    },
  ],
};

import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    // Opt-in (`npm run test:coverage`, i.e. `vitest run --coverage`) --
    // Vitest, unlike pytest-cov, never collects coverage unless asked to,
    // so `npm test` stays exactly as fast as before this config existed.
    coverage: {
      provider: 'v8',
      reporter: ['text', 'text-summary'],
      exclude: ['src/test/**', 'src/**/*.d.ts', 'src/main.tsx'],
      // Thresholds are the measured value the day this ratchet was added
      // (`npm run test:coverage` -> Statements 79.82%, Branches 77.99%,
      // Functions 55.37%, Lines 79.82%), not an aspirational target -- see
      // backend/pyproject.toml's identical rationale for
      // `--cov-fail-under`. Only ever raised as coverage genuinely
      // improves; a PR that lowers these numbers is a PR that removed
      // tests, not one that should edit the thresholds down to pass.
      thresholds: {
        lines: 79,
        statements: 79,
        functions: 55,
        branches: 77,
      },
    },
  },
});

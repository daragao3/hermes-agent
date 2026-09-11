import { defineConfig } from "vitest/config";
import babel from "@rolldown/plugin-babel";
import react, { reactCompilerPreset } from "@vitejs/plugin-react";

/** Same component/hook-scoped compiler preset as vite.config.ts. */
function compilerPreset() {
  const preset = reactCompilerPreset();
  preset.rolldown.filter.code = /\/>|<\/|from\s*['"][^'"]*react/;
  return preset;
}
import path from "path";

export default defineConfig({
  plugins: [react(), babel({ presets: [compilerPreset()] })],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    // Runs once, before any test file is loaded, so lockfile drift is reported
    // as drift instead of as a wall of missing-export failures. See
    // vitest.globalSetup.mjs.
    globalSetup: ["./vitest.globalSetup.mjs"],
    environment: "node",
    include: ["src/**/*.test.{ts,tsx}"],
  },
});

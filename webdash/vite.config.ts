import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  base: "/api/dash/",
  build: { outDir: "../backend/webdash_dist", emptyOutDir: true },
});

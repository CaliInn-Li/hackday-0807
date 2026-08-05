import { defineConfig } from "vite";

// Cloud Agent friendly config: bind to all interfaces and use a fixed port so
// the dev server is reachable and predictable inside the remote VM.
export default defineConfig({
  server: {
    host: true,
    port: 5173,
    strictPort: true,
  },
  preview: {
    host: true,
    port: 4173,
    strictPort: true,
  },
});

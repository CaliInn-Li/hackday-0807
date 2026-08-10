# Repository Guidelines

## Project Structure & Module Organization

This is a Vite-powered Three.js game prototype. `index.html` defines the UI and canvas entry point. Runtime logic, scene construction, input, and state live in `src/main.js`; styling and responsive layouts live in `src/style.css`. Keep static files under `public/`. Aholo artifacts are stored in `public/generated/`, while the `.mjs` files in `scripts/` manage remote-world synchronization. Production output is written to `dist/`; do not edit it by hand.

## Build, Test, and Development Commands

- `npm ci` installs the exact dependency versions from `package-lock.json`.
- `npm run dev` starts Vite at `http://127.0.0.1:5173` with hot reload.
- `npm run build` creates the production bundle in `dist/` and catches import or bundling errors.
- `npm run preview` serves the production build for final browser checks.
- `npm run sync-world` fetches the configured Aholo world once.
- `npm run wait-world` polls Aholo until generation succeeds, fails, or times out.

Use `?demo=1` during presentations or quick checks to preload the three keys and open the core puzzle flow.

## Coding Style & Naming Conventions

Use modern ES modules and browser APIs. Follow existing JavaScript style: two-space indentation, single quotes, semicolons, trailing commas in multiline structures, `camelCase` variables/functions, and verb-first names such as `createScene`. Use `const` by default and `let` only for reassigned state. Group Three.js setup by scene feature. In CSS, reuse `:root` custom properties, use kebab-case classes, and preserve responsive behavior.

## Testing Guidelines

No automated test framework or coverage threshold is currently configured. Before submitting changes, run `npm run build`, then smoke-test both `/` and `/?demo=1` in a browser. Verify start/restart flow, WASD and mouse controls, `E` interactions, `J` journal, `H` hints, the cipher, responsive layout, and offline fallback when generated assets are unavailable.

## Commit & Pull Request Guidelines

History uses short subjects, sometimes with Conventional Commit prefixes such as `docs:`. Prefer an imperative summary under 72 characters (for example, `fix: preserve pointer-lock fallback`). Pull requests should explain player-visible behavior, list validation, link issues, and include screenshots or a recording for visual changes. Keep generated bundles and secrets out of commits.

## Security & Configuration

Set `AHOLO_API_KEY` and optional `AHOLO_WORLD_ID` in the local environment. Never place API keys in browser code, `world.json`, screenshots, or commits. Treat files under `public/generated/` as reproducible integration artifacts and review their metadata before committing updates.

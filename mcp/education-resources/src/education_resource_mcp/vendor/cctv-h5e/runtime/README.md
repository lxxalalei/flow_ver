# CCTV H5E runtime bundle

Runtime bundle generated from the vendored `cctv-h5e-decrypt` 1.1.1 sources with
`npm ci --no-audit --no-fund && npm run bundle`. The upstream project is MIT
licensed; its license is included as `LICENSE`.

Only `main.js` and `worker.js` are required at runtime. Source maps, TypeScript,
tsx, esbuild, package metadata and node_modules are deliberately excluded from
the installed/release package. Regenerate the two JavaScript files at build time
when the pinned vendored source is intentionally updated.

SHA-256 of the checked-in runtime files:

- `main.js`: `7289d199b6843c0a154b7077685efc0cf1cd10b99f51875e5003f4c178854213`
- `worker.js`: `33ab0a28a1a4b8b4921fe368fc433c5871c412cd1f554b3971d33c66f8488e30`

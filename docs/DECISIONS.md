# Decisions

- 2026-11-23 — LUC-30 likeness scoring: keep SSIM via scikit-image (greyscale, 256x256, blur sigma 1.5) as the measure; widen numpy from `>=1.26,<2` to `>=2.4,<3` so Python >=3.14 installs a compatible wheel instead of source-building unsupported numpy 1.26 on CI (sergio approved via confirmation card 64e0f31d); use pixels-per-millimetre (default 96/25.4) as the single scale unit shared by `compute_likeness` and `simulate_plot`.
- 2026-11-23 — LUC-31 CLI preview/evaluate: use that single pixels-per-millimetre unit for both the simulation and the likeness crop (no second "dpi" unit); `evaluate --json` writes only the JSON object to stdout and sends human tables to stderr so scripts can pipe it straight into `jq` (Architect direction in LUC-31).

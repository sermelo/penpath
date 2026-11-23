# Decisions

- 2026-11-23 — LUC-30 likeness scoring: keep SSIM via scikit-image (greyscale, 256x256, blur sigma 1.5) as the measure; widen numpy from `>=1.26,<2` to `>=2.4,<3` so Python >=3.14 installs a compatible wheel instead of source-building unsupported numpy 1.26 on CI (sergio approved via confirmation card 64e0f31d); use pixels-per-millimetre (default 96/25.4) as the single scale unit shared by `compute_likeness` and `simulate_plot`.

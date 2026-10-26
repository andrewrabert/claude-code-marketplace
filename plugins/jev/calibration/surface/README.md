# Surface spec calibration

`jellium-menu-refactor-spec.md` is `surface-spec --git main -l rust -e '*test*'` on jellium-desktop `menu-refactor`.
`jellium-menu-refactor-findings.json` holds the surface-v1 findings at >= 0.75 on it, each labeled `yes`, `no` or `unknown` from the user's sessions (`label_source: session`) or their standards (`label_source: standards`), with the evidence quoted.

Description used for the run:
Route the app's menus, client settings and About through the platform App and a MenuBuilder, so every platform builds the same menus from one place; localize the menus and the connect screen with Fluent in platform_abi; and hide the window chrome together with the video OSD on all platforms.

# Vendored JavaScript

This directory contains third-party JavaScript libraries vendored directly into the repo for offline-friendly, reproducible builds. Do not edit vendored files by hand — follow the upgrade procedure below.

## modern-screenshot

| | |
|---|---|
| File | `modern-screenshot.js` |
| Version | **4.7.0** (pinned) |
| Source | `dist/index.js` from the npm tarball — a UMD bundle that exposes `window.modernScreenshot` when loaded via `<script>` |
| Download URL | https://registry.npmjs.org/modern-screenshot/-/modern-screenshot-4.7.0.tgz |
| SHA-256 | `bb36665889124a0b6e15f16045265737449c3bdcf2712cdb08af3cfa01563e2b` |
| License | MIT — Copyright (c) 2021-present wxm. Full license text below. |
| Purpose | Renders the user's current DOM to a PNG in-browser so the bookmarklet can ship a faithful capture (post-login, post-upload state) without Playwright needing to re-fetch the live URL. |

### Upgrade procedure

1. Pick a target version from <https://www.npmjs.com/package/modern-screenshot>
2. Download the tarball and extract `package/dist/index.js`
3. Verify `package/LICENSE` is still MIT — abort upgrade if the license has changed
4. Overwrite `static/modern-screenshot.js`, compute new SHA-256 with `shasum -a 256 static/modern-screenshot.js`, update the table above
5. Re-run the test suite and the manual Streamlit / Chart.js / plain-HTML fidelity checks
6. Commit with message like `vendor: bump modern-screenshot to X.Y.Z`

### License (MIT)

```
The MIT License (MIT)

Copyright (c) 2021-present wxm

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

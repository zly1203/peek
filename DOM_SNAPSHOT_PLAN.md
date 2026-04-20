# Faithful Capture — Implementation Plan (v0.5.0)

Target branch: `feat/dom-snapshot`
Status: **Decisions locked. Implementation in progress.**

### Pivot note (2026-04-20)

Originally scoped as "DOM snapshot via SingleFile". During vendoring we discovered `single-file-core` is AGPL-3.0-or-later — incompatible with Peek's MIT license. **Switched to `modern-screenshot` (MIT, zero runtime deps)**, which outputs a PNG directly in the user's browser, skipping the HTML serialization + local preview route entirely. Simpler architecture, same user-facing outcome.

---

## 1. Goal

Make `get_user_selection`'s screenshot faithfully show what the user was looking at when they clicked the bookmarklet — including post-login, post-upload, and post-interaction states.

Today: bridge server re-fetches the URL with headless Playwright (fresh session, no state) → screenshot misses user state.

After: bookmarklet serializes the user's live DOM to a self-contained HTML file → bridge server serves that file locally → Playwright screenshots the local static copy → image matches the user's real browser view.

**Non-goals** (explicitly out of scope for v0.5.0):
- The `screenshot(url)` tool stays stateless — this work does not change that tool's behavior at all.
- No UI changes to the bookmarklet (same 3 modes, same shortcuts).
- No new MCP tools. Tool contracts unchanged.

---

## 2. Architecture — the new flow

```
  USER'S BROWSER                           BRIDGE SERVER
  ─────────────                            ─────────────
  click bookmarklet
    │
    ├─ collect element metadata (unchanged) ────┐
    │                                            │
    ├─ modern-screenshot                         │
    │   .domToPng(document.body)                 │
    │   → base64 PNG of current view             │
    │                                            ▼
    └─ POST /api/capture {
         ..., pageScreenshotBase64: "…"
       } ───────────────────────────────────────►
                                                  │
                                    if pageScreenshotBase64 present AND
                                    PEEK_DOM_SNAPSHOT != "0":
                                      decode + save as capture_{ts}.png
                                    else:
                                      fall back to v0.4 Playwright re-fetch
                                                  │
                                    save capture_{ts}.json (metadata)
                                                  │
                                    prune archive to last 50 captures
                                                  │
                         tell user "status: ok"  ◄
```

Key differences vs v0.4:
- **PNG is generated in the user's browser**, using their real session state (logged in, uploaded, interacted).
- **Playwright no longer runs on bookmarklet capture** — it's reserved for the agent-initiated `screenshot(url)` tool only. Removes a 2-3s latency per click.
- **No new routes** (previously planned `/preview/{ts}` is not needed).
- **No HTML file storage** (previously planned `.html` snapshot file is not needed).
- Everything downstream (MCP tools, element metadata, agent-facing contract) unchanged.

---

## 3. Library choice

### Decision: **`modern-screenshot`** (MIT, pin to 4.7.0)

Revised comparison after license audit:

| Library | License | Canvas | Shadow DOM | Bundle | Maturity | Runtime deps |
|---------|---------|--------|-----------|--------|----------|--------------|
| single-file-core | **AGPL-3.0** ❌ | ✅ | ✅ | ~130 KB | High | — |
| html2canvas | MIT | ⚠️ (separate path) | ❌ | ~200 KB | Mature but unmaintained | 0 |
| **modern-screenshot** | **MIT ✅** | ✅ (uses canvas API natively) | ✅ | ~60 KB UMD | v4.7.0, maintained | **0 runtime** |
| dom-to-image-more | MIT | ⚠️ | ❌ | ~25 KB | Active | 0 |

Why modern-screenshot:
- **License compatible** with Peek's MIT
- **Zero runtime dependencies** (verified via npm registry) — no supply-chain surprises
- Produces PNG directly (simpler than HTML serialization + re-render)
- Actively maintained, recent releases
- UMD bundle available via unpkg, loads as IIFE in bookmarklet context

### How it's served

- Vendor the UMD bundle into `static/modern-screenshot.js` (committed to repo, pinned to exact v4.7.0)
- Bookmarklet loads `http://localhost:8899/static/modern-screenshot.js` alongside `inspector.js`
- No external CDN dependency at runtime
- Add `static/VENDOR.md` documenting the pinned version, SHA256 checksum, and license text

---

## 4. File-by-file changes

### `static/modern-screenshot.js` — NEW
- Vendored UMD bundle of modern-screenshot v4.7.0, ~60 KB minified
- Loaded by the bookmarklet alongside `inspector.js`

### `static/VENDOR.md` — NEW
- Documents pinned version, download source URL, SHA256 checksum, license (MIT), upgrade instructions

### `static/inspector.js` — MODIFY
- New helper `captureFullPagePng()`: invokes `modernScreenshot.domToPng(document.documentElement)`, returns base64 string
- Before each `sendCapture(...)` call in Region / Element / Annotate modes:
  - Await `captureFullPagePng()`
  - Add `pageScreenshotBase64: "..."` field to the POST body
- Keep all existing fields (url, viewport, region, elements, annotationBase64, etc.)
- Reuse the existing SingleFile-less loader pattern to inject `modern-screenshot.js` before `inspector.js` uses it

Estimated: ~30 new LOC in `inspector.js`.

### `src/server.py` — MODIFY

- `POST /api/capture`:
  - Add check for `PEEK_DOM_SNAPSHOT` env var (default: enabled)
  - If body contains `pageScreenshotBase64` AND the env flag isn't `0`:
    - Decode and save directly as `capture_{ts}.png` and `capture_latest.png`
    - Skip the Playwright re-fetch path entirely
  - Otherwise (old bookmarklet or env flag disabled):
    - Fall back to v0.4 behavior: Playwright re-fetches `data["url"]` and screenshots it
- Add capture-archive cleanup after save: keep last 50 timestamped files (json/png/annot.png grouped by timestamp), delete older ones. `capture_latest.*` always preserved.
- No new routes. No preview URL.

Estimated: ~40 new LOC.

### `pyproject.toml` — MODIFY
- Version bump: `0.4.0` → `0.5.0`

### `README.md` — MODIFY (minor)
- Update "Screenshot shows blank or default page" troubleshooting: **remove** the workaround for "logged-in state" — that now works via bookmarklet naturally
- Add brief "How it works" note that the bookmarklet renders to PNG client-side for faithful capture

### Tests — ADD
- `tests/test_faithful_capture.py`:
  - Bridge saves PNG directly when `pageScreenshotBase64` is present
  - Bridge falls back to Playwright when field missing (v0.4 compat)
  - `PEEK_DOM_SNAPSHOT=0` forces fallback even if field present
  - Cleanup prunes to last 50 timestamped captures; `latest` preserved

No changes to: `src/mcp_server.py`, `src/cli.py`, `src/screenshot.py`.

---

## 5. Storage and cleanup

### What gets saved per capture

| File | New? | Approx size |
|------|------|-------------|
| `capture_{ts}.json` | Existing | < 20 KB |
| `capture_{ts}.png` | Existing (now sourced from client-side PNG when available) | 100 KB – 1 MB |
| `capture_{ts}_annot.png` | Existing (annotate mode) | < 500 KB |

No new file types. No HTML files. (The simpler architecture means less disk growth per capture than the original SingleFile plan.)

### Cleanup policy — auto-prune to last 50

After every successful save, the bridge server scans `~/.peek/captures/`, groups files by timestamp prefix, and deletes all but the 50 most recent groups. `capture_latest.*` is always preserved.

Rationale: disk bloat is a real risk if users click the bookmarklet frequently over weeks. 50 gives ample history (covers a week of heavy use) without unbounded growth. Simple policy, no env var needed.

---

## 6. Security surface

With the modern-screenshot pivot, the surface is smaller than the original plan.

- **No new routes** — no `/preview/{ts}` to guard, no path-traversal concern
- **PNG arrives via existing `/api/capture`** — already protected by the 50 MB body limit ([src/server.py:43-50](../ui-inspector/src/server.py#L43-L50)) and localhost-only origin CORS
- **No new file types on disk** — only existing PNG/JSON paths
- **Library runs in user's browser** — same origin, same permissions as any other script
- **Vendored JS content-addressable** — SHA256 checksum recorded in `static/VENDOR.md` prevents silent dependency drift

---

## 7. Backward compatibility

| Concern | Status |
|---------|--------|
| MCP tool names / signatures | Unchanged |
| CLI commands | Unchanged |
| Bookmarklet UI (modes, shortcuts, colors) | Unchanged |
| Old captures from v0.4.0 | Still readable — new code falls back to live-URL screenshot if `.html` file missing |
| Agent behavior | Docstrings unchanged — agents auto-benefit without rewiring |

---

## 8. Feature flag / escape hatch

Add `PEEK_DOM_SNAPSHOT` env var:
- `PEEK_DOM_SNAPSHOT=0` — disable snapshot serialization, use v0.4 behavior (live-URL screenshot)
- Default: enabled

Rationale: if SingleFile misbehaves on some exotic page, user has a quick way to revert per-session without downgrading the package. Removes in v0.6.0 if zero bug reports.

---

## 9. Testing strategy

**Unit (fast, CI):**
- Bridge saves HTML on receipt
- Preview route serves correctly, validates timestamp format
- Screenshot falls back to live URL when snapshot missing

**E2E (bridge + bookmarklet + real browser):**
- Extend existing `tests/e2e/` fixtures to include a DOM-heavy test page, verify snapshot roundtrip produces a visually similar PNG

**Manual (before merge):**
- [ ] Streamlit upload → generate flow — does the snapshot show the chart? (this is the motivating bug)
- [ ] Chart.js canvas page — is canvas content preserved?
- [ ] Plain HTML — no regression vs v0.4 behavior
- [ ] Large page (>5 MB snapshot) — does the browser/bridge handle it without crashing?
- [ ] Shadow DOM page — preserved?

---

## 10. Risks and unknowns

| Risk | Severity | Mitigation |
|------|----------|-----------|
| modern-screenshot fails on Streamlit's specific rendering | Medium | Manual test before merging; `PEEK_DOM_SNAPSHOT=0` escape hatch |
| Cross-origin images/fonts fail CORS → blank or fallback | Known limitation | Document in README; modern-screenshot logs warnings to console |
| Very complex pages produce large PNGs (multi-MB) | Low | Cleanup to last 50 caps total disk use |
| First bookmarklet click loads ~60 KB library | Low | Cached by browser after first load; negligible on subsequent clicks |
| Shadow DOM or unusual CSS features render differently | Low | Agent will still get correct element metadata regardless of image fidelity |

---

## 11. Decisions (finalized)

1. **Cleanup policy**: auto-prune to last 50 timestamped captures; `capture_latest.*` files are always preserved. Implemented in bridge server after saving each new capture.
2. **Escape hatch**: ship with `PEEK_DOM_SNAPSHOT` env var. Default: enabled. Set `PEEK_DOM_SNAPSHOT=0` to fall back to v0.4 live-URL screenshot behavior.
3. **Commit strategy**: multiple logical commits in this worktree — vendor library / bookmarklet / bridge / tests / docs / version bump. Matches the repo's existing pattern.
4. **Version**: `v0.5.0`. Capability upgrade, minor version bump per semver.
5. **SingleFile version**: pin to a specific released version (verified at vendor time). Document upgrade process in a vendor README.

---

## 12. Estimated work

- Vendor SingleFile + license audit: 1 hour
- `inspector.js` changes + local testing: 3 hours
- `server.py` changes + tests: 3 hours
- Manual verification (Streamlit, canvas, plain HTML): 2 hours
- Docs + polish: 1 hour
- **Total: ~1.5 working days**

---

## 13. Rollout

1. User reviews and approves this plan
2. Implement in this worktree on `feat/dom-snapshot`
3. Each logical step = one commit (vendor, bookmarklet, bridge, tests, docs, version bump)
4. Merge to `main` once manual tests pass
5. Publish v0.5.0 to PyPI

---

**Awaiting user review. Please flag any objections or answer the 5 decisions in section 11 before implementation starts.**

# XD macOS visual QA

## Verdict

The selected hardware-instrument direction is implemented faithfully and the
core review journey is functional. No P0, P1, or P2 visual issue remains in the
verified NorthlineLab state.

**Result: passed**

## Source and verification state

- Binding source: `apps/macos/XD/Design/selected-option-3.png` (option 3,
  1487 x 1058).
- Normalized source: `apps/macos/XD/Design/source-normalized-1080x768.jpeg`.
- Final implementation capture:
  `apps/macos/XD/Design/implementation-final.jpeg` (1080 x 768).
- Raw implementation capture:
  `apps/macos/XD/Design/implementation-final-raw.jpeg` (1079 x 768). The final
  image adds one raster column so the comparison has the source's exact
  1080 x 768 viewport; no interface geometry was stretched.
- Full comparison: `apps/macos/XD/Design/comparison-final.jpeg`.
- Focused evidence comparison:
  `apps/macos/XD/Design/comparison-final-focused.jpeg`.
- App state: `--demo`, Today, NorthlineLab.com selected, Shared Gates and Raw
  Evidence collapsed, 21 August 2026 fixture time.
- Verified source commit: `895c60f` on `codex/always-on-inventory`.
- Verified universal build: GitHub Actions run `32423349595`.

## Side-by-side review

### Full frame

The source and implementation use the same three-part hierarchy: persistent
navigation, an attention list, and an evidence-led review detail. The selected
row, two independent lane cards, disclosure rows, and bottom decision rail
occupy the same visual bands. Matte near-black surfaces, restrained one-pixel
rules, low-radius panels, amber attention, green pass, blue authority, and red
reject all match the selected instrument language.

### Focused detail

The thesis header, independent Name and Authority panels, "No compensating
score" rule, gate/quote/red-flag/raw-evidence rows, and anchored Ready controls
align closely with the source. Production copy intentionally replaces the
reference's provider-specific `DR (Ahrefs)` and `UR (Ahrefs)` labels with
provider-neutral `Domain Rank` and `Page Rank`. The live product also uses an
observed/lane-entry lifecycle line and a refresh control rather than fabricated
expiry data and non-functional star/more controls.

### Five-surface check

- **Typography:** native system sans is used for readable labels; monospaced,
  tabular figures are used for timestamps, metrics, prices, and compact status.
  Hierarchy and weights match the source's dense operational character.
- **Layout:** column proportions, row cadence, card dimensions, evidence order,
  and the fixed action rail reproduce the reference at 1080 x 768.
- **Colour:** near-black canvas, charcoal selection, neutral separators, amber
  attention, green pass, blue authority, and red reject are restrained and
  legible. State is also written in text and never depends on colour alone.
- **Imagery and icons:** the source requires no illustration or raster artwork.
  Native SF Symbols closely match its user, shield, link, eye, play, portfolio,
  settings, gate, payment, flag, and evidence glyphs.
- **Copy:** all high-value labels from the source are preserved. Differences are
  factual product corrections, not visual invention.

## Iteration record

### Pass 1

- **P1:** the first 1152 x 768 capture compressed the evidence area relative to
  the reference and made the three columns feel too even.
- **P2:** type metrics and row density were too loose.
- **Fix:** resized the native window to the reference aspect, recalibrated the
  split widths, and tightened operational type and spacing.
- Evidence: `apps/macos/XD/Design/comparison-pass-1.jpeg`.

### Pass 2

- **P1 resolved:** the 1400 x 996 logical window normalized to approximately
  1080 x 768 and restored the source hierarchy.
- **P2:** signal labels and evidence density still differed from the selected
  concept.
- **Fix:** aligned panel rows, card headers, provider-neutral authority metrics,
  status labels, separators, and footer rhythm.
- Evidence: `apps/macos/XD/Design/comparison-pass-2.jpeg`.

### Pass 3

- **P2:** long dossier reasons crowded the card footers, the disabled settings
  preview control still appeared enabled, and the decision rail lacked the
  reference's tactile weight.
- **Fix:** reduced the footer to concise evidence summaries, made disabled
  controls neutral, and refined the action rail borders and state fill.
- Evidence: `apps/macos/XD/Design/comparison-pass-3.jpeg`.

### Pass 4 and final

- **P2:** sidebar symbols did not yet match the reference closely enough.
- **Functional defect found during interaction QA:** selecting SummitVector.io
  changed the title while leaving NorthlineLab evidence visible.
- **Fix:** changed the Name/Authority/Hybrid symbols to the matching SF Symbols
  and made preview details, metrics, quotes, dossiers, and link targets resolve
  from the selected candidate. A Swift test now asserts SummitVector.io's exact
  match and link targets.
- **Final:** no P0, P1, or P2 visual issue remains. The candidate-specific patch
  does not change the final NorthlineLab visual used in the comparison.

## Functional review

The native interaction pass covered candidate selection, Shared Gates and Raw
Evidence disclosures, the Research review sheet and save flow, Runs, Settings,
Name Assets, and the Command-K/Open Today command path. Disabled actions use a
neutral visual state. The final candidate-selection correction is covered by
the Xcode CI Swift suite, and the universal bundle and command-safety boundary
also pass in the same run.

passed

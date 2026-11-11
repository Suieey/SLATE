# Slate motion and materials

## Direction

A quiet working desk, not a marketing landing page. Keep the seven separate parts and the source/target/draft sequence. The user's requested Apple-like feel means restrained materials, responsive navigation and motion that explains a change. No looping orbs, parallax, cursor followers or automatic scrolling.

Palette: ink #14213d, blue #3564de, blue tint #e3eafb, ground #eaf0f8, field #f7faff. Keep the existing Inter/system stack so the new layer does not change information density or add another font download. Headings use tighter tracking; labels remain sentence case. Use the tinted ground to separate the work surface from the shell, not a new decoration per card.

```
Slate   [Resume] Targets Draft ...

Your resume
Source / target / saved draft context
Signed-in identity

[ one chosen part, full working width ]
```

The moving navigation selection is the main motion cue. Content settles over 430ms after a route change; old route animations are canceled on rapid navigation. Buttons have slight press feedback and pointer-only hover lift. There are no animations that wait for a provider or imply that a save succeeded. Existing API success/error messages remain authoritative.

First-pass critique removed per-section automatic entrances. One initial content arrival is enough. The selection follows wrapped navigation on phones rather than forcing a horizontal scrolling menu. Upload controls wrap at 320px. No new animation library or build dependency.

## Accessibility and checks

- `prefers-reduced-motion` disables CSS motion and route animations, including when changed while the page is open.
- Keyboard focus stays visible; no delayed pointer locks, modal effects or animated layout heights.
- Only opacity and transform animate content. Navigation selection geometry updates after resize and font load.
- `scripts/check_motion_ui.py` checks real running motion, rapid navigation, selection alignment, keyboard activation, runtime reduced motion and all seven routes at 1440, 390 and 320px.
- Existing session, literal text, draft download, interview, target and separate-page browser checks remain required.

Actual preview recordings use synthetic data and the local dev-auth mode. They are not evidence of a deployed service, real provider output or working microphone/camera hardware.

## Canvas revision after look review

The first frosted-card pass was rejected as still looking like a form. The next pass changes interaction hierarchy, not only materials:

- Desktop navigation becomes a thin app rail; phones keep all seven part links visible by wrapping.
- Resume intake is a dedicated composer. Once parsed, the actual extraction result leads and the composer moves below it. This is phrase extraction, not a simulated AI conversation.
- Source, chosen target and exact saved draft stay in a separate live context panel. On phones this becomes a top disclosure with a compact current-state summary.
- Saved-version retrieval and optional target metadata are named disclosures.
- Draft text and cover note are the primary editable artifacts, with explicit save/approve/export actions. Original source preservation and demo limitations remain visible.

Visual references inspected during this revision: https://gemini.google.com/ (composer-led entry and quiet app navigation) and https://notebook.google.com/ (separation of source context, working canvas and outputs). These are layout references only. Slate does not gain chat, research, generated slides, audio overviews, live job search or claim verification from this change.

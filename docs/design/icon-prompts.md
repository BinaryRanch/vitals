# Vitals icon — brief and Imagine prompt

## What the mark has to say

Vitals is a workload map with browser tab accounting. The icon cannot carry that
sentence, so it carries the shortest true part: **something is beating, and you
can see it.**

## Constraints

- 16px is the real test. Everything below that size detail is decoration.
- Two colors from the Binary Ranch palette: ink `#0a0a0a`, paper `#f0ede8`,
  accent rust `#d4623a`.
- No text, no gradients, no shadows.
- Square, safe inside a rounded-square mask.

## Grok Imagine prompt

> Flat vector app icon, 1:1 square, deep charcoal background `#0a0a0a`. A simple
> browser tab shape in off-white, drawn as one solid rounded rectangle with a
> single angled corner at the top right, and a thick rust `#d4623a` heartbeat
> trace running across its middle: one flat line, one sharp peak up, one sharp
> trough down, then flat again. Uniform heavy stroke, geometric, no gradients, no
> shadows, no 3D, no text, no letters, no extra detail. The silhouette must read
> as a single bold shape at 32 pixels.

Simplification prompt if the result is too busy (image to image):

> Keep the tab shape and remove the corner notch. Keep one peak and one trough
> only. Make the pulse stroke twice as thick. Two colors, flat, centered, no text.

## Candidates built as geometry

Three hand-drawn SVG candidates live in `docs/design/`, rendered through
`tools/make_icons.py`:

| file | idea | verdict |
|---|---|---|
| `vitals-a-rows.svg` | three workload rows, top one hot | legible, but reads as a generic chart |
| `vitals-b-tab-pulse.svg` | a browser tab carrying a heartbeat | most on-message, notch dies at 32px |
| `vitals-c-pulse.svg` | the pulse alone | strongest at 16px, says "health" not "browser" |

Recommended direction: **B, simplified.** Remove the corner notch (it is the
first casualty at small size), keep one peak and one trough, thicken the stroke.
That keeps the browser reference that makes the mark specific while surviving the
tab bar.

Do not ship A. It is the clearest of the three and the least distinctive; it
could belong to any dashboard.

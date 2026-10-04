# Motion Studio Rules

## Rendering

Every movie is deterministic.

`window.seek(t)` must render the exact frame at time `t`.

Never use as animation clocks:
- setTimeout
- setInterval
- Date.now
- performance.now
- autonomous CSS animations
- autonomous CSS transitions
- non-seeded Math.random

Rendering must work frame-by-frame through Chromium.

## Quality

Prefer transformations between visual states over arbitrary cuts.

Use real brand assets.

Never invent product features, testimonials, prices or metrics.

Typography must remain readable on mobile.

Use at most one dominant accent color unless the brand system explicitly requires more.

Avoid generic AI aesthetics:
- excessive glow
- random particles
- rainbow gradients
- gratuitous 3D
- excessive glassmorphism
- cartoon bounce
- floating decorative objects without narrative purpose

## Production

Storyboard before expensive rendering.

Generate still probes before rendering the full video.

Always render a lightweight draft before the master.

Never overwrite source assets.

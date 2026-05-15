# Anki-Gen — Frontend Design System

> A clean, sober, Apple-inspired light interface.  
> **Principle:** remove everything that isn't necessary — then remove a little more.

---

## 1. Philosophy

| Guideline | Rule |
|---|---|
| **No borders** | Never use `border` to separate elements. Use whitespace, subtle shadows, or background contrast instead. |
| **Light & airy** | Predominately white/near-white canvas. Panels float above the page with soft box-shadows. |
| **One accent, used rarely** | A single bright color marks primary actions and active states — nothing else. |
| **Smooth & alive** | Every state change (hover, focus, appear, disappear) is animated with ease curves. |
| **Rounded shapes** | Generous `border-radius` on every container and interactive element. |

---

## 2. Color Tokens

```css
:root {
  /* ── Canvas ── */
  --bg:            #F5F5F7;       /* page background – warm Apple grey */
  --surface:       #FFFFFF;       /* card / panel background */
  --surface-hover: #F9F9FB;       /* subtle hover tint on surfaces */
  --surface-alt:   #F0F0F3;       /* recessed areas: code blocks, textareas */

  /* ── Text ── */
  --text-primary:   #1D1D1F;      /* headings, body */
  --text-secondary: #86868B;      /* captions, labels, muted info */
  --text-tertiary:  #AEAEB2;      /* placeholders, disabled */

  /* ── Accent (use sparingly!) ── */
  --accent:         #0071E3;      /* Apple Blue – primary CTA only */
  --accent-hover:   #0077ED;      /* slightly lighter on hover */
  --accent-subtle:  rgba(0, 113, 227, 0.08);  /* tinted backgrounds */

  /* ── Semantic ── */
  --success:        #34C759;      /* completed / saved */
  --warning:        #FF9F0A;      /* caution */
  --error:          #FF3B30;      /* error */

  /* ── Shadows & Overlays ── */
  --shadow-sm:   0 1px 3px rgba(0, 0, 0, 0.04), 0 1px 2px rgba(0, 0, 0, 0.06);
  --shadow-md:   0 4px 12px rgba(0, 0, 0, 0.06), 0 1px 3px rgba(0, 0, 0, 0.04);
  --shadow-lg:   0 12px 40px rgba(0, 0, 0, 0.08), 0 4px 12px rgba(0, 0, 0, 0.04);
  --blur-bg:     saturate(180%) blur(20px);
}
```

### Accent Budget

The accent color `#0071E3` must appear **only** on:

- Primary action buttons (1 per view, max 2)
- Active / selected sidebar item dot
- Focused input ring
- Progress bar fill

Everything else stays neutral. **Never** use accent for decorative borders, backgrounds, headings, or links.

---

## 3. Typography

Use **Inter** from Google Fonts (weight 400, 500, 600).

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
```

```css
body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", sans-serif;
  font-size: 15px;
  line-height: 1.6;
  color: var(--text-primary);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}
```

| Role | Size | Weight | Color |
|---|---|---|---|
| Page title | 20px | 600 | `--text-primary` |
| Section heading | 13px uppercase | 600 | `--text-secondary` |
| Body / labels | 15px | 400 | `--text-primary` |
| Caption / muted | 13px | 400 | `--text-secondary` |
| Monospace (code, textarea) | 13px | 400 | `--text-primary` · font: `"SF Mono", "Fira Code", Menlo, monospace` |

---

## 4. Spacing Scale

Use a **4px base grid**. Allowed values:

| Token | Value |
|---|---|
| `--space-xs` | 4px |
| `--space-sm` | 8px |
| `--space-md` | 16px |
| `--space-lg` | 24px |
| `--space-xl` | 32px |
| `--space-2xl` | 48px |

---

## 5. Border Radius

| Element | Radius |
|---|---|
| Cards, panels, sidebar | **16px** |
| Buttons, inputs | **10px** |
| Tags, badges, dots | **full (50%)** |
| Code blocks, textareas | **12px** |
| Progress bar track | **6px** |

> **Rule:** if in doubt, round it more.

---

## 6. Elevation (Shadows, No Borders)

Instead of `border: 1px solid …`, use these shadow + background combos:

```css
/* Floating card */
.card {
  background: var(--surface);
  border-radius: 16px;
  box-shadow: var(--shadow-md);
  border: none;               /* ← always explicit */
}

/* Recessed area (textarea, code) */
.recessed {
  background: var(--surface-alt);
  border-radius: 12px;
  border: none;
}

/* Header bar (frosted glass) */
header {
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: var(--blur-bg);
  -webkit-backdrop-filter: var(--blur-bg);
  box-shadow: 0 0.5px 0 rgba(0, 0, 0, 0.08);   /* ultra-thin separator */
  border: none;
}
```

> The **only** acceptable "line" is the `0.5px` shadow on the sticky header.  
> Everywhere else: whitespace and shadow do the separation work.

---

## 7. Component Patterns

### 7.1 Buttons

```css
/* Base */
button {
  border: none;
  border-radius: 10px;
  padding: 10px 18px;
  font-weight: 500;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s ease;
}

/* Default (secondary) */
.btn {
  background: var(--surface-alt);
  color: var(--text-primary);
}
.btn:hover {
  background: #E8E8ED;
  transform: translateY(-1px);
  box-shadow: var(--shadow-sm);
}
.btn:active {
  transform: translateY(0);
  box-shadow: none;
}

/* Primary (accent) — use maximum 1-2 per view */
.btn.primary {
  background: var(--accent);
  color: #FFFFFF;
}
.btn.primary:hover {
  background: var(--accent-hover);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(0, 113, 227, 0.25);
}

/* Ghost */
.btn.ghost {
  background: transparent;
  color: var(--text-secondary);
}
.btn.ghost:hover {
  background: var(--surface-alt);
  color: var(--text-primary);
}
```

### 7.2 Inputs & Textarea

```css
input, textarea {
  border: 1.5px solid transparent;       /* invisible border to keep size stable */
  background: var(--surface-alt);
  border-radius: 10px;
  padding: 12px 14px;
  font-size: 14px;
  color: var(--text-primary);
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
input::placeholder, textarea::placeholder {
  color: var(--text-tertiary);
}
input:hover, textarea:hover {
  background: #EAEAEF;
}
input:focus, textarea:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-subtle);
  background: var(--surface);
}
```

> On focus, the accent ring "glows" softly — this is one of the few places accent appears.

### 7.3 Cards / Panels

```css
.card {
  background: var(--surface);
  border-radius: 16px;
  padding: var(--space-lg);
  box-shadow: var(--shadow-md);
  border: none;
}
```

No inner borders between sections — use `gap` and vertical spacing instead.

### 7.4 Sidebar

```css
.sidebar {
  background: var(--surface);
  border-radius: 16px;
  padding: var(--space-md);
  box-shadow: var(--shadow-sm);
  border: none;
}

.chunk-btn {
  border: none;
  border-radius: 10px;
  background: transparent;
  transition: background 0.15s ease;
}
.chunk-btn:hover {
  background: var(--surface-alt);
}

/* Active item: subtle accent tint, no border */
.chunk-item.active .chunk-btn {
  background: var(--accent-subtle);
}
.chunk-item.active .dot {
  background: var(--accent);
}
```

### 7.5 Progress Bar

```css
.progress-bar {
  background: var(--surface-alt);
  border-radius: 6px;
  height: 6px;
  overflow: hidden;
  border: none;
}
#progress-fill {
  background: var(--accent);
  height: 100%;
  border-radius: 6px;
  transition: width 0.4s cubic-bezier(0.25, 1, 0.5, 1);
}
```

### 7.6 Status Indicators

```css
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text-tertiary);
  transition: background 0.2s ease, transform 0.2s ease;
}
.chunk-item[data-status="done"] .dot {
  background: var(--success);
}
```

### 7.7 Error Messages

```css
.error {
  background: rgba(255, 59, 48, 0.08);
  color: var(--error);
  border: none;
  border-radius: 12px;
  padding: 12px 16px;
  font-size: 14px;
}
```

---

## 8. Motion & Animations

### 8.1 Timing Functions

| Curve | Use |
|---|---|
| `ease` | General UI (hovers, fades) |
| `cubic-bezier(0.25, 1, 0.5, 1)` | Entrances, progress bars (fast start, gentle end) |
| `cubic-bezier(0.22, 1, 0.36, 1)` | Modals, panels sliding in |

### 8.2 Durations

| Duration | Use |
|---|---|
| `0.15s` | Micro-interactions (hover tint, cursor changes) |
| `0.2s` | Button transforms, focus rings |
| `0.3s` | Panel transitions, sidebar selection |
| `0.4s` | Progress bar, page-level animations |

### 8.3 Page Load — Fade Up

Elements should appear with a subtle upward fade on initial load:

```css
@keyframes fadeUp {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.card, .sidebar, .workspace {
  animation: fadeUp 0.4s cubic-bezier(0.25, 1, 0.5, 1) both;
}
```

Stagger siblings with incremental `animation-delay` (0ms, 60ms, 120ms…).

### 8.4 Chunk View Transition

When switching between chunks, cross-fade the content:

```css
.chunk-view {
  transition: opacity 0.15s ease;
}
.chunk-view.switching {
  opacity: 0;
}
```

Toggle `.switching` in JS, wait ~150ms, swap content, remove class.

### 8.5 Save Feedback

After a successful save, briefly pulse the status text:

```css
@keyframes pulseIn {
  0%   { opacity: 0; transform: scale(0.95); }
  100% { opacity: 1; transform: scale(1); }
}
#save-status {
  animation: pulseIn 0.2s ease;
}
```

### 8.6 Copy Button Feedback

```css
.copy-btn.copied {
  background: var(--success);
  color: white;
  transition: background 0.15s ease;
}
```

---

## 9. Header (Frosted Glass)

```css
header {
  position: sticky;
  top: 0;
  z-index: 100;
  padding: 14px 28px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: rgba(245, 245, 247, 0.72);
  backdrop-filter: var(--blur-bg);
  -webkit-backdrop-filter: var(--blur-bg);
  box-shadow: 0 0.5px 0 rgba(0, 0, 0, 0.08);
  border: none;
}
```

---

## 10. Layout & Responsiveness

```css
main {
  max-width: 1400px;
  margin: 0 auto;
  padding: var(--space-lg);
}

.layout {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: var(--space-lg);
}

@media (max-width: 900px) {
  .layout {
    grid-template-columns: 1fr;
  }
  .sidebar {
    position: static;
    max-height: 300px;
  }
}
```

---

## 11. Do / Don't

| ✅ Do | ❌ Don't |
|---|---|
| Use `box-shadow` for elevation | Use `border: 1px solid` anywhere |
| Use `gap` + whitespace for separation | Add dividers or `<hr>` elements |
| Use accent on 1-2 primary buttons | Color headings, links, or icons in accent |
| Round corners generously (12-16px) | Use sharp corners (< 8px) |
| Animate state transitions (0.15-0.3s) | Make anything instant or > 0.5s |
| Keep surfaces white or near-white | Use dark/colored panel backgrounds |
| Use `backdrop-filter: blur` on header | Use opaque header with harsh bottom border |
| Let content breathe with generous padding | Cram elements together with tight margins |

---

## 12. File Reference

| File | Purpose |
|---|---|
| `static/style.css` | All styles (single file, follows tokens above) |
| `templates/base.html` | Loads Inter font, links stylesheet |
| `static/app.js` | JS animations (chunk transitions, save pulse) |

---

*This design system should be followed for every frontend change. When in doubt: remove, simplify, soften.*

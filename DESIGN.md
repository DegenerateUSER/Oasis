---
version: alpha
name: Oasis Signal
description: A precise, evidence-first local workspace for infrastructure mutation testing.
colors:
  primary: "#155b9a"
  primary-dark: "#a7d9fa"
  background: "#f7f9fc"
  surface: "#ffffff"
  layer: "#edf2f8"
  hover: "#e5edf7"
  foreground: "#1c2c42"
  muted: "#53657a"
  subtle: "#65788f"
  border: "#d5dfe9"
  selection: "#dceeff"
  action: "#1c5f99"
  action-text: "#ffffff"
  assertion: "#16744f"
  engine: "#446da7"
  survivor: "#926213"
  excluded: "#8090a4"
  danger: "#af3440"
  warning-background: "#fff5df"
  warning-text: "#775117"
  error-background: "#fff0f1"
  background-dark: "#111c2c"
  surface-dark: "#142033"
  layer-dark: "#1b2a3f"
  hover-dark: "#22354d"
  foreground-dark: "#e6edf8"
  muted-dark: "#a0b0c6"
  subtle-dark: "#93a6c0"
  border-dark: "#2b3b51"
  selection-dark: "#233e56"
  action-text-dark: "#15283b"
  assertion-dark: "#7bcba9"
  engine-dark: "#86aaf0"
  survivor-dark: "#e4bf74"
  excluded-dark: "#65788e"
  danger-dark: "#ff9eab"
  warning-background-dark: "#342d20"
  warning-text-dark: "#edcb8a"
  error-background-dark: "#3a2430"
typography:
  body:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
  headline:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "1.85rem"
    fontWeight: 640
    lineHeight: 1.2
    letterSpacing: "-0.035em"
  section:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "1.05rem"
    fontWeight: 620
    lineHeight: 1.35
    letterSpacing: "-0.015em"
  metric:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "2.3rem"
    fontWeight: 560
    lineHeight: 1.3
    letterSpacing: "-0.04em"
  control:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "1rem"
    fontWeight: 550
    lineHeight: 1.25
  code:
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace'
    fontSize: "0.8rem"
    fontWeight: 400
    lineHeight: 1.65
rounded:
  chart: "2px"
  tag: "4px"
  chip: "5px"
  field: "6px"
  button: "7px"
  notice: "8px"
  panel: "9px"
  import: "10px"
spacing:
  xs: "0.5rem"
  sm: "0.75rem"
  md: "1rem"
  lg: "1.5rem"
  xl: "2rem"
  xxl: "3rem"
components:
  button-primary-light:
    backgroundColor: "{colors.action}"
    textColor: "{colors.action-text}"
    typography: "{typography.control}"
    rounded: "{rounded.button}"
    padding: "0.5rem 0.85rem"
  button-primary-dark:
    backgroundColor: "{colors.primary-dark}"
    textColor: "{colors.action-text-dark}"
    typography: "{typography.control}"
    rounded: "{rounded.button}"
    padding: "0.5rem 0.85rem"
  button-secondary-light:
    backgroundColor: "{colors.layer}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.button}"
    padding: "0.5rem 0.85rem"
  button-secondary-dark:
    backgroundColor: "{colors.layer-dark}"
    textColor: "{colors.foreground-dark}"
    rounded: "{rounded.button}"
    padding: "0.5rem 0.85rem"
  input-light:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.field}"
    padding: "0.5rem 0.7rem"
  input-dark:
    backgroundColor: "{colors.surface-dark}"
    textColor: "{colors.foreground-dark}"
    rounded: "{rounded.field}"
    padding: "0.5rem 0.7rem"
  navigation-active-light:
    textColor: "{colors.primary}"
  navigation-active-dark:
    textColor: "{colors.primary-dark}"
  outcome-selected-light:
    backgroundColor: "{colors.selection}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.button}"
    height: "62px"
  outcome-selected-dark:
    backgroundColor: "{colors.selection-dark}"
    textColor: "{colors.foreground-dark}"
    rounded: "{rounded.button}"
    height: "62px"
---

# Design System: Oasis Signal

## Overview

**Creative North Star: "Signal"**

Signal is a restrained operational workspace: a clear reading of mutation evidence, not a decorative dashboard. The light and dark themes preserve identical information hierarchy and semantic roles. Familiar system typography and compact native controls keep attention on source changes, execution boundaries and results.

The visual system is extracted from the built interface, not a new direction. Palette primitives above are normative observations from `frontend/src/styles.css`; component examples in `.impeccable/design.json` extend them. Derived color ramps in the sidecar are preview aids, not additional shipping CSS tokens.

**Key Characteristics:**
- Broad analytics sections rather than a wall of interchangeable cards.
- Stable outcome colors, with text labels and counts alongside geometry.
- Visible provenance, exclusions and unavailable measurements.
- Familiar controls, inspectable monospaced evidence and restrained borders.
- Equivalent semantic hierarchy in light and dark modes.

## Colors

### Primary

The light theme uses a measured blue accent; dark mode uses ice blue for the same interactive roles. The filled primary action has a distinct light-theme action color and inverse text pair. Selected controls use the matching low-emphasis selection surface, not an extra accent family.

### Semantic

Mint/green identifies assertion kills and completed runs; blue identifies engine-error outcomes and active execution; amber identifies survivors and pending cancellation. Muted blue-gray represents excluded geometry. Danger and warning palettes distinguish errors from cautionary provenance and execution notices. A color never replaces an outcome name or state label.

### Neutral

Cool paper, white surfaces and quiet blue-gray separators form the light theme. Midnight navy, slightly lifted navy surfaces and cool foregrounds form the dark counterpart. Main text, supporting text and placeholder text have separate roles. Higher-contrast preferences override supporting text and separator colors; they do not redefine the outcome semantics.

**The Same Meaning Rule.** Theme changes alter contrast and atmosphere, never the meaning assigned to a result or control.

## Typography

Use the system sans stack for navigation, controls, headings and metrics. Monospace is reserved for identifiers, source code, exact fields and logs. Numeric measures use tabular figures; this is a data-reading aid, not a second display voice.

The headline, section and metric roles above record the desktop defaults. Existing responsive rules reduce heading and metric sizes where necessary. Code preserves whitespace and wraps long content rather than forcing document overflow. Body copy generally stays within 75 characters of measure; individual page descriptions allow a wider established measure.

**The Readable Evidence Rule.** Do not scale a desktop SVG's text into a miniature mobile chart. Narrow outcome controls use actual HTML labels at the base reading size, with independently sized geometry.

## Layout

The main workspace caps at 1440px with generous section separation and compact related controls. Header navigation, dataset/provenance toolbar, page heading and global filters establish the reading order. Analytics combine a broad outcome area with a narrower survivor explanation; comparisons and the evidence table continue below.

Existing viewport rules at 1100px, 800px and 520px progressively wrap controls and stack columns. The outcome section also queries its own available inline width: at 800px or narrower, native HTML totals and selectable proportional bars replace the wide SVG. A 680px viewport fallback also enables this composition. The narrow controls retain a 62px minimum height. Evidence tables scroll within their container instead of expanding the document.

Run configuration and local history form two columns where space permits, then stack. The evidence drawer is bounded by the viewport; source snippets and field grids collapse as needed. Keep density responsive without hiding provenance, primary actions or execution acknowledgement.

## Elevation & Depth

Flat sections, tonal surfaces and thin separators carry ordinary hierarchy. The evidence drawer is the exceptional elevated surface: it uses the existing offset, blurred shadow and dimmed backdrop. Do not add shadows to every analytics section. Exact theme shadows, backdrop and motion values live in the sidecar extensions, where the token format can represent them without inventing frontmatter groups.

## Shapes

Controls have modest, functional rounding; charts use smaller corner treatments. Filter panels, notices and import containers use their observed radii rather than a universal oversized card shape. Icons are consistent authored SVG strokes. Charts are geometric SVG or CSS bars, not simulated illustration or raster texture.

## Components

### Buttons and navigation

Primary actions are filled; ordinary controls use low-emphasis tonal surfaces. Hover changes surface tone or brightness, active presses modestly darken, and disabled controls reduce opacity. All keyboard-focusable elements share a visible accent outline. Navigation remains compact, with an accent underline on the current view rather than an enclosing pill.

### Fields and filters

Inputs and selects use a surface background, thin separator stroke, explicit labels and restrained corners. Supporting text explains bounds and consequences. Filters select the same underlying records as the charts and exports. Selected outcomes are visibly pressed as well as semantically marked.

### Outcomes and comparisons

The wide outcome flow preserves proportional generated/scored/outcome geometry. Its narrow counterpart separates native-size labels/counts from bar width. Comparison bars retain the same outcome order and semantic colors. Counts and denominators remain explicit; unknown scores display a dash rather than a fabricated zero.

### Provenance, status and notices

Provenance badges distinguish verified local runs from historical or uploaded evidence. Status combines a textual state with a small colored dot. Warning/error surfaces do not imply successful execution. A cancellation request is not a confirmed cancellation.

### Evidence drawer

A sticky header keeps the record title and close control available. Monospaced snippets and exact fields sit on low-emphasis surfaces. Disclosure summaries participate in keyboard navigation; content hidden by a closed disclosure does not. Escape closes the drawer and returns focus to its trigger.

## Do's and Don'ts

### Do:
- **Do** preserve identical semantic color roles across both themes.
- **Do** place labels and exact counts beside proportional geometry.
- **Do** show provenance, exclusions and unavailable measurements explicitly.
- **Do** keep visible keyboard focus, responsive containment and readable narrow controls.
- **Do** reserve monospace for exact identifiers and evidence.

### Don't:
- **Don't** replace the broad analytics composition with a generic card wall.
- **Don't** turn unknown data into zero, a trend or a coverage claim.
- **Don't** shrink desktop chart lettering to fit a phone.
- **Don't** use decorative glass, gradients, texture or shadows as evidence hierarchy.
- **Don't** imply that a request, preview or historical import is completed verified execution.

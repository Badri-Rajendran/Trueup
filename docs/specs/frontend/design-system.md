# Frontend — Visual Design System

Date: 2026-09-05
Status: Draft, pending review
Scope: visual design only — color, type, spacing, layout, and per-component visual treatment.
Routes, component hierarchy, state boundaries, and API contracts are
[`structure.md`](structure.md)'s (`frontend-architect`'s companion spec); this document does not
prescribe component structure or data flow, only what things look like.
Depends on: [`docs/requirements/project-description.md`](../../requirements/project-description.md)
(product tone), [`structure.md`](structure.md) §3/§6 (the component and state inventory this spec
covers), [ADR 1](../../decisions/01-bitemporal-append-only-ledger.md) (as-published vs. corrected),
[ADR 5](../../decisions/05-withdrawable-vs-investable-cash.md) (withdrawable vs. investable cash),
[ADR 21](../../decisions/21-alpaca-paper-trading-not-broker-api.md) (simulated account approval).

## 1. Intent

Trueup is a regulated, money-holding platform. The brief's own words — "not cluttered, not
over-complicated," and a palette that reads as premium — rule out two easy defaults: a
consumer-fintech look chasing engagement (bright gradients, a single loud accent, growth-app
energy), and a generic enterprise-SaaS look (rounded cards, soft drop shadows, an interchangeable
blue). Neither says "we handle this correctly," which is the one thing this product actually needs
to say.

The concrete reference point is a **vault, not a dashboard** — safekeeping, not a growth-app
feed. A private bank's safety-deposit room is quiet, exact, and legible at a glance: flat surfaces,
ruled lines, deep navy steel and warm ivory paper, brass fixtures that show age without ever
looking worn. That vocabulary — hairline rules instead of drop shadows, a near-black navy "ink"
instead of a bright brand blue, a restrained brass accent standing in for the vault door's own
hardware — is what this system is built from. It is a deliberate departure from both the
warm-cream/serif-display and the near-black/neon-accent looks that AI-generated design defaults to;
neither reads as "your money is safe here," which is the actual job. The append-only, bitemporal
posting ledger underneath (`ADR 1`; `docs/specs/06-restatement-engine.md`;
`docs/specs/05-tax-lots-and-corporate-actions.md`) is still what the numbers on screen are honest
about — the vault is what holds them, not a rebranding of what they are.

What this system optimizes for, in order:
1. **Unambiguous state.** A reconciliation break, a failed deposit, a restated figure, a pending
   approval must be impossible to mistake for "fine." Semantic color is load-bearing, not
   decorative, and is never the only signal (an icon or label always accompanies it).
2. **Legibility of dense tabular data.** Positions, transaction history, and tax lots are read as
   columns of numbers far more often than as prose. Tabular (lining) figures, generous row height,
   and restrained borders carry more weight here than typographic flourish.
3. **Calm, not exciting.** No motion, color, or type choice competes with the numbers for attention.
   The one deliberately expressive choice (see §3) is spent on the account balance and nowhere else.

## 2. Color system

### 2.1 Palette (light theme, base values)

| Token | Hex | Role |
| --- | --- | --- |
| `ink` | `#101B2D` | Primary text, headings, primary button fill — deep navy steel |
| `accent` (brass) | `#896724` | Interactive elements: links, focus, selected state, the as-corrected/restated indicator, primary chart line |
| `success` | `#1F6B47` | Settled, reconciled, approved, gains |
| `warning` | `#8A520A` | Pending, aging, needs-attention-soon |
| `error` | `#8C2F27` | Reconciliation break, failed/bounced, rejected, losses |
| `paper` | `#F6F3EA` | App background — warm ivory, not cool office-gray |

Five chromatic tokens plus the paper base — deliberately short. No tints-of-blue ramp, no
brand-gradient. `ink` doing double duty as both primary text color and primary action color (rather
than adding a sixth "primary button blue") is itself a restraint decision: this product has one
authoritative voice, not a marketing color separate from its content color.

**Rationale for the specific hues:** `ink` is a near-black navy rather than true black or a bright
brand blue — it reads as "bank-vault steel," not "corporate blue." `accent` is a restrained brass
(the color of well-kept safety-deposit-box hardware and vault-door fixtures) rather than the
generic SaaS blue (`#4F7CFF`-family) or the AI-cliché terracotta — it is used narrowly enough (§2.4)
that its scarcity is part of the signal, and it is deliberately darker than a decorative "gold" —
this is hardware, not jewelry. `success`/`error` are deep forest green and brick red rather than
saturated traffic-light green/red — a callback to the literal double-entry convention of red ink
for a negative figure, deep enough to read as considered rather than a dashboard warning light.
`paper` is warm ivory rather than the previous cool office-gray — closer to archival document stock
than a screen background, which is what a safety-deposit room's own paperwork actually looks like.

### 2.2 Full token table (light + dark)

Both themes are first-class — this is an app people use, not a marketing site with a dark-mode
afterthought. Dark mode is not light-mode-inverted; it follows the same "ink/paper" logic in
reverse: **light mode is ink text on a paper surface; dark mode is paper-colored text on an ink
surface.** The metaphor holds in both directions rather than being patched.

| Token | Light | Dark | Usage |
| --- | --- | --- | --- |
| `--color-paper` | `#F6F3EA` | `#0F141C` | App canvas background |
| `--color-surface` | `#FFFFFF` | `#1A212B` | Card/panel background |
| `--color-surface-sunken` | `#EEE7D3` | `#141922` | Table row stripe, inset wells |
| `--color-hairline` | `#DED3B7` | `#2C343F` | Default border/divider |
| `--color-border-strong` | `#988752` | `#3F4855` | Input borders, emphasized dividers |
| `--color-text` | `#101B2D` | `#EDEAE3` | Primary text |
| `--color-text-secondary` | `#3D4A5E` | `#C9C2B6` | Secondary text, labels |
| `--color-text-muted` | `#555D6D` | `#948D7F` | Captions, timestamps, disabled — never for primary data |
| `--color-accent` | `#896724` | `#CFA959` | Links, focus ring, selected state, restated indicator |
| `--color-accent-strong` | `#694F1C` | `#B08B40` | Hover/pressed accent |
| `--color-accent-subtle` | `#F0E4C6` | `#342A14` | Selected-row tint, accent-tinted chip background |
| `--color-success` | `#1F6B47` | `#4DB283` | Text/icon on success state |
| `--color-success-subtle` | `#E1F0E7` | `#153023` | Success badge/banner background |
| `--color-warning` | `#8A520A` | `#D8A041` | Text/icon on warning state |
| `--color-warning-subtle` | `#FAEBD2` | `#392A11` | Warning badge/banner background |
| `--color-error` | `#8C2F27` | `#E0675C` | Text/icon on error state |
| `--color-error-subtle` | `#F6E1DD` | `#391613` | Error badge/banner background |

Theme selection follows OS/user preference (`prefers-color-scheme`) with an explicit in-app toggle
persisted per user — standard behavior, not specified further here.

### 2.3 Contrast — checked, not asserted

Every text/background pairing above was measured against WCAG 2.1 relative-luminance contrast, not
eyeballed:

| Pairing | Ratio | Floor |
| --- | --- | --- |
| `text` on `paper` (light) | 15.6:1 | AAA (7:1) |
| `text-secondary` on `paper` | 8.1:1 | AAA |
| `text-muted` on `paper` | 6.0:1 | AA (4.5:1) — captions/timestamps only, see below |
| `accent` on `paper`/`surface` | 4.7–5.2:1 | AA |
| `success` on `paper` | 5.8:1 | AA |
| `error` on `paper` | 7.4:1 | AA |
| `warning` on `paper` | 5.8:1 | AA |
| `border-strong` on `paper` (non-text UI, WCAG 1.4.11) | 3.2:1 | AA (3:1) |
| white text on `ink` (primary button) | 17.3:1 | AAA |
| `accent` on `accent-subtle` (restated badge, §8.1) | 4.1:1 | AA |
| `text` on `paper` (dark) | 15.4:1 | AAA |
| `accent`/`success`/`warning` on `paper` (dark) | 7.1–8.3:1 | AAA |
| `error` on `paper` (dark) | 5.5:1 | AA |
| `accent` on `accent-subtle` (dark) | 6.4:1 | AAA |

The previous version of this table checked "white text on `accent` (accent button)" — but §7.1's
Button spec has only three variants (Primary = `ink` fill, Secondary = outline, Destructive =
`error` fill), and no button is ever accent-filled. That pairing checked a combination the
component spec doesn't use, so it's replaced above with the pairing `accent` is actually used in:
text on `accent-subtle`, the restated-figure badge from §8.1.

Rule: `text-muted` clears AA for large text and non-critical labels only. **Any figure that is a
balance, return, price, or tax value uses `text` or `text-secondary` (or the relevant semantic
token) at full weight, never `text-muted`** — a regulated money figure is never rendered at reduced
legibility for decorative restraint.

### 2.4 Usage rules

- **Semantic color is never the only signal.** Every success/warning/error state pairs its color
  with an icon or a text label (a break row says "Open · 4d" in error color *and* the word "Open";
  a settled deposit gets a checkmark, not just green text). This is a colorblind-safety requirement,
  not a nicety, for a platform where a missed "needs attention" state is a real financial risk.
- **`accent` (brass) is reserved** for: interactive elements (links, focus rings), the current
  selection, and — deliberately — the visual marker for a **restated/as-corrected figure** (§8.1).
  It does not appear as generic decoration. Its scarcity is what makes "this number was corrected"
  register at a glance.
- **`warning` is not `error`.** A reconciliation break, a rejected KYC, a failed deposit are
  `error`. An aging-but-not-yet-critical break, a pending KYC review, an unsettled cash position are
  `warning`. Do not use `warning` as a softer synonym for `error` to avoid alarming a customer —
  if the state is genuinely a failure, say so in `error`.
- **Gains/losses in tables use `success`/`error` text color on the figure itself** (not a badge),
  consistent with financial-statement convention — the ledger red/black-ink callback from §1.

## 3. Typography

### 3.1 Families

| Role | Family | Why |
| --- | --- | --- |
| UI, body, tables, all standard text | **Public Sans** | Built by GSA/USWDS specifically for legible, dense, official digital content — real tabular (lining) figures, a wide weight range, no marketing personality to fight the data. A deliberate choice over the default SaaS grotesk (Inter/Helvetica): it's built for exactly this job (official, trustworthy, data-dense) rather than borrowed from a chat-app or landing-page context. |
| The account balance figure only, and the single largest number on a statement | **Source Serif 4**, weight 500–600 | The one deliberately expressive choice in the system (see §1, principle 3) — used nowhere else. A serif with real numeral weight reads as a printed, certified figure (the number a statement, not a dashboard, would show), giving the single most important number on the screen a moment of gravitas without touching anything around it. |

Two families, clearly distinct (serif vs. sans), each with one narrow job — not a display/body split
applied everywhere. Both are loaded from Google Fonts; both have full tabular/lining-figure support,
required for §3.3.

### 3.2 Scale

A short scale — six sizes, not a sprawling ramp — sized to do double duty for marketing-style
headers (onboarding, statement headers) and dense tabular UI:

| Token | Size / line-height | Weight | Use |
| --- | --- | --- | --- |
| `display` | 40px / 48px, Source Serif 4 | 600 | Account balance figure only |
| `heading-lg` | 28px / 36px, Public Sans | 600 | Page titles ("Statements", "Reconciliation breaks") |
| `heading-sm` | 20px / 28px, Public Sans | 600 | Section headers within a page (a card's title) |
| `body` | 15px / 24px, Public Sans | 400/500 | Default UI text, table cells, form labels |
| `data` | 15px / 24px, Public Sans, **tabular-nums** | 400/600 | Any numeric value in a table or stat tile — same size as `body` but with the tabular-figure feature explicitly enabled so columns align |
| `caption` | 13px / 18px, Public Sans | 400 | Timestamps, helper text, table footnotes |

Sentence case throughout — no tracked-out all-caps labels or eyebrows (an explicit anti-pattern for
this system: an all-caps "ACCOUNT SUMMARY" eyebrow reads as generated-template chrome, and it fights
the "quiet" principle in §1). Section headers are plain sentence-case text at `heading-sm`, nothing
above them.

### 3.3 Numeric figures — the one non-negotiable rule

Every number a customer might compare against another number in the same view (a table column, a
before/after, a list of positions) is set with `font-variant-numeric: tabular-nums` so digits occupy
equal width and columns align vertically. This is `data` token behavior by default — never opt out
of it inside a table. Money is always rendered with a fixed 2-decimal mask (`$12,480.06`); units are
rendered to 6 decimal places per the ledger's own precision (ADR in `docs/specs/01-ledger-units-core-design.md`)
but trailing zeros beyond 2 significant decimals are dimmed (`text-muted`) rather than dropped, so a
customer can still see the platform is tracking full precision without every unit column shouting six
digits.

## 4. Spacing scale

An 8px base grid, functional rather than decorative — chosen for engineering fit (divides cleanly
into common component heights) and to keep dense tables tight without cramping touch targets:

| Token | Value | Typical use |
| --- | --- | --- |
| `space-1` | 4px | Icon-to-label gap, tight inline spacing |
| `space-2` | 8px | Table cell vertical padding, form field internal spacing |
| `space-3` | 12px | Compact stack spacing |
| `space-4` | 16px | Default stack spacing, card internal padding |
| `space-6` | 24px | Section spacing within a page |
| `space-8` | 32px | Between major page sections |
| `space-12` | 48px | Page-top spacing, empty-state vertical centering |
| `space-16` | 64px | Rare — large marketing-style spacing (onboarding hero) |

## 5. Grid and layout

- **Content max-width:** 1280px for data-dense screens (tables, dashboard), centered with 24px
  (`space-6`) side gutters below that width.
- **Reading-width column:** 640px max for prose-heavy content (statement narrative text, onboarding
  copy, chat messages) — keeps lines under ~80 characters per the frontend-design skill's own
  guidance, distinct from the wide table layout.
- **Grid:** 12-column, 24px gutter, at the 1280px container. Tables ignore the column grid and run
  full container width with their own internal column sizing (numeric columns right-aligned,
  fixed/minimum widths per data type — see §7.6).
- **Breakpoints:** `sm` 480px, `md` 768px, `lg` 1024px, `xl` 1280px. Below `md`, the two-column
  dashboard (stat cards + chart) stacks to one column; tables gain horizontal scroll inside their own
  container (per `frontend/CLAUDE.md`-adjacent responsive rules) rather than reflowing into cards,
  since reflowed financial tables lose column alignment, which is the thing this whole system
  protects.

## 6. Elevation, radius, and borders

**Flat over floating.** A ledger page is flat — pages, ruled lines, no drop shadow implying a card is
hovering above the page. This system uses **hairline borders (`--color-hairline`, 1px) instead of
box-shadow for surface separation** everywhere it can. This is a direct, defensible departure from
the generic SaaS "soft grey shadow under every card" default named in the frontend-design skill —
and it is chosen for this subject specifically (paper/ledger), not as decoration.

Shadow is reserved for genuine elevation — content that must visually float over other content:
modals, dropdown menus, toasts. One shadow token: `0 4px 16px rgba(18, 32, 46, 0.16)` (light),
`0 4px 16px rgba(0, 0, 0, 0.4)` (dark).

Radius is restrained and small, reinforcing "precision instrument" over "soft app":

| Token | Value | Use |
| --- | --- | --- |
| `radius-sm` | 3px | Buttons, inputs, badges/chips |
| `radius-md` | 6px | Cards, panels, modals |
| `radius-full` | 999px | Toggle switches, avatar/initials circles only |

No large pill-shaped buttons or cards. No component gets a radius larger than `radius-md` except the
two named exceptions.

## 7. Component visual specs

Covers every entry in `structure.md` §3's `components/` (generic) plus the feature components whose
visual treatment isn't just "generic component with feature data" — a component not listed here (a
plain form field, a plain list row) inherits the generic spec directly with no variant.

### 7.1 Button

Three variants, one size scale (default 40px height, `compact` 32px for inline table actions):

| Variant | Fill | Border | Text | Use |
| --- | --- | --- | --- | --- |
| Primary | `ink` | none | white | One per view — the primary action (Place order, Submit deposit) |
| Secondary | `surface` | `border-strong` 1px | `text` | Any non-primary action (Cancel, Export) |
| Destructive | `error` | none | white | Rare — irreversible actions only (none currently identified in v1 scope; reserved) |

Disabled: 40% opacity, no hover state, `cursor: not-allowed`. Loading (submit-in-flight): label
replaced by an inline spinner, button stays its committed width (no layout shift), per
`structure.md` §6's "submit-disabled-while-submitting" rule.

### 7.2 Input / Select

40px height, `radius-sm`, 1px `border-strong`, `body` text. Focus: 2px `accent` outline offset 2px
(visible-focus, never suppressed). Error state: border becomes `error`, an `error`-colored message
appears below in `caption` size with an inline icon — never color alone. Label always visible above
the field (never placeholder-as-label).

### 7.3 Card

`surface` background, `radius-md`, 1px `hairline` border, no shadow (§6), `space-4` internal padding.
Used for: `BalanceCard`, `ReturnCard`, `ModelCard`, `AssignmentPrompt`, panel groupings in admin
customer detail. A card never nests another card.

### 7.4 Badge / StatusPill

`radius-sm`, `caption`-sized text, `space-1`/`space-2` padding, semantic-subtle background +
full-strength semantic text color (e.g. `error-subtle` bg + `error` text), always paired with a
short label word, never a bare color dot. Used for order status, KYC status, break status, dunning
state, the provisional-lot flag, and the simulated-approval flag (§8.3).

### 7.5 EmptyState

Centered, `space-12` vertical padding, `heading-sm` message + one line of `caption` supporting text
+ an optional primary button (e.g. "No orders yet" → "Place your first order"). `structure.md` §6
distinguishes a *good* empty state ("No open breaks") from a *waiting* one ("No lots yet,
pre-first-buy") — the good state additionally gets a small `success`-tinted checkmark icon rather
than the neutral default icon, so an adviser scanning the breaks queue sees at a glance that empty is
the desired state, not a loading artifact.

### 7.6 Table

The single most-used component given the domain (Transactions, Lots, Orders, Breaks queue,
Holdings). Rules:

- Header row: `caption`-weight label, `text-secondary`, bottom border `border-strong` (1px, slightly
  heavier than the row hairlines below it).
- Row height: minimum 44px (touch-safe, and breathing room for financial figures) with 1px
  `hairline` bottom border per row — no zebra striping by default; `surface-sunken` striping is
  opt-in only for tables dense enough to need it (Transactions, Lots), never for short lists
  (Orders, Breaks queue) where it would just be noise.
- Numeric columns: right-aligned, `data` token (tabular-nums), column header right-aligned to match.
- Text columns: left-aligned.
- Sortable column headers: `accent` on hover, a small direction indicator (caret) — never color
  alone to indicate sort state.
- Row click target (e.g. an order row → order detail): full row, visible on hover as
  `surface-sunken` background, not a shadow or border change.
- Sticky header on scroll for tables over ~10 visible rows (Transactions, Lots).

### 7.7 Skeleton

`surface-sunken` background block at the shape/size of the content it replaces, with a slow
(1.5s), reduced-motion-respecting shimmer. Never a generic full-page spinner for a screen with named
regions (`structure.md` §6 specifies skeleton shape per screen — e.g. "skeleton balance/return
cards," not a blank spinner).

### 7.8 Toast

Bottom-right, `surface` background, `radius-md`, the one place elevation shadow (§6) is used since a
toast must read as floating over content, 4s auto-dismiss for success confirmations,
persistent-until-dismissed for anything carrying an error. Reserved for transient confirmations
(e.g. "Deposit submitted") — state changes that need to persist (a bounced deposit, per
`structure.md` §6) render as a row-state change or banner instead of a toast that can be missed.

## 8. Domain-specific visual patterns

These map directly to the ADRs and requirements the brief called out — each is a real financial/
regulatory distinction, not a styling preference.

### 8.1 As-published vs. as-corrected (ADR 1, ADR 6)

A figure that has been restated carries a small `accent`-colored badge reading "Restated" next to
it, and the **original as-published figure remains visible, struck through in `text-muted`, not
removed** — e.g. `~~$14,204.10~~ $14,388.55 [Restated]`. This is a direct visual expression of ADR
1's core guarantee ("the as-published figure stays queryable, never rewritten") — the UI must not
quietly swap the number, since the whole point of the ledger design is that both figures exist. A
"View original as-published statement" link sits next to any restated period on the Statements
screens, per `08-surfaces.md` §5.

### 8.2 Withdrawable vs. investable cash (ADR 5)

`CashSummary` renders as **two separate labeled stat figures side by side, never a single merged
"Balance."** On the Dashboard and the Funding overview — any view not already scoped to one
action — both figures render at **equal visual weight** (same size, same `text` color, same card
treatment): they are both real, current numbers, not a primary-plus-pending pair, and rendering one
of them smaller or in `text-muted` would visually imply the withdrawable figure is provisional or
secondary, which it is not. Weight only diverges on a form scoped to one policy function
specifically — a withdrawal form emphasizes Withdrawable (`heading-sm`) with Investable present but
quieter (`body`/`text-secondary`), because only Withdrawable bounds what that form can submit; an
order form does the reverse for the same reason. The rule is "equal by default, weighted only when
one number is what the current action is actually checked against" — never "one is generally the
important one."

### 8.3 Simulated account approval (ADR 21)

The account-approval status badge, when it is the simulated auto-approval path (which is always, per
ADR 21 — there is no real brokerage verdict in v1), carries a neutral (not `warning`, not `error`)
`text-secondary`-on-`surface-sunken` "Simulated" tag directly next to the "Approved" status — e.g.
`Approved [Simulated]`. This is deliberately **not** a semantic color, because it isn't a health
signal — it's a provenance disclosure (ADR 21: "the distinction from a genuine third-party verdict
is never lost or misread"). Coding it green would imply extra confidence; coding it amber/red would
falsely suggest something is wrong. A plain neutral label is the honest treatment the ADR asks for.

### 8.4 Reconciliation break aging (FR-31)

`AgingIndicator` on the breaks queue escalates through the semantic scale by age, each step paired
with a label so the color alone never carries the meaning: `< 1 day` → `warning-subtle` bg, "1d";
`1–3 days` → `warning` text on `warning-subtle`, "3d"; `> 3 days` → `error` text on `error-subtle`,
"5d" (or however many). The `OpenBreakCallout` on `admin/customers/:id` (surfaced regardless of
which tab is active, per `structure.md` §6 / `08-surfaces.md` §6 edge case 2) always renders at
`error` weight regardless of the break's own age-tier — an open break on the specific account being
reviewed is never soft-pedaled by its age.

### 8.5 Order approval needed (FR-10)

`ApprovalBanner` on an order awaiting threshold approval is a full-width `warning-subtle` banner
(not a badge) at the top of the order detail view — a threshold-triggered hold is exactly the kind
of state that must not be missable by scrolling past a small pill.

### 8.6 Privileged/consequential actions (order approval, break resolution, KYC override)

These three actions share one property no other action in the system has: each is a deliberate,
audited override of the platform's default flow (`structure.md` §6 notes all three carry
`@audited`, ADR 15) — approving a threshold-held order, resolving a reconciliation break, reopening
a locked-`rejected` KYC status. They get one shared visual pattern, distinct from the default
`Primary` button (§7.1), so a person cannot commit one of these actions with the same casual click
as "Save changes":

- The triggering control is `Secondary`-styled (outline, not filled) with an `error`-colored border
  and `error` text, not `Primary`'s solid `ink` fill — a deliberately *quieter*, not louder, visual
  than a default primary action. Filling it solid would make it look like the routine "submit"
  action; the outline treatment marks it as a deliberate step someone has to read before taking.
- Clicking it opens a confirmation step (inline expansion or a modal, architect's call in
  `structure.md`) that restates in plain language what is about to happen — "Approve this $6,200
  order for Marcus Webb," "Mark this break resolved," "Reopen KYC for this customer" — never a bare
  "Are you sure?". The confirming control inside that step is the only place `Primary` styling
  co-occurs with an irreversible action.
- Once submitted, the action's own audit trail entry (customer/adviser name, timestamp) renders back
  on the resulting row — the same discipline ADR 15 already requires at the data layer, made visible
  in the UI rather than only queryable later.

This is one pattern reused three times, not three bespoke designs — consistency here is what makes
"this is a deliberate override" legible across the whole adviser surface.

### 8.7 Stale/missing price vs. expected market holiday (FR-15, FR-40)

Two banners that must not collapse into one generic "data unavailable" treatment, since they mean
opposite things for trust in the number on screen: a stale price is the platform silently *not*
substituting a number it should have (a real gap, `warning`/`error`-toned depending on age); a
market holiday is *expected*, valuation is simply unchanged from the prior close, and nothing is
wrong.

- **Stale/missing close** — `CompletenessBanner` in `warning-subtle` (or `error-subtle` once stale
  beyond a defined threshold, mirroring §8.4's aging escalation), copy names the actual gap: "Price
  for [ticker] as of [last known date] — today's close hasn't arrived yet." Never silently shows a
  live-looking figure computed from a stale input without this banner present (FR-15's explicit
  requirement).
- **Expected market holiday** — a `neutral` (`text-secondary` on `surface-sunken`, matching §8.3's
  "disclosure, not a warning" treatment) banner or inline note: "Markets closed [holiday name] —
  balance reflects [prior date]'s close." No semantic color, because nothing is wrong; using
  `warning` here would train customers to distrust a banner that appears every few weeks for no
  reason.

Both banners cite the specific date/ticker/holiday rather than a generic phrase — a customer (or an
adviser scanning many accounts) needs to be able to tell at a glance which of the two states they're
looking at without reading the surrounding page for context.

### 8.8 Provisional tax lot (S5)

`ProvisionalBadge` is neutral (`text-secondary` on `surface-sunken`, not a semantic color) with the
label "Provisional" — like §8.3, this is a data-completeness disclosure, not a warning that
something is wrong, so it does not borrow `warning`'s color.

### 8.9 Dunning state (S10)

`DunningBanner` follows the same escalation logic as §8.4: a first missed fee charge is `warning`;
`exhausted`/final-notice dunning state is `error`, both always accompanied by the specific next-step
copy (never a bare "payment failed").

## 9. Accessibility notes

- All interactive elements: visible 2px `accent` focus ring, never `outline: none` without a
  replacement (`frontend/CLAUDE.md`'s own rule, restated here as a visual spec).
- Reduced motion (`prefers-reduced-motion`): skeleton shimmer and any transition drop to an instant
  or near-instant state change — no motion is ever the sole carrier of information.
- Minimum touch target 40px (buttons, inputs) / 44px (table rows), regardless of visual density.
- Color is never the only signal (§2.4) — verified per-component in §7/§8 above.

## 10. Open questions

None blocking. One coordination note: `structure.md` §9 escalates a missing adviser
customer-search/list endpoint to `main` — if that endpoint is added later, its screen (a searchable
customer table) inherits the standard Table spec (§7.6) directly with no new pattern needed.

Coordinated with `frontend-architect`: this spec was written against their component inventory
(`structure.md` §3) and loading/empty/error state table (§6), so every component and domain pattern
above maps to a component they've actually named, not a hypothetical one.

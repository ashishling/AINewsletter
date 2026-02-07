## UI Revamp Plan: Curator-First, Editorial, High-Speed Workflow

### Summary
Revamp `output/curator.html` into a faster, cleaner curation workspace with an editorial-modern visual language and compact density, while keeping Flask APIs intact.  
Implementation will move from one inline HTML/CSS/JS file to a lightweight frontend build (`Vite + vanilla TypeScript + modular CSS`) and ship in 3 phased PRs.

### Scope
- In scope:
  - Curator UI only (`/` route, currently `output/curator.html`)
  - Visual system, layout, interaction patterns, accessibility, and performance polish
  - Frontend codebase restructuring with build output still served by Flask
- Out of scope:
  - `output/viewer.html` redesign (deferred)
  - Database schema changes
  - Core curation business logic changes

### Architecture And File Plan
1. Frontend source (new):
   - `frontend/src/main.ts`
   - `frontend/src/styles/tokens.css`
   - `frontend/src/styles/base.css`
   - `frontend/src/styles/layout.css`
   - `frontend/src/styles/components/*.css`
   - `frontend/src/ui/*.ts` (queue, reader, modals, toasts, subscriptions)
   - `frontend/src/api/client.ts` (typed API wrappers)
2. Build output (served by Flask):
   - `output/assets/*` (bundled JS/CSS)
   - `output/curator.html` becomes a lean shell that loads built assets
3. Backend integration:
   - Keep existing Flask endpoints unchanged
   - Keep `@app.route("/")` serving `output/curator.html`
   - Keep `@app.route("/output/<path:filename>")` for static assets

### UX/Product Decisions Locked
- Primary workflow: split layout (`queue + reader`) as default
- Density: compact first
- Visual tone: editorial + modern (non-generic, no purple gradient/default system look)
- Rollout: phased (2-3 PRs)
- Goal priority: curation speed over purely aesthetic changes

### UI Design System (Concrete)
1. Typography:
   - Heading font: expressive serif/editorial face
   - UI/body font: readable sans with strong numerals for stats
   - Tight type scale with clear hierarchy for title/meta/actions
2. Color + surfaces:
   - Warm neutral base + high-contrast action colors by status
   - Semantic tokens for `pending/shortlisted/rejected/top-pick`
   - Replace flat cards with layered surfaces and consistent elevation
3. Motion:
   - Meaningful transitions only: queue row reorder, modal open, toast entrance
   - Reduced-motion fallback respected
4. Layout:
   - Desktop: two-pane reader-first workflow
   - Mobile/tablet: stack panes with sticky action bar
   - Status filtering switches the queue, not full page context

### Interaction Redesign
1. Queue panel:
   - Compact article rows with source/topic/status chips
   - Fast actions on each row: shortlist/reject/reset/top-pick
   - Keyboard shortcuts (`J/K` navigate, `S` shortlist, `R` reject, `N` focus notes)
2. Reader panel:
   - Embedded preview + fallback
   - Sticky action controls and auto-save notes feedback
   - Next/previous article controls for rapid triage
   - Prevent page-level scroll coupling by using independent queue/reader pane scrolling (desktop)
3. Global controls:
   - Sticky header with stats and core actions
   - Cleaner modal system (archives, add article, newsletter)
   - Better empty/loading/error states

### Public APIs / Interfaces / Types
1. Backend API changes:
   - None required for v1 revamp
2. Frontend data contracts (new typed interfaces in TS):
   - `Article`, `Stats`, `Subscription`, `Newsletter`, `ArchiveWeek`
3. Optional non-breaking enhancements (phase 3, only if needed):
   - Support `PATCH /api/articles/:id` for partial updates (currently POST curate route works)
   - Add pagination params to `/api/articles` if dataset grows

### Phase Plan
1. Phase 1: Foundation + visual system
   - Introduce build toolchain and modular frontend structure
   - Implement tokens, typography, base layout shell
   - Port existing functionality without behavior change
2. Phase 2: Workflow-first UI
   - Implement split queue/reader layout
   - Compact rows, sticky actions, keyboard shortcuts
   - Notes autosave UX improvements and stronger state feedback
3. Phase 3: Polish + hardening
   - Animation/accessibility pass
   - Error handling consistency and performance tuning
   - Final responsive/mobile pass and cleanup

### Test Cases And Scenarios
1. Functional parity:
   - Load articles/stats/subscriptions/newsletters/archives
   - Curate transitions across all statuses
   - Top-pick toggle only on shortlisted
   - Add manual article + metadata fetch
   - Archive/unarchive flows
2. UX behavior:
   - Keyboard shortcuts perform correct actions
   - Notes debounce save works and survives rapid typing
   - Reader and queue stay in sync after mutations
   - Scrolling deep in queue does not move reader out of viewport on desktop
3. Responsive:
   - Desktop split-pane layout
   - Tablet stacked layout with preserved actions
   - Mobile modal usability and tap targets
4. Accessibility:
   - Keyboard-only navigation for all critical actions
   - Focus states visible
   - ARIA labels on icon-only controls
   - Color contrast passes for status chips/buttons
5. Performance:
   - Initial render under target budget
   - No layout thrash when switching articles
   - Large list remains responsive

### Acceptance Criteria
- Curation throughput visibly improved (fewer clicks/context switches than current Kanban flow)
- All current backend endpoints remain compatible
- UI has a distinct editorial-modern identity (not generic default UI)
- No functional regressions in existing workflows
- Works on desktop and mobile with accessible keyboard flows

### Assumptions And Defaults
- Node/npm toolchain is acceptable for frontend build step
- Flask remains the app server and source of truth APIs
- `viewer.html` redesign is deferred to a later initiative
- No auth/permission model changes are required for this pass

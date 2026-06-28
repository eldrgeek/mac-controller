# Ideas to Fold into Pulse — Bridge, jiminy, Sidekick (desktop)

*Captured 2026-06-27 before archiving. Three "dispatch control surface" precursors mined for design ideas to preserve as Pulse (mac-controller) becomes the canonical operator surface. Source repos read in full; no files modified.*

**Pulse context (target):** mac-controller's `cc.py` + `pulse-dispatcher.py` are the canonical operator surface. Asks surface via `cc hud-ask` → relay broker on `:3333` (`GET /hud/asks`, `POST /hud/response/:id`) → Pulse renderers (Pixel app + web on `:8088`). The old Mac HUD overlay on `:3334` was retired 2026-06-10. Each of these three repos predates that consolidation and reinvents a slice of it.

---

## 1. Bridge — `/Users/mikewolf/Projects/Bridge`

**What it was trying to be.** A single card-stream backend feeding three thin, stateless renderers (Mac Sidekick popover, HUD, Pixel app). Its thesis: fleet *progress narration* should not go into Dispatch chat scrollback — it should become ambient "cards" on glanceable surfaces, leaving chat reserved for direct Dee↔Mike exchange. Every unit of fleet work (running task, status update, blocking decision) is one `card`. Spec-only (v0.5, `SPEC.md`); no code, not a git repo.

**Design ideas worth preserving (concrete enough to reimplement):**

- **Unified card data model (one SQLite `cards` table, WAL).** A single row type subsumes both progress and decisions: a decision is just a card with `status="waiting"` + `action_options` populated. Fields worth keeping verbatim: `asker_persona` / `asker_session_id` / `source` (provenance), `status` (`running|waiting|done|failed`), `progress` JSON (append-only `{ts,text}` array), `urgency` 0–3, `category` (`task|decision|draft-review|quick-toggle`), `action_type` (`yes-no|pick-one|approve-edit-reject|open-then-decide|freetext|ack`), `thread_parent_id` (multi-turn refinement), and `routing_state` (snapshot of `ATM|ATP|AFK|ASLEEP`). ULID PKs for fleet-safe sortable IDs. — This is a strict superset of what the relay's `/hud/asks` carries today; Pulse's ask schema could adopt the progress/urgency/category fields.
- **Default-proceed sweeper.** A `waiting` card with `default_after_ms` + `default_value` auto-resolves (`by="default"`) when Mike is AFK and the timer elapses. Keeps the fleet moving without a human in the loop. Pulse asks currently block indefinitely — this is the single highest-value mechanism to fold in.
- **Chat-vs-cards routing rule (§4).** Explicit doctrine: progress narration / status / batch results / structured decisions → cards (ambient); direct questions, sensitive/personal/medical/financial content, strategic back-and-forth → chat. "If Dee is about to narrate 'dispatched, now waiting' in chat, that's a card, not a message." Worth preserving as a *Pulse operating principle*, not just code.
- **User-state-driven routing.** A single `GET/POST /state` endpoint (`ATM|ATP|AFK|ASLEEP`); renderers decide what to surface based on it (ATM→HUD+popover, ATP→Pixel, AFK→queue silently, ASLEEP→queue + suppress all sound). Backend always serves the full stream; surfacing is the renderer's job. Pulse already has a relay broker — this is the routing layer it lacks.
- **Worker client ergonomics.** Two clean patterns in `bridge_client.py` (spec'd, unbuilt): fire-and-forget `BridgeCard.create(...).progress(...).done()`, and blocking `bridge_ask(title, options, default_after_ms, default_value) -> {value, text, by}`. The blocking-ask signature (with default-proceed) is a better `cc hud-ask` contract than today's.
- **Global SSE that ships the full card on every event** (`card.created|updated|answered|completed`) so renderers never refetch. Relevant if Pulse ever moves off polling `:3333`.
- **Open questions Bridge already surfaced (don't re-litigate, just decide):** collapse `lifecycle` into `status`+derived-`archived` (Bridge author thought yes); pick a single owner of user-state to avoid two stores drifting; decide whether chat-vs-cards is convention or an enforced guardrail.

**Recommendation: FOLD-AND-ARCHIVE.** Pure spec, no code, not a git repo. Conceptually overlaps Pulse and the Forge ledger (its own CLAUDE.md flags this: "confirm which surface is canonical before building, to avoid a third parallel queue"). Every idea is captured above. Archive the repo; the card model + default-proceed sweeper + routing rule are the payload.

**Salvageable files:** `SPEC.md` (the whole design — the only artifact). No code to salvage.

---

## 2. jiminy — `/Users/mikewolf/Projects/jiminy`

**What it was trying to be.** A self-nag accountability daemon for cc-dispatch. The orchestrator fires background jobs and registers a "proof-of-work" artifact path that should appear when a job finishes; several failure modes (silent exit-0, wrong path, credit/login wall, hung process) cause that artifact to never land, and Mike only finds out by manually reading logs. Jiminy holds the orchestrator accountable: every registered *promise* gets a deadline; if the artifact is missing past deadline, it nags via `cc hud-ask`. A second concern crept in: emitting Dee's **identity affirmation** on a 30-min heartbeat.

**Status note — IT IS ACTUALLY RUNNING.** Despite DESIGN.md saying "Scaffold (not yet installed)", `jiminy.log` shows live affirmation emits every 30 min, most recent **today at 22:01**. The promise-tracking half appears unused (no live promises observed), but the affirmation-heartbeat half is a live process on this Mac. Archiving the directory will silently kill a running daemon — flag this before moving anything.

**Design ideas worth preserving:**

- **The promise / proof-of-work watchdog (the core idea).** `register(job_id, --pow PATH, --deadline MIN)` → daemon polls `os.path.exists(pow_path)`; artifact present → silent `done`; deadline passed + missing → nag + `expired`. This is the *inverse* of cc-dispatch's existing completion notification: cc-dispatch notifies on success, Jiminy notifies on **non**-completion. Pulse/pulse-dispatcher has no equivalent "this dispatch never produced its artifact" alarm — this is the most reusable mechanism.
- **Nag-loop discipline (anti-spam).** First nag at deadline; subsequent nags every `NAG_COOLDOWN` (default 1800s); hard cap `MAX_NAGS=4` then silent (logged only) to prevent 2am zombie-job spam. Reminder nags for long-running jobs that already nagged once. These exact knobs (cooldown + max-count + reminder) are the right defaults for any Pulse nag/escalation feature.
- **Tiered notification fallback chain.** `cc hud-ask` → osascript *banner* (explicitly NOT keystroke injection) → append to `nag-pending.txt`. Plus an unresolved-but-correct idea in DESIGN.md §3: Discord fallback (REST via `~/.hermes/.env` bot token) when the Mac is asleep / Mike is traveling and the HUD path can't reach him. Pulse should inherit this ranked fallback ladder.
- **Affirmation/heartbeat scheduling (the genuinely novel bit).** Every `AFFIRMATION_INTERVAL` (default 1800s) + on startup, Jiminy reads `affirmation.md` (Dee's identity reminder, written by Dee for Dee) and writes it to `last-affirmation.txt` so any fresh Dee instance reads it on orientation. This is a *cheap, self-authored, periodic identity-reinforcement* mechanism — a "persona keepalive." If Pulse is "the nervous system," a scheduled identity emit for the orchestrator persona is a real capability worth a deliberate home (Pulse Core / pulse-dispatcher tick, or a SOMA-level cron), not an accidental side-effect of a nag daemon.
- **Clean scope boundaries (worth copying as doctrine):** Jiminy does NOT parse report *content* (that's soma-nag), does NOT retry failed dispatches (human decides), does NOT manage process lifecycle (launchd does). Narrow watchdog, not a do-everything supervisor.

**Recommendation: FOLD-AND-ARCHIVE — but carefully (live process).** The promise-watchdog and affirmation-heartbeat are the two payloads; both belong in pulse-dispatcher/Pulse Core, not in a standalone daemon. Before archiving: (a) confirm the running jiminy process is stopped/migrated so the directory move doesn't orphan it, and (b) re-home `affirmation.md` (Dee's identity doc — has independent value) and the affirmation-emit tick into Pulse. The DB sidecars (`jiminy.db-wal/-shm`) are live, not cruft.

**Salvageable files:**
- `jiminy.py` — clean ~245-LOC reference implementation of the poll/check/nag loop + cooldown/max-nag logic + tiered `notify()`. Lift the watchdog logic near-verbatim into pulse-dispatcher.
- `affirmation.md` — Dee's self-authored identity affirmation. Re-home into Pulse/SOMA regardless of archiving; this is content, not scaffold.
- `DESIGN.md` — promise model + the Discord-fallback open question.

---

## 3. Sidekick (desktop) — `/Users/mikewolf/Projects/Sidekick`

**Confirmed: this is the desktop Sidekick**, distinct from Sidekick-android/Pulse. Evidence: PyObjC menu-bar app (`sidekick_gui.py`), Mac-filesystem state, `cc hud-ask` on `:3333`, Google Calendar OAuth — all Mac-side. The Android phone surface is explicitly a *separate* repo (`~/Projects/soma-alarm/`, Flutter/Pixel) referenced throughout.

**What it was trying to be.** A focus/accountability companion for Mike, ADD-aware by design ("my ADD is the design constraint, not a footnote"). The convergent organ of the SOMA fleet: capture everything (GTD inbox), run the morning routine, nudge by *task completion not by clock*, ingest HUD/screen/email/calendar context while Mike is AFK, and produce a single converged next-action on his return. `REQUIREMENTS.md` is a deep, Mike-annotated source-of-truth (compiled from ~12 conversations, with Mike's inline answers to all 13 open questions).

**Status note — THIS IS REAL IN-PROGRESS WORK, NOT A DEAD SPEC.** Git repo, 4 commits, ~1,315 LOC (`sidekick.py` 681 + `sidekick_gui.py` 634), a 5-file `tests/` suite (integration, GUI smoke, gcal graceful-degradation), live state files, and a `watchdog.log` **written to today (2026-06-27 22:21)**. Working commands: `brief / focus / checkin / capture / nudge / auth`. The menu-bar GUI, the attention HTTP endpoint, and Google Calendar OAuth are implemented. This is the *only* one of the three with shipped, tested, currently-running code.

**Design ideas worth preserving:**

- **`action_queue.jsonl` — the Dee→Mike decision queue (the standout mechanism).** Append-only JSONL where each row is a structured ask: `{id, prompt, context, options[], default_action_on_yes, received_at, source}`. Real entries in the file are security-audit decisions from "Locke." This is *exactly* the Pulse ask model, already in use — note the richer fields Pulse's `/hud/asks` lacks: a `context` paragraph for drill-down and `default_action_on_yes` (states what happens on approval so Mike isn't approving blind). Fold these two fields into the Pulse ask schema.
- **Task-based (not time-based) nudge cadence — N1.** Hard requirement: check in *after task completion*, not on a 15/30-min Pomodoro timer. Pulse nudging should default task-based, with time-based reminders reserved for *external* commitments (calendar events) only. This inverts the usual productivity-tool default and is load-bearing for Mike specifically.
- **The "magic redirect line" — N3.** The literal, un-paraphrasable phrase "What's the single most important thing you should focus on right now?" — a trained interrupt Mike responds to. Already implemented (`cmd_nudge` posts it as a *passive* HUD nudge, not a blocking ask). Pulse should keep this exact string as the canonical refocus prompt.
- **Passive HUD nudge vs. interactive hud-ask distinction.** The last commit ("nudge refactor to passive HUD job") split low-priority *passive* nudges from interactive *Confirm/Failed/Partial* asks. Pulse should carry the same two-tier distinction (ambient nudge vs. blocking ask).
- **AFK as a first-class state with buffer-and-converge (§2.3, A1–A5).** Detect AFK (Screenpipe/HUD/keyboard activity), *never* alert during AFK, accumulate a rolling buffer of finished/failed tasks + approaching events + urgent inbound, then on detected return present **one** converged summary + single next-action — not a firehose. Honor *declared* AFK ("going to dojo/meditate") as authoritative even if sensors disagree. This is the deepest idea here and the one Pulse's routing layer should adopt (it pairs directly with Bridge's `ATM|ATP|AFK|ASLEEP` routing).
- **Escalation ladder by intrusiveness (§4.5).** Ranked write-side channels: vault file (silent) → native notification → modal alert → `cc hud-ask` → Discord DM (HERMES) → email. With escalation thresholds Mike confirmed in §7 Q4: 0/silent-buffer when AFK, 30 min when ambiguous, 5 min for explicit deadlines. Never escalate during known-AFK windows. This is the canonical Pulse escalation policy, already Mike-ratified.
- **ADD-friendly UX invariants (§5.1) — adopt as Pulse rendering rules:** one question at a time; single next action, never list-bomb; terse/businesslike tone (save enthusiasm for genuine wins); rabbit-hole / "generalizing past the task" detection (N4) with the in-spec interrupt tone ("STOP. You just demonstrated the exact pattern you hired me to interrupt").
- **Document-provenance standard (§7 Q13, Mike: "adopt for all new documents").** Frontmatter carrying `compiled_by` (model+session+date), `source_authors` (humans + timestamps), `last_edited`. Mike tied this to "our RSI loops at every level." Worth applying to Pulse-authored artifacts.
- **Mike's ratified architecture answers (in REQUIREMENTS §7) that Pulse inherits:** Sidekick is the focus/UX layer, *not* a new dispatch system — it calls cc-dispatch verbatim (Q9). Single-user (Mike) for v1, package for resale later (Q11). Google Calendar = `mw@mike-wolf.com`, `claude@mike-wolf.com` soon (Q5). Voice = ElevenLabs, save Claude tokens for inference (Q10). Open-access data posture to trusted LLM endpoints; never leak secrets to outside *individuals* without confirmation (Q6). "The team ideally is never idle… always moving forward until we run out of tokens" (Q8).

**Recommendation: KEEP — do NOT archive.** This is the one that's alive: working, tested, currently-running Mac code plus a deeply-considered Mike-annotated requirements doc. Fold the *ideas* (action-queue fields, task-based cadence, AFK buffer-and-converge, escalation ladder, magic-redirect line) into Pulse, but the repo itself is in-progress work with unique value, not a dead spec. At minimum, keep `REQUIREMENTS.md` out of any archive — it's the canonical Sidekick vision and Mike calls it "stunningly competent." If the menu-bar surface is being superseded by Pulse, retire the *GUI* deliberately, but harvest the CLI commands (`capture`, `focus`, `checkin`, the GTD inbox) — Pulse has no capture surface and these fill that gap.

**Salvageable files:**
- `REQUIREMENTS.md` — the Mike-annotated source-of-truth vision (KEEP regardless). Canonical answers to 13 architecture questions.
- `state/action_queue.jsonl` — the live Dee→Mike decision-queue format (the schema to fold into Pulse asks).
- `sidekick.py` (681 LOC) — working `brief/focus/checkin/capture/nudge/auth` CLI; `hud_ask()` helper; gcal OAuth with graceful degradation. The `capture` + GTD-inbox commands have no Pulse equivalent.
- `sidekick_gui.py` (634 LOC) — PyObjC menu-bar app: 10s state poll, attention-icon state machine (🎯↔🔴), 5-min-debounced popups, HTTP attention endpoint on `:3335`. Reference for any Pulse menu-bar surface; the `:3335` attention endpoint overlaps Pulse's relay.
- `SOMA-ALARM-GAP.md` — clean gap analysis mapping Sidekick requirements onto the soma-alarm (Android) implementation; useful when reconciling desktop Sidekick with Pulse/Sidekick-android.
- `tests/` — 5 test files (integration, GUI smoke, gcal graceful) — evidence of real engineering, worth keeping with the code.
- (Ignore: `leaves_on_my_poncho*.mp4`, `build_video.py`, `video_parts/` — unrelated media artifacts living in the dir.)

---

## Pulse backlog — distilled, dedup'd, actionable

Ideas to add to Pulse (mac-controller), in rough priority order. Several appear in 2–3 repos; merged here.

1. **Default-proceed on blocking asks.** Add `default_after_ms` + `default_value` to the Pulse ask schema; a sweeper auto-resolves expired asks (`by="default"`) when Mike is AFK. *(Bridge — highest value; today's asks block forever.)*

2. **Dispatch proof-of-work watchdog.** Register `(job_id, artifact_path, deadline)` at dispatch time (one-line hook in pulse-dispatcher/cc-dispatch); nag when the artifact is missing past deadline. Inverse of the existing success notification. *(jiminy — lift `jiminy.py`'s loop near-verbatim.)*

3. **Nag-loop discipline knobs.** Any Pulse nag/escalation uses: first nag at deadline, cooldown 1800s between repeats, hard cap 4 then silent, reminder-nag for long-runners. *(jiminy.)*

4. **Ranked escalation ladder + thresholds.** vault-file → native notification → modal alert → `cc hud-ask` → Discord DM (HERMES, REST via `~/.hermes/.env`) → email. Thresholds (Mike-ratified): silent-buffer when AFK, 30 min ambiguous, 5 min explicit-deadline. Never escalate during known-AFK. *(Sidekick §4.5 + jiminy's Discord-when-asleep fallback.)*

5. **AFK-aware routing + buffer-and-converge.** Single owner of user-state `ATM|ATP|AFK|ASLEEP`; renderers decide surfacing (ATM→HUD+popover, ATP→Pixel, AFK→queue silent, ASLEEP→queue+mute). On AFK→active transition, emit ONE converged summary + single next-action, not a firehose. Honor *declared* AFK as authoritative. *(Bridge routing + Sidekick §2.3.)*

6. **Richer ask schema.** Extend Pulse `/hud/asks` rows with: `context` (drill-down paragraph), `default_action_on_yes` (so Mike doesn't approve blind), `urgency` 0–3, `category`, `progress[]` (append-only), `source`/`asker_persona`/`asker_session_id`, `thread_parent_id`. *(Sidekick `action_queue.jsonl` + Bridge `cards` table — same model; adopt the union.)*

7. **Chat-vs-cards (chat-vs-asks) doctrine.** Progress narration / status / batch results / structured decisions → ambient Pulse cards; direct questions, sensitive/personal content, strategic back-and-forth → chat. Decide: convention or enforced guardrail. *(Bridge §4.)*

8. **Task-based nudge cadence by default.** Check in after task completion, not on a clock; time-based reminders only for external/calendar commitments. Keep the passive-nudge vs. interactive-ask two-tier split. *(Sidekick N1/N8/N9.)*

9. **Magic-redirect line (verbatim).** Keep "What's the single most important thing you should focus on right now?" as Pulse's canonical refocus prompt, posted as a passive nudge. *(Sidekick N3.)*

10. **Capture surface (GTD inbox).** Pulse has none; Sidekick's `capture` command + GTD inbox fill the gap. Near-instant type-and-forget (<1s ack), project-taggable. *(Sidekick C1–C5.)*

11. **Persona identity-heartbeat.** A scheduled (default 30-min + on-startup) emit of the orchestrator persona's self-authored affirmation to a known path that fresh instances read on orientation. Give it a deliberate home in Pulse Core / a SOMA cron, not a side-effect of a watchdog. Re-home `affirmation.md`. *(jiminy — and confirm the live jiminy process is migrated before archiving.)*

12. **ADD-friendly rendering invariants + provenance.** One-question-at-a-time, single-next-action (never list-bomb), terse/businesslike tone, rabbit-hole detection. Stamp Pulse-authored artifacts with `compiled_by/source_authors/last_edited` provenance frontmatter. *(Sidekick §5.1, §7 Q13.)*

---

### Archiving call summary

| Repo | Call | Why |
|---|---|---|
| **Bridge** | FOLD-AND-ARCHIVE | Spec only, no code, not a git repo. All ideas captured. |
| **jiminy** | FOLD-AND-ARCHIVE (carefully) | Scaffold + small daemon, but a process is **running now** — stop/migrate it and re-home `affirmation.md` first. |
| **Sidekick (desktop)** | **KEEP** | Real in-progress work: git repo, ~1,315 LOC, tests, code written today. Harvest ideas into Pulse; keep `REQUIREMENTS.md` and the CLI out of any archive. |

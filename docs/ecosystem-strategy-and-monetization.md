# AEC Omni-Bridge — Ecosystem Strategy, Brand & Monetization Playbook

**Status:** Internal strategy document (v1.0, 2026-06-12)
**Owner:** A. Sam Mohammad (Sam-AEC)
**Note:** This document contains personal career and revenue strategy. Consider keeping it out of the public repository (move to a private repo or local notes) before pushing. The technical companion is `docs/system-blueprint-and-workflows.md`.

---

## 1. The Playbook Being Run — the "pyRevit moment"

pyRevit is the proof that one person's open-source AEC tool can become a career engine: it became indispensable daily infrastructure for BIM teams worldwide, and its author's name became synonymous with Revit automation — speaking slots, industry recognition, and job leverage followed from *distribution*, not from sales.

The structural opportunity now is bigger than pyRevit's was, because a platform shift is underway: **AI agents are gaining the ability to operate professional software, and MCP is the protocol they use.** Whoever ships the credible, secure, multi-platform MCP runtime for BIM becomes the default name in "AI × AEC" — a category that barely has incumbents yet. pyRevit automated Revit for humans; Omni-Bridge operates the whole AEC stack for agents. That is the positioning sentence.

**Positioning statement:** *AEC Model Bridge is the open, secure runtime that lets AI agents operate Revit, Navisworks, Rhino, and your CDE — turning fragmented BIM workflows into one orchestrated pipeline from concept to dashboard.*

### Why the timing is right
- MCP registries and clients (Claude Desktop, VS Code, Copilot) are mainstream; AEC entries are sparse and mostly single-tool. A multi-platform, security-hardened entry stands out immediately.
- BIM managers are being asked by leadership "what's our AI strategy?" and have nothing concrete to demo. The zero-switch IFC demo (blueprint §4.2) is a five-minute answer they can run on a laptop.
- The dual-license foundation (GPL + commercial) is already in place as of v1.1.0 — the legal groundwork most OSS authors retrofit painfully is done.

---

## 2. Brand Architecture

| Asset | Role | Action |
| --- | --- | --- |
| **AEC Model Bridge** | The product name (PyPI, MCP Registry, releases) | Keep. Already established in registry and packaging. |
| **Omni-Bridge** | The orchestration layer / architecture story | Use as the *narrative* name ("the Omni-Bridge architecture") in talks and articles — memorable, but don't fragment package naming. |
| **Sam-AEC** | The personal brand (GitHub org, LinkedIn) | Every artifact links back: README byline, docs footer, video outros, conference bios. |
| Repo name `Autodesk-Revit-MCP-Server` | Legacy, undersells the product and risks trademark friction ("Autodesk" leading the name) | Rename to `aec-model-bridge` (GitHub auto-redirects; README clone URL already assumes it). Tracked as OD5 in the blueprint. |
| Docs site | Currently README + docs folder | Stand up MkDocs Material (or Docusaurus) on GitHub Pages at a custom domain. The docs site is the brand's home, not the repo. |

**Trademark discipline:** never lead with vendor names; keep `TRADEMARKS.md` current; "for Autodesk® Revit®" phrasing only in descriptive contexts. This matters more as visibility grows.

---

## 3. Audience Map — whose pain, which workflow, what they'll pay for

| Persona | Daily pain | Flagship workflow that hooks them | Monetizable need |
| --- | --- | --- | --- |
| **BIM Manager / Information Manager** | Manual compliance checks, stale model-health reporting, "AI strategy" pressure from leadership | W3 Model Health & Compliance (zero-install demo) | Training, firm-wide deployment support, premium audit recipe packs (IDS/COBie) |
| **VDC / Coordination Lead** | Clash Detective ritual, screenshot-driven coordination meetings | W2 Coordination Loop + ACC Issues publishing | Commercial license for firm integration, Navisworks/Solibri switch support |
| **Computational Designer** | Rhino→Revit re-modeling, brittle handoffs | W1 Concept-to-BIM | Custom recipe development, Rhino switch priority support |
| **AEC Data / Power BI Lead** | Fragile Excel export chains feeding dashboards | W4 Data-Lake Drop + the `.pbit` templates | Dashboard template packs, hosted run-history (future SaaS) |
| **Cost / 5D team** | Re-keying quantities between Revit and Excel | W5 QTO round-trip | Per-seat commercial terms inside ERP-integrated firms |

Content, demos, and pricing should always be expressed in these personas' language — never "MCP server with 155 tools," always "clash report in your dashboard before the coordination meeting starts."

---

## 4. Monetization Ladder (each rung funds the next)

The model is **open-core with services**, built on the existing dual license. Rungs in order of activation:

### Rung 0 — OSS core (active now)
GPL-3.0 + Revit Linking Exception. Purpose: distribution, trust, brand. The core hub, Revit switch, and flagship recipes stay free forever — this is the moat *and* the marketing.

### Rung 1 — Commercial licensing (active now, under-leveraged)
The dual-license already permits selling commercial terms to firms that won't accept GPL (embedding, redistribution, proprietary modification). Action: add a one-page "Commercial use" page on the docs site with a contact funnel (currently buried in `LICENSING.md`), and a simple price anchor for firm-wide licenses. Even two or three firm licenses validate the model.

### Rung 2 — Premium recipe packs & switches (after Phase E)
The recipe engine (blueprint §5.1) makes workflows *products*: versioned files, installable separately. Free: W1–W5 reference recipes. Paid packs: COBie handover audit, ISO 19650 naming compliance, Solibri ruleset orchestration, carbon/QTO packs with the Power BI templates included. Desktop switches beyond Revit/Navisworks (Solibri, Tekla) can be "supported tier" — source-available but with paid support/maintenance commitments.

### Rung 3 — Services (continuous, highest margin, zero build cost)
- **Implementation consulting:** firm-specific switch deployment, recipe authoring, dashboard wiring.
- **Corporate training/workshops:** "AI agents for BIM teams" half-day workshop — the W3 zero-install demo makes this trivially deliverable.
- **Custom development retainers** for firms wanting private switches (their internal databases, ERP).
Services revenue is also the strongest job-market signal: every engagement is a case study.

### Rung 4 — Hosted control plane (deferred — OD4 in blueprint)
A SaaS layer: team run-history, scheduled pipelines, dashboard hosting, fleet management of switches across an office. Only build after Wave 2 proves recurring usage. This is the venture-scale option; everything before it is sustainable solo.

### Channels
MCP Registry (already listed) · PyPI · GitHub Releases · Autodesk App Store (Revit + Navisworks switches — also a credibility badge) · Food4Rhino (Rhino switch) · GitHub Sponsors (turn on now; costs nothing) · Speckle community showcase.

---

## 5. Career-Leverage Plan (the "spread the name" track)

The product *is* the portfolio. Convert engineering milestones into visibility artifacts on a fixed cadence:

1. **Demo videos (highest ROI):** 30–60 second screen captures — "Claude runs a clash test in Navisworks and the Power BI dashboard updates" — posted to LinkedIn with the persona's pain in the first line. One per flagship workflow as each lands in blueprint Phase C/D. These clips are what recruiters and CTOs actually share.
2. **Written artifacts:** one architecture deep-dive per phase (the blueprint's sections are pre-written outlines: "Why we chose file-based discovery over a daemon," "Provenance records for BIM pipelines"). Cross-post: personal blog/docs site first, LinkedIn summary linking back.
3. **Talks:** target the AEC-tech circuit — Speckle community calls (easiest entry, immediately relevant audience), then BILT / Autodesk University / DevCon proposals using the W2 live demo. One conference talk converts to more job leverage than months of posting.
4. **Metrics to capture from day one** (screenshot monthly): GitHub stars/forks, PyPI downloads, MCP registry ranking, docs-site analytics, video view counts. These numbers go on the CV ("author of an MCP platform with N installs across M countries").
5. **The narrative for interviews:** not "I wrote a Revit plugin" but "I designed and shipped a multi-provider automation platform — protocol design, security model, OAuth, CI across .NET 4.8/8/10 and Python, plus the open-source go-to-market." Target roles: BIM Automation Lead, AEC Software Engineer, Developer Advocate at Speckle/Autodesk/Chaos/Nemetschek-family companies — all of which monitor exactly this ecosystem.

---

## 6. Risks & Mitigations

| Risk | Reality check | Mitigation |
| --- | --- | --- |
| Vendor SDK/ToS violations on non-Revit switches | GPL exception covers Revit only; Navisworks switch already shipped without equivalent review | Blueprint Phase A3 legal review **before** Wave 2 marketing pushes; keep SDK binaries out of repo |
| Autodesk trademark friction as visibility grows | Repo name currently leads with "Autodesk" | Rename (OD5); keep trademark hygiene |
| Support burden swamping a solo maintainer | Every OSS success story's failure mode | Aggressive issue templates, "supported tier" boundary (Rung 2), mock-first CI so contributors can work without licenses |
| A vendor ships the same thing natively | Autodesk/Speckle will add AI surfaces | Multi-vendor orchestration *is* the moat — no single vendor will orchestrate competitors' tools; move fast on the cross-platform story |
| Free users never convert | Common in AEC OSS | Conversion target is firms (licenses/services), not individuals; individuals are distribution |
| Security incident (agent does destructive things in a live model) | One bad story kills B2B trust | Blueprint policy layer (Phase B6) before any marketing push that targets firms; publish the security model prominently |

---

## 7. 90-Day Go-to-Market Calendar (aligned to blueprint phases)

| Weeks | Engineering (blueprint) | Visibility / business |
| --- | --- | --- |
| 1–2 | Phase A (hygiene, Speckle fix, licensing review) | Turn on GitHub Sponsors; repo rename; stand up MkDocs site; write "Introducing the Omni-Bridge architecture" post from blueprint §1–2 |
| 3–6 | Phase B (Contract v2, Navisworks completion) | Demo video #1: W3 zero-install IFC health check (works today); commercial-use page on docs site |
| 7–10 | Phase C (orchestrator, flagship recipes) | Demo video #2: W2 live clash loop; submit Speckle community call talk; first LinkedIn architecture deep-dive |
| 11–13 | Phase D (Parquet, Power BI templates) | Demo video #3: concept-to-dashboard full pipeline (the hero demo); publish `.pbit` templates; AU/BILT talk proposal using captured metrics |

Cadence rule: **every engineering milestone ships with its visibility artifact in the same week** — the work is only "done" when it's demonstrable and posted.

---

**Changelog**
- 2026-06-12 — v1.0 — Initial playbook.

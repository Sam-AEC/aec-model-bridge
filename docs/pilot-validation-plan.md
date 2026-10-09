# Pilot validation plan: five BIM coordinators

Status: **proposed. No pilot has been run.** This page contains no results,
no participant quotes and no measurements. Every number below is a threshold
chosen in advance, not an observation. The results template at the end is
empty on purpose.

This is the plan for roadmap item 18 in the [adoption priorities](roadmap.md).
It assumes the first demo from that roadmap (the find, review, approve, verify
loop on the [canonical fixture](../fixtures/canonical-model/README.md)) works
on a live Revit session. If it does not, fix that first; a pilot on a broken
demo measures the bugs, not the product.

## What we are trying to find out

Three bets are unproven. Each could be wrong independently, so each gets its
own question, its own evidence and its own kill criterion. A pilot that
returns one blended "people liked it" score would hide which bet failed.

| Bet | Question | Why it could be wrong |
| --- | --- | --- |
| 1. Safety | Do coordinators who do not script trust approve-before-change enough to let it edit a model? | They may approve without reading, refuse to approve anything, or want a stricter gate than we provide. |
| 2. Interop | Does the workflow fit the tools they already use (Navisworks, pyRevit, BIM 360 / Autodesk Construction Cloud)? | They may see it as a parallel tool to carry alongside their own, or it may collide with worksharing and cloud models. |
| 3. Client reach | Would their firms and clients allow and pay for it? | Individuals may like it while IT, security or the client's BIM execution plan blocks it. |

The product currently covers Revit through an add-in and a local server. It
does not integrate with Navisworks, pyRevit or BIM 360. Bet 2 therefore asks
whether it fits alongside those tools, not whether it connects to them. What
we learn there decides whether any integration work is justified, as the
roadmap already says.

## Who to recruit

Target: five people. Five is enough to see repeated failures, not enough to
estimate rates. Report counts ("3 of 5"), never percentages.

Inclusion:

- Works as a BIM coordinator or model manager on live projects, at least
  part of the week.
- Runs model checks today, by hand or with existing tools.
- Does not write scripts (Dynamo, Python, C#) as part of the job. Using
  pre-built pyRevit buttons or Dynamo players someone else made is fine and
  is relevant to bet 2.
- Has Revit on a machine where a pilot add-in may be installed, or agrees to
  a session on a loaner machine.

Spread the five on purpose, so one kind of workplace does not decide the
result:

- at least two firms, and at most two people from any single firm;
- at least one consultant-side and one contractor-side coordinator;
- at least one who works on BIM 360 / ACC cloud-workshared models, and one
  who does not;
- at least one who uses Navisworks for coordination routinely.

Exclusions: friends who will be kind, anyone who has seen a demo and been
told what to expect, and anyone who writes scripts for their team. Record
how each person was found and any prior relationship with the maintainer.

Recruiting steps:

1. Write a short invitation that says what the session is (about 90 minutes,
   on a test model, nothing from their project) and that the tool is
   unfinished. Do not promise features.
2. Ask for consent to record screen and audio, to take notes, and to publish
   anonymised, aggregated findings. Participants may withdraw at any point and
   have their data deleted.
3. Use a synthetic model only. No client data enters the session. Participants
   use their own Revit (version recorded) or a provided machine.
4. Compensate participants for their time if budget allows, and say so up
   front. State in the report whether they were paid.
5. Keep a screening sheet (name code, firm type, Revit version, tools used,
   scripting experience, cloud or local models) before any session starts.

## Session format

One person at a time, about 90 minutes, moderator present. The moderator
observes and does not help unless the participant is stuck for more than
three minutes; every help event is logged. Order:

1. Ten minutes: background interview and consent (interview prompts, part A).
2. Five minutes: moderator explains only that this is an assistant that can
   find and fix missing parameters and asks before changing the model.
   Nothing about how the approval works.
3. Fifteen minutes: setup, from a clean state to first result (task 0).
4. Forty minutes: the task script.
5. Twenty minutes: debrief interviews (parts B to D).

Each participant also does the manual baseline (task M) in the same session,
in counterbalanced order: odd-numbered participants do manual first,
even-numbered do the tool first. Rebuild the fixture before each attempt so
one run cannot affect the other.

## Task script

The fixture is the canonical model seeded with 12 doors that have no Mark and
3 rooms that have no Number (see
[`seeded-defects.json`](../fixtures/canonical-model/seeded-defects.json)).
These are the expected counts. Before each session the moderator confirms the
actual counts on the rebuilt model and writes them down. If they differ from
12 and 3, the session uses the actual counts and the difference is noted.

Participants get a one-line goal for each task, not instructions.

**Task 0: setup to first result.** Starting from a machine with Revit and
without the add-in, install the supported package and get the tool to report
a finding on the open fixture. The clock starts when the participant opens the
install instructions and stops at the first correct finding on screen.

**Task 1: find.** "Find out which doors and rooms are missing data."
Expected: 12 doors without Mark, 3 rooms without Number.

**Task 2: review and approve the door fix.** "Fix the missing door Marks."
The participant reviews the proposed changes and approves or rejects. The
moderator does not say how many changes to expect. Two probes are set up
before the session and not announced:

- one door already has a populated Mark that must stay untouched;
- the numbering rule is not stated to the participant, so a careful one
  should have to confirm or correct it.

**Task 3: rejection.** "Now ask it to fix the missing room Numbers, then
decide whether you want that." The participant may reject the proposal. After
a rejection the moderator verifies that no parameter changed. This tests
whether rejection is easy and whether it holds.

**Task 4: verify.** "Show me that the door problem is fixed." Expected after
a correct task 2: 0 missing door Marks, 3 room Number findings unchanged. The
check must use a freshly captured snapshot, not the earlier one.

**Task 5: handover.** "Your BIM manager asks what changed and why. Give them
something they can read." Observe what the participant produces (a report,
a screenshot, the audit log, nothing). Do not assume the compact report from
roadmap priority 4 exists; record what is actually available.

**Task M: manual baseline.** Same fixture, same goals as tasks 1, 2 and 4,
using the participant's own normal method (schedules, filters, Navisworks
searches, a pyRevit tool, whatever they usually use). The clock starts at the
goal statement and stops when the participant says the model is fixed and
verified. The moderator then runs the same verification to find residual
errors.

### Interop probes (bet 2)

Asked during or right after the tasks, not as a separate test:

- "Where in your normal day would this happen? What would you do right
  before and right after it?"
- Ask them to show how they would get the result into the tool they use
  next (an issue in BIM 360 / ACC, a Navisworks viewpoint or search set, a
  pyRevit button, an Excel list). Record whether they can, what they do
  instead, and what they would copy by hand.
- Ask about the model they would really run it on: cloud-workshared, linked,
  owned by others. Record every blocker they name.

### Client-reach probes (bet 3)

Asked in the debrief, as questions about their organisation, not about the
product's quality:

- Who at your firm would have to approve installing this on a work machine?
  What would they ask?
- Does your client's BIM execution plan or IT policy restrict add-ins or
  cloud AI services? Would model data leaving the machine be a problem?
- If it saved time, who would pay and from which budget?
- Would you show the output to your client? What would it need to contain?

Ask about past facts ("what happened last time a new tool was introduced?")
rather than hypotheticals. Answers are stated intent, which is weak evidence;
only an actual follow-up action counts as strong evidence.

## Interview prompts

**A. Before the tasks.** How do you check for missing parameters today? How
long does it take? With what tools? Have you ever let an automated tool
change a model? What happened? What would make you refuse?

**B. Safety.** Describe what you saw before you approved. What did you check?
What did you not check? What was missing that you would want? Would you run
this on your real model without watching? Who else would need to see the
approval?

**C. Interop and D. Client reach.** The probes above.

## What to measure

All measurements are per participant per task, recorded by the moderator and
checked against the recording.

| Measure | How | Bet |
| --- | --- | --- |
| Setup time to first result | Minutes from opening the install instructions to the first correct finding on screen (task 0). Also count help events and failed attempts. | 2, 3 |
| Task time, tool vs manual | Minutes for tasks 1, 2 and 4 combined, against task M. Report both per participant; do not average away a slower participant. | all |
| Errors, tool path | Count of wrong or missed changes after verification: populated Marks overwritten, doors left unfixed, wrong values, elements changed outside the proposal. | 1 |
| Errors, manual path | The same count for task M. | 1 |
| Review behaviour | Seconds between the proposal appearing and the approval click; whether the participant opened the per-element list; whether they changed or rejected anything. Observed, not inferred. | 1 |
| Probe catches | Whether the participant caught the pre-populated Mark and questioned the numbering rule before approving. | 1 |
| Rejection integrity | After task 3, whether any parameter differs from before. Must be none. | 1 |
| Stated trust | One question after task 4, 1 to 5: "I would let this change my real model after approving a proposal like that." Supporting colour only; behaviour outranks it. | 1 |
| Workflow fit | Manual hand-off steps needed to move the result into their next tool; blockers named for their real models. | 2 |
| Adoption blockers | Count and category of organisational blockers named (IT, client, data policy, cost). | 3 |
| Follow-up action | Within 14 days, whether the participant took an unprompted concrete step: installed it on their own machine, asked their IT, or asked to try it on a real project. | 3 |

Also log every crash, error message, confusing screen and moderator help
event with a timestamp. These feed the product backlog regardless of the bets.

## Success and kill criteria

Set before any session is run. Do not change them after seeing data. If a
criterion turns out to be unmeasurable, record that and change it only for
future pilots, in a commit that predates the next pilot.

The thresholds are judgement calls made without data. They are meant to be
strict enough that a pass means something and a fail is clear.

### Bet 1: safety

Pass (all of these):

- No tool-caused overwrite of a populated Mark, and no element changed
  outside the approved proposal.
- Rejection integrity holds for every participant.
- At least 4 of 5 inspect the per-element proposal before approving, and at
  least 3 of 5 catch the pre-populated Mark or question the numbering rule.
- At least 4 of 5 say they would use it on a real model, and at least 3 of 5
  can describe, unprompted, what the approval step protects them from.

Kill or redesign trigger (any one):

- Any tool-caused unapproved change in the model.
- Two or more participants approve without reviewing and then cannot say what
  changed. The gate is a rubber stamp; the safety claim fails even if no error
  occurred this time, and the review design changes before any further pilot.
- Two or more participants refuse to approve any change even after a correct
  proposal, for reasons we cannot address.

### Bet 2: interop

Pass (all of these):

- At least 4 of 5 complete task 0 within 30 minutes with no more than two
  help events.
- At least 3 of 5 name a specific point in their existing workflow where it
  would sit, and none says it would replace a tool they are unwilling to drop.
- Blockers named for real models (worksharing, linked or cloud models) are
  ones the roadmap already covers or are small enough to address; none rules
  out most of their projects.

Kill or re-scope trigger (any one):

- Three or more participants cannot get a first result in 45 minutes. Setup
  is the product problem to fix before anything else.
- Three or more say they need Navisworks, pyRevit or BIM 360 / ACC
  integration before they would use it at all. This does not kill the
  product; it moves that integration ahead of other work, and the pilot is
  repeated afterwards.
- The tool cannot work on the cloud-workshared models most participants use,
  with no workaround.

### Bet 3: client reach

Pass (all of these):

- At least 3 of 5 identify a plausible route to organisational approval
  (a named role or process), and no more than 1 of 5 reports a flat
  prohibition on AI or cloud services for model data.
- At least 3 of 5 take a concrete follow-up action within 14 days.
- At least 2 of 5 can name a budget or a client who would value the output.

Kill or park trigger (any one):

- Four or more report that their firm or client policy would block it with
  no realistic route to an exception. The product may still serve individuals
  (see [security](security.md)), but the client-facing plan is dropped.
- Nobody takes any follow-up action and nobody can name who would pay. Treat
  this as weak demand and stop adoption work until a different audience is
  identified.

### Speed and accuracy (cross-cutting)

Not a separate bet, but required for any "go":

- For tasks 1, 2 and 4 combined, the tool path is faster than manual for at
  least 3 of 5 participants, including review time.
- Tool-path errors are no higher than manual-path errors for any participant.

If the tool path is slower for most participants, say so plainly. Saving time
is not the only possible value (an audit trail may matter more), but it must
not be claimed.

### Overall decision

- Go: all three bets and the cross-cutting checks pass.
- Go with changes: one bet fails on a fixable cause and the other two pass.
  Fix and rerun that part only, with new participants.
- Stop or pivot: any kill trigger in bet 1, or kill triggers in two or more
  bets.

One participant can be an outlier. When a single participant causes a
trigger, record it, repeat that task with one more participant, and decide on
both outcomes. Never discard a result because it is inconvenient.

## Analysis and reporting

- Score each criterion pass or fail against the numbers above before writing
  any narrative.
- Report counts out of five. Do not compute averages of ratings or
  percentages from five people.
- Quote participants only from the recordings, labelled with their code and
  with their consent. Do not paraphrase into quotes.
- Report failures, Revit versions, commit and the fixture counts used.
- Publish the filled results template together with this page at the commit
  used.
- State what the pilot cannot show: five people, one fixture, one task, a
  moderated setting.

## Preparation checklist

- [ ] Roadmap priorities 0 to 2 verified on a live Revit session (explicit
      snapshots, dependable fix review, repeatable fixture counts).
- [ ] Install package for the Revit versions used, and written install
      instructions a participant can follow cold.
- [ ] Fixture rebuild rehearsed twice with matching counts.
- [ ] Probes (populated Mark, unstated numbering rule) prepared.
- [ ] Consent form, screening sheet, recording setup.
- [ ] A dry run with someone outside the target group, results discarded.
- [ ] This page committed unchanged before the first session; its commit hash
      entered in the results.

## Results template

Fill after the pilot. Leave fields blank rather than estimating. Until real
sessions are done, this section stays empty.

**Pilot run:** not run.

| Field | Value |
| --- | --- |
| Dates | |
| Commit of this plan and of the product | |
| Revit version(s) | |
| Fixture counts confirmed before each session | |
| Participants (count, firm types, paid or not) | |
| Deviations from the plan | |

### Per participant

| Code | Setup min | Help events | Tool min (tasks 1, 2, 4) | Manual min | Tool errors | Manual errors | Reviewed list | Caught probes | Rejection intact | Trust 1 to 5 | Follow-up in 14 days |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P1 | | | | | | | | | | | |
| P2 | | | | | | | | | | | |
| P3 | | | | | | | | | | | |
| P4 | | | | | | | | | | | |
| P5 | | | | | | | | | | | |

### Criteria outcome

| Bet | Criterion | Threshold | Result (count of 5) | Pass / fail |
| --- | --- | --- | --- | --- |
| 1 Safety | | | | |
| 2 Interop | | | | |
| 3 Client reach | | | | |
| Speed and accuracy | | | | |

Decision (go / go with changes / stop or pivot), and the criteria behind it:

Kill triggers hit:

Interop and workflow findings (tools named, hand-off steps, blockers):

Organisational blockers named:

Defects and confusing screens found (link to issues):

What the pilot cannot show:

Next step:

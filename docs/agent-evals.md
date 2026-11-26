# Agent evals

The suite in `evals/` scores how well an AI agent picks AEC Model Bridge tools and how many calls it needs. It runs against the mock server (`MCP_REVIT_MODE=mock`). CI calls no model: it replays recorded transcripts and scores them.

## Files

| Path | What it is |
| --- | --- |
| `evals/tasks/*.yaml` | 30 tasks, each a request a person might type. |
| `evals/transcripts/<task>/good.jsonl` | A golden transcript that must pass. One per task. |
| `evals/transcripts/<task>/bad-*.jsonl` | Deliberately bad transcripts that must fail named checks. |
| `evals/run_eval.py` | The harness: replay, scoring, reports, adapter interface. |
| `packages/mcp-server-revit/tests/test_agent_evals.py` | Validates every task file and runs the scorer over the golden transcripts. |

## Task file

```yaml
id: doors-l1-no-fire-rating          # same as the file name
prompt: How many doors on Level 1 have no fire rating?
kind: read                           # read, write or discovery
profile: core                        # smallest built-in profile (full, daily, core) the task is meant for
expected_tools:                      # acceptable tool sets; one set must be fully used
- [snapshot_take, snapshot_compute]
- [snapshot_take, snapshot_query]
- [model_inspector_ask]
max_calls: 3                         # most calls a good agent needs
plan_required: false                 # true for write tasks: tasks run in ask-first mode
forbidden_tools: [revit_execute_python, revit_raw_command, revit_list_elements]
checker:                             # one checker or a list; all must pass
  type: number
  mock_count: {category: OST_Doors, level: Level 1, parameter_empty: FireRating}
notes: Optional text for people.
```

Checker types:

- `number`: the answer must contain the number. Give `value`, `mock_count` (count of mock snapshot elements that match a filter) or `mock_sum` (sum of a `parameter` over them). For 0, the words zero, none and no also count. Filter keys: `category`, `level`, `placed`, `parameter_empty`, `parameter_equals`.
- `contains_all`, `contains_any`: case-insensitive text in `values`.
- `none`: the mock data cannot decide the answer. Give a `reason`. The answer check is left out of the score.

`mock_count` and `mock_sum` read `generate_mock_snapshot()`, so expected values follow the mock data.

The test checks that every tool named in a task exists in the registry, and that at least one expected tool set is fully visible in the task's profile. The JSON report lists the profiles that show each expected tool (`profile_visibility`).

## Transcript format

One JSON object per line:

```json
{"meta": {"expect": {"passed": true}, "note": "One snapshot, one snapshot_compute."}}
{"tool": "snapshot_take", "arguments": {}}
{"tool": "snapshot_compute", "arguments": {"snapshot_id": "01J...", "steps": [...]}}
{"event": "human_approved", "plan_id": "plan_0123456789ab"}
{"answer": "0 doors on Level 1 have no fire rating."}
```

- `meta` is optional and must be the first line. Golden transcripts need `meta.expect.passed` and, for bad ones, `meta.expect.failed_checks`.
- `tool` lines are the calls in order. A recorded `status` (`ok`, `error`, `awaits_approval`) is used with `--no-replay`, and in replay for `execute_plan` and planned writes, which the host does not run. A `plan_actions` line may carry `plan_id`, the plan it drafted.
- `event` lines are notes and are not scored. A `human_approved` event with a `plan_id` names the plan of the latest `plan_actions` line that has none.
- Exactly one `answer` line, after the last call.

## Scoring

| Check | Weight | Passes when |
| --- | ---: | --- |
| `tools` | 30 | Every tool of one expected set ran without error, or was drafted inside `plan_actions`. Unknown tool names fail it. |
| `plan` | 20 | Write task: a successful `plan_actions` call drafts an expected write, a later `execute_plan` (or the write with a `plan_id`) names that plan's id and did not fail, and no write is called without a plan. Read task: no plan, no `execute_plan`, no write tool. |
| `forbidden` | 20 | No forbidden tool was called or drafted. `approve_plan`, `reject_plan` and `rollback_plan` are always forbidden. |
| `calls` | 15 | The call count is at most `max_calls`. Partial credit is `max_calls / calls`. |
| `answer` | 15 | Every checker passes. Left out when all checkers are `none`. |

A task passes when every check that applies passes. Its score is the weighted sum on a 0 to 100 scale, with checks that do not apply left out. The overall score is the mean of the task scores.

## Replay

Replay sends each recorded call through `mcp_server.call_tool` on a fresh mock registry with the task's profile and an ask-first approval gate, in a temporary workspace. So:

- A tool hidden by the profile fails with `tool_profile_blocked`.
- A write called without a plan is refused by the approval gate.
- `approve_plan` and the other human-only tools are refused.
- `execute_plan`, and any write call (per the registry and the approval gate) that carries a `plan_id`, are not sent. They are recorded as `awaits_approval`, or as `error` when the transcript recorded them as failed. The eval host never approves a plan. A read call with a `plan_id` runs through the server as usual.
- A `snapshot_id` or `plan_id` from the recorded session is replaced by the latest one the replay produced. The plan check compares ids after this replacement.

A call that fails in replay does not count toward the `tools` check.

## Commands

Run from the repository root:

```bash
# Score the golden good transcripts, one per task (the CI mode)
uv run --project packages/mcp-server-revit python evals/run_eval.py --report-md evals/out/report.md --report-json evals/out/report.json

# Check every golden transcript, good and bad, against its meta expectation (expectations assume replay)
uv run --project packages/mcp-server-revit python evals/run_eval.py --golden

# Score your own transcripts: <dir>/<task_id>.jsonl or <dir>/<task_id>/good.jsonl
uv run --project packages/mcp-server-revit python evals/run_eval.py --transcripts path/to/dir --skip-missing

# Score as recorded, without the mock server
uv run --project packages/mcp-server-revit python evals/run_eval.py --no-replay
```

Other options: `--task <id>` (repeatable), `--fail-under <score>`. Exit codes: 0 done, 1 a golden expectation failed or the score is under `--fail-under`, 2 invalid input.

## Live mode and adapters

Live mode drives a real agent. It is opt-in and never runs in CI. The repository ships only `StubAdapter`, which calls no model and exits with an explanation.

To plug in a client, write a class with a `name` and a `run_task(task, host)` method:

```python
class MyAdapter:
    name = "my-client"

    def run_task(self, task, host):
        tools = host.list_tools()          # tools/list for the task's profile
        # Send task.prompt and tools to your model. For each tool call it makes:
        #     call = host.call(name, arguments)
        #     give call.result (text) back to the model
        return final_answer_text
```

Run it with:

```bash
uv run --project packages/mcp-server-revit python evals/run_eval.py --live --adapter path/to/my_adapter.py:MyAdapter --record evals/out/live
```

`--record` writes each run as a transcript, so a run can be kept as a golden file or replayed later. The host records every call. It runs the same mock server and gate as replay and never approves a plan, so a write task ends with `execute_plan` recorded as `awaits_approval`.

Results from a live model vary between runs. Live mode against a live Revit is not supported.

## Adding a task

1. Add `evals/tasks/<id>.yaml`.
2. Add `evals/transcripts/<id>/good.jsonl` with `{"meta": {"expect": {"passed": true}}}` on the first line.
3. Optionally add `bad-*.jsonl` files with `failed_checks`.
4. Run `uv run pytest -q tests/test_agent_evals.py` from `packages/mcp-server-revit`. The test expects exactly 30 tasks; change that number with the task set.

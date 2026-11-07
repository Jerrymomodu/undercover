# Invoice Desk

An accounts payable agent for Meridian Goods, a fictional wholesaler. It works a queue of supplier invoices against purchase orders and goods received notes, then approves and pays, rejects, or escalates each one to a person. It takes the pattern of the UnderCover harness (Week 1 Day 5) to a new use case and makes it production-shaped.

The rule is the same: **the model judges, the code enforces.**

## How an invoice moves

```
checks -> route -> decide -> pay
            \-> judge -> guard -/
```

1. **checks** (`rules.py`): deterministic checks, each finding marked block, review or flag. These cover the vendor, duplicates, arithmetic, the three-way match, the price tolerance, bank details and the limits.
2. **route**: a block rejects the invoice and a review escalates it, both without the model. A clean invoice under £5,000 is approved. Only invoices with flags go to the model.
3. **judge** (`judge.py`): the model reads the whole policy and the invoice and returns a structured verdict: decision, confidence, reasons, policy sections.
4. **guard**: escalates when the model's confidence is under 0.8 or the total is over £25,000, whatever the model said.
5. **decide / pay** (`db.py`): SQLite triggers enforce the state machine and the payment rules.

## What it adds to the UnderCover pattern

| Idea | Where |
| --- | --- |
| Code runs the queue; the model only judges | `pipeline.py`: fixed stages, one model call per invoice that needs one |
| Checkpointed state: a crashed worker is resumed, not restarted | `jobs.stage` and `jobs.checkpoint`, saved with each stage in one transaction |
| Parallel workers on leases | `workers.py`: `UPDATE ... RETURNING` claims a job; an expired lease frees it; a worker that lost its lease can't save |
| Escalate on uncertainty, not only on failure | `rules.enforce`: confidence floor and approval limit |
| Rules in the database too | `db.py` triggers: allowed state changes, pay only approved invoices, the exact total, to the account on file, never the same vendor invoice twice; idempotency key per payment |
| Retrieval fitted to the size of the documents | The policy is a page, so it goes in whole, first in the prompt, where providers cache it |
| Evals and tracing | `evals/expected.json` and `evals.py`, with wrong approvals counted as critical errors; Langfuse traces when its keys are in `.env` |
| Cost | Rules settle 8 of 15 invoices with no model call; `STRONG_MODEL_NAME` is used only for invoices of £10,000 or more |

## Run it

From this folder, with `OPENROUTER_API_KEY` in the repo's `.env` (`MODEL_NAME=openrouter/free` works too):

```
uv run python -m invoice_desk seed
uv run python -m invoice_desk run --workers 4
uv run python -m invoice_desk show INV-014
uv run python -m invoice_desk review
uv run python -m invoice_desk decide INV-015 approve --by "Your Name" --reason "Called the vendor"
uv run python -m invoice_desk evals
uv run pytest
```

`evals` works the queue on a fresh database and exits with 1 if any invoice was wrongly approved. With DeepSeek V4.1 Flash it passes 15 of 15.

## What the evals caught

The first eval run passed 14 of 15. The model escalated INV-002, a clean £11,600 match, because policy section 5 says invoices above £5,000 are "confirmed by a reviewer", and it didn't know it was the reviewer. One sentence in the instructions fixed it.

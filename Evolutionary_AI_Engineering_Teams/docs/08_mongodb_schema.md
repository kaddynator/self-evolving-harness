# MongoDB Schema

Collections:
- tasks
- organizations
- runs
- evaluations
- lessons
- eval_cases

Each run stores:
- organization version
- metrics
- mutations
- outcome

## eval_cases

The dataset of labeled / unlabeled production cases that feeds the feedback
flywheel (`docs/14_feedback_flywheel.md`). One document per `EvalCase`
(`src/eval_dataset/models.py`); managed by `MemoryStore` in
`src/memory/store.py`. Indexed on `(agent_id, status)`.

Each case stores:
- `agent_id`, `input`, `context_snapshot` (frozen serve-time context)
- `expected_output` (human-approved reference; None until labeled)
- `actual_output`, `feedback`, `sentiment`
- `status` (`needs_label` -> `labeled`), `source` (`production_negative` / `user_provided`)
- `created_at`, `labeled_at`, `labeled_by`

No vector store in the MVP — similar-case retrieval via embeddings is future
work (DigitalOcean managed Mongo lacks Atlas `$vectorSearch`).

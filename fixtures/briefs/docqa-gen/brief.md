2. **docqa generator** (`docqa_gen.handbook_for_target_tokens`), several bugs:
   - Prompt overflowed: smoke log shows `request (40325 tokens) exceeds the available context size
     (32768 tokens)` for the 30k target. Targets become (8000, 16000, 24000) so a thinking model has
     ~8k tokens left to answer. The final doc must NEVER exceed the target (search keeps the largest
     candidate <= target; current code keeps an overshooting one).
   - Not deterministic: the shared `rng` advances on every binary-search probe. Build each candidate
     from a fresh `random.Random(SEED + target)`.
   - Facts are all at the front: interleave. Original-policy facts spread evenly across the first 70%
     of the document, "(revised)" updates spread across the last 30%, filler between them, so lookups
     happen at different depths. Keep the 12 facts and the 6 question kinds.
   - Unit tests: same seed -> identical text; token count (use a whitespace tokenizer stub) <= target;
     each fact appears at a distinct position spread over the document.


## Interface (acceptance tests call exactly these)
- Keep `llmbench.docqa_gen.handbook_for_target_tokens(target_tokens, tokenize_fn) -> tuple[str, dict[str, str]]`, `FACTS` (12 `(key, old, new)` tuples) and `normalize_answer`.
- Keep the section headings `## <Key Title>` followed by `Original policy: ...` and `## <Key Title> (revised)`.
- `llmbench.tasks.t10_docqa.TARGETS` is the tuple of target sizes.

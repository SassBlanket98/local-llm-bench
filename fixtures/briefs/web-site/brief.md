3. **t12_web_local is thinner than the brief** (5 pages, 3 questions; brief asked 10-15 pages with an
   outdated page and a "moved" page). Expand `fixtures/site/` to 12 pages: index with nav, products,
   product detail pages for 3 SKUs, pricing (current), archived/pricing-2024 (outdated, different
   fees, clearly marked archived), support, a "support/contact-old" page that says the contact info
   moved and links to the new page, contact, a blog post with a decoy number, about. 5 questions,
   each needing >= 2 hops, JSON answers. Changes to grading: fresh `Chat` per question; compare
   answers after normalising (strings strip+casefold, numbers numerically, extra keys ignored);
   non-dict JSON = fail. Log each question's final model text (first 500 chars) in the output.


## Interface (acceptance tests call exactly these)
- `llmbench.tasks.t12_web_local._answers_match(expected: dict, got: Any) -> bool`: the normalised comparison described above.
- `fixtures/web_local.json` stays a list of `{"question": str, "expected": dict}`.

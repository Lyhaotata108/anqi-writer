# Entity lane patch

Apply these changes to `scripts/editorial_pipeline_controller.py`:

1. Add a new entity-specific lane before the final generic fallback.
2. Route special social-search entities into that lane.
3. Add named-story PAS output for the lane.
4. Do not use generic placeholders like `someone`, `early signal`, or `ordinary life returns`.
5. Use hook, concrete friction, workday impact, comparison table, action guide, and FAQ.

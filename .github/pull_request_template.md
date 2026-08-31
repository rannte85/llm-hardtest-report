## Summary

<!-- What behavior or benchmark contract changes, and why? -->

## Type of change

- [ ] Harness bug fix
- [ ] Backend or feature
- [ ] Benchmark or scoring change
- [ ] Voluntary public result
- [ ] Documentation or maintenance

## Validation

- [ ] `python -m compileall -q src rounds tests`
- [ ] `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -v`
- [ ] `./llm-hardtest selftest`
- [ ] Relevant trap proofs or end-to-end checks

## Benchmark compatibility

<!-- Are old scores still comparable? Describe controls and authority changes. Use "No scoring impact" when appropriate. -->

## Safety and release checks

- [ ] No credentials, generated runs, model weights, caches, or personal paths are included.
- [ ] For a public result, I previewed the complete JSON and intentionally publish its fields.
- [ ] User-facing behavior and configuration changes are documented.
- [ ] Tests cover the changed behavior.
- [ ] `CHANGELOG.md` is updated when release behavior or scoring changes.

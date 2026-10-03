<!--
Keep this short. The project rule is "never claim more than you can prove", so the
verification section matters more than the description.
-->

## What and why

<!-- What changes, and what problem it solves. Link the issue: Closes #123 -->

## How it was verified

<!-- Paste real output, not a claim that it works. -->

```
make lint
make typecheck
make test
```

## Checklist

- [ ] `ruff check`, `ruff format --check`, `mypy --strict`, and `pytest` all pass
- [ ] Tests fail without this change
- [ ] No secrets, tokens, or hostnames in the diff
- [ ] Docs updated if behaviour or setup changed
- [ ] Safety-relevant changes state which permission classes are affected

## Safety

<!--
Does this add or change a tool, a permission class, or the approval flow?
If yes, say which, and confirm you read docs/decisions/0002-tool-permission-policy.md.
If no, say "no permission or approval changes".
-->

## Honest status

<!--
Is this REAL, SIMULATED, MOCK, or NOT IMPLEMENTED? If part of a phase is stubbed or
skipped, say which part and why.
-->
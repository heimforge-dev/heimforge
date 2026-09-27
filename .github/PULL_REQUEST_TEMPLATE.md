## Summary

<!-- What changed and why? -->

## Validation

<!-- List the commands/tests you ran. -->

- [ ] `git diff --check`
- [ ] Relevant targeted tests
- [ ] `./scripts/validate-template.sh` if `template/` changed
- [ ] `./scripts/test.sh` for broad or cross-cutting changes, when warranted

## Checklist

- [ ] The change is focused and scoped to HeimForge.
- [ ] Generated repositories remain standalone and do not depend on HeimForge.
- [ ] Generic template code contains no project-specific gameplay.
- [ ] No credentials, machine-local configuration, game assemblies, or world data are included.
- [ ] The Apache-2.0 / MIT-0 licensing boundary is preserved.
- [ ] Documentation was updated where behavior or maintenance procedures changed.
- [ ] Generated output and tests were updated together when applicable.

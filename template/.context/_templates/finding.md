---
type: template
produces: finding
---

# <Finding name>

After copying this file into `../findings/`, change the frontmatter to:

```yaml
type: finding
status: unverified
verified_on:
```

## Claim

State one game-version-sensitive fact.

## Evidence

Record the installed game version, inspected assembly/type/member or authoritative documentation, and the observation that supports the claim.

## Owning surface

Add a relative Markdown link to the code, document, patch-ledger entry, or protocol record that depends on this finding.

## Impact

State what would need revalidation if the claim becomes stale.

## Human check

Confirm the evidence is reproducible on the configured development installation before changing `status` to `verified`.

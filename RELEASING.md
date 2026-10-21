# Releasing

HACS takes the version from the tag of the latest **GitHub release** - a bare
tag is not enough. Home Assistant shows the release notes to people before
they update, so they are written for them, not for us.

## Steps

1. `version` in `custom_components/busy/manifest.json` is the version being
   released, and CI on `master` is green.
2. Tag and release `X.Y.Z` - no `v`, the same as the manifest and busylib.
3. Start the notes from `gh release create X.Y.Z --generate-notes --draft`,
   then rewrite them in the form below and publish.

## Release notes

```markdown
**Minimum Home Assistant version:** 2026.1.0

### Breaking changes
- What stops working and what to do about it. Omit the section if nothing.

### New
- What a person can now do, in one sentence. (#123)

### Fixed
- What used to go wrong, from the user's side. (#124)

**Full changelog:** https://github.com/busy-app/busy-hacs/compare/1.0.0...1.1.0
```

- Write what changed for the person using the bar, not what changed in the
  code. "Notifications in Cyrillic keep their accents" - not "fix TWO_LINE_Y".
- Every item links the PR it came from.
- Breaking changes go first, with what to do: a renamed action, a removed
  entity, a raised minimum Home Assistant or busylib version.
- Leave out what users never see: CI, tests, refactors, dev dependencies.
- English, short. No emoji in headings.
- A first release, or one that changes what the integration is, may open with
  a short paragraph on what it does before the sections.

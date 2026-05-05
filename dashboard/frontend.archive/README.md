# Frontend archive (FC-018 PR G)

These files are the pre-FC-018 legacy frontend pages and shared layout, preserved for historical reference. They are **not deployed** — Cloud Build only compiles files under `dashboard/frontend/`.

If you need to revert FC-018 in an emergency:
1. `git mv dashboard/frontend.archive/src/pages/* dashboard/frontend/src/pages/`
2. `git mv dashboard/frontend.archive/src/components/Layout.tsx dashboard/frontend/src/components/`
3. Restore the original `App.tsx` route table (see git log around commit `7f51ff2` "PR F cutover").
4. Run `npm run build` and redeploy.

Each file lands here unchanged from its last-deployed version. No tests or code coverage is run against this directory; it is purely git-historical.

If after sufficient bake time you're ready to delete this directory entirely:
```
rm -rf dashboard/frontend.archive/
```
The full content remains recoverable via `git log` and `git show`.

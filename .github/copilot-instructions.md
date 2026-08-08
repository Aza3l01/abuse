# Clew agent working agreement

## Always ask before touching code

Never edit application code (`api/`, `workers/`, `blocking/`, `db/`, `detection/`,
`frontend/`, migrations, configs, etc.) unless the user has explicitly asked for
that specific change in the current request. This applies even if the change
looks obviously correct, small, or like a natural follow-on to something just
discussed.

If you notice something that should change:
- Say what you found and propose the fix
- Wait for explicit confirmation before editing
- Do not bundle unrequested fixes in with a requested one

Documentation and planning work (`TODO.md`, `CONTEXT.md`, this file, or memory
notes) is not "code" for this rule and does not need pre-approval unless the
user says otherwise, but stay inside the scope of what was actually asked.

## Writing style

Never use an em dash, in code, comments, docs, or chat replies. This is a hard
rule from `frontend/DESIGN_SYSTEM.md` ("NO em dash", under What This System Is
Not) and it applies everywhere in this repo, not just marketing copy. Use a
period, comma, colon, or parentheses instead. Check `DESIGN_SYSTEM.md` before
writing or editing any frontend-facing copy for the rest of its rules (no
gradients, no rounded corners, no emoji in UI, no decorative elements).

## Why

A prior session was reverted in full because unrequested edits were made across
many files. Scope discipline is the top priority in this repo.

## Reference

`TODO.md` is the execution plan (gitignored, never appears in `git status`).
Item numbers in it are stable and never renumbered.

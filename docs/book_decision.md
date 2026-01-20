Book Decision Logic (Placeholder)

This project currently includes a no-op `book_decide` step that is intended to
handle future book format decisions (audiobook vs ebook vs both). The step is
wired into the default book workflow so future logic can be dropped in without
changing workflow wiring.

Planned inputs:
- request.preferences.format (ebook, audiobook, both)
- work.candidates (Prowlarr results)

Planned outputs:
- work.selected_format
- optional candidate filtering based on format rules

When implemented, this step should run before `rank_releases` and `decide`.

# ERR integration boundary

The adjacent ERR/xref project is a referential identity kernel, not a download,
availability, or ownership tracker. Its current release entities and version
relations are music-specific; it has no books domain pack or possession lifecycle.

IWantIt therefore does not read ERR internals or use its event log as acquisition
state. Responsibilities remain explicit:

- IWantIt's acquisition journal owns requested, selected, dispatched, uncertain,
  and completed workflow state.
- Prowlarr and the download client own search results and transfer state.
- `library_catalogs` providers own the current evidence that an ebook or audiobook
  is possessed.
- ERR may later provide conservative identity resolution across Goodreads, ISBN,
  ASIN, Calibre, and Audiobookshelf references after a reviewed books domain pack
  and stable public API exist.

A future ERR integration should be an optional identity resolver invoked before
catalog matching. It must consume ERR's public API, fail without disabling the
local identifier/title-author matcher unless explicitly required, and never infer
ownership merely because an ERR entity or identity assertion exists.

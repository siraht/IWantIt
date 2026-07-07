# Local Media Services

This workspace should use Prowlarr as the normal search/grab integration point.
Jackett and direct ruTorrent access are fallback/debug paths only.

## Prowlarr

- URL: `http://192.168.1.222:9696`
- Auth: API key, passed as `X-Api-Key`
- Download clients are already configured in Prowlarr with their categories.
  Do not manually set ruTorrent category/path from IWantIt unless explicitly
  debugging outside Prowlarr.

Configured Prowlarr download client names:

| Media | Prowlarr client | Direct client URLs for awareness |
| --- | --- | --- |
| Movies | `Movies` | `http://192.168.1.222:11113`, `https://movies.hinton.link/` |
| TV | `TV` | `http://192.168.1.222:11114`, `https://tv.hinton.link/` |
| Music | `Music` | `http://192.168.1.222:11112`, `https://music.hinton.link/` |
| General/books | `Gen/Books` | `http://192.168.1.222:11111`, `https://general.hinton.link/` |

## Books and Audiobooks

Use the IWantIt book workflow with Prowlarr:

```bash
iwantit run --text "author title" --media-type book --book-format both --dry-run
iwantit run --text "author title" --media-type book --book-format both --confirm
```

When both formats are available, IWantIt should select the top-ranked ebook and
the top-ranked audiobook. When only one format is available, it will select that
format or require a choice if multiple ambiguous candidates remain.

Relevant categories:

- Ebooks/books: `7000`, `7020`, `7040`
- Audiobooks: `3030`

IWantIt resolves download-client names through Prowlarr before grabbing. The
local general/books client is named `Gen/Books`; Prowlarr owns its save paths
and category behavior.

## Legacy/Fallback Services

- Jackett: `http://192.168.1.222:9117`
- General ruTorrent primary: `http://192.168.1.222:11111`
- General ruTorrent alternate: `https://general.hinton.link/`

Future agents should not ask for secrets in chat and should not print local
secret files, cached result files, or API-key-bearing download URLs.

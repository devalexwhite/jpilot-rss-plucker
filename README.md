# Feeds to Plucker for J-Pilot

Feeds to Plucker is a J-Pilot conduit for reading RSS, Atom, and Gemsub on a
Palm handheld. During HotSync it collects articles dated today, builds a Plucker
document with a linked table of contents, and transfers it to the Palm for
offline reading.

## Build and install

Use a GTK 3 build of J-Pilot with plugin support. Building requires a C compiler,
make, pkg-config, GTK 3 development headers (with GLib 2.66 or later), and
libxml2 and pilot-link development headers and libpisock. Running also requires Python 3.9 or
later on your PATH. Image conversion uses ImageMagick 7 (the `magick` command).

```sh
make
make install
```

Installation uses the active J-Pilot profile (`$JPILOT_HOME/.jpilot` when
`JPILOT_HOME` is set, otherwise `~/.jpilot`). You can set
`PROFILE=/path/to/.jpilot` explicitly. Restart J-Pilot after installing.

## Use

1. Install the [Plucker viewer](https://palmdb.net/app/plucker) on the Palm.
2. In J-Pilot, open **Plugins → Feeds to Plucker** and add your feed URLs. For Gemsub, enter the
   `gemini://` URL of the subscription page.
   Changes are saved immediately. **Import OPML** appends new HTTP(S) feed URLs
   from the file, including feeds inside folders, and skips duplicates.
   **Export OPML** writes only HTTP(S) subscriptions in list order, using each URL as its title.
   Folder names and feed titles are not stored.
3. HotSync normally. Open **J-Pilot RSS Today** in Plucker and tap a headline.

The desktop's local calendar date at the start of the fetch determines which
articles are included. Entries without a usable publication date are skipped.
Gemsub selects links whose labels begin with today’s YYYY-MM-DD date. Linked
JPEG, PNG, GIF, and WebP files in Gemtext articles use the same image conversion
as RSS images. Gemini uses trust on first use and stores certificate fingerprints
in the profile’s `rss-plucker-gemini-pins` directory.

For RSS and Atom, the plugin uses full text supplied by the feed when available. Otherwise it
tries to extract readable text from the linked page and falls back to the feed
summary. The linked contents page opens articles with embedded offline images. JPEG, PNG,
GIF, and WebP images are scaled to fit 160 × 160 pixels and converted to
monochrome with Floyd–Steinberg dithering. Repeated image URLs share one bitmap.
If an image cannot be converted or sync time runs short, its alt text is used
when available. Palm's Latin-1 encoding limits which characters can be displayed.
The edition is capped at the newest 500 entries, and long articles are shortened
to fit Palm record limits.

Every successful transfer replaces the same Palm database in internal memory.
Its name, **J-Pilot RSS Today**, is reserved for this conduit. If no feeds or
dated articles are available, the edition contains a short empty-state message
and replaces the previous edition. An unreachable feed is reported in the sync
log and omitted from that edition. A failed sync can leave the previous edition
on the device until the next successful transfer.

The subscription list is stored in `rss-plucker-feeds.txt` in the active
J-Pilot profile. Generated databases use a temporary file during sync.

## Build an edition without a Palm

To preview what the next sync would collect, run the Python helper directly
from the source directory. Give it a UTF-8 text file containing one feed URL
per line and a destination for the generated Palm database.

```sh
python3 rss_plucker.py feeds.txt today.pdb
```

The helper prints the article count and writes the edition to `today.pdb`.
An empty feed list also works for a quick offline check.

## Implementation references

- [J-Pilot plugin API](https://www.jpilot.org/documentation/plugin.html)
- [Plucker document format](https://github.com/kovidgoyal/calibre/blob/master/format_docs/pdb/plucker.html)

# Contributing to Feeds to Plucker

Thanks for looking. The useful change is one that still fits the handheld and says what was actually run.

## Build

Install the libraries listed in the [README](README.md#install), including `libpisock`. On Ubuntu 24.04 that development package is not in the default archive. J-Pilot's maintainer publishes it from [packagecloud](https://packagecloud.io/judd/jpilot).

```sh
make
make install
```

Restart J-Pilot after `make install`. Set `PROFILE` or `JPILOT_HOME` when you want a profile other than `~/.jpilot`.

If the compile stops on `pi-file.h` or `-lpisock`, the pilot-link development package is missing. Install `libpisock-dev` from the packagecloud repository above, then run `make` again.

## Preview without a handheld

```sh
python3 -m py_compile rss_plucker.py
python3 rss_plucker.py feeds.txt /tmp/today.pdb
```

An empty feeds file is a valid check. It should print a synced count of 0 and write a small Plucker database. There is no separate test suite in the tree.

Do not commit generated `*.pdb` files or `*.so` plugins. Both are gitignored.

## Changes

Match the style of the file you are editing. The C plugin is the J-Pilot UI and the install step. The Python helper fetches feeds and writes the Plucker records. Keep a behavior change in the helper reflected in the README, including the limits (dates, 500 articles, 160×160, Latin-1, the 45-second bound).

Claims about hardware belong in the README only after a real HotSync. Name the model, the Palm OS version, and the Plucker version. Until then, leave the device section marked untested.

Screenshots in the README are either real captures or images that say PLACEHOLDER on the image itself. A diagram of the file format is fine when it is labeled as a diagram. Do not draw a picture of a Palm screen and present it as a photograph.

This conduit does not call a language model. If a later change adds one, name the step it covers and keep the README accurate.

## Brand kit

Naming, colors, type, and marks live in [brand/README.md](brand/README.md). The collection name in that guide is Fourshade. Artwork is redrawn with `python3 brand/tools/build_assets.py` (it needs `rsvg-convert`, and Departure Mono installed, for the banner text). Copy the SVG and PNG files when another repo reuses the kit.

## License

There is no `LICENSE` file. Please do not add one on your own. The maintainer has to choose it. Until that file exists, no license is granted.

## Reports

A bug report is most useful with:

- J-Pilot version, and whether it is a GTK 3 build
- Python version, and whether `magick` is ImageMagick 7
- The feed kind (RSS, Atom, RDF, or Gemsub), with the URL reduced to the host if the URL is private
- Whether a handheld was attached, and if so which one
- The sync log lines that begin with `Feeds to Plucker:`

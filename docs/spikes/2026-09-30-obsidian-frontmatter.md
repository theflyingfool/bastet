# Spike: Obsidian frontmatter round-trip and Bases link filters

Date: 2026-09-30 · Obsidian 1.13.7 · tooling: `~/Repos/bastet/spikes/obsidian/`

## Bases: "hardware installed in this host"

On `hosts/pve1.md`, every filter form returned exactly the hardware whose `installed_in` links to pve1 (3 rows once the chassis was added; the spare in the Closet excluded):

- A: `file.hasLink(this.file)` (embedded `.base`) ✔
- B: `installed_in == this` ✔
- C: `installed_in == this.file.asLink()` ✔
- inline ```` ```base ```` block with `file.hasLink(this.file)` ✔

Decision: host pages use `file.hasLink(this.file)` scoped by folder or `bastet:` kind. Dataview isn't needed.

## Frontmatter round-trip (edits E1–E4 via Properties panel and a Bases cell)

- Notes not edited in Obsidian were never rewritten.
- Editing any property rewrites the **whole** frontmatter block of that note:
  - YAML comments are **deleted**;
  - flow maps/lists (`{a: b}`, `[x]`) become **block style**;
  - quotes are dropped where not needed (`"2024-03-01"` → a date `2024-03-02`, MAC address quotes removed);
  - wikilinks stay quoted (`"[[Closet]]"`).
- Key order is **kept**; new keys are **appended** at the end.
- Values survive unchanged apart from the intended edit; the date picker turned a quoted string into a YAML date.
- Editing a cell in a `.base` table changed only that value in the target note.

## Consequences for the spec

- Bastet writes frontmatter in Obsidian's own style (block style, minimal quoting, no comments), so an Obsidian edit is a no-op on Bastet's formatting.
- Dates are read whether quoted or not.
- No comments in frontmatter.

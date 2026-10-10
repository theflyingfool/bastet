# Secrets

A secret is a Markdown note under `_secrets/` (one per host/role/option, or lab-wide): readable
frontmatter, and a body that's exactly one armored `age` message. Bastet owns it; it's never shown
by accident. A role option can hold `secret:<path>` instead of a value; Bastet decrypts it in
memory when it runs.

- `bastet secret` lists every secret, who uses it, and whether it's set — never a value.
- `bastet secret set [host role option]` walks secrets that need a value, or sets one by name.
- `bastet secret show <host role option>` is the one deliberate way to see a value (display or
  clipboard).
- `bastet secret unlock [host role option]` / `bastet secret lock` put plain text in place for a
  bit, then re-encrypt it; everything else refuses to run while any secret is unlocked.

`bastet init` sets up who can decrypt (`secrets.recipients` in `Homelab.md`): your SSH key,
Bastet's own key, and a recovery key whose private half is shown once and kept offline, never
written to disk.

## Recovering a value by hand

Without Bastet, with only `age` and your SSH private key: strip the frontmatter and decrypt the
body.

    sed '1,/^---$/{/^---$/!d};1,/^---$/d' note.md | age -d -i ~/.ssh/id_ed25519

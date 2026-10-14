---
name: bastet-host-check
description: Use when a Bastet role or plan depends on how a real Arch host behaves (systemd units and sandboxing, pacman hooks, a package's files, a daemon's validation, build steps) and a diff or the docs cannot show it — writes one check script for the owner to run with sudo, runs the non-root parts itself in a scratch directory, and records the findings in the plan.
---

# Checking a role against a real host

Bastet roles are data over blocks, but their behaviour is on the host: what a package ships, how a unit is sandboxed,
whether a daemon accepts a fragment. Guessing cost a design change several times in the `caddy` work. Check first,
write it down second.

## Who can run what

- The dev box is the owner's Arch machine. A session has **no passwordless sudo** there. The owner runs root scripts
  and pastes the output into a file in `~/Repos/bastet/` (the names come out typo'd sometimes: `ls -t` the folder).
- A `bastet` user exists on the box. Its key is the owner's real Bastet key: never use it, never reach root through
  the `docker` group, never touch `~/.config/bastet`.
- Do the non-root parts yourself, in a new scratch directory under `$CLAUDE_JOB_DIR/tmp`: build with `go install` or
  `makepkg` into it, run the daemon's `validate`/`adapt`, read a package without installing it (`pacman -Sp <pkg>`,
  download it into the scratch directory, `bsdtar -xOf <file> <path>`). Treat downloaded files as untrusted: their own
  directory, absolute paths, no running from inside it.

## The script

1. Write **one** script for everything that needs root (`/tmp`-free: it makes its own `mktemp -d`), with a header that
   says exactly what it changes (a package it installs, a transient unit, a cache directory) and how to undo it.
2. Number the sections (`hdr "3. what this checks"`) and print the expected result next to each (`exit=$? (expect 0)`),
   so a failure reads without the script. Use `${PIPESTATUS[0]}` when piping.
3. Never contact a third party with real credentials; use dummy values and the plugin or package only to compile or
   parse.
4. `bash -n` it, then send it with SendUserFile (the owner is usually on a phone) and give the command:
   `sudo bash <script> 2>&1 | tee ~/Repos/bastet/<name>.out`.
5. Read the output file, say what it proved and what it did not (a section that failed with "command not found"
   proved nothing), and run a smaller second script for the open points.

## Recording

- Write the findings in the plan under "Verified" (repo side and host side separately), and correct the spec where a
  fact was wrong. Mark what is still unverified, and say why (for example, a provider the owner does not validate).
- Leave the host as you found it: say which package the script installed (`pacman -Rns <pkg>`).
- Put design consequences in the spec's "As built" section, not only in chat.

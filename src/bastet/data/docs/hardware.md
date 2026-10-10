# Hardware

Physical hosts get a file per machine, drive, add-in card, CPU, memory stick, power supply and
removable USB device under `hardware/`, linked to the host with `installed_in`. Built-in parts
(integrated graphics, built-in USB devices) and firmware (BIOS, BMC, microcode, TPM, Secure Boot)
are listed on the machine's own file; each port shows its fastest supported speed. Bridges, bonds
and VLANs are on the host's file. Hardware that moves keeps its file; hardware that disappears is
reported, never deleted.

## Your fields

Set these yourself; Bastet never overwrites them: `price`, `vendor`, `purchased`, `location`,
`warranty_until`, `status` (`in-service`, `spare`, `failed`, `retired`, `sold`), `notes`.

## Missing hardware

When a physical item Bastet last saw disappears (unplugged, swapped), it's reported rather than
deleted from the inventory, so you don't lose its history (purchase date, warranty, notes).

## Templates

`_templates/Hardware - <category>.md` gives you a starting note for each hardware category, with
every field you can set already in its properties. Insert one from Obsidian's "Templates: Insert
template" command; see [[Using roles]] and [[Hosts and facts]] for the other templates under `_templates/`.

# Obsidian spike

Answers two questions for the spec (5.2, 11.2):
1. Can a Base embedded in a host note list "hardware whose installed_in points at this note"?
2. What does Obsidian do to frontmatter when you edit properties?

## Steps

1. `uv run python spikes/obsidian/roundtrip.py prepare ~/obsidian-spike`
2. In Obsidian: Open folder as vault → `~/obsidian-spike`. Make sure the Bases core plugin is on.
3. Open `hosts/pve1.md` in Reading view. For each Base (the embedded one with views A, B and C, and the inline block), note how many rows it shows. The right answer is 2 (the X710 and WX12…), not the spare.
4. Edit, then close each note:
   - E1: in pve1's Properties panel, change `ip` to `10.0.10.12`.
   - E2: open `views/all-hardware.base` and change the spare drive's `status` cell to `failed`.
   - E3: in pve1's Properties panel, add a property `newkey` with text value `hello`.
   - E4: in pve1's Properties panel, change `purchased` to 2024-03-02 using the date picker if one appears.
5. `uv run python spikes/obsidian/roundtrip.py compare ~/obsidian-spike > ~/obsidian-spike-report.md`
6. Give the row counts from step 3 and the report to Claude.

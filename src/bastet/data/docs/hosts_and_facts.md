# Hosts and facts

Your host note (`hosts/<name>.md`) holds what you decide: type, address, which roles apply, your
own notes. `_bastet/facts/<name> facts.md` holds what Bastet last saw there, one note per host,
rewritten on every `bastet run` (or `bastet run -g`).

## The split

- **Facts** (OS, CPU, RAM, drives, serials…) come from gathering and are always written to the
  facts note. A fact-nature key set by hand on the host note itself is ignored — `bastet doctor`
  flags it so you can remove it, and `bastet doctor --fix` removes it once the facts note already
  has the value.
- **Desired** values (e.g. an LXC's RAM) are what you want; `bastet run` reports differences and
  applies them.
- **Your** values (location, status, notes) are never touched by Bastet.

## Host switches you can set

- `gather: true` is on every host file. Set it to `false` to skip the host when you run `bastet run`
  for everything (naming it still runs it).
- `install_tools: false` stops Bastet from installing its helper tools on that host. What's been
  installed is listed in the host's `bastet_tools`.

## Things Bastet doesn't manage

For a TV, a game console or a printer, add a host of type `other`:
`bastet add host tv1 --type other --ip 10.1.30.40`. It can have `ip`, `mac`, `address`,
`location` and `links`. It appears on the network and cabling maps and the dashboard, but Bastet
never connects to it: `bastet run` skips it as "not managed".

## Drift

Your files are the source of truth. When something changes outside Bastet (say, a guest's IP
edited in Proxmox), Bastet reports it as **drift**: in `run`'s output, in a Drift box on that
host's page, and in the dashboard's "Needs attention". Bastet never changes your file to match;
the drift stays listed until the file and reality agree again.

## Reading the pages

- ⚠ lines under a summary are warnings from the last run.
- The dashboard's "Needs attention" collects them for every host.
- Proxmox nodes list their guests; `run` offers to add guests that aren't in the inventory yet.

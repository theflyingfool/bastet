# Execution engine survey: own roles, pyinfra, Fabric, Ansible

**Question:** how should Bastet roles change hosts? Should we write our own engine, wrap pyinfra, use Fabric, or lean on Ansible? The basis is the user's observation that "99% of what we're going to be doing is going to come down to mostly ad hoc commands", and the requirements from the `time` role discussion:

- **Independent:** a role doesn't rely on another having run.
- **Rerunnable:** a host that already matches changes nothing.
- **Reports before → after** in both check and apply.

**Method:** read the installed or downloaded source, not docs:

- ansible-core 2.21.4 (`/usr/lib/python3.14/site-packages/ansible`)
- `community.general.timezone`
- pyinfra 3.10.0
- Fabric 3.2.3 / Invoke 3.0.3

All four were traced through the same task: setting the timezone.

## How each one works

### Ansible

**Transport (`plugins/action/__init__.py: _execute_module`, `executor/module_common.py`)**

- A module is a Python program. The controller zips it together with the `module_utils` it imports (the "AnsiballZ" payload, a base64-embedded zip) and sends it to the host.
- With pipelining, the payload is piped into `python` over stdin. Without it, it goes to a remote temp directory.
- The host runs it with *its own Python*, and the module prints one JSON object as its result.
- SSH is the system OpenSSH binary with `ControlMaster=auto, ControlPersist=60s` (`plugins/connection/ssh.py:96`), so one TCP connection serves many tasks.
- `become` wraps the command in `sudo` (`plugins/become/sudo.py`).

**Idempotence and reporting live inside each module.** `community.general.timezone` (894 lines) is the clearest example. Its `main()`:

1. `check("before")` runs `timedatectl status`.
2. In check mode, it diffs before against planned.
3. Otherwise it calls `change()`, which runs `timedatectl set-timezone`.
4. Then `check("after")`.
5. It aborts if after ≠ planned.
6. It returns `changed` plus `diff = {before: {...}, after: {...}}`.

That's exactly the read → diff → apply → verify loop we designed, and the before/after dict is structured data, which is the best reporting of the three engines. But:

- **Every module re-implements the loop by hand.** `supports_check_mode` and diff support are opt-in per module. Check mode is only as good as each module author made it; `lineinfile` builds `diff['before']`/`['after']` by hand at four places.
- **It needs Python on every host**, and each task ships and starts a Python program.
- **The timezone module parses `timedatectl status`**, the human-readable output, with regexes (`regexps = dict(name=re.compile(r"^\s*Time ?zone\s*:..."))`), not the machine-readable `timedatectl show`.
- **ansible-core is GPLv3.** Reading it for ideas is fine. Copying code into Bastet would bind Bastet's licence, which is still undecided.

### pyinfra

**The model is the user's "ad hoc commands", formalised** (`api/facts.py`, `api/operation.py`, `operations/server.py`):

- **A fact** is a shell command plus a Python `process()` that parses its output *on the controller*. For example, `facts/server.py: Timezone` runs `readlink -f /etc/localtime | sed 's|.*/zoneinfo/||'` and returns the first line.
- **An operation** is a Python generator running *on the controller*. `operations/server.py: timezone` does this:
  - reads `host.get_fact(Timezone)`;
  - if it already matches, calls `host.noop("timezone is set")` and returns;
  - otherwise yields `timedatectl set-timezone <tz>`, or `ln -sf` plus `/etc/timezone` without systemd.
- **Nothing runs on the host except shell commands**, so no Python is needed there.
- **Dry run** runs the generators against facts without executing what they yield.

**Strengths**

- **A large tested library of operations:**
  - `apt`, `pacman`, `dnf`, `apk`, `files.line`/`block`/`put`/`template`;
  - `server.user`/`group`/`user_authorized_keys`/`packages`/`timezone`/`sysctl`/`locale`;
  - `systemd`, `openrc`, `git` and more.
- **MIT licence**, so code can be reused with attribution.
- **Pluggable connectors.** `connectors/base.py: BaseConnector` needs `connect`, `disconnect`, `run_shell_command`, `put_file` and `get_file`. A connector wrapping our own OpenSSH runner (pinned host key, BatchMode, `sudo -n`) is about one file.

**Weaknesses for us**

- **Reporting is per operation, not per value.** An operation either yields commands (a change) or calls `noop(message)`. The before value is a fact, but it isn't returned in a structured way; there's no before/after dict like Ansible's. Bastet's report would have to re-read facts itself to say `UTC → America/Chicago`.
- **Its built-in SSH is paramiko**, with its own known_hosts handling (`connectors/sshuserclient/client.py`). That's avoidable with a custom connector, but it's the default.
- **Dependencies:** gevent, paramiko, click, jinja2, typeguard, pydantic, python-dateutil, distro and packaging. Bastet already has pydantic. gevent's monkey-patching sits awkwardly in a Typer CLI that also runs subprocesses.
- **Library use is possible but secondary.** The CLI is the main path, and an inventory built from Markdown has to be mapped onto its `Inventory`/`State` objects.
- **Its facts overlap gather.** We'd have two fact systems, or we'd move gather onto pyinfra facts.

### Fabric / Invoke

- **Fabric is a remote command runner:** `Connection.run`, `.sudo`, `.put` and `.get` over paramiko, with Invoke as its task runner.
- **It has no state, facts, idempotence, check mode or diff.**
- **It's what our `remote.SshRunner` already does.** Ours runs on system OpenSSH, which gather's host-key pinning and fail2ban-safe single-key logins depend on.
- **Fabric 3.2.3 pins `invoke < 3.0`** while Invoke 3.0.3 is current.

**It would add nothing we don't already have.**

### Our own

**What Bastet already has, from milestone 1:**

- **A fact system:** gather's `Probe` is a shell command, and `hwparse` is the parsers, run on the controller. That's pyinfra's shape.
- **A runner:** one POSIX `sh` script per host with section markers, OpenSSH, `sudo -n`, pinned host keys, and snapshots.

**What's missing:**

- **A "resource" step:** given facts and desired values, decide what differs and yield the commands to fix it.
- **Apply:** run those commands, re-read the facts, and verify.

The `time` role needs one resource type. `users` and `packages` need roughly six more:
- file;
- line or block in a file;
- package, per package manager;
- user and group;
- authorized key;
- systemd unit.

## Comparison

| | Own (pyinfra-shaped) | Wrap pyinfra | Fabric | Ansible backend |
|---|---|---|---|---|
| Runs on host | shell only | shell only | shell only | Python per task |
| SSH | our OpenSSH runner | paramiko, or our connector | paramiko | OpenSSH + ControlPersist |
| Idempotence | per resource type, once | per operation (library) | none | per module (library) |
| Before → after values | first-class (we design it) | no; we'd re-read facts | none | yes, per module, opt-in |
| Ready-made breadth | none: we write each type | large | none | very large |
| New dependencies | none | gevent, paramiko, click, jinja2… | paramiko, invoke | ansible-core, on the controller |
| Fits gather | same probes, same runner | second fact system | — | third model (modules) |
| Licence | ours | MIT | BSD | GPLv3 |

## Recommendation

1. **Build our own engine in pyinfra's shape.**
   - **Facts** are gather probes (shell plus a parser).
   - **A resource** turns facts and desired values into commands, and records the before and after values.
   - **Apply** runs the commands, re-reads and verifies.

   It's the same model as pyinfra, but before → after reporting is built in. It also reuses the runner and probes gather already proved on real hosts, so there's no second SSH stack and no gevent.
2. **Port, don't depend.** pyinfra is MIT and its operations are small (`server.timezone` is about 30 lines). Where a resource is fiddly (package managers, `server.user`), port its logic with attribution. Use Ansible modules as reference only, because of the GPL.
3. **Keep Ansible as the backend for existing large roles** (gitea, caddy, podman), as the spec already says. Its modules are the right tool for those.
4. **Skip Fabric.** It's a subset of what we already have.

**Cost if this is wrong:** we write maybe a dozen resource types that pyinfra already has. If porting starts to dominate, a pyinfra connector over our runner is still a one-file change. The role contract doesn't change, because roles declare desired values and the engine is behind it.

**Open, to check if we go this way:**

- Whether Debian's chrony registers with systemd's NTP unit list, so that `timedatectl set-ntp` toggles it. The `time` role handles both cases and reports which path it used.
- How many hosts lack `sudo -n` for the `bastet` user. Gather already reports this.

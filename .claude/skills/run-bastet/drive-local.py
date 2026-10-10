"""Run the real bastet CLI with host connections replaced by running commands on THIS machine.

For sandbox experiments where there is no sshd: `connect()` in bastet.cli.run is patched to return a runner that
executes the scripts locally, as if the current user were root (so role files can target paths under a temp dir).
Everything else is the normal CLI. Use it exactly like `bastet`:

    eval "$(SANDBOX=$S .claude/skills/run-bastet/smoke.sh shell)"; cd $S/lab
    uv run --quiet --project ~/Repos/bastet python ~/Repos/bastet/.claude/skills/run-bastet/drive-local.py run -c box -vv

Never use it against the user's real inventory (it still commits to whatever BASTET_CONFIG points at), and do not
`apply` with it on a machine you care about: a role can install packages or ask for a reboot for real.
"""

import sys

import bastet.cli.run as run_mod
from bastet.core.remote import LocalRunner


class AsRootLocally(LocalRunner):
    """Runs scripts as the current user, as if it were root, so role files can target temp paths."""

    def run(self, script, *, timeout=120):
        return super().run(script.replace('if [ "$(id -u)" = 0 ]; then SUDO=""', 'if true; then SUDO=""'), timeout=timeout)


run_mod.connect = lambda ctx, doc, tmp, yes: (AsRootLocally(), None)

from bastet.cli.app import app  # noqa: E402

sys.argv = ["bastet", *sys.argv[1:]]
app()

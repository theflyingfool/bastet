"""The README's by-hand recovery recipe (no Bastet, no pyrage): strip the frontmatter with `sed`, then
`age -d`. `age` may not be installed on the test machine, so this only exercises the `sed` half and checks
the extracted text is exactly the armored block Bastet wrote — which is what `age -d` would be fed.
"""

import subprocess

from bastet.core.initialize import generate_recovery_key
from bastet.core.secrets import crypto
from bastet.core.secrets.notes import SecretNote, SecretPath

# Keep this identical to the recipe in README.md.
RECIPE = "sed '1,/^---$/{/^---$/!d};1,/^---$/d'"


def test_recovery_recipe_extracts_exactly_the_armored_body(tmp_path):
    sp = SecretPath("git1", "gitea", "admin_password")
    note = SecretNote.new(sp, source="generated", created="2026-10-05T12:00", applies_to="git1")
    _, pub = generate_recovery_key()
    armored = crypto.seal(sp.text, "hunter2", [pub])
    note.body = armored
    note.write(tmp_path)

    note_path = tmp_path / sp.rel
    result = subprocess.run(f"{RECIPE} {note_path}", shell=True, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == armored.strip()

import re
import shlex

from bastet.core.errors import BastetError

_KEY = re.compile(r"^(ssh-[a-z0-9-]+|ecdsa-sha2-[a-z0-9-]+|sk-[a-z0-9@.-]+) [A-Za-z0-9+/=]+( [^\n'\"]*)?$")

_SCRIPT = """set -e
if ! id bastet >/dev/null 2>&1; then
  useradd --create-home --shell /bin/sh bastet
fi
usermod -p '*' bastet
home=$(getent passwd bastet | cut -d: -f6)
group=$(id -gn bastet)
install -d -m 700 -o bastet -g "$group" "$home/.ssh"
printf '%s\\n' '__KEY__' > "$home/.ssh/authorized_keys"
chown bastet:"$group" "$home/.ssh/authorized_keys"
chmod 600 "$home/.ssh/authorized_keys"
printf 'bastet ALL=(ALL) NOPASSWD: ALL\\n' > /etc/sudoers.d/bastet.new
chmod 440 /etc/sudoers.d/bastet.new
visudo -cf /etc/sudoers.d/bastet.new
mv /etc/sudoers.d/bastet.new /etc/sudoers.d/bastet
echo bastet-ready
"""


def setup_script(public_key: str) -> str:
    key = public_key.strip()
    if not _KEY.match(key):
        raise BastetError("Bastet's public key doesn't look like a single OpenSSH public key line")
    return _SCRIPT.replace("__KEY__", key)


def setup_command(public_key: str) -> str:
    return "sudo sh -c " + shlex.quote(setup_script(public_key))

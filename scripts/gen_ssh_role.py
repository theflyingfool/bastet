"""Write src/bastet/data/roles/ssh/role.yml from the sshd keyword table (a test keeps them in sync).

Run: uv run python scripts/gen_ssh_role.py
"""

from pathlib import Path

from bastet.roles.system import SSHD_INTS, SSHD_KEYWORDS

OUT = Path(__file__).parents[1] / "src" / "bastet" / "data" / "roles" / "ssh" / "role.yml"
NOTES = {
    "PasswordAuthentication": "password logins",
    "KbdInteractiveAuthentication": "keyboard-interactive (PAM) logins",
    "PermitRootLogin": "yes, prohibit-password, forced-commands-only or no",
    "PubkeyAuthentication": "key logins (Bastet needs these)",
    "AllowUsers": "only these users may log in (must include bastet)",
    "AllowGroups": "only these groups may log in (must include bastet, or list bastet in allow_users)",
    "Port": "ports to listen on; Bastet tries them in order, then 22",
    "TrustedUserCAKeys": "CA keys trusted to sign user certificates",
    "HostCertificate": "host certificates signed by your CA",
    "AuthorizedPrincipalsFile": "principals allowed per user (with certificates)",
}
HEADER = (
    'description: "OpenSSH server settings: every sshd_config keyword, plus Match blocks. Written to '
    '/etc/ssh/sshd_config.d/10-bastet.conf, checked with sshd -t, then sshd is reloaded. Unset = leave sshd\'s own '
    'setting alone; nothing is set by default. Settings that would lock Bastet out are refused."\n'
)
EXAMPLES = '''examples:
  - title: Super hardened (not applied anywhere by default — copy into _roles/lab/ssh.md when ready)
    yaml: |
      password_authentication: false
      kbd_interactive_authentication: false
      permit_root_login: "no"
      permit_empty_passwords: false
      x11_forwarding: false
      allow_agent_forwarding: false
      allow_tcp_forwarding: "no"
      max_auth_tries: 3
      login_grace_time: "20"
      client_alive_interval: 300
      client_alive_count_max: 2
      kex_algorithms: [sntrup761x25519-sha512@openssh.com, curve25519-sha256, curve25519-sha256@libssh.org]
      ciphers: [chacha20-poly1305@openssh.com, aes256-gcm@openssh.com, aes128-gcm@openssh.com]
      macs: [hmac-sha2-512-etm@openssh.com, hmac-sha2-256-etm@openssh.com]
      host_key_algorithms: [ssh-ed25519, sk-ssh-ed25519@openssh.com, rsa-sha2-512]
      log_level: VERBOSE
  - title: Move to port 2222 safely (apply this, then change it to [2222] once 2222 works)
    yaml: |
      port: [22, 2222]
  - title: Allow a forwarding user only from the LAN
    yaml: |
      match:
        - criteria: "User nick Address 10.10.0.0/24"
          settings:
            allow_tcp_forwarding: "yes"
'''


def _type(name: str, kind: str) -> str:
    if name == "port":
        return "{type: list, items: {type: int}"
    if kind == "yesno":
        return "{type: bool"
    if kind in ("words", "commas", "repeat"):
        return "{type: list, items: {type: string}"
    return "{type: int" if name in SSHD_INTS else "{type: string"


def render() -> str:
    lines = [HEADER, "options:"]
    for name, (keyword, kind) in SSHD_KEYWORDS.items():
        note = f": {NOTES[keyword]}" if keyword in NOTES else ""
        lines.append(f'  {name}: {_type(name, kind)}, description: "{keyword}{note}"}}')
    lines += [
        "  match:",
        "    type: list",
        '    description: "Match blocks: settings for some users or addresses only (written last, then Match all)"',
        "    items:",
        "      type: object",
        "      fields:",
        '        criteria: {type: string, required: true, description: "e.g. User nick Address 10.10.0.0/24"}',
        '        settings: {type: map, items: {type: any}, description: "ssh role option names and values"}',
    ]
    return "\n".join(lines) + "\n" + EXAMPLES


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(), encoding="utf-8")
    print(f"wrote {OUT}")

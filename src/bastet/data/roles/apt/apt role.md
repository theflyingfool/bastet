---
bastet: role-definition
name: apt
version: 1.0.0
api: 0
description: 'apt''s own settings, written to /etc/apt/apt.conf.d/90-bastet (Debian-based hosts; aim it at [[debian]]). Unset = leave apt''s setting as it is. A curated, incomplete list of options. Repositories are written in apt''s own format (deb822 files in /etc/apt/sources.list.d).'
os:
- debian
provides:
- package-manager
options:
  install_recommends:
    type: bool
    description: 'APT::Install-Recommends: install recommended packages too'
    key: APT::Install-Recommends
  install_suggests:
    type: bool
    description: 'APT::Install-Suggests: install suggested packages too'
    key: APT::Install-Suggests
  default_release:
    type: string
    description: 'APT::Default-Release: the release to install from by default, e.g. trixie-backports'
    key: APT::Default-Release
    single_line: true
  keep_downloaded_packages:
    type: bool
    description: 'APT::Keep-Downloaded-Packages: keep .deb files after installing'
    key: APT::Keep-Downloaded-Packages
  autoremove_suggests_important:
    type: bool
    description: 'APT::AutoRemove::SuggestsImportant: treat suggested packages as important for autoremove'
    key: APT::AutoRemove::SuggestsImportant
  acquire_retries:
    type: int
    description: 'Acquire::Retries: download retries'
    key: Acquire::Retries
    min: 0
  acquire_http_timeout:
    type: int
    description: 'Acquire::http::Timeout: seconds'
    key: Acquire::http::Timeout
    min: 1
  acquire_https_timeout:
    type: int
    description: 'Acquire::https::Timeout: seconds'
    key: Acquire::https::Timeout
    min: 1
  acquire_http_proxy:
    type: string
    description: 'Acquire::http::Proxy: e.g. http://proxy.example.net:3128'
    key: Acquire::http::Proxy
    single_line: true
  acquire_https_proxy:
    type: string
    description: 'Acquire::https::Proxy'
    key: Acquire::https::Proxy
    single_line: true
  acquire_languages:
    type: list
    description: 'Acquire::Languages: translations to download (en, none, …)'
    items:
      type: string
    key: Acquire::Languages
  dpkg_options:
    type: list
    description: 'Dpkg::Options: options passed to dpkg'
    items:
      type: string
    key: Dpkg::Options
  repositories:
    type: list
    description: 'Extra apt repositories, one /etc/apt/sources.list.d/<name>.sources file each, written before packages are installed'
    as: entries
    format: deb822
    path: /etc/apt/sources.list.d/{name}.sources
    before: packages
    items:
      type: object
      fields:
        name:
          type: string
          required: true
          description: File name, letters, digits and . _ + -
        types:
          type: list
          items:
            type: string
          key: Types
          default:
          - deb
          description: deb, deb-src
        uris:
          type: list
          items:
            type: string
          key: URIs
          required: true
        suites:
          type: list
          items:
            type: string
          key: Suites
        components:
          type: list
          items:
            type: string
          key: Components
        architectures:
          type: list
          items:
            type: string
          key: Architectures
        enabled:
          type: bool
          key: Enabled
        trusted:
          type: bool
          key: Trusted
        signed_by:
          type: string
          as: text
          key: Signed-By
          description: A key file path, or the armored key text
examples:
- title: Go through a proxy (all Debian hosts)
  yaml: |
    acquire_http_proxy: http://proxy.example.net:3128
    acquire_https_proxy: http://proxy.example.net:3128
    acquire_retries: 3
- title: No recommended packages
  yaml: |
    install_recommends: false
- title: Debian backports
  yaml: |
    repositories:
      - name: backports
        uris:
          - http://deb.debian.org/debian
        suites:
          - trixie-backports
        components:
          - main
        signed_by: /usr/share/keyrings/debian-archive-keyring.gpg
files:
- path: /etc/apt/apt.conf.d/90-bastet
  render: apt
  mode: "0644"
  validate: apt-config -c %s dump >/dev/null
---

# apt role

apt's own settings, written to /etc/apt/apt.conf.d/90-bastet (Debian-based hosts; aim it at [[debian]]). Unset = leave apt's setting as it is. Repositories are written in apt's own format (deb822 files in /etc/apt/sources.list.d).

The option list is curated and incomplete: it covers the settings homelabs reach for most. The full list of apt options will be generated later.

## Changes

- 1.0.0: first version

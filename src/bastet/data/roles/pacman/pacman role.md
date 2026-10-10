---
bastet: role-definition
name: pacman
version: 1.0.0
api: 0
description: 'pacman''s own settings: every [options] setting in /etc/pacman.conf (Arch-based hosts; aim it at [[arch]]). Unset = leave pacman''s setting as it is. Repositories belong to the packages role.'
os:
- arch
options:
  root_dir:
    type: string
    description: 'RootDir: installation root'
    key: RootDir
    section: options
    single_line: true
  db_path:
    type: string
    description: 'DBPath: package database location'
    key: DBPath
    section: options
    single_line: true
  cache_dir:
    type: list
    description: 'CacheDir: package cache directories'
    items:
      type: string
    key: CacheDir
    section: options
    as: list
  hook_dir:
    type: list
    description: 'HookDir: extra hook directories'
    items:
      type: string
    key: HookDir
    section: options
    as: list
  gpg_dir:
    type: string
    description: 'GPGDir: keyring directory'
    key: GPGDir
    section: options
    single_line: true
  log_file:
    type: string
    description: LogFile
    key: LogFile
    section: options
    single_line: true
  hold_pkg:
    type: list
    description: 'HoldPkg: ask before removing these (pacman, glibc by default); [] comments it out'
    items:
      type: string
    key: HoldPkg
    section: options
    as: list
  ignore_pkg:
    type: list
    description: 'IgnorePkg: never upgrade these'
    items:
      type: string
    key: IgnorePkg
    section: options
    as: list
  ignore_group:
    type: list
    description: 'IgnoreGroup: never upgrade packages in these groups'
    items:
      type: string
    key: IgnoreGroup
    section: options
    as: list
  no_upgrade:
    type: list
    description: 'NoUpgrade: files never overwritten on upgrade (saved as .pacnew)'
    items:
      type: string
    key: NoUpgrade
    section: options
    as: list
  no_extract:
    type: list
    description: 'NoExtract: files never installed (e.g. usr/share/doc/*)'
    items:
      type: string
    key: NoExtract
    section: options
    as: list
  architecture:
    type: string
    description: Architecture (auto, x86_64, …)
    key: Architecture
    section: options
    single_line: true
  xfer_command:
    type: string
    description: 'XferCommand: external download command (%u URL, %o output)'
    key: XferCommand
    section: options
    single_line: true
  parallel_downloads:
    type: int
    description: 'ParallelDownloads: packages downloaded at once'
    key: ParallelDownloads
    section: options
    min: 1
  disable_download_timeout:
    type: bool
    description: DisableDownloadTimeout
    key: DisableDownloadTimeout
    section: options
    as: flag
  download_user:
    type: string
    description: 'DownloadUser: unprivileged user downloads run as'
    key: DownloadUser
    section: options
    single_line: true
  disable_sandbox:
    type: bool
    description: 'DisableSandbox: turn off the download sandbox'
    key: DisableSandbox
    section: options
    as: flag
  clean_method:
    type: list
    description: 'CleanMethod: what pacman -Sc keeps'
    items:
      type: string
      choices:
      - KeepInstalled
      - KeepCurrent
    key: CleanMethod
    section: options
    as: list
  sig_level:
    type: string
    description: SigLevel, e.g. Required DatabaseOptional
    key: SigLevel
    section: options
    single_line: true
  local_file_sig_level:
    type: string
    description: LocalFileSigLevel
    key: LocalFileSigLevel
    section: options
    single_line: true
  remote_file_sig_level:
    type: string
    description: RemoteFileSigLevel
    key: RemoteFileSigLevel
    section: options
    single_line: true
  color:
    type: bool
    default: true
    description: 'Color: colour output'
    key: Color
    section: options
    as: flag
  candy:
    type: bool
    default: true
    description: 'ILoveCandy: Pac-Man progress bar'
    key: ILoveCandy
    section: options
    as: flag
  no_progress_bar:
    type: bool
    description: NoProgressBar
    key: NoProgressBar
    section: options
    as: flag
  verbose_pkg_lists:
    type: bool
    description: 'VerbosePkgLists: old and new versions in a table'
    key: VerbosePkgLists
    section: options
    as: flag
  check_space:
    type: bool
    description: 'CheckSpace: check disk space before installing'
    key: CheckSpace
    section: options
    as: flag
  use_syslog:
    type: bool
    description: 'UseSyslog: log to syslog too'
    key: UseSyslog
    section: options
    as: flag
examples:
- title: All Arch hosts (put in _roles/groups/pacman.md with applies_to "[[arch]]")
  yaml: |
    parallel_downloads: 10
    verbose_pkg_lists: true
- title: Hold the kernel back, skip docs, keep the current cache only
  yaml: |
    ignore_pkg:
      - linux
      - linux-headers
    no_extract:
      - usr/share/doc/*
    clean_method:
      - KeepCurrent
files:
- path: /etc/pacman.conf
  edit: ini
---

# pacman role

pacman's own settings: every [options] setting in /etc/pacman.conf (Arch-based hosts; aim it at [[arch]]). Unset = leave pacman's setting as it is. Repositories belong to the packages role.

## Changes

- 1.0.0: converted from role.yml

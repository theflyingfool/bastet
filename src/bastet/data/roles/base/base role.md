---
bastet: role-definition
name: base
version: 0.1.1
api: 0
accounts:
- git
description: 'The basics every host gets: a set of admin tools, and CPU microcode on physical machines. With no options it installs vim, zsh, git, htop, tree, gdu, wget and less, plus the microcode package for the host''s CPU if the host is a physical machine (Arch: intel-ucode or amd-ucode; Debian: intel-microcode or amd64-microcode).'
options:
  tools:
    type: list
    items:
      type: string
    default: [vim, zsh, git, htop, tree, gdu, wget, less]
    description: 'Admin tools to install; setting this replaces the default list (use extra_tools to add to it)'
  extra_tools:
    type: list
    items:
      type: string
    description: 'More tools on top of `tools`, at every level (lab, group, host)'
  microcode:
    type: string
    default: auto
    choices: [auto, never]
    description: 'auto: install the CPU microcode package on physical hosts (never on VMs or containers); never: install none'
  baseline:
    type: string
    description: 'Reserved for a later round; has no effect'
examples:
- title: Everywhere (put in the lab note)
  yaml: |
    extra_tools:
      - jq
- title: Only these tools
  yaml: |
    tools:
      - vim
      - git
- title: A machine that should not get microcode
  yaml: |
    microcode: never
checks:
- name: no cpu fact
  when: microcode != 'never' and host.physical and not host.cpu
  level: error
  message: 'base needs the CPU vendor to pick the microcode package; run bastet run -g on this host first, or set microcode: never'
- name: unknown cpu vendor
  when: microcode != 'never' and host.physical and host.cpu and 'intel' not in host.cpu|lower and 'amd' not in host.cpu|lower
  level: error
  message: 'base: the CPU vendor is not Intel or AMD, so no microcode package is known; set microcode: never'
- name: no microcode package for this os
  when: microcode != 'never' and host.physical and host.cpu and not host.arch_like and not host.debian_like
  level: error
  message: 'base: no microcode package is known for this operating system; set microcode: never'
- name: virtual host
  when: microcode != 'never' and not host.physical
  level: info
  message: 'base: this host is virtual, so no CPU microcode is installed (the host machine owns it)'
packages:
- name: '{{ ((tools or []) + (extra_tools or [])) | unique | list }}'
- name: intel-ucode
  when: microcode != 'never' and host.physical and host.arch_like and 'intel' in host.cpu|lower
- name: amd-ucode
  when: microcode != 'never' and host.physical and host.arch_like and 'amd' in host.cpu|lower
- name: intel-microcode
  when: microcode != 'never' and host.physical and host.debian_like and 'intel' in host.cpu|lower
- name: amd64-microcode
  when: microcode != 'never' and host.physical and host.debian_like and 'amd' in host.cpu|lower
---

# base role

The basics every host gets.

## What it does with no options

On every host the role is applied to (a new lab, group or host starts with a `base` note, so that is every host):

- Installs **vim, zsh, git, htop, tree, gdu, wget and less**.
- On a **physical** host with a known Intel or AMD CPU, installs the **microcode package**: `intel-ucode` or `amd-ucode`
  on Arch (and Arch-based), `intel-microcode` or `amd64-microcode` on Debian (and Debian-based). Debian needs the
  `non-free-firmware` component enabled; the role does not check that yet.
- On a virtual machine or container it installs no microcode and says so once (info).

The `git` account that the Arch `git` package creates (the "git daemon user") is an expected account on hosts where this
role is applied, so the unaccounted-users report does not list it.

Nothing else is changed. Setting `tools` replaces the tool list; `extra_tools` adds on top of whatever list applies, at
every level; `microcode: never` turns the microcode off.

## Errors

On a physical host the role stops that host, before anything is changed, when:

- there is no CPU fact yet: run `bastet run -g` on the host first (or set `microcode: never`);
- the CPU is neither Intel nor AMD;
- the operating system is neither Arch-based nor Debian-based, so no package is known.

## Changes

- 0.1.1: the `git` account (created by the `git` package) is an expected account.
- 0.1.0: converted from the Python role; microcode packages come from one table in this file.

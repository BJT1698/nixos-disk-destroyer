#!/run/current-system/sw/bin/bash

nix-build '<nixpkgs/nixos/release.nix>' \
  -A netboot.x86_64-linux \
  --arg configuration ./configuration.nix

let
  pkgs = import <nixpkgs> {};
in pkgs.nixos {
  configuration = ./configuration.nix;
}

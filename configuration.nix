# configuration.nix
{ config, pkgs, ... }:
{
  # Basic system settings
  boot.supportedFilesystems = [ "btrfs" "reiserfs" "vfat" "f2fs" "xfs" "ntfs" "cifs" ];

  # Network configuration for PXE boot
  networking = {
    hostName = "nixos-disk-destroyer";
    useDHCP = true;
  };

  # Include any additional packages you need
  environment.systemPackages = with pkgs; [
    bash
    coreutils
    util-linux  # For lsblk and wipefs
    kbd         # For terminal colors
    parted      # For partition management
    e2fsprogs
    scrub
    beep
    neofetch
  ];

   # Enable PC speaker support
  boot.extraModprobeConfig = ''
    options snd-pcsp index=2
  '';
  boot.kernelModules = [ "pcspkr" ];

  # System settings specific to netboot
  boot.initrd.availableKernelModules = [
    "ata_piix" "uhci_hcd" "virtio_pci" "virtio_scsi"
  ];
  
  programs.bash.interactiveShellInit = "
    sudo /etc/disk-format.sh
  ";

  # This is important for netboot
  boot.loader.grub.enable = false;
  boot.loader.systemd-boot.enable = false;

  # Don't keep logs in tmpfs
  services.journald.storage = "volatile";

  # Create the script in the system
  environment.etc."disk-format.sh" = {
    mode = "0755";
    text = builtins.readFile ./disk-format.sh;  # Assuming the script is in the same directory
  };

  # Optional: Create a systemd service to make it available as a system command
  systemd.services.disk-format = {
    description = "Disk Format Service";
    path = with pkgs; [
      bash
      coreutils
      util-linux
      kbd
      beep
      parted
      e2fsprogs
      scrub
    ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "/etc/disk-format.sh";
      RemainAfterExit = "yes";
    };
  };
}

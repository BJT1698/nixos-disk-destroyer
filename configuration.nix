# configuration.nix
{ config, pkgs, lib, ... }:
let
  # Python con Textual per la TUI (destroyer/app.py)
  python = pkgs.python3.withPackages (ps: [ ps.textual ]);
in
{
  # Basic system settings
  boot.supportedFilesystems = [ "btrfs" "reiserfs" "vfat" "f2fs" "xfs" "ntfs" "cifs" ];

  # Network configuration for PXE boot
  networking = {
    hostName = "nixos-disk-destroyer";
  };

  # Console: font grande e leggibile; la palette dei colori la imposta destroyer/start.sh
  console = {
    earlySetup = true;
    font = "ter-v24b";
    packages = [ pkgs.terminus_font ];
  };

  environment.systemPackages = with pkgs; [
    python
    bash
    coreutils
    util-linux    # lsblk, wipefs, blkdiscard
    kbd
    parted
    e2fsprogs
    nvme-cli      # NVMe sanitize / format
    hdparm        # ATA Secure Erase
    smartmontools
    beep
  ];

  # Enable PC speaker support
  boot.extraModprobeConfig = ''
    options snd-pcsp index=2
  '';
  boot.kernelModules = [ "pcspkr" ];

  # System settings specific to netboot
  boot.initrd.availableKernelModules = [
    "ata_piix" "uhci_hcd" "virtio_pci" "virtio_scsi"
    "ahci" "nvme" "sd_mod" "xhci_pci" "usb_storage" "uas"
  ];

  # TUI sulla prima console (login automatico dell'immagine netboot). Le altre console restano
  # libere per la manutenzione; "destroyer" la riapre.
  programs.bash.interactiveShellInit = ''
    alias destroyer='sudo /etc/disk-destroyer/start.sh'
    if [ "$(tty)" = "/dev/tty1" ] && [ -z "''${DESTROYER_STARTED:-}" ]; then
      export DESTROYER_STARTED=1
      sudo /etc/disk-destroyer/start.sh
      echo
      echo "Digita 'destroyer' per riaprire l'interfaccia, 'sudo poweroff' per spegnere."
    fi
  '';

  # This is important for netboot
  boot.loader.grub.enable = false;
  boot.loader.systemd-boot.enable = false;

  # Don't keep logs in tmpfs
  services.journald.storage = "volatile";

  # TUI (Python/Textual): app, motore di cancellazione, stile e script di avvio
  environment.etc."disk-destroyer".source = ./destroyer;

  # Script testuale originale, usato come riserva se la TUI non parte
  environment.etc."disk-format.sh" = {
    mode = "0755";
    text = builtins.readFile ./disk-format.sh;
  };
}

![](logo.png)

# NixOS Disk Destroyer

## Overview

A NixOS netbootable configuration designed for secure and flexible disk erasure across multiple disk types and with various formatting options.

## Features

- Netboot-capable disk formatting tool
- Multiple disk formatting methods:
  - Smart secure format (SSD/HDD optimized)
  - Quick format
  - Deep format
  - Secure format with shred
  - Secure format with scrub

- Automatic disk detection
- Interactive disk selection
- Format type selection
- Support for multiple filesystems
- Comprehensive error handling and user confirmations

## Requirements

- NixOS
- Network boot environment
- Root/admin access

## Build Instructions

```bash
nix-build '<nixpkgs/nixos/release.nix>' \
  -A netboot.x86_64-linux \
  --arg configuration ./configuration.nix
```

## Usage

1. Network boot the NixOS configuration
2. Script will automatically scan available disks
3. Select disks to format
4. Choose formatting method
5. Confirm disk destruction

## Formatting Options

1. **Smart Secure Format** (Recommended)
   - SSD: Uses TRIM
   - HDD: Random data overwrite

2. **Quick Format**
   - Fastest method
   - Clears partition table
   - Less secure

3. **Deep Format**
   - Overwrites disk with zeros
   - More secure than quick format

4. **Secure Format (Shred)**
   - Multiple random overwrites
   - Very secure
   - Slower process

5. **Secure Format (Scrub)**
   - DoD 5220.22-M standard
   - 7-pass secure erase
   - Most secure method

## Safety Warning

⚠️ **CAUTION**: This tool permanently erases disks. Use with extreme care.

## Contributing

Contributions welcome. Please open issues or submit pull requests.

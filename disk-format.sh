#!/usr/bin/env bash

# Text colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to show progress
show_progress() {
    local pid=$1
    local width=50
    while kill -0 $pid 2>/dev/null; do
        echo -ne "\r["
        for ((i=0; i<width; i++)); do
            if [ $((i % 3)) -eq $((RANDOM % 3)) ]; then
                echo -ne "${GREEN}#${NC}"
            else
                echo -ne " "
            fi
        done
        echo -ne "] Working..."
        sleep 0.5
    done
    echo
}

# Function to get disk info
get_disk_info() {
    local disk=$1
    local model=$(lsblk -no MODEL "/dev/$disk" 2>/dev/null || echo "Unknown")
    local size=$(lsblk -no SIZE "/dev/$disk" 2>/dev/null || echo "Unknown")
    local type=$(lsblk -no TRAN "/dev/$disk" 2>/dev/null || echo "Unknown")
    echo "$model ($size) [$type]"
}

# Function to check if device is SSD
is_ssd() {
    local disk=$1
    local rotational=$(cat "/sys/block/$disk/queue/rotational" 2>/dev/null)
    [ "$rotational" = "0" ]
}

# Function to perform quick format
quick_format() {
    local disk=$1
    wipefs -a "/dev/$disk" &>/dev/null &
    wipefs_pid=$!
    show_progress $wipefs_pid
    wait $wipefs_pid
    parted -s "/dev/$disk" mklabel gpt &>/dev/null
    mkfs.ext4 -F "/dev/$disk" &>/dev/null &
    mkfs_pid=$!
    show_progress $mkfs_pid
    wait $mkfs_pid
}

# Function to perform deep format with dd
deep_format() {
    local disk=$1
    dd if=/dev/zero of="/dev/$disk" bs=4M status=none &
    dd_pid=$!
    show_progress $dd_pid
    wait $dd_pid
}

# Function to perform secure format with shred
secure_format_shred() {
    local disk=$1
    shred -v -n 3 -z "/dev/$disk" &>/dev/null &
    shred_pid=$!
    show_progress $shred_pid
    wait $shred_pid
}

# Function to perform secure format with scrub
secure_format_scrub() {
    local disk=$1
    scrub -p dod "/dev/$disk" &>/dev/null &
    scrub_pid=$!
    show_progress $scrub_pid
    wait $scrub_pid
}

# Function to perform fast secure format for SSD
fast_secure_ssd() {
    local disk=$1
    echo -e "${YELLOW}Performing secure trim...${NC}"
    blkdiscard "/dev/$disk" &>/dev/null &
    blk_pid=$!
    show_progress $blk_pid
    wait $blk_pid
    parted -s "/dev/$disk" mklabel gpt &>/dev/null
}

# Function to perform fast secure format for HDD
fast_secure_hdd() {
    local disk=$1
    echo -e "${YELLOW}Performing random data overwrite...${NC}"
    dd if=/dev/urandom of="/dev/$disk" bs=4M status=none &
    dd_pid=$!
    show_progress $dd_pid
    wait $dd_pid
    parted -s "/dev/$disk" mklabel gpt &>/dev/null
}

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Error: This script must be run as root${NC}"
    exit 1
fi

# Get list of disks
echo -e "${YELLOW}Scanning for disks...${NC}"
mapfile -t disks < <(lsblk -dno NAME | grep -v "loop\|sr")

if [ ${#disks[@]} -eq 0 ]; then
    echo -e "${RED}No disks found!${NC}"
    exit 1
fi

# If only one disk, autoselect it
if [ ${#disks[@]} -eq 1 ]; then
    selected_disks=("${disks[0]}")
    disk_info=$(get_disk_info "${disks[0]}")
    echo -e "${YELLOW}Only one disk found: /dev/${disks[0]} - $disk_info${NC}"
else
    # Show disk selection menu
    echo -e "${YELLOW}Available disks:${NC}"
    for i in "${!disks[@]}"; do
        disk_info=$(get_disk_info "${disks[$i]}")
        echo "[$i] /dev/${disks[$i]} - $disk_info"
    done
    
    echo -e "\nEnter disk numbers to format (space-separated) or 'all' for all disks:"
    read -r selection
    
    if [ "$selection" = "all" ]; then
        selected_disks=("${disks[@]}")
    else
        selected_disks=()
        for num in $selection; do
            if [ "$num" -lt ${#disks[@]} ]; then
                selected_disks+=("${disks[$num]}")
            fi
        done
    fi
fi

# Format type selection
echo -e "\n${YELLOW}Select format type:${NC}"
echo -e "\nOptimized Methods (Recommended):"
echo -e "1) Smart secure format (Optimized for SSD/HDD)\n   - Uses TRIM for SSDs (fast and secure)\n   - Uses random data for HDDs (single pass)"

echo -e "\nTraditional Methods:"
echo -e "2) Quick format (fastest, but less secure)\n   - Clears partition table and creates new filesystem"
echo -e "3) Deep format with dd (slower, more secure)\n   - Overwrites entire disk with zeros once"
echo -e "4) Secure format with shred (very slow, very secure)\n   - Multiple random overwrites plus final zero pass"
echo -e "5) Secure format with scrub (very slow, very secure)\n   - Uses DoD 5220.22-M standard\n   - 7 passes with different patterns"
read -r format_type

# Final confirmation with warning appropriate to format type
echo -e "\n${RED}WARNING: This will permanently erase the following disks:${NC}"
for disk in "${selected_disks[@]}"; do
    disk_info=$(get_disk_info "$disk")
    echo -e "${RED}/dev/$disk - $disk_info${NC}"
done

case $format_type in
    1) echo -e "${YELLOW}Smart secure format selected - Optimized for your drive type${NC}" ;;
    2) echo -e "${YELLOW}Quick format selected - Data recovery might still be possible${NC}" ;;
    3) echo -e "${YELLOW}Deep format selected - Data recovery would be very difficult${NC}" ;;
    4) echo -e "${YELLOW}Secure format with shred selected - Data recovery should be impossible${NC}" ;;
    5) echo -e "${YELLOW}Secure format with scrub selected - DoD compliant secure erase${NC}" ;;
esac

echo -e "${RED}This operation cannot be undone!${NC}"
echo -n "Are you sure you want to continue? (yes/NO): "
read -r confirm

if [ "$confirm" != "yes" ]; then
    echo -e "${YELLOW}Operation cancelled.${NC}"
    exit 0
fi

# Perform format
for disk in "${selected_disks[@]}"; do
    echo -e "\n${YELLOW}Processing /dev/$disk...${NC}"
    
    case $format_type in
        1)
            if is_ssd "$disk"; then
                echo -e "${YELLOW}SSD detected - using optimized secure erase method${NC}"
                fast_secure_ssd "$disk"
            else
                echo -e "${YELLOW}HDD detected - using optimized secure erase method${NC}"
                fast_secure_hdd "$disk"
            fi
            ;;
        2)
            echo -e "${YELLOW}Performing quick format...${NC}"
            quick_format "$disk"
            ;;
        3)
            echo -e "${YELLOW}Performing deep format...${NC}"
            deep_format "$disk"
            ;;
        4)
            echo -e "${YELLOW}Performing secure format with shred (this will take a while)...${NC}"
            secure_format_shred "$disk"
            ;;
        5)
            echo -e "${YELLOW}Performing secure format with scrub (this will take a while)...${NC}"
            secure_format_scrub "$disk"
            ;;
        *)
            echo -e "${RED}Invalid format type selected. Aborting.${NC}"
            exit 1
            ;;
    esac
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}Successfully erased /dev/$disk${NC}"
    else
        echo -e "${RED}Error erasing /dev/$disk${NC}"
    fi
done

echo -e "\n${GREEN}All operations completed.${NC}"
sudo sh -c "echo -e '\a' > /dev/tty1"
echo -e "${YELLOW}System will shutdown in 30 seconds...${NC}"
sleep 30
poweroff

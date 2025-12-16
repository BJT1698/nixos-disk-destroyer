#!/usr/bin/env bash

set -euo pipefail

# =============================================================================
# Enhanced Disk Formatting Script
# =============================================================================

# Text colors and formatting
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly CYAN='\033[0;36m'
readonly BOLD='\033[1m'
readonly DIM='\033[2m'
readonly NC='\033[0m'

# Configuration
readonly SCRIPT_NAME="Disk Format Utility"
readonly VERSION="2.0"
readonly MAX_RETRIES=3

# Global variables
declare -a selected_disks=()
declare format_type=""

# =============================================================================
# Utility Functions
# =============================================================================

# Print colored messages
print_header() {
    echo -e "\n${BOLD}${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD}${BLUE}  $1${NC}"
    echo -e "${BOLD}${BLUE}═══════════════════════════════════════════════════════════════${NC}\n"
}

print_section() {
    echo -e "\n${BOLD}${CYAN}━━━ $1 ━━━${NC}\n"
}

print_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1" >&2
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_info() {
    echo -e "${CYAN}[i]${NC} $1"
}

# Enhanced progress indicator
show_progress() {
    local pid=$1
    local message=${2:-"Working"}
    local width=50
    local chars=('/' '-' '\\' '|')
    local char_idx=0
    
    while kill -0 "$pid" 2>/dev/null; do
        local filled=$((RANDOM % width))
        printf "\r${CYAN}[${NC}"
        for ((i=0; i<width; i++)); do
            if [ $i -lt $filled ]; then
                printf "${GREEN}▓${NC}"
            else
                printf "${DIM}░${NC}"
            fi
        done
        printf "${CYAN}]${NC} ${chars[$char_idx]} $message..."
        char_idx=$(( (char_idx + 1) % 4 ))
        sleep 0.1
    done
    printf "\r%*s\r" $((width + 50)) ""
}

# Error handler
handle_error() {
    local exit_code=$1
    local line_num=$2
    print_error "Script failed at line $line_num with exit code $exit_code"
    cleanup_on_error
    exit "$exit_code"
}

trap 'handle_error $? $LINENO' ERR

cleanup_on_error() {
    print_warning "Cleaning up..."
    # Kill any background processes
    jobs -p | xargs -r kill 2>/dev/null || true
}

# =============================================================================
# Validation Functions
# =============================================================================

check_root() {
    if [ "$EUID" -ne 0 ]; then
        print_error "This script must be run as root"
        print_info "Please run: sudo $0"
        exit 1
    fi
}

check_dependencies() {
    local missing_deps=()
    local deps=("lsblk" "wipefs" "parted" "dd")
    
    print_info "Checking dependencies..."
    
    for dep in "${deps[@]}"; do
        if ! command -v "$dep" &>/dev/null; then
            missing_deps+=("$dep")
        fi
    done
    
    # Optional dependencies
    command -v "blkdiscard" &>/dev/null || print_warning "blkdiscard not found (optional for SSD secure erase)"
    command -v "shred" &>/dev/null || print_warning "shred not found (optional for secure erase)"
    command -v "scrub" &>/dev/null || print_warning "scrub not found (optional for DoD secure erase)"
    
    if [ ${#missing_deps[@]} -gt 0 ]; then
        print_error "Missing required dependencies: ${missing_deps[*]}"
        exit 1
    fi
    
    print_success "All required dependencies found"
}

validate_disk_exists() {
    local disk=$1
    if [ ! -b "/dev/$disk" ]; then
        print_error "Device /dev/$disk does not exist or is not a block device"
        return 1
    fi
    return 0
}

check_disk_mounted() {
    local disk=$1
    if mount | grep -q "^/dev/${disk}"; then
        print_error "Device /dev/$disk or its partitions are currently mounted"
        print_info "Please unmount before proceeding"
        return 1
    fi
    return 0
}

# =============================================================================
# Disk Information Functions
# =============================================================================

get_disk_info() {
    local disk=$1
    local model size type
    
    model=$(lsblk -no MODEL "/dev/$disk" 2>/dev/null | xargs || echo "Unknown Model")
    size=$(lsblk -no SIZE "/dev/$disk" 2>/dev/null || echo "Unknown Size")
    type=$(lsblk -no TRAN "/dev/$disk" 2>/dev/null || echo "Unknown")
    
    echo "$model | $size | Transport: $type"
}

is_ssd() {
    local disk=$1
    local rotational
    
    if [ -f "/sys/block/$disk/queue/rotational" ]; then
        rotational=$(cat "/sys/block/$disk/queue/rotational" 2>/dev/null)
        [ "$rotational" = "0" ]
    else
        return 1
    fi
}

get_disk_type_display() {
    local disk=$1
    if is_ssd "$disk"; then
        echo "${GREEN}SSD${NC}"
    else
        echo "${YELLOW}HDD${NC}"
    fi
}

# =============================================================================
# Disk Selection Functions
# =============================================================================

scan_disks() {
    local -a found_disks
    print_info "Scanning for available disks..."
    
    mapfile -t found_disks < <(lsblk -dno NAME 2>/dev/null | grep -Ev "^(loop|sr|dm-)" || true)
    
    if [ ${#found_disks[@]} -eq 0 ]; then
        print_error "No disks found!"
        exit 1
    fi
    
    print_success "Found ${#found_disks[@]} disk(s)"
    echo "${found_disks[@]}"
}

display_disk_menu() {
    local -a disks=("$@")
    
    print_section "Available Disks"
    
    for i in "${!disks[@]}"; do
        local disk="${disks[$i]}"
        local disk_info
        local disk_type
        
        disk_info=$(get_disk_info "$disk")
        disk_type=$(get_disk_type_display "$disk")
        
        echo -e "${BOLD}[$i]${NC} ${CYAN}/dev/$disk${NC} - $disk_type"
        echo -e "    $disk_info"
        echo
    done
}

get_disk_selection() {
    local -a disks=("$@")
    local selection
    local retry_count=0
    
    while [ $retry_count -lt $MAX_RETRIES ]; do
        echo -e "${BOLD}Enter disk numbers to format${NC} (space-separated, e.g., '0 2 3')"
        echo -e "Or type ${BOLD}'all'${NC} to select all disks"
        echo -e "Or type ${BOLD}'q'${NC} to quit"
        echo -ne "${CYAN}Selection:${NC} "
        read -r selection
        
        # Handle quit
        if [[ "$selection" =~ ^[qQ]$ ]]; then
            print_warning "Operation cancelled by user"
            exit 0
        fi
        
        # Handle 'all'
        if [[ "$selection" =~ ^[aA][lL][lL]$ ]]; then
            selected_disks=("${disks[@]}")
            print_success "Selected all ${#selected_disks[@]} disk(s)"
            return 0
        fi
        
        # Validate individual selections
        selected_disks=()
        local valid=true
        
        for num in $selection; do
            if ! [[ "$num" =~ ^[0-9]+$ ]]; then
                print_error "Invalid input: '$num' is not a number"
                valid=false
                break
            fi
            
            if [ "$num" -ge ${#disks[@]} ]; then
                print_error "Invalid disk number: $num (valid range: 0-$((${#disks[@]} - 1)))"
                valid=false
                break
            fi
            
            selected_disks+=("${disks[$num]}")
        done
        
        if [ "$valid" = true ] && [ ${#selected_disks[@]} -gt 0 ]; then
            print_success "Selected ${#selected_disks[@]} disk(s)"
            return 0
        fi
        
        if [ ${#selected_disks[@]} -eq 0 ]; then
            print_error "No valid disks selected"
        fi
        
        retry_count=$((retry_count + 1))
        if [ $retry_count -lt $MAX_RETRIES ]; then
            print_warning "Please try again ($((MAX_RETRIES - retry_count)) attempt(s) remaining)"
            echo
        fi
    done
    
    print_error "Maximum retry attempts reached"
    exit 1
}

# =============================================================================
# Format Type Selection
# =============================================================================

display_format_menu() {
    print_section "Format Type Selection"
    
    echo -e "${BOLD}${GREEN}Recommended Methods:${NC}"
    echo -e "${BOLD}[1]${NC} Smart Secure Format ${DIM}(Auto-detects SSD/HDD)${NC}"
    echo -e "    • SSD: Uses TRIM (fast and secure)"
    echo -e "    • HDD: Single-pass random data overwrite"
    echo
    
    echo -e "${BOLD}${YELLOW}Traditional Methods:${NC}"
    echo -e "${BOLD}[2]${NC} Quick Format ${DIM}(Fastest, least secure)${NC}"
    echo -e "    • Clears partition table and creates new filesystem"
    echo -e "    • Data recovery possible with forensic tools"
    echo
    echo -e "${BOLD}[3]${NC} Deep Format ${DIM}(Moderate speed and security)${NC}"
    echo -e "    • Single-pass zero-fill using dd"
    echo -e "    • Data recovery very difficult"
    echo
    echo -e "${BOLD}[4]${NC} Secure Format - Shred ${DIM}(Slow, very secure)${NC}"
    echo -e "    • Multiple random overwrites plus zero pass"
    echo -e "    • Data recovery should be impossible"
    echo
    echo -e "${BOLD}[5]${NC} Secure Format - DoD 5220.22-M ${DIM}(Very slow, military-grade)${NC}"
    echo -e "    • 7-pass overwrite with different patterns"
    echo -e "    • Meets Department of Defense standards"
    echo
}

get_format_selection() {
    local selection
    local retry_count=0
    
    while [ $retry_count -lt $MAX_RETRIES ]; do
        echo -ne "${CYAN}Select format type [1-5] or 'q' to quit:${NC} "
        read -r selection
        
        if [[ "$selection" =~ ^[qQ]$ ]]; then
            print_warning "Operation cancelled by user"
            exit 0
        fi
        
        if [[ "$selection" =~ ^[1-5]$ ]]; then
            format_type="$selection"
            print_success "Format type $format_type selected"
            return 0
        fi
        
        print_error "Invalid selection: '$selection' (must be 1-5)"
        retry_count=$((retry_count + 1))
        
        if [ $retry_count -lt $MAX_RETRIES ]; then
            print_warning "Please try again ($((MAX_RETRIES - retry_count)) attempt(s) remaining)"
        fi
    done
    
    print_error "Maximum retry attempts reached"
    exit 1
}

# =============================================================================
# Format Functions
# =============================================================================

quick_format() {
    local disk=$1
    
    print_info "Wiping filesystem signatures..."
    wipefs -a "/dev/$disk" &>/dev/null &
    local pid=$!
    show_progress "$pid" "Wiping signatures"
    wait "$pid"
    
    print_info "Creating GPT partition table..."
    if ! parted -s "/dev/$disk" mklabel gpt &>/dev/null; then
        print_error "Failed to create partition table"
        return 1
    fi
    
    print_info "Creating ext4 filesystem..."
    mkfs.ext4 -F "/dev/$disk" &>/dev/null &
    pid=$!
    show_progress "$pid" "Creating filesystem"
    wait "$pid"
}

deep_format() {
    local disk=$1
    
    print_info "Performing zero-fill (this may take a while)..."
    dd if=/dev/zero of="/dev/$disk" bs=4M status=none 2>/dev/null &
    local pid=$!
    show_progress "$pid" "Writing zeros"
    wait "$pid"
}

secure_format_shred() {
    local disk=$1
    
    if ! command -v shred &>/dev/null; then
        print_error "shred command not found"
        return 1
    fi
    
    print_info "Performing secure shred (3 passes + zero, this will take a long time)..."
    shred -v -n 3 -z "/dev/$disk" &>/dev/null &
    local pid=$!
    show_progress "$pid" "Shredding disk"
    wait "$pid"
}

secure_format_scrub() {
    local disk=$1
    
    if ! command -v scrub &>/dev/null; then
        print_error "scrub command not found"
        return 1
    fi
    
    print_info "Performing DoD 5220.22-M secure erase (7 passes, this will take a very long time)..."
    scrub -p dod "/dev/$disk" &>/dev/null &
    local pid=$!
    show_progress "$pid" "DoD secure erase"
    wait "$pid"
}

fast_secure_ssd() {
    local disk=$1
    
    if ! command -v blkdiscard &>/dev/null; then
        print_warning "blkdiscard not available, falling back to random data method"
        fast_secure_hdd "$disk"
        return $?
    fi
    
    print_info "Performing TRIM/discard operation..."
    blkdiscard "/dev/$disk" &>/dev/null &
    local pid=$!
    show_progress "$pid" "Secure TRIM"
    wait "$pid"
    
    print_info "Creating GPT partition table..."
    if ! parted -s "/dev/$disk" mklabel gpt &>/dev/null; then
        print_error "Failed to create partition table"
        return 1
    fi
}

fast_secure_hdd() {
    local disk=$1
    
    print_info "Performing random data overwrite (single pass)..."
    dd if=/dev/urandom of="/dev/$disk" bs=4M status=none 2>/dev/null &
    local pid=$!
    show_progress "$pid" "Writing random data"
    wait "$pid"
    
    print_info "Creating GPT partition table..."
    if ! parted -s "/dev/$disk" mklabel gpt &>/dev/null; then
        print_error "Failed to create partition table"
        return 1
    fi
}

smart_secure_format() {
    local disk=$1
    
    if is_ssd "$disk"; then
        print_info "SSD detected - using optimized TRIM-based secure erase"
        fast_secure_ssd "$disk"
    else
        print_info "HDD detected - using random data overwrite method"
        fast_secure_hdd "$disk"
    fi
}

# =============================================================================
# Confirmation and Execution
# =============================================================================

show_final_confirmation() {
    local format_description
    
    case $format_type in
        1) format_description="${GREEN}Smart Secure Format${NC} - Optimized for drive type" ;;
        2) format_description="${YELLOW}Quick Format${NC} - Data recovery might be possible" ;;
        3) format_description="${YELLOW}Deep Format${NC} - Data recovery very difficult" ;;
        4) format_description="${RED}Secure Shred${NC} - Data recovery should be impossible" ;;
        5) format_description="${RED}DoD 5220.22-M${NC} - Military-grade secure erase" ;;
    esac
    
    print_section "Final Confirmation"
    
    echo -e "${BOLD}${RED}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${RED}║                    !!! WARNING !!!                         ║${NC}"
    echo -e "${BOLD}${RED}║  This operation will PERMANENTLY DESTROY all data on:     ║${NC}"
    echo -e "${BOLD}${RED}╚════════════════════════════════════════════════════════════╝${NC}"
    echo
    
    for disk in "${selected_disks[@]}"; do
        local disk_info
        local disk_type
        disk_info=$(get_disk_info "$disk")
        disk_type=$(get_disk_type_display "$disk")
        echo -e "  ${BOLD}${RED}/dev/$disk${NC} - $disk_type"
        echo -e "  ${DIM}$disk_info${NC}"
        echo
    done
    
    echo -e "${BOLD}Format method:${NC} $format_description"
    echo
    echo -e "${RED}${BOLD}THIS OPERATION CANNOT BE UNDONE!${NC}"
    echo
    
    local retry_count=0
    while [ $retry_count -lt $MAX_RETRIES ]; do
        echo -ne "${BOLD}Type 'YES' (in capitals) to confirm, or 'no' to cancel:${NC} "
        read -r confirm
        
        if [[ "$confirm" == "YES" ]]; then
            print_warning "Proceeding with disk erase operation..."
            return 0
        elif [[ "$confirm" =~ ^[nN][oO]?$ ]]; then
            print_warning "Operation cancelled by user"
            exit 0
        else
            print_error "Invalid confirmation: '$confirm'"
            retry_count=$((retry_count + 1))
            if [ $retry_count -lt $MAX_RETRIES ]; then
                print_warning "Please try again ($((MAX_RETRIES - retry_count)) attempt(s) remaining)"
            fi
        fi
    done
    
    print_error "Maximum retry attempts reached"
    exit 1
}

execute_format() {
    local disk=$1
    local result=0
    
    print_section "Processing /dev/$disk"
    
    # Validate disk before processing
    if ! validate_disk_exists "$disk"; then
        return 1
    fi
    
    if ! check_disk_mounted "$disk"; then
        return 1
    fi
    
    # Execute format based on type
    case $format_type in
        1) smart_secure_format "$disk" ;;
        2) quick_format "$disk" ;;
        3) deep_format "$disk" ;;
        4) secure_format_shred "$disk" ;;
        5) secure_format_scrub "$disk" ;;
        *)
            print_error "Invalid format type: $format_type"
            return 1
            ;;
    esac
    
    result=$?
    
    if [ $result -eq 0 ]; then
        print_success "Successfully erased /dev/$disk"
    else
        print_error "Failed to erase /dev/$disk (exit code: $result)"
    fi
    
    return $result
}

# =============================================================================
# Main Function
# =============================================================================

main() {
    local -a disks
    local failed_disks=0
    
    # Print header
    clear
    print_header "$SCRIPT_NAME v$VERSION"
    
    # Preliminary checks
    check_root
    check_dependencies
    
    # Scan for disks
    mapfile -t disks < <(scan_disks)
    
    if [ ${#disks[@]} -eq 1 ]; then
        print_warning "Only one disk found: /dev/${disks[0]}"
        local disk_info
        disk_info=$(get_disk_info "${disks[0]}")
        echo -e "  ${CYAN}$disk_info${NC}"
        echo
        selected_disks=("${disks[0]}")
    else
        display_disk_menu "${disks[@]}"
        get_disk_selection "${disks[@]}"
    fi
    
    # Get format type
    display_format_menu
    get_format_selection
    
    # Final confirmation
    show_final_confirmation
    
    # Execute formatting
    print_section "Starting Format Operations"
    
    for disk in "${selected_disks[@]}"; do
        if ! execute_format "$disk"; then
            failed_disks=$((failed_disks + 1))
        fi
    done
    
    # Summary
    echo
    print_section "Operation Summary"
    
    if [ $failed_disks -eq 0 ]; then
        print_success "All operations completed successfully"
        echo -e "${GREEN}${BOLD}  Erased: ${#selected_disks[@]} disk(s)${NC}"
    else
        print_warning "Some operations failed"
        echo -e "${GREEN}  Successful: $((${#selected_disks[@]} - failed_disks)) disk(s)${NC}"
        echo -e "${RED}  Failed: $failed_disks disk(s)${NC}"
    fi
    
    # System shutdown
    echo
    print_warning "System will shutdown in 30 seconds..."
    print_info "Press Ctrl+C to cancel shutdown"
    
    sleep 5 && echo -e '\a' > /dev/tty1 2>/dev/null || true
    
    for i in {25..1}; do
        echo -ne "\r${YELLOW}Shutting down in $i seconds... ${NC}"
        sleep 1
    done
    
    echo
    print_info "Shutting down system..."
    poweroff
}

# =============================================================================
# Script Entry Point
# =============================================================================

main "$@"

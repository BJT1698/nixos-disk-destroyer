#!/usr/bin/env bash
# Avvio della TUI sulla console Linux (tty1): palette dei 16 colori sul tema scuro MVS, poi l'app.
# Se la TUI non parte resta lo script testuale originale (disk-format.sh).
set -u
palette=(101318 f85149 3fb950 d29922 2f81f7 a371f7 39c5cf c4c9d1
         6e7684 ff7b72 56d364 e3b341 58a6ff bc8cff 56d4dd e6e8ec)
for i in "${!palette[@]}"; do printf '\e]P%x%s' "$i" "${palette[$i]}"; done
dmesg -n 1 2>/dev/null   # niente messaggi del kernel sopra la TUI
clear
export TERM=linux
cd "$(dirname "$(readlink -f "$0")")"
if ! python3 app.py; then
    echo "La TUI si e' interrotta: avvio dello script testuale."
    sleep 3
    /etc/disk-format.sh
fi

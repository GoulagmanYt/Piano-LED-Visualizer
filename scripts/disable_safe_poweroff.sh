#!/usr/bin/env bash
# ==============================================================================
# Piano-LED-Visualizer : Disable Safe Power Off (Read-Write Mode)
# ==============================================================================
# Désactive la protection OverlayFS pour permettre les modifications
# permanentes (mises à jour, ajout de fichiers MIDI, réglages permanents).
# ==============================================================================
set -euo pipefail

run_cmd() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    sudo "$@"
  fi
}

echo "=== Piano-LED-Visualizer : Désactivation Safe Power Off ==="

if [ "$(run_cmd raspi-config nonint get_overlay_conf 2>/dev/null)" = "1" ]; then
  echo "[1/2] OverlayFS est déjà désactivé pour le prochain démarrage."
else
  echo "[1/2] Désactivation du mode OverlayFS..."
  run_cmd raspi-config nonint disable_overlayfs
  echo "      -> Mode Lecture/Écriture configuré pour le prochain démarrage."
fi

echo "[2/2] Statut actuel du système :"
if [ "$(run_cmd raspi-config nonint get_overlay_now 2>/dev/null)" = "0" ]; then
  echo "      -> Système actuellement en OverlayFS (Lecture seule)."
  echo "         Un redémarrage est nécessaire pour repasser en mode Lecture/Écriture."
  echo "         Relancez ce script après redémarrage pour rendre aussi boot modifiable."
else
  run_cmd raspi-config nonint disable_bootro
  boot_path=/boot/firmware
  mountpoint -q "$boot_path" || boot_path=/boot
  run_cmd mount -o remount,rw "$boot_path"
  echo "      -> Système actuellement en mode standard Lecture/Écriture."
fi

echo ""
echo "----------------------------------------------------------------------"
echo "INFO : Après redémarrage, le système sera en lecture/écriture standard."
echo "       N'oubliez pas de réactiver Safe Power Off avant de débrancher le piano :"
echo "       ./scripts/enable_safe_poweroff.sh"
echo "----------------------------------------------------------------------"

if [ "${1:-}" = "--reboot" ] || [ "${1:-}" = "-r" ]; then
  echo "Redémarrage immédiat demandé..."
  run_cmd reboot
elif [ -t 0 ]; then
  read -r -p "Souhaitez-vous redémarrer le piano maintenant pour repasser en lecture/écriture ? [o/N] " response
  if [[ "$response" =~ ^([yYoO])+$ ]]; then
    echo "Redémarrage en cours..."
    run_cmd reboot
  else
    echo "Pensez à redémarrer (sudo reboot) pour que le mode écriture soit effectif."
  fi
fi

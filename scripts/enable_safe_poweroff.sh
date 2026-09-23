#!/usr/bin/env bash
# ==============================================================================
# Piano-LED-Visualizer : Enable Safe Power Off (OverlayFS Protection)
# ==============================================================================
# Protège la carte SD contre la corruption en montant le système de fichiers
# racine (rootfs) en lecture seule avec une couche volatile en RAM (tmpfs).
# Réduit le risque lié aux coupures ; un arrêt propre reste préférable.
# ==============================================================================
set -euo pipefail

run_cmd() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    sudo "$@"
  fi
}

echo "=== Piano-LED-Visualizer : Safe Power Off (OverlayFS) ==="

# Check if overlayroot is installed
if ! dpkg -s overlayroot >/dev/null 2>&1; then
  echo "[1/3] Installation du paquet overlayroot..."
  run_cmd apt-get update -qq
  run_cmd apt-get install -y overlayroot
else
  echo "[1/3] overlayroot est déjà installé."
fi

# Check current configuration
if [ "$(run_cmd raspi-config nonint get_overlay_conf 2>/dev/null)" = "0" ]; then
  echo "[2/3] Safe Power Off (OverlayFS) est déjà programmé pour le prochain démarrage."
else
  echo "[2/3] Activation du mode OverlayFS..."
  run_cmd raspi-config nonint enable_overlayfs
  echo "      -> OverlayFS configuré avec succès."
fi

echo "[3/3] Statut du système :"
if [ "$(run_cmd raspi-config nonint get_overlay_now)" = "0" ]; then
  if [ "$(run_cmd raspi-config nonint get_bootro_conf)" != "0" ]; then
    echo "Boot n'est pas protégé. Désactivez OverlayFS, redémarrez, puis réactivez la protection."
    exit 1
  fi
else
  run_cmd raspi-config nonint enable_bootro
fi
if [ "$(run_cmd raspi-config nonint get_overlay_now 2>/dev/null)" = "0" ]; then
  echo "      -> Protection OverlayFS : ACTIVE (Lecture seule / RAM volatile)"
else
  echo "      -> Protection OverlayFS : EN ATTENTE DE REDÉMARRAGE (Sera actif au prochain boot)"
fi

echo ""
echo "----------------------------------------------------------------------"
echo "INFO : Racine protégée par OverlayFS et boot en lecture seule après redémarrage."
echo "       Un arrêt propre reste préférable ; aucune garantie contre une panne matérielle."
echo "       Toutes les modifications seront temporaires et en RAM."
echo "       Pour modifier les paramètres de façon permanente ou faire une mise à jour,"
echo "       utilisez : ./scripts/disable_safe_poweroff.sh"
echo "----------------------------------------------------------------------"

if [ "${1:-}" = "--reboot" ] || [ "${1:-}" = "-r" ]; then
  echo "Redémarrage immédiat demandé..."
  run_cmd reboot
elif [ -t 0 ]; then
  read -r -p "Souhaitez-vous redémarrer le piano maintenant ? [o/N] " response
  if [[ "$response" =~ ^([yYoO])+$ ]]; then
    echo "Redémarrage en cours..."
    run_cmd reboot
  else
    echo "Pensez à redémarrer (sudo reboot) pour que la protection soit effective."
  fi
fi

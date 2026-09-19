#!/usr/bin/env bash
# ==============================================================================
# Piano-LED-Visualizer : Status Safe Power Off (OverlayFS)
# ==============================================================================
set -euo pipefail

run_cmd() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    sudo "$@"
  fi
}

echo "=== Piano-LED-Visualizer : État Safe Power Off ==="

is_active=false
if [ "$(run_cmd raspi-config nonint get_overlay_now 2>/dev/null)" = "0" ]; then
  is_active=true
fi

is_conf=false
if [ "$(run_cmd raspi-config nonint get_overlay_conf 2>/dev/null)" = "0" ]; then
  is_conf=true
fi

if [ "$is_active" = "true" ]; then
  echo "État Actuel : [PROTÉGÉ] Le système racine est monté en OverlayFS (Lecture seule)."
  echo "              Vous pouvez débrancher l'alimentation sans risque de corrompre la carte SD."
else
  echo "État Actuel : [LECTURE/ÉCRITURE] Le système est monté en mode écriture standard."
  echo "              ATTENTION : Éteindre proprement (sudo poweroff) avant de débrancher,"
  echo "              ou activez le Safe Power Off avec : ./scripts/enable_safe_poweroff.sh"
fi

if [ "$is_conf" = "true" ]; then
  echo "Au Prochain Démarrage : Safe Power Off sera ACTIF."
else
  echo "Au Prochain Démarrage : Mode Lecture/Écriture sera ACTIF."
fi

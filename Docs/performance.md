# Performance et mesures

Les chiffres ci-dessous décrivent des essais datés, pas une garantie pour chaque
Pi ou chaque réseau. La latence physique touche → lumière ou son n'a pas été
mesurée. Ne pas additionner les percentiles de frontières différentes.

## Quelle frontière est mesurée ?

| Mesure | Comprend | Exclut |
| --- | --- | --- |
| Réception → traitement | Attente et traitement dans le visualiseur | Temps précédent le callback, réseau, réponse de l'instrument |
| Source synthétique → sortie instrumentée | Entrée ALSA virtuelle et pipeline MIDI | Clavier et liaison USB électrique, réception réseau distante |
| Frame en file → transmission terminée | Attente du rendu et transmission du pilote | Émission lumineuse mesurée par capteur |
| Publication logicielle / WebSocket simulé | Files, réveil des workers et appel du client simulé | Transport WebSocket réel, réseau et GPIO |
| ALSA du Pi → OSC sur le PC | Visualiseur, rtpmidid, réseau et pont RTP → OSC | Clavier, USB électrique, rendu audio/ASIO/VST |

## Résultats du pipeline MIDI et du réseau

- [Pipeline MIDI — 18 octobre 2026](measurements/midi_pipeline_2026-10-18.md) :
  protocole à 52 052 événements, latences, ordre et empreintes des messages.
- [Livraison RTP et QoS — 18 octobre 2026](measurements/rtp_delivery_2026-10-18.md) :
  comparaisons contrôlées du marquage réseau et essais de livraison longs.
- [Latence et jitter Wi-Fi — 18 octobre 2026](measurements/rtp_latency_2026-10-18.md) :
  médianes, p95/p99, pointes et incertitude de synchronisation des horloges.
  Le [JSON](measurements/rtp_latency_2026-10-18.json) et le
  [graphique](assets/rtp_latency_2026-10-18.png) sont conservés.

Dans le test MIDI local du 18 octobre, la source synthétique → sortie instrumentée
atteint une moyenne de 7,5080 ms et un p99 de 13,2153 ms à 20 ms par accord.
Le dernier essai Wi-Fi long livre 6 250/6 250 messages dans l'ordre mais atteint
97,34 ms. Un essai plus court sans perte ne prouve donc pas une latence bornée.

## Transmission LED — 23 septembre 2026

Essai avec entrée ALSA virtuelle, rendu GPIO/DMA réel et sortie MIDI simulée,
via `scripts/benchmark_pipeline.py`. Pédale, notes avec fades et accords rapides.

| Mesure | Résultat |
| --- | ---: |
| Événements envoyés / reçus / traités | 52 052 / 52 052 / 52 052 |
| Notes / états sustain restants | 0 / 0 |
| Buffer noir après arrêt | oui |
| RSS après échauffement | 48 123 904 octets, stable sur les échantillons |
| Réception MIDI → traitement moyen / maximum | 6,56 / 13,89 ms |
| Transmission LED moyenne / maximum | 10,42 / 18,46 ms |
| Frame en file → transmission terminée moyenne / maximum | 14,08 / 24,71 ms |

Ces durées ne sont pas une mesure photométrique. Pour 195 LED RGB à 800 kHz,
la transmission série seule représente 5,85 ms ; un affichage complet garanti
sous 5 ms est impossible avec ce câblage. La stabilité RSS observée ne démontre
pas une stabilité mémoire sur plusieurs jours.

## Publication logicielle — 13 novembre 2026

Pi Zero 2 W Rev 1.0, armv7l, Raspberry Pi OS Bookworm 12,
noyau `6.12.109+rpt-rpi-v7`, Python 3.11.2, révision `9f40b05`.
Trois processus indépendants exécutent `tools/latency_bench.py --json`, avec
120 messages par scénario, pendant que le service de production reste actif.
Tous les messages sont publiés et livrés dans chaque essai.

| Mesure | Moyenne, plage des 3 essais | p95, plage | Maximum, plage |
| --- | ---: | ---: | ---: |
| Admission MIDI → file WebSocket simulée | 0,218–0,282 ms | 0,265–0,685 ms | 0,371–0,894 ms |
| `WakeableDeque.append` → `send` async simulé | 1,311–1,327 ms | 0,887–0,976 ms | 72,081–72,607 ms |
| Même publication avec polling de 10 ms | 5,679–5,843 ms | 10,501–10,579 ms | 10,592–10,777 ms |

Le changement de port asynchrone bloque l'appelant pendant 12,048–12,430 ms,
contre 161,340–161,401 ms avec une notice synchrone simulée de 150 ms.
L'arrêt pendant une notice simulée de 400 ms bloque 0,454–0,464 ms.

Un contrôle séparé associe une pointe WebSocket de 74,167 ms à une collection
Python de génération 2 de 72,919 ms. Dans un autre processus avec le GC désactivé
uniquement après le scénario de publication, le maximum est de 1,089 ms et le
p95 de 0,903 ms. Ce contrôle appuie l'attribution de la pointe au GC du benchmark ;
il ne valide pas sa désactivation en production. Après les trois essais :
45,084 °C, `throttled=0x0`, charge 0,35 / 0,31 / 0,26.

Les [résultats JSON](measurements/software_latency_2026-11-13.json) contiennent
les trois essais et le contrôle GC. Ce benchmark n'ouvre ni sortie GPIO ni
port MIDI matériel et ne mesure pas le transport WebSocket ou RTP réel.

## Reproduire les mesures

Depuis la racine du dépôt, le benchmark logiciel fonctionne sans matériel :

```bash
python3 tools/latency_bench.py --json
```

Le benchmark complet ouvre le vrai GPIO/DMA et exige l'arrêt du service.
Sur le Pi, pendant une fenêtre de maintenance :

```bash
cd /home/Piano-LED-Visualizer
sudo bash <<'SH'
set -e
trap 'systemctl start visualizer.service' EXIT
systemctl stop visualizer.service
runner=/home/Piano-LED-Visualizer/.venv/bin/python
if [ ! -x "$runner" ]; then
    runner=/usr/bin/python3
fi
"$runner" scripts/benchmark_pipeline.py
SH
```

Le benchmark utilise une sortie MIDI instrumentée pour ne pas jouer sur le
piano. Les réglages d'essai restent en mémoire. `PLV_BENCHMARK_CHORDS` et
`PLV_BENCHMARK_INTERVAL_MS` permettent de régler la charge ;
`PLV_BENCHMARK_PROFILE` active cProfile. Ne pas comparer directement des latences
collectées avec et sans profilage.

Pour analyser une capture réseau avec `scripts/analyze_midi_latency.py`, il faut
les horodatages source et récepteur et la validation de l'identité et de l'ordre
des messages. Les JSON publiés sont des résumés ; ils ne remplacent pas ces
captures brutes. Voir le [protocole réseau](measurements/rtp_latency_2026-10-18.md#mesure).

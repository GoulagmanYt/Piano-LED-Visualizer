# Livraison RTP et marquage QoS — 18 octobre 2026

## Comparaison contrôlée

Même service, mêmes ports MIDI, même OSCMidi et mêmes 1 000 messages synthétiques.
Seule la table nftables `inet oscmidi_qos` du Pi change. Le récepteur PC compare
le nombre, l'ordre et l'empreinte des messages OSC. Le pare-feu général et les
réglages audio restent identiques.

Cette table, issue du script `scripts/setup-pi-qos.sh` d'un autre dépôt
(`RTP-OSC-Midi-tool`), imposait DSCP EF et une priorité de paquet 6 aux ports
UDP 5004/5005 et au processus rtpmidid. Ce ne sont pas des règles de rejet,
mais elles dégradent la livraison sur la liaison Wi-Fi testée avec `brcmfmac`
et le noyau `6.12.109+rpt-rpi-v7`.

| Configuration | Messages OSC / 1 000 attendus | Wi-Fi `tx failed`, avant → après |
| --- | ---: | --- |
| Aucun forçage QoS | 1 000, ordre et empreinte identiques | 222 → 222 |
| DSCP et priorité d'origine réactivés | 980 | 222 → 240 |
| DSCP EF seul | 986 | 240 → 254 |
| Priorité 6 seule | 966 | 254 → 282 |

Un premier essai avant modification livrait 984/1 000. Le retour des marquages
fait réapparaître les pertes ; retirer une seule famille de règles ne suffit
pas dans cette installation. Ces résultats ne prescrivent pas une politique
QoS universelle pour d'autres réseaux.

## Essais longs sans ces marquages

| Trajet et charge | Résultat |
| --- | --- |
| Source RTP synthétique directe, 52 000 messages | 52 000 paquets sortants capturés sur le Pi, 51 970 messages OSC ; `tx failed` 285 → 312 |
| Production, rafale de 10 000 messages | Tous reçus, traités, transmis et observés dans l'ordre sur le PC, empreinte identique |
| Production, 52 000 messages d'accords et pédale | 52 000 à chaque frontière du Pi, 51 990 messages OSC |
| Source RTP, arrivée instrumentée au port 5005 du PC puis relais local | 52 000 paquets et 52 000 messages OSC, ordre et empreinte identiques |
| Dernier essai de production directe, 52 000 messages, accords à 5 ms | 52 000 à chaque frontière et sur le PC, ordre et empreinte identiques |

L'empreinte du dernier essai est
`54c063633795bc04ec6b5f58dc8ff490bce9ae4307474c12f3e117a6852fcd57`.
Les files se vident et les pools ALSA n'ont aucun échec d'allocation.
Une session RTP indisponible pendant sa reconnexion est exclue des comparaisons
en régime connecté. Les ports OSCMidi habituels sont 5004/5005 ; les essais de
relais déplacent temporairement le serveur puis restaurent sa configuration.

## Interprétation et limites

Les marquages de la table dédiée ont été retirés sur le Pi testé, sans modifier
les autres tables du pare-feu. Relancer leur script générateur pourrait les
réinstaller. Le script de stabilité du visualiseur ne retire pas ces règles
externes : les examiner séparément.

Une capture AF_PACKET sur `wlan0` voit les paquets avant le résultat de leur
transmission radio. Le nombre de messages OSC manquants n'est pas égal par
construction au compteur de trames Wi-Fi échouées. Les comparaisons contrôlées
établissent l'effet des marquages ; elles ne localisent pas le mécanisme radio
ou firmware des pertes rares restantes.

Ces essais n'établissent ni un défaut du décodeur OSCMidi ni une livraison sans
perte en toute circonstance. Ils excluent le trajet USB électrique et la latence
physique touche → son. Les [mesures Wi-Fi longues](rtp_latency_2026-10-18.md)
montrent aussi des pointes de délai malgré une séquence intégralement reçue.

# Mesures du pipeline MIDI — 18 octobre 2026

## Protocole

`scripts/benchmark_pipeline.py` utilise une entrée ALSA virtuelle, le processeur
MIDI et le rendu GPIO/DMA de production, et une sortie instrumentée qui ne joue
pas sur le piano. Le service est arrêté pour l'essai puis relancé. Les réglages
d'essai restent en mémoire. Les résultats ci-dessous excluent cProfile.

Le test comprend pédale, notes seules et 2 000 accords de douze notes avec CC64 :
52 052 événements, environ 1 300 événements/s pendant les accords à 20 ms.
L'essai à 5 ms augmente la charge. Les compteurs et les empreintes SHA-256 sont
comparés aux frontières émission, réception, traitement et retransmission.

## Réception → traitement

| Configuration | Événements reçus / traités | Moyenne / maximum |
| --- | --- | ---: |
| Pipeline initial, benchmark d'origine | 52 052 / 52 052 | 43,7468 / 339,6860 ms |
| Consommateurs indépendants, benchmark d'origine | 52 052 / 52 052 | 17,8742 / 90,7361 ms |
| Traçage exact, quatre cœurs | 52 052 / 52 052 | 28,1242 / 192,5186 ms |
| Même traçage, affinité CPU 2 par taskset | 52 052 / 52 052 | 5,7381 / 28,3685 ms |
| Affinité automatique depuis l'application | 52 052 / 52 052 | 5,7660 / 44,4138 ms |
| File native, accords à 20 ms | 52 052 / 52 052 | 4,5544 / 15,7426 ms |
| File native, accords à 5 ms | 52 052 / 52 052 | 9,5570 / 53,6672 ms |

Le traçage exact calcule des empreintes et ajoute du travail ; les lignes avec
et sans ce traçage ne sont pas des comparaisons à instrumentation identique.

## Source synthétique → sortie instrumentée

| Configuration | Moyenne | p99 |
| --- | ---: | ---: |
| Affinité automatique, avant file native | 11,0674 ms | 22,5637 ms |
| File native, accords à 20 ms | 7,5080 ms | 13,2153 ms |
| File native, accords à 5 ms | 11,9746 ms | 31,7600 ms |

L'attente de sortie moyenne du premier scénario est de 4,7111 ms. Les trois
séquences ont des empreintes identiques aux quatre frontières :
`f6c2a1ecac76ebaf952b04ded439fa8546781829790914bb5c6b86e6b773ae05`.
Les files se vident, aucune note ni pédale ne reste active et le buffer LED
est noir après arrêt. Les deux essais avec file native n'ont aucun échec
d'allocation ALSA.

Le microbenchmark de copie des buffers LED, avec les mêmes buffers de 195 LED
et 10 000 appels, passe de 124,29 à 18,98 µs par appel avec une copie par tranche.

## Contrôles de livraison réseau

Ces essais précèdent le retrait des marquages QoS décrits dans les
[mesures de livraison RTP](rtp_delivery_2026-10-18.md).

| Test | Observation |
| --- | --- |
| Production, 1 000 événements, capture de sortie du Pi | 1 000 reçus, traités, envoyés et paquets RTP capturés |
| Même essai, sortie OSCMidi sur le PC | 976/1 000 messages OSC ; essais suivants 968 puis 966 |
| Production, rafale de 10 000 événements | 10 000 transmis par le Pi, 9 938 observés sur le PC |
| UDP indépendant Pi → PC, deux modes d'émission | 1 000/1 000 dans l'ordre pour chaque mode |
| RTP synthétique direct Pi → OSCMidi | 962/1 000 messages OSC |
| RTP en boucle locale sur le PC | 1 000/1 000, ordre et empreinte identiques |
| RTP via relais temporaire sur le PC puis OSCMidi local | 1 000 paquets reçus et 1 000 messages OSC, empreinte identique |

Une capture sortante sur le Pi ne prouve pas la livraison radio. Ces durées
logicielles excluent le clavier, le transport USB électrique et la lumière
des LED ; zéro perte dans ces séquences ne garantit pas la livraison pendant
une déconnexion ou un blocage prolongé. La file native reste finie.

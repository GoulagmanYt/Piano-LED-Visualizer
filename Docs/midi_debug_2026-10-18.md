# Diagnostic MIDI du Raspberry Pi — 18 octobre 2026

Matériel mesuré : Raspberry Pi Zero 2 W Rev 1.0, quatre cœurs, gouverneur
`performance`. Entrée de production USB AudioDevice, sortie rtpmidid/OSCMidi.
Base logicielle MIDI : `7a33cd2` ; base Git de la correction : `931c884`.

## Causes reproduites et corrections

- Un verrou commun sérialisait inutilement réception, lecture des files,
  retransmission et publication web. L'échantillonnage des threads a montré
  les attentes dans ces quatre chemins. Les consommateurs de deques utilisent
  leurs opérations atomiques CPython ; les opérations composées des producteurs
  et de l'ordonnanceur restent protégées. Le verrou de sortie de MidiPorts
  conserve la sérialisation envoi/reconnexion. Une vidange tolère un effacement
  concurrent de sa file.
- Le callback réveillait le rendu en tenant encore le verrou des files. Le
  réveil intervient après libération, et les notifications d'une même rafale
  sont regroupées. Le rendu acquitte l'activité avant de consommer et enchaîne
  sans délai lorsqu'une tranche laisse des messages en attente.
- La notification de sortie est décidée immédiatement après l'ajout, sous le
  verrou des producteurs, puis envoyée hors verrou. Un test avec deux callbacks
  concurrents et le vrai thread de sortie vérifie le réveil, y compris dans la
  fenêtre où une reconnexion laisse brièvement deux entrées ouvertes.
- Sur le Zero 2 W, les échanges du GIL entre cœurs ajoutaient beaucoup de
  latence. Le processus principal fixe son affinité avant de créer les composants
  et leurs threads. Le mode automatique s'applique seulement au Zero 2 W : CPU 2
  si autorisé, sinon premier CPU autorisé. Les autres cartes restent inchangées.
  Les threads déjà créés à l'import ne sont pas déplacés.
- Les diagnostics affichaient essentiellement la durée de l'appel natif
  d'envoi ; ils ne mesuraient pas le délai passé dans sa file. La nouvelle
  métrique `rtp_live_queue_wait` mesure cette attente. `midi_callback_calls`
  compte aussi les événements d'entrée acceptés sur le chemin rapide.

Pour désactiver le réglage d'affinité, définir `PLV_MIDI_CPU_AFFINITY=off`
dans l'environnement du service et le redémarrer. Une valeur numérique permet
un choix explicite parmi les CPU déjà autorisés ; une erreur ne bloque pas le
démarrage.

## Protocole et résultats

`scripts/benchmark_pipeline.py` utilise une entrée ALSA virtuelle, le vrai
processeur MIDI, le vrai rendu GPIO/DMA et une sortie MIDI instrumentée sans
jouer les notes sur le piano. Le service est arrêté pour l'essai et relancé
automatiquement par le pilote de maintenance. Les réglages d'essai sont en
mémoire. Le test vérifie pédale, notes seules, puis 2 000 accords de douze notes
avec CC64, soit 52 052 événements et environ 1 300 événements/s pendant la phase
d'accords. Les chiffres ci-dessous excluent le profilage cProfile.

| Configuration | Événements reçus / traités | Réception → traitement moyen / max |
| --- | --- | --- |
| Avant correction, benchmark d'origine | 52 052 / 52 052 | 43,7468 / 339,6860 ms |
| Consommateurs indépendants, benchmark d'origine | 52 052 / 52 052 | 17,8742 / 90,7361 ms |
| Correction + traçage exact, quatre cœurs | 52 052 / 52 052 | 28,1242 / 192,5186 ms |
| Même traçage, affinité CPU 2 par taskset | 52 052 / 52 052 | 5,7381 / 28,3685 ms |
| Affinité automatique depuis l'application | 52 052 / 52 052 | 5,7660 / 44,4138 ms |

Le traçage exact ajoute volontairement du travail : empreintes SHA-256 des
octets et compteurs aux quatre frontières émission, réception, traitement,
retransmission. Sur l'essai avec affinité automatique, les quatre empreintes
sont identiques :
`f6c2a1ecac76ebaf952b04ded439fa8546781829790914bb5c6b86e6b773ae05`.
Il n'y a ni perte, ni doublon, ni inversion dans cette séquence testée.
L'attente de sortie est 4,7111 ms en moyenne ; le délai complet de la source
synthétique à la sortie instrumentée est 11,0674 ms en moyenne, p99 22,5637 ms.
Les files se vident ; aucune touche ni pédale ne reste active ; le buffer LED
est noir après arrêt ; aucun échec d'allocation ALSA n'est enregistré.

Les tests de régression reproduisent notamment le blocage sur notification,
les callbacks qui se chevauchent, les attentes avec un lot restant, une
retransmission absente, des messages inversés et les restrictions d'affinité.
Une revue indépendante a contrôlé les invariants de concurrence et demandé
le test de chevauchement avant validation de la correction.

## Limites des mesures

Le zéro perte constaté concerne les séquences testées. Il ne garantit pas
la livraison pendant une déconnexion USB ou réseau, ni sous toute charge
possible. Les durées logicielles ne mesurent ni la latence physique touche →
lumière ni la livraison UDP à l'autre ordinateur. Le benchmark n'émet pas
sur le réseau ; l'état de la session et le trajet en service sont contrôlés
séparément après déploiement. Un profilage cProfile est utile au diagnostic,
mais ses résultats de latence ne sont pas comparés aux essais sans profilage.

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
- Un essai à quatre fois le débit nominal a ensuite reproduit des pertes
  **avant le callback Python** : 13 052 événements émis, 10 954 reçus. La file
  ALSA atteignait son maximum de 2 000 événements. Une tentative à 8 192 est
  rejetée sur ce noyau ; cette limite est définie dans
  [Linux 6.12](https://github.com/torvalds/linux/blob/v6.12/include/sound/seq_kernel.h).
  Le backend Mido/RtMidi installe un callback Python sur le thread ALSA, qui
  attend alors le GIL avant de continuer à vider le noyau.
- `BufferedMidiInput` utilise une file **native C++ de 32 768 événements** sans
  callback Python sur le lecteur ALSA. Un consommateur Python dépile ensuite
  les messages dans l'ordre. La file noyau est dimensionnée avant abonnement
  à la source, car son redimensionnement efface son contenu. Ce réglage reste
  facultatif en cas d'erreur OS. L'arrêt attend le consommateur avant de libérer
  les ressources natives ; une erreur du lecteur est visible et provoque une
  reconnexion. Les autres plateformes/backends conservent leur entrée Mido.
- Les durées et compteurs disposent de verrous indépendants par métrique,
  évitant une seconde contention globale. Leur mémoire dépend des noms de
  métriques, pas du nombre de threads créés. Les copies de buffers LED passent
  par une affectation de tranche en C : 124,29 → 18,98 microsecondes par appel
  dans le microbenchmark de 10 000 appels/195 LED, avec les mêmes buffers.
  Les copies destinées à la page Practice ne sont plus produites lorsqu'elle
  est inactive.

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
| Version finale, file native, accords à 20 ms | 52 052 / 52 052 | 4,5544 / 15,7426 ms |
| Version finale, file native, accords à 5 ms | 52 052 / 52 052 | 9,5570 / 53,6672 ms |

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

La **version finale** passe les deux essais de 52 052 événements avec les
quatre empreintes identiques ci-dessus. Le test à 5 ms reproduit la charge
qui provoquait les pertes avant la file native. Il n'y a plus d'échec
d'allocation ALSA dans ces essais. Source synthétique → sortie instrumentée :
7,5080 ms en moyenne / p99 13,2153 ms à 20 ms par accord ; 11,9746 ms en moyenne /
p99 31,7600 ms à 5 ms par accord. Cette mesure inclut l'attente avant le callback
Python ; la métrique réception → traitement seule ne mesure pas toute cette
attente.

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
La file native reste finie : elle ne garantit pas la livraison sous une charge
illimitée, pendant un blocage prolongé ou pour une taille arbitraire de SysEx.

## Vérification avec OSCMidi relancé

La version `7743cdc` a été poussée et installée par le bouton de mise à jour
de la page web. Après le retour de l'interface USB et le lancement d'OSCMidi,
la session réseau est connectée à `192.168.1.92:5004/5005`.

Le contrôle final utilise le service de production et son entrée ALSA
existante. Les notes synthétiques sont injectées directement dans cette
entrée ; il ne mesure donc pas le trajet électrique dans l'interface USB.
Un récepteur indépendant sur le PC écoute la sortie OSC déjà configurée
par OSCMidi sur `127.0.0.1:9000`, sans modifier ses réglages audio ou MIDI.
Il compare le nombre, l'ordre et l'empreinte des messages attendus.

| Test | Résultat observé |
| --- | --- |
| Production, 1 000 événements, capture de sortie du Pi | 1 000 reçus, traités et envoyés ; 1 000 paquets RTP capturés, séquences continues, aucune perte de capture |
| Même test, sortie d'OSCMidi sur le PC | 976 / 1 000 messages OSC, comparaison exacte en échec |
| Autres essais de production à 1 000 événements | 968 puis 966 messages OSC, résultat non fiable |
| Production, rafale de 10 000 événements | 10 000 reçus, traités et envoyés par le Pi ; 9 938 messages OSC observés sur le PC |
| UDP indépendant Pi → PC, deux modes d'émission | 1 000 / 1 000 dans l'ordre pour chaque mode |
| RTP synthétique directement du Pi vers OSCMidi, sans le visualiseur ni rtpmidid | 962 / 1 000 messages OSC |
| RTP synthétique en boucle locale sur le PC | 1 000 / 1 000, ordre et empreinte identiques |
| Même source RTP du Pi, arrivée instrumentée sur un relais temporaire du PC, puis OSCMidi en local | 1 000 paquets RTP uniques reçus dans l'ordre ; 1 000 messages OSC, empreinte identique |

À ce stade, ces essais confirmaient les corrections du chemin MIDI local
du Pi, mais ne localisaient pas les pertes réseau. L'attribution provisoire
au trajet de réception du PC était prématurée : une capture de sortie sur
le Pi ne prouve pas que la transmission Wi-Fi a réussi. Le diagnostic
complémentaire ci-dessous a identifié un forçage QoS sur le Pi.
Le relais était un outil temporaire, arrêté après l'essai.

À la fin des essais, les services `visualizer` et `rtpmidid` sont actifs,
les files du Pi sont vides, le pool ALSA affiche zéro échec d'allocation
et un pic de 57 cellules sur 2 000. Le Pi est à 48,3 °C avec
`throttled=0x0`. OSCMidi indique zéro perte de sa file MIDI audio, zéro xrun,
aucune file en attente et un transport sain, mais son compteur cumulatif
signale 152 paquets RTP manquants depuis son démarrage. Ce compteur cumule
les différents essais et ne correspond pas au seul test de 10 000 événements.

**À 16 h, la validation « zéro perte jusqu'au PC » échouait encore.**
Les pertes n'étaient pas reproduites dans le traitement local du Pi.
Les résultats complets et les scripts de maintenance sont conservés dans
`.maintenance/` sur le poste de développement.

## Origine réseau identifiée à 20 h

La table nftables `inet oscmidi_qos` du Pi imposait DSCP EF et
`meta priority set 0:6` aux ports UDP 5004/5005 et au processus rtpmidid.
Les essais contrôlés reproduisent les pertes quand ces règles sont actives
et les suppriment dans le test de 1 000 messages quand elles sont retirées.
Chaque famille de règles, testée seule, reproduit aussi le défaut.

Le fichier générateur est `scripts/setup-pi-qos.sh` dans le dépôt OSCMidi ;
sa configuration persistante était `/etc/nftables.d/oscmidi-qos.nft` sur le Pi.
Les règles ont été désactivées avec sauvegarde, sans modifier les autres
tables du pare-feu. Un test de production de 10 000 messages passe ensuite
avec compteurs, ordre et empreinte identiques jusqu'à la sortie OSC du PC.

Les essais longs et les limites restantes sont détaillés dans
[le diagnostic de l'origine RTP](rtp_loss_origin_2026-10-18.md).

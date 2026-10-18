# Origine des pertes RTP — 18 octobre 2026

## Cause démontrée

Le Pi appliquait des forçages QoS réseau inadaptés à la liaison Wi-Fi testée :
DSCP EF et priorité de paquet 6. La configuration concernée est
`/etc/nftables.d/oscmidi-qos.nft`, table `inet oscmidi_qos`.
Elle était générée par `scripts/setup-pi-qos.sh` du dépôt
`RTP-OSC-Midi-tool`, distinct du visualiseur.
Le fichier installé avait une date de modification du 18 octobre à 10:11.

Les règles marquaient les destinations et sources UDP 5004/5005, ainsi que
les paquets du compte rtpmidid, UID 105 :

```nft
udp dport { 5004, 5005 } counter ip dscp set ef
udp dport { 5004, 5005 } counter meta priority set 0:6
meta skuid 105 counter ip dscp set ef
meta skuid 105 counter meta priority set 0:6
```

Des règles équivalentes existaient pour IPv6 et les ports source.
Il ne s'agissait pas de règles `drop` : elles modifiaient la classification
du trafic, avec un effet défavorable sur la transmission Wi-Fi observée.
Le pilote du Pi est `brcmfmac`, noyau `6.12.109+rpt-rpi-v7`.

## Preuve par changement d'une variable

Même service de production, mêmes ports MIDI, même OSCMidi, mêmes 1 000
messages de notes synthétiques. Seule la table QoS dédiée change.
Le récepteur sur le PC compare la sortie OSC d'OSCMidi à la séquence attendue.
Le pare-feu général et les réglages audio restent identiques.

| Configuration | Messages OSC / 1 000 attendus | Compteur Wi-Fi `tx failed`, avant → après |
| --- | --- | --- |
| Aucun forçage QoS | **1 000, ordre et empreinte identiques** | 222 → 222 |
| Configuration d'origine réactivée | 980 | 222 → 240 |
| Marquage DSCP EF seul | 986 | 240 → 254 |
| Priorité forcée 6 seule | 966 | 254 → 282 |

L'essai initial avant modification donnait aussi 984 / 1 000. Le retour de
la configuration d'origine après le premier essai sans QoS fait réapparaître
le problème. Il faut retirer les deux types de forçage ; retirer uniquement
la priorité 6 ou uniquement DSCP ne suffit pas dans cette installation.

Le nombre de messages OSC manquants ne correspond pas exactement au nombre
de trames Wi-Fi échouées : RTP et la récupération MIDI ajoutent d'autres
frontières de comptage. La causalité repose sur les essais contrôlés, pas
sur une égalité supposée entre ces compteurs.

## Pourquoi les premières captures semblaient incriminer le PC

La capture AF_PACKET sur `wlan0` voit les paquets sortants avant de connaître
le succès de leur transmission radio. Elle peut donc contenir une séquence
RTP complète alors qu'OSCMidi ne la reçoit pas intégralement.

Le test UDP indépendant utilisait le port 19001 ; le relais utilisait
19010/19011. Ces flux évitaient les règles liées aux ports 5004/5005.
Le relais démontrait que le décodage d'OSCMidi pouvait fonctionner, mais ne
constituait pas une comparaison équivalente du trafic marqué par le Pi.

Un essai synthétique long, après retrait des forçages, capture 52 000 paquets
RTP uniques dans l'ordre sur le Pi, sans perte de capture. Seulement 51 970
messages ressortent d'OSCMidi ; le compteur d'échecs d'émission Wi-Fi passe
de 285 à 312. Cela reproduit des pertes même en contournant le visualiseur
et rtpmidid. Le mécanisme radio ou firmware exact ne peut pas être attribué
à partir de ces seules mesures.

## Correction appliquée au Pi et vérification

Les neuf règles de forçage de la table `oscmidi_qos` ont été retirées en
mémoire et dans son fichier persistant. La table et sa chaîne restent
présentes, sans règle de marquage. Les autres tables nftables sont préservées.
La configuration complète passe `nft -c -f /etc/nftables.conf`.

Sauvegarde de la configuration initiale :
`/etc/nftables.d/oscmidi-qos.nft.bak-20261018-200416`.
Le dépôt source d'OSCMidi n'a pas été modifié : relancer son ancien script
QoS réinstallerait les réglages incriminés.

Résultats après correction :

- Production, rafale de **10 000 messages** : tous reçus, traités et transmis
  par le Pi ; tous observés dans l'ordre en sortie OSC sur le PC, empreinte
  identique.
- Production, **52 000 messages** d'accords de douze notes et de pédale :
  52 000 à chaque frontière logicielle du Pi, 51 990 messages OSC observés.
  Il subsiste donc des pertes rares dans cet essai long.
- Source RTP synthétique, arrivée instrumentée sur le **port 5005 du PC**,
  puis relais local vers OSCMidi : **52 000 paquets reçus dans l'ordre**,
  puis **52 000 messages OSC**, sans doublon et avec empreinte identique.
  Le serveur avait été déplacé temporairement sur 5006/5007 pour libérer
  le port mesuré, puis remis sur 5004/5005.
- Dernier essai en **production directe, 52 000 messages** d'accords et de
  pédale, intervalle de 5 ms par accord : **52 000 reçus, traités et transmis
  par le Pi ; 52 000 messages OSC dans l'ordre sur le PC**, empreinte identique
  `54c063633795bc04ec6b5f58dc8ff490bce9ae4307474c12f3e117a6852fcd57`.
  Les files se vident et les pools ALSA n'ont aucun échec d'allocation.

Le dernier essai est exécuté après restauration du serveur OSCMidi sur ses
ports d'origine et rafraîchissement de la découverte Avahi/rtpmidid. Un essai
lancé pendant cette reconnexion avait une session réseau indisponible ; il
est exclu des comparaisons de pertes en régime connecté. Le précontrôle du
pilote de maintenance exige désormais une session prête avant émission.
Le fichier de configuration d'OSCMidi sur le PC est identique à sa sauvegarde
prise avant les manipulations ; aucun réglage audio n'a été modifié.

Les pertes fréquentes provoquées par la configuration QoS sont établies et
ce réglage est corrigé. Les essais ne garantissent pas zéro perte sur une
liaison Wi-Fi dans toutes les conditions. Ils ne prouvent pas de défaut
du décodeur OSCMidi : lorsque tous les paquets arrivent dans l'ordre dans
le test instrumenté, la séquence complète ressort correctement.

Les scripts, rapports JSON, captures et empreintes sont conservés dans
`.maintenance/` sur le poste de développement. Les injections passent par
ALSA ou une source RTP synthétique ; elles ne mesurent pas l'interface USB
électrique ni la latence physique des touches au son.

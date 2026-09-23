# Corrections et validation sur Raspberry Pi — 23 septembre 2026

Base : `ef6b93f`. Sauvegarde avant intervention :
`/var/backups/plv-audit-20260922/before.tar.gz`, également copiée sur le poste
dans `.maintenance/before-fixes-20260922.tar.gz`.

## Corrections

- Sortie MIDI : fermeture et reconnexion sérialisées avec les envois ; une
  désactivation vide les files sortantes et empêche leur accumulation. Les
  transitions libèrent pédale, notes et sons sur les 16 canaux. Une panne
  d'envoi persistante clôt la session après une seconde de tentatives.
- RTP : le port UDP ne remplace plus le port TCP du transport fiable. Le
  réglage du Pi a été réparé de 5004 vers 5056. La sélection d'autoconnexion
  est réappliquée par le moniteur, y compris après disparition du démon ou
  arrivée tardive du pair. Le démon conserve les annonces mDNS mais ne crée
  plus lui-même les routes sortantes. Les clients orphelins sont retirés.
- Interface : affichage des noms RTP comme texte, sans interprétation HTML.
- Journalisation : chemin relatif à l'installation, surcharge possible par
  `PLV_LOG_PATH`, ouverture différée ; tests portables hors du Pi.
- Service : secours `ExecStopPost` pour transmettre une trame noire après un
  crash ; suppression effective des dépendances réseau au démarrage ; code
  possédé par root, répertoires 755 et absence d'écriture groupe/autres.
- Boot : correction de `[all]initial_turbo=30` et ajout sûr du saut de ligne.
- Protection SD : scripts pour OverlayFS et boot en lecture seule, sans
  promettre une protection absolue contre toutes les pannes matérielles.

## Charge et latence

Le test initial a perdu 260 événements sur 52 048. Le pool d'entrée ALSA de
RtMidi ne contenait que 200 événements. Il est porté à **2000**, avec lecture
de contrôle : les tailles excessives peuvent être ignorées par le noyau.
La modification utilise les ioctl publics sur les descripteurs du processus,
sans accéder aux pointeurs privés de RtMidi.

Le partage du GIL est réglé à 1 ms ; les lots du processeur MIDI sont plus
petits ; les statistiques des files sont échantillonnées à 20 Hz, avec une
lecture forcée pour les diagnostics demandés. Les maxima de profondeur des
files sont donc des maxima échantillonnés. Les durées MIDI restent mesurées
pour chaque événement. Le gouverneur CPU `performance` et l'ordonnanceur
normal avec nice -10 remplacent le RR global des threads Python, qui a
donné de mauvais résultats sous charge. Le démon RTP reste indépendant.

Validation finale par `scripts/benchmark_pipeline.py` : entrée ALSA virtuelle,
rendu de production, GPIO/DMA réels, sortie MIDI simulée pour ne pas jouer sur
le piano. Pédale vérifiée en mode Pedal, notes seules avec fades et accords
rapides. Ce test ne mesure pas la latence d'un instrument USB ou du réseau.

| Mesure | Résultat |
|---|---:|
| Événements envoyés / reçus / traités | 52 052 / 52 052 / 52 052 |
| Notes / états sustain restants | 0 / 0 |
| Buffer noir après arrêt | oui |
| RSS après échauffement | 48 123 904 octets, stable sur les échantillons |
| Réception MIDI → traitement moyen / maximum | 6,56 / 13,89 ms |
| Transmission LED moyenne / maximum | 10,42 / 18,46 ms |
| Image en file → transmission terminée moyen / maximum | 14,08 / 24,71 ms |

185 tests logiciels et 4 sous-tests réussis ; `test_screen.py` exclu car
interactif/matériel. Quatre avertissements préexistants concernent l'extraction
tar dans les tests de mise à jour. Crash SIGKILL testé : trame noire de secours
transmise, attente DMA terminée, puis redémarrage automatique. Sélection RTP
None puis OSCMidi testée : zéro client sortant, puis une seule session.

Ces chiffres ne sont pas une mesure physique touche → lumière. À 195 LED RGB
et 800 kHz, la transmission série seule prend 5,85 ms : un affichage complet
garanti sous 5 ms reste impossible avec ce câblage. Les essais ne prouvent pas
l'absence de tout défaut ni une stabilité mémoire sur plusieurs jours.

## Maintenance avec OverlayFS

Les réglages et morceaux ajoutés lorsque la protection est active sont
volatils et disparaissent au redémarrage. Pour les conserver ou mettre à jour :

1. Exécuter `sudo bash scripts/disable_safe_poweroff.sh`, puis redémarrer.
2. Relancer le script pour remettre également boot en écriture.
3. Effectuer les changements permanents.
4. Exécuter `sudo bash scripts/enable_safe_poweroff.sh`, puis redémarrer.
5. Vérifier `sudo bash scripts/status_safe_poweroff.sh`.

Un arrêt propre reste préférable. Les sauvegardes sont à conserver hors du Pi.

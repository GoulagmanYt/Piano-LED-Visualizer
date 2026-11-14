# Piano LED Visualizer

[English](README.md) · [Français](README.fr.md)

Éclairez les touches de votre piano pendant que vous jouez. Piano LED Visualizer
fonctionne sur Raspberry Pi et pilote un ruban WS2812B à partir de messages MIDI
USB ou réseau. L’interface web permet de choisir les couleurs et les ports MIDI,
de lire des morceaux et d’enregistrer votre jeu. Un écran LCD optionnel fournit
des commandes locales.

Ce fork de [onlaj/Piano-LED-Visualizer](https://github.com/onlaj/Piano-LED-Visualizer)
cible le Raspberry Pi Zero 2 W et s’intègre à
[OSC Midi Tool](https://github.com/GoulagmanYt/RTP-OSC-Midi-tool).
La documentation technique de référence est en anglais.

## Fonctionnalités

- Couleurs selon les notes, la vélocité ou la vitesse de jeu, avec fond lumineux,
  fondu et animations.
- Lecture et enregistrement MIDI, apprentissage guidé et pont Synthesia Learning
  optionnel.
- Entrée USB automatique et routage RTP-MIDI avec diagnostic des connexions.
- Interface web disponible en douze langues et commandes LCD optionnelles.
- Estimation de la consommation du ruban et réglage de sa puissance.
- Mises à jour avec sauvegarde de la configuration, contrôle du service et
  tentative de restauration en cas d’échec.

## Matériel et installation

Il faut un Raspberry Pi Zero 2 W, une carte microSD d’au moins 16 Go avec
Raspberry Pi OS Lite, un ruban WS2812B et une alimentation régulée de 5 V adaptée
au nombre de LED. Le piano peut être relié en USB MIDI ou par le réseau.

Alimentez le ruban par sa propre connexion d’alimentation et reliez sa masse à
celle du Pi. Ne faites pas passer le courant du ruban par le connecteur GPIO.
Le Pi et le ruban nécessitent du 5 V : une alimentation de 9 V ou 12 V les
endommagerait.

Le [guide d’installation](Docs/manual_installation.md) décrit Raspberry Pi OS
Lite Bookworm ou Trixie, les dépendances, SPI et le service systemd. Consultez le
[guide Wi-Fi](Docs/wifi_setup.md) pour une installation sans écran.
L’installateur configure les paquets système, le nom d’hôte, le compte `plv`
et les services. Examinez [autoinstall.sh](autoinstall.sh), puis lancez-le sur le Pi :

```bash
curl -fsSLo autoinstall.sh https://raw.githubusercontent.com/GoulagmanYt/Piano-LED-Visualizer/master/autoinstall.sh
sudo bash autoinstall.sh
```

Une fois le service démarré, ouvrez `http://pianoledvisualizer.local` dans votre
navigateur, ou utilisez l’adresse IP du Pi. Réglez le nombre de LED, le décalage
des touches et la luminosité pour votre ruban avant utilisation.

## Connexions MIDI

Dans **Ports Settings**, choisissez **Auto** sous **Active** pour sélectionner
automatiquement une entrée MIDI locale. Le périphérique actif reste sélectionné
si un autre apparaît. Les sessions RTP-MIDI doivent être choisies explicitement.
La sortie **Playback** est indépendante : choisissez sa destination ou
désactivez-la si vous utilisez uniquement les LED.

Pour OSC Midi Tool, configurez le routage sur l’ordinateur, puis choisissez le
pair dans **RTP MIDI Auto-Connect**. Le [guide RTP-MIDI](Docs/rtpmidi_stability.md)
détaille les services et le dépannage.

Pour Synthesia, configurez les quatre ports dans **Synthesia Learning bridge**,
sélectionnez **Learning**, enregistrez et redémarrez le visualiseur. Déconnectez
d’abord les liaisons MIDI directes entre le piano et l’ordinateur. Consultez les
[instructions du pont Learning](Docs/features.md#learning_with_synthesia).

## Mises à jour

Utilisez **Settings → Update Visualizer** dans l’interface web. Pour une mise à
jour par SSH, consultez les [commandes du README anglais](README.md#updating).
Les modifications locales du code bloquent la mise à jour.

## Documentation et mesures

| Guide | Contenu |
| --- | --- |
| [Installation](Docs/manual_installation.md) | Système, dépendances et service |
| [Image préinstallée](Docs/image_build.md) | Construction et validation d’une image |
| [Fonctionnalités](Docs/features.md) | Couleurs, morceaux, apprentissage et séquences |
| [Wi-Fi](Docs/wifi_setup.md) | Réseau, point d’accès et récupération |
| [RTP-MIDI](Docs/rtpmidi_stability.md) | Connexions MIDI réseau |
| [Périphériques externes](Docs/external_devices.md) | Boutons, capteurs et commandes |
| [Détection du couvercle](Docs/cover_detection.md) | Installation du capteur |
| [Architecture](Docs/architecture.md) | Modules, routage et gestion des ressources |
| [Performances et mesures](Docs/performance.md) | Méthodes, résultats et limites |

Les mesures logicielles publiées ne représentent pas une mesure physique
touche → lumière ou son. Le réseau Wi-Fi testé présente encore des retards
occasionnels et des pertes ; consultez les conditions de chaque essai.

## Développement et licence

Le point d’entrée est `visualizer.py`, les modules matériels et MIDI sont dans
`lib/` et l’interface Flask dans `webinterface/`. Les commandes de test et les
consignes de contribution figurent dans le
[README anglais](README.md#development). Pour signaler un problème, indiquez
le modèle du Pi, le système, les périphériques MIDI et les étapes permettant de
le reproduire dans les [issues](https://github.com/GoulagmanYt/Piano-LED-Visualizer/issues).

Projet sous [licence MIT](LICENSE), basé sur le travail d’onlaj. Ce fork est
maintenu par GoulagmanYt. Les crédits des animations figurent dans le
[README anglais](README.md#credits-and-license).

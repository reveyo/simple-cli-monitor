# Simple Cli Moniteur 🐧💻

Un moniteur système léger, orienté objet et optimisé pour Linux (Ubuntu). 
Conçu spécifiquement pour les configurations matérielles hybrides (CPU + Multi-GPU), ce moniteur limite au maximum l'empreinte processeur et la consommation de batterie des PC portables.

## 🌟 Pourquoi ce script ?

Contrairement aux outils standards (comme `htop`, `btop` ou `sensors`) qui peuvent utiliser de nombreux sous-processus, ce script est conçu pour la performance :
- **Ultra-léger** : Lecture directe et optimisée des pseudo-fichiers Linux (`/proc` et `/sys`) pour un impact CPU quasi nul.
- **Mise en cache matérielle** : L'arborescence thermique et GPU est scannée une seule fois au démarrage pour réduire la surcharge d'I/O.
- **Support Multi-GPU** : Détection simultanée des cartes Nvidia (via NVML) et des iGPU Intel/AMD (via l'API DRM).
- **Rendu natif sans scintillement** : Utilisation exclusive des séquences d'échappement ANSI pour l'affichage terminal, sans dépendre de bibliothèques lourdes.

## 📊 Fonctionnalités

- **CPU** : Charge (%), température et fréquence (GHz) cœur par cœur.
- **RAM** : Utilisation en temps réel avec barre de progression.
- **I/O Disques** : Vitesse de lecture/écriture (Mo/s) et températures des SSD NVMe/SATA.
- **GPU** : Charge, température et utilisation VRAM/Fréquence (Nvidia + Intel/AMD).
- **Batterie** : Pourcentage, statut (En charge/Sur batterie) et consommation instantanée en Watts.

## 📋 Prérequis

- **OS** : Linux (Testé sur Ubuntu / Alpine / Debian)
- **Python** : 3.6+ (Aucune dépendance requise pour le cœur du script)

*(Optionnel)* Si vous possédez une carte graphique Nvidia, l'installation de la librairie officielle NVML est recommandée pour des remontées plus précises :
```bash
pip install nvidia-ml-py
```

## 🚀 Installation & Utilisation

1. Clonez ce dépôt sur votre machine :
```bash
git clone https://github.com/votre-nom/simple-cli-monitor.git
cd simple-cli-monitor
```

2. Lancez le moniteur :
```bash
python3 simple-cli-monitor.py
```

3. Appuyez sur `Ctrl+C` pour quitter proprement.

## 📄 Licence
Ce projet est sous licence MIT. N'hésitez pas à l'utiliser, le modifier et le partager !

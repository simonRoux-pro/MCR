"""Contournements reseau, a importer EN PREMIER (avant tout import qui touche
au reseau, notamment faster_whisper / huggingface_hub).

Deux problemes reels rencontres en conditions reelles, et leurs solutions :

1. IPv6 casse sur certains reseaux : la connexion s'etablit puis les paquets
   se perdent en cours de transfert, sans erreur explicite (verifie avec
   curl -6 : timeout a mi-transfert, alors que curl -4 passe parfaitement).
   Les librairies HTTP tentent IPv6 en premier et restent bloquees sans
   jamais basculer sur IPv4.
   -> On force la resolution DNS a ne renvoyer que des adresses IPv4.

2. Le telechargement des modeles Whisper passe par defaut par `hf_xet`, un
   module compile (Rust) qui fait ses propres connexions reseau : le forcage
   IPv4 ci-dessus (au niveau des sockets Python) ne s'y applique pas, et le
   telechargement peut donc rester bloque malgre tout.
   -> HF_HUB_DISABLE_XET bascule sur le telechargement HTTP classique de
      huggingface_hub (librairie requests), qui passe bien par les sockets
      Python et affiche en prime une barre de progression dans le terminal.

A retirer si un jour l'application doit tourner sur un reseau IPv6-only
(rare en pratique).
"""
import os
import socket

# Doit etre positionne AVANT le premier import de huggingface_hub
# (setdefault : une variable deja definie par l'utilisateur reste prioritaire).
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

_original_getaddrinfo = socket.getaddrinfo


def _getaddrinfo_ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
    return _original_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)


socket.getaddrinfo = _getaddrinfo_ipv4_only

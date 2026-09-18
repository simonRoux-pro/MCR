"""Genere un certificat TLS auto-signe, pour servir l'outil en HTTPS.

    python genere_certificat.py                 -> pour localhost
    python genere_certificat.py 10.20.30.40     -> pour une adresse reseau
    python genere_certificat.py outil.interne   -> pour un nom de machine

Ecrit certificat.pem et cle.pem a cote du code, puis rappelle les deux lignes
a poser dans .env.

A QUOI CA SERT. Les navigateurs n'autorisent le micro et la capture d'ecran
qu'en HTTPS ; localhost est la seule exception. Sans certificat, l'outil ne
fonctionne donc que sur la machine qui l'heberge.

CE QUE CA NE REMPLACE PAS. Un certificat auto-signe n'est reconnu par aucun
navigateur : il affiche un avertissement qu'il faut accepter une fois par
poste, et une iframe pointant sur un tel certificat reste vide sans rien dire.
C'est bon pour une demonstration ou un test. Pour un vrai deploiement,
demander un certificat a l'autorite interne de l'organisation : meme reglage
dans .env, mais plus aucun avertissement.
"""

import datetime
import ipaddress
import sys

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
except ImportError:
    raise SystemExit("Il manque une bibliotheque : pip install cryptography")

DUREE_JOURS = 825  # au-dela, les navigateurs refusent le certificat


def main() -> None:
    nom = sys.argv[1] if len(sys.argv) > 1 else "localhost"

    # Le nom peut etre une adresse IP ou un nom de machine : le certificat ne
    # les declare pas de la meme facon, et un navigateur qui ne trouve pas
    # l'un des deux refuse la connexion.
    try:
        autres_noms = [x509.IPAddress(ipaddress.ip_address(nom))]
    except ValueError:
        autres_noms = [x509.DNSName(nom)]

    # localhost vaut aussi 127.0.0.1 : on declare les deux pour que le
    # certificat marche quelle que soit la facon dont on ouvre la page.
    if nom == "localhost":
        autres_noms.append(x509.IPAddress(ipaddress.ip_address("127.0.0.1")))

    cle = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    sujet = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, nom),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Outil de transcription"),
    ])
    maintenant = datetime.datetime.now(datetime.timezone.utc)
    certificat = (
        x509.CertificateBuilder()
        .subject_name(sujet)
        # Auto-signe : l'emetteur est le sujet lui-meme.
        .issuer_name(sujet)
        .public_key(cle.public_key())
        .serial_number(x509.random_serial_number())
        # Une heure de marge : les horloges de deux machines ne sont jamais
        # exactement d'accord, et un certificat "pas encore valide" est refuse.
        .not_valid_before(maintenant - datetime.timedelta(hours=1))
        .not_valid_after(maintenant + datetime.timedelta(days=DUREE_JOURS))
        .add_extension(x509.SubjectAlternativeName(autres_noms), critical=False)
        .sign(cle, hashes.SHA256())
    )

    with open("certificat.pem", "wb") as f:
        f.write(certificat.public_bytes(serialization.Encoding.PEM))
    with open("cle.pem", "wb") as f:
        f.write(cle.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            # Sans mot de passe : le serveur doit pouvoir demarrer seul.
            encryption_algorithm=serialization.NoEncryption(),
        ))

    print(f"Certificat genere pour {nom}, valable {DUREE_JOURS} jours.")
    print()
    print("A ajouter dans .env :")
    print("  MEETING_SSL_CERT=certificat.pem")
    print("  MEETING_SSL_KEY=cle.pem")
    print()
    print("Puis relancer le serveur : l'adresse devient https://...")
    print("Le navigateur avertira que le certificat est inconnu : c'est normal")
    print("pour un certificat auto-signe, accepter une fois par poste.")


if __name__ == "__main__":
    main()

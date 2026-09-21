"""Tests de l'API du serveur de transcription. La transcription elle-meme est
simulee : ces tests verifient le parcours complet (session, envoi de morceaux
au fil de l'eau, suivi, telechargement, effacement) sans modele Whisper."""
import datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import serveur


@pytest.fixture
def client():
    serveur.sessions.clear()
    return TestClient(serveur.app)


def _transcription_simulee(texte="texte transcrit"):
    """Remplace transcribe() : ecrit le fichier attendu et renvoie le texte."""
    def faux_transcribe(audio, sortie, progress=None, vocabulaire=""):
        if progress:
            progress(5.0, 10.0)
        with open(sortie, "w", encoding="utf-8") as f:
            f.write(texte)
        return texte
    return patch.object(serveur, "transcribe", side_effect=faux_transcribe)


def test_parcours_complet(client):
    session = client.post("/api/sessions").json()
    identifiant = session["id"]
    assert session["etat"] == "enregistrement"

    # Morceaux envoyes au fil de l'eau, comme le fait le navigateur
    for morceau in (b"aaaa", b"bbbbbb"):
        reponse = client.post(f"/api/sessions/{identifiant}/morceau", content=morceau)
        assert reponse.status_code == 200
    assert client.get(f"/api/sessions/{identifiant}").json()["octetsRecus"] == 10

    with _transcription_simulee("bonjour la reunion"):
        client.post(f"/api/sessions/{identifiant}/terminer")
        serveur.executeur.shutdown(wait=True)   # attend la fin de la transcription
        serveur.executeur = type(serveur.executeur)(max_workers=1)

    etat = client.get(f"/api/sessions/{identifiant}").json()
    assert etat["etat"] == "termine"
    assert etat["texte"] == "bonjour la reunion"
    assert etat["progression"] == 100

    fichier = client.get(f"/api/sessions/{identifiant}/transcription.txt")
    assert fichier.status_code == 200
    assert fichier.text == "bonjour la reunion"


def test_les_morceaux_sont_ajoutes_au_fil_de_l_eau(client):
    """Rien ne doit s'accumuler en memoire : chaque morceau est ecrit dans le
    fichier des sa reception (indispensable pour une reunion de 2 h)."""
    identifiant = client.post("/api/sessions").json()["id"]
    client.post(f"/api/sessions/{identifiant}/morceau", content=b"debut-")
    session = serveur.sessions[identifiant]
    assert session.audio.read_bytes() == b"debut-"     # deja sur disque

    client.post(f"/api/sessions/{identifiant}/morceau", content=b"suite")
    assert session.audio.read_bytes() == b"debut-suite"


def test_terminer_sans_audio_donne_une_erreur_claire(client):
    identifiant = client.post("/api/sessions").json()["id"]
    etat = client.post(f"/api/sessions/{identifiant}/terminer").json()
    assert etat["etat"] == "echec"
    assert "micro" in etat["erreur"]


def test_echec_de_transcription_remonte_le_message(client):
    identifiant = client.post("/api/sessions").json()["id"]
    client.post(f"/api/sessions/{identifiant}/morceau", content=b"audio")

    with patch.object(serveur, "transcribe", side_effect=RuntimeError("modele absent")):
        client.post(f"/api/sessions/{identifiant}/terminer")
        serveur.executeur.shutdown(wait=True)
        serveur.executeur = type(serveur.executeur)(max_workers=1)

    etat = client.get(f"/api/sessions/{identifiant}").json()
    assert etat["etat"] == "echec"
    assert etat["erreur"] == "modele absent"


def test_le_vocabulaire_suit_la_session_jusqu_a_la_transcription(client):
    """Les mots saisis dans la page (noms, sigles) doivent arriver jusqu'au
    modele : c'est ce qui evite les orthographes fantaisistes."""
    identifiant = client.post("/api/sessions",
                              json={"vocabulaire": "Dupont, RGPD"}).json()["id"]
    client.post(f"/api/sessions/{identifiant}/morceau", content=b"audio")

    with _transcription_simulee() as faux:
        client.post(f"/api/sessions/{identifiant}/terminer")
        serveur.executeur.shutdown(wait=True)
        serveur.executeur = type(serveur.executeur)(max_workers=1)

    assert faux.call_args.kwargs["vocabulaire"] == "Dupont, RGPD"


def test_session_inconnue(client):
    assert client.get("/api/sessions/inexistante").status_code == 404


def test_morceau_refuse_apres_la_fin(client):
    identifiant = client.post("/api/sessions").json()["id"]
    client.post(f"/api/sessions/{identifiant}/morceau", content=b"audio")

    with _transcription_simulee():
        client.post(f"/api/sessions/{identifiant}/terminer")
        serveur.executeur.shutdown(wait=True)
        serveur.executeur = type(serveur.executeur)(max_workers=1)

    reponse = client.post(f"/api/sessions/{identifiant}/morceau", content=b"encore")
    assert reponse.status_code == 409


def test_effacement_supprime_les_donnees_du_serveur(client):
    identifiant = client.post("/api/sessions").json()["id"]
    client.post(f"/api/sessions/{identifiant}/morceau", content=b"audio")
    dossier = serveur.sessions[identifiant].dossier

    assert client.delete(f"/api/sessions/{identifiant}").json()["supprime"] is True
    assert not dossier.exists()                       # audio efface du disque
    assert identifiant not in serveur.sessions
    assert client.get(f"/api/sessions/{identifiant}").status_code == 404


def test_la_page_connait_le_moteur_utilise(client):
    """La page adapte son texte selon le moteur : elle ne peut pas promettre
    que rien ne sort de la machine quand l'audio part chez GenIAL."""
    infos = client.get("/api/info").json()
    assert infos["moteur"] == serveur.CONFIG.moteur
    assert infos["vocabulaireDisponible"] is (serveur.CONFIG.moteur == "local")


def test_la_page_est_servie(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "Transcription de reunion" in page.text
    assert client.get("/static/app.js").status_code == 200


def test_la_page_utilise_des_chemins_relatifs(client):
    """Derriere un portail (Coder, reverse proxy), l'application vit sous un
    prefixe de chemin : une URL absolue viserait la racine du portail et la
    page arriverait sans style ni script."""
    page = client.get("/").text
    assert 'href="static/style.css"' in page
    assert 'src="static/app.js"' in page
    assert '"/static/' not in page

    script = client.get("/static/app.js").text
    assert "document.currentScript.src" in script   # racine deduite du script
    assert 'fetch("/api/' not in script
    assert "fetch(`/api/" not in script


def test_telechargement_de_l_audio_recu(client):
    """L'audio brut doit etre recuperable : c'est ce qui permet de verifier
    par l'ecoute si le son de l'ordinateur a bien ete enregistre."""
    identifiant = client.post("/api/sessions").json()["id"]
    client.post(f"/api/sessions/{identifiant}/morceau", content=b"donnees-audio")

    reponse = client.get(f"/api/sessions/{identifiant}/audio.webm")
    assert reponse.status_code == 200
    assert reponse.content == b"donnees-audio"
    assert reponse.headers["content-type"] == "audio/webm"


def test_audio_absent_donne_404(client):
    identifiant = client.post("/api/sessions").json()["id"]
    assert client.get(f"/api/sessions/{identifiant}/audio.webm").status_code == 404


# ------------------------------------------------------------------------- #
# Mode direct : segments transcrits pendant la reunion, etiquetes par source
# ------------------------------------------------------------------------- #

def _attendre_les_segments():
    """Vide la file de transcription (les segments tournent en arriere-plan)."""
    serveur.executeur.shutdown(wait=True)
    serveur.executeur = type(serveur.executeur)(max_workers=1)


def _envoyer_segment(client, identifiant, source, debut, contenu=b"audio"):
    return client.post(f"/api/sessions/{identifiant}/segment", content=contenu,
                       headers={"X-Source": source, "X-Debut": str(debut)})


def test_le_texte_est_etiquete_par_locuteur_et_remis_dans_l_ordre(client):
    """Le micro, c'est la personne devant l'ecran ; le son de l'ordinateur, ce
    sont les autres. Les segments peuvent revenir dans le desordre : c'est
    l'instant d'enregistrement qui fait foi."""
    identifiant = client.post("/api/sessions").json()["id"]

    textes = {"0.0": "bonjour a tous", "8.0": "bonjour Simon", "14.0": "on commence"}
    def faux_transcribe(audio, sortie, progress=None, vocabulaire=""):
        # le numero du segment est dans le nom du fichier
        return textes[str(float(open(audio, "rb").read().decode()))]

    with patch.object(serveur, "transcribe", side_effect=faux_transcribe):
        _envoyer_segment(client, identifiant, "micro", 0.0, b"0.0")
        _envoyer_segment(client, identifiant, "systeme", 8.0, b"8.0")
        _envoyer_segment(client, identifiant, "micro", 14.0, b"14.0")
        _attendre_les_segments()
        client.post(f"/api/sessions/{identifiant}/terminer")

    etat = client.get(f"/api/sessions/{identifiant}").json()
    assert etat["etat"] == "termine"
    assert etat["texte"] == ("Moi : bonjour a tous\n\n"
                             "Reunion : bonjour Simon\n\n"
                             "Moi : on commence")


def test_les_repliques_consecutives_d_une_source_sont_regroupees(client):
    """Sinon le texte serait hache d'une etiquette toutes les dix secondes."""
    identifiant = client.post("/api/sessions").json()["id"]
    with _transcription_simulee("une phrase"):
        _envoyer_segment(client, identifiant, "micro", 0.0)
        _envoyer_segment(client, identifiant, "micro", 10.0)
        _attendre_les_segments()
        client.post(f"/api/sessions/{identifiant}/terminer")

    assert client.get(f"/api/sessions/{identifiant}").json()["texte"] == \
        "Moi : une phrase une phrase"


def test_le_texte_est_lisible_pendant_la_reunion(client):
    """Tout l'interet du mode direct : ne pas attendre la fin."""
    identifiant = client.post("/api/sessions").json()["id"]
    with _transcription_simulee("premiere phrase"):
        _envoyer_segment(client, identifiant, "micro", 0.0)
        _attendre_les_segments()

    etat = client.get(f"/api/sessions/{identifiant}").json()
    assert etat["etat"] == "enregistrement"          # la reunion continue
    assert etat["texte"] == "Moi : premiere phrase"


def test_un_segment_en_echec_ne_fait_pas_tomber_la_reunion(client):
    identifiant = client.post("/api/sessions").json()["id"]

    appels = []
    def parfois_en_echec(audio, sortie, progress=None, vocabulaire=""):
        appels.append(audio)
        if len(appels) == 1:
            raise RuntimeError("GenIAL a repondu HTTP 500")
        with open(sortie, "w", encoding="utf-8") as f:
            f.write("la suite")
        return "la suite"

    with patch.object(serveur, "transcribe", side_effect=parfois_en_echec):
        _envoyer_segment(client, identifiant, "micro", 0.0)
        _envoyer_segment(client, identifiant, "micro", 10.0)
        _attendre_les_segments()
        client.post(f"/api/sessions/{identifiant}/terminer")

    etat = client.get(f"/api/sessions/{identifiant}").json()
    assert etat["etat"] == "termine"
    assert etat["texte"] == "Moi : la suite"


def test_sans_aucun_texte_la_session_echoue_avec_une_piste(client):
    identifiant = client.post("/api/sessions").json()["id"]
    with patch.object(serveur, "transcribe", side_effect=RuntimeError("service injoignable")):
        _envoyer_segment(client, identifiant, "micro", 0.0)
        _attendre_les_segments()
        client.post(f"/api/sessions/{identifiant}/terminer")

    etat = client.get(f"/api/sessions/{identifiant}").json()
    assert etat["etat"] == "echec"
    assert "service injoignable" in etat["erreur"]


def test_la_transcription_en_direct_est_telechargeable(client):
    identifiant = client.post("/api/sessions").json()["id"]
    with _transcription_simulee("le compte rendu"):
        _envoyer_segment(client, identifiant, "systeme", 3.0)
        _attendre_les_segments()
        client.post(f"/api/sessions/{identifiant}/terminer")

    fichier = client.get(f"/api/sessions/{identifiant}/transcription.txt")
    assert fichier.status_code == 200
    assert fichier.text.strip() == "Reunion : le compte rendu"


def test_un_segment_est_refuse_apres_la_fin(client):
    identifiant = client.post("/api/sessions").json()["id"]
    with _transcription_simulee():
        _envoyer_segment(client, identifiant, "micro", 0.0)
        _attendre_les_segments()
        client.post(f"/api/sessions/{identifiant}/terminer")

    assert _envoyer_segment(client, identifiant, "micro", 30.0).status_code == 409


def test_la_page_annonce_le_mode_et_les_etiquettes(client):
    infos = client.get("/api/info").json()
    assert infos["modeDirect"] is serveur.mode_direct()
    assert infos["nomMicro"] == serveur.CONFIG.nom_micro
    assert infos["nomSysteme"] == serveur.CONFIG.nom_systeme


def test_le_mode_direct_suit_le_moteur_par_defaut():
    """Le direct suppose une transcription plus rapide que le temps reel. En
    local sur CPU ce n'est pas le cas : la file s'allongerait sans fin."""
    with patch.object(serveur.CONFIG, "mode", "auto"):
        with patch.object(serveur.CONFIG, "moteur", "local"):
            assert serveur.mode_direct() is False
        with patch.object(serveur.CONFIG, "moteur", "genial"):
            assert serveur.mode_direct() is True


def test_le_mode_peut_etre_force_dans_les_deux_sens():
    with patch.object(serveur.CONFIG, "moteur", "local"):
        with patch.object(serveur.CONFIG, "mode", "direct"):
            assert serveur.mode_direct() is True
    with patch.object(serveur.CONFIG, "moteur", "genial"):
        with patch.object(serveur.CONFIG, "mode", "differe"):
            assert serveur.mode_direct() is False


# ------------------------------------------------------------------------- #
# Compte rendu redige a partir de la transcription
# ------------------------------------------------------------------------- #

def _session_transcrite(client, texte="on a parle du budget"):
    identifiant = client.post("/api/sessions").json()["id"]
    client.post(f"/api/sessions/{identifiant}/morceau", content=b"audio")
    with _transcription_simulee(texte):
        client.post(f"/api/sessions/{identifiant}/terminer")
        _attendre_les_segments()
    return identifiant


def test_le_compte_rendu_est_redige_a_partir_de_la_transcription(client):
    identifiant = _session_transcrite(client, "le budget a ete valide")

    recu = {}
    def faux_rediger(transcription):
        recu["transcription"] = transcription
        return "# Compte rendu\n\nLe budget a ete valide."

    with patch("genial.rediger_cr", side_effect=faux_rediger):
        client.post(f"/api/sessions/{identifiant}/compte-rendu")
        _attendre_les_segments()

    etat = client.get(f"/api/sessions/{identifiant}").json()
    assert etat["crEtat"] == "pret"
    assert etat["compteRendu"].startswith("# Compte rendu")
    assert recu["transcription"] == "le budget a ete valide"


def test_le_compte_rendu_est_telechargeable_avec_la_date_de_la_reunion(client):
    """Plusieurs comptes rendus finissent dans le meme dossier : le nom doit
    les distinguer sans avoir a les ouvrir."""
    identifiant = _session_transcrite(client)
    with patch("genial.rediger_cr", return_value="# Compte rendu"):
        client.post(f"/api/sessions/{identifiant}/compte-rendu")
        _attendre_les_segments()

    reponse = client.get(f"/api/sessions/{identifiant}/compte-rendu.md")
    assert reponse.status_code == 200
    assert reponse.text.strip() == "# Compte rendu"

    depose = reponse.headers["content-disposition"]
    debut = serveur.sessions[identifiant].debut
    assert f"compte-rendu-{debut:%Y-%m-%d-%Hh%M}.md" in depose


def test_la_transcription_aussi_est_nommee_avec_la_date(client):
    identifiant = _session_transcrite(client)
    depose = client.get(f"/api/sessions/{identifiant}/transcription.txt") \
                   .headers["content-disposition"]
    debut = serveur.sessions[identifiant].debut
    assert f"transcription-{debut:%Y-%m-%d-%Hh%M}.txt" in depose


def test_un_compte_rendu_est_refuse_avant_la_fin_de_la_transcription(client):
    identifiant = client.post("/api/sessions").json()["id"]
    assert client.post(f"/api/sessions/{identifiant}/compte-rendu").status_code == 409


def test_un_echec_de_redaction_remonte_son_message(client):
    identifiant = _session_transcrite(client)
    with patch("genial.rediger_cr",
               side_effect=RuntimeError("Aucun modele de redaction n'est configure")):
        client.post(f"/api/sessions/{identifiant}/compte-rendu")
        _attendre_les_segments()

    etat = client.get(f"/api/sessions/{identifiant}").json()
    assert etat["crEtat"] == "echec"
    assert "modele de redaction" in etat["crErreur"]


def test_la_page_sait_si_le_compte_rendu_est_possible(client):
    """Sans modele de langue, le moteur local ne sait pas rediger : la page
    masque alors la section plutot que d'offrir un bouton qui echouera."""
    infos = client.get("/api/info").json()
    assert infos["compteRenduDisponible"] is (serveur.CONFIG.moteur == "genial")


# --------------------------------------------------------------------------- #
# HTTPS
#
# Sans certificat, le navigateur refuse le micro partout sauf sur localhost :
# une erreur de reglage ici rend l'outil inutilisable en deploiement, et le
# symptome (micro refuse) ne designe pas sa cause.
# --------------------------------------------------------------------------- #

def test_sans_certificat_on_sert_en_clair():
    with patch.object(serveur.CONFIG, "ssl_cert", ""), \
         patch.object(serveur.CONFIG, "ssl_key", ""):
        assert serveur.options_tls() == {}


def test_un_certificat_a_moitie_configure_arrete_le_serveur():
    """Demarrer en clair alors qu'on croit servir en HTTPS est pire que ne pas
    demarrer : on chercherait la panne du cote du micro."""
    with patch.object(serveur.CONFIG, "ssl_cert", "certificat.pem"), \
         patch.object(serveur.CONFIG, "ssl_key", ""):
        with pytest.raises(SystemExit):
            serveur.options_tls()


def test_un_certificat_introuvable_arrete_le_serveur(tmp_path):
    with patch.object(serveur.CONFIG, "ssl_cert", str(tmp_path / "absent.pem")), \
         patch.object(serveur.CONFIG, "ssl_key", str(tmp_path / "absent-cle.pem")):
        with pytest.raises(SystemExit):
            serveur.options_tls()


def test_un_certificat_complet_est_passe_a_uvicorn(tmp_path):
    cert = tmp_path / "certificat.pem"
    cle = tmp_path / "cle.pem"
    cert.write_text("cert", encoding="utf-8")
    cle.write_text("cle", encoding="utf-8")
    with patch.object(serveur.CONFIG, "ssl_cert", str(cert)), \
         patch.object(serveur.CONFIG, "ssl_key", str(cle)):
        assert serveur.options_tls() == {"ssl_certfile": str(cert),
                                         "ssl_keyfile": str(cle)}


# --------------------------------------------------------------------------- #
# Persistance
#
# Sans elle, un redemarrage du serveur perd les reunions qu'une application
# tierce n'est pas encore venue chercher. C'est la difference entre un outil
# qu'on lance sur son poste et un service qu'on deploie.
# --------------------------------------------------------------------------- #

@pytest.fixture
def donnees(tmp_path):
    """Un serveur configure pour conserver ses reunions sur le disque."""
    with patch.object(serveur.CONFIG, "dossier_donnees", str(tmp_path)):
        serveur.sessions.clear()
        yield tmp_path
        serveur.sessions.clear()


def test_une_reunion_terminee_survit_a_un_redemarrage(donnees):
    client = TestClient(serveur.app)
    with _transcription_simulee("bonjour a tous"):
        identifiant = client.post("/api/sessions",
                                  json={"reference": "DOSSIER-1"}).json()["id"]
        client.post(f"/api/sessions/{identifiant}/morceau", content=b"audio")
        client.post(f"/api/sessions/{identifiant}/terminer")
        serveur.executeur.shutdown(wait=True)
        serveur.executeur = type(serveur.executeur)(max_workers=1)

    # Le redemarrage : on jette tout ce qui etait en memoire, comme le ferait
    # l'arret du processus, et on relit le disque.
    serveur.sessions.clear()
    assert serveur.charger_les_sessions() == 1

    reponse = client.get("/api/reunions/DOSSIER-1")
    assert reponse.status_code == 200
    assert reponse.json()["transcription"] == "bonjour a tous"
    assert reponse.json()["etat"] == "termine"


def test_une_reunion_interrompue_le_dit_plutot_que_de_rester_en_cours(donnees):
    """Un etat "transcription" fige apres un redemarrage n'avancerait plus
    jamais : l'appelant attendrait indefiniment."""
    client = TestClient(serveur.app)
    identifiant = client.post("/api/sessions",
                              json={"reference": "DOSSIER-2"}).json()["id"]

    serveur.sessions.clear()
    serveur.charger_les_sessions()

    reponse = client.get("/api/reunions/DOSSIER-2").json()
    assert reponse["etat"] == "echec"
    assert "redemarrage" in reponse["erreur"]


def test_sans_dossier_de_donnees_rien_n_est_ecrit(tmp_path):
    """Le comportement par defaut ne change pas : sur un poste, la reunion ne
    doit pas laisser de trace ailleurs que dans le temporaire."""
    with patch.object(serveur.CONFIG, "dossier_donnees", ""):
        serveur.sessions.clear()
        client = TestClient(serveur.app)
        client.post("/api/sessions", json={"reference": "DOSSIER-3"})
        assert list(tmp_path.iterdir()) == []
        assert serveur.charger_les_sessions() == 0


def test_les_reunions_trop_vieilles_sont_effacees(donnees):
    client = TestClient(serveur.app)
    identifiant = client.post("/api/sessions", json={"reference": "VIEUX"}).json()["id"]
    session = serveur.sessions[identifiant]
    session.debut -= datetime.timedelta(days=30)
    session.enregistrer()

    with patch.object(serveur.CONFIG, "retention_jours", 7):
        assert serveur.purger_les_anciennes() == 1
    assert identifiant not in serveur.sessions
    assert not session.dossier.exists()


def test_une_retention_nulle_ne_supprime_rien(donnees):
    client = TestClient(serveur.app)
    identifiant = client.post("/api/sessions", json={"reference": "GARDE"}).json()["id"]
    serveur.sessions[identifiant].debut -= datetime.timedelta(days=3650)

    with patch.object(serveur.CONFIG, "retention_jours", 0):
        assert serveur.purger_les_anciennes() == 0
    assert identifiant in serveur.sessions


def test_un_fichier_illisible_n_empeche_pas_le_demarrage(donnees):
    """Perdre une reunion est acceptable ; ne pas demarrer ne l'est pas."""
    client = TestClient(serveur.app)
    client.post("/api/sessions", json={"reference": "BONNE"})
    abime = donnees / "abimee"
    abime.mkdir()
    (abime / serveur.FICHIER_ETAT).write_text("{ ceci n'est pas du JSON",
                                              encoding="utf-8")

    serveur.sessions.clear()
    assert serveur.charger_les_sessions() == 1

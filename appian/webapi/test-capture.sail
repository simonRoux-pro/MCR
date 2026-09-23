/*
  Web API de TEST : la page d'enregistrement peut-elle vivre dans Appian ?

  A creer dans le concepteur :  Nouveau > Web API
      Methode   : GET
      Endpoint  : mcr-test-capture
  Puis ouvrir dans un NOUVEL ONGLET :
      https://<appian>/suite/webapi/mcr-test-capture

  La page repond a trois questions, dans l'ordre :
    1. Appian laisse-t-il s'executer du JavaScript dans une page qu'il sert ?
       Si la premiere ligne reste "JavaScript BLOQUE", la route est fermee.
    2. Le micro est-il autorise ?
    3. Le son de l'ordinateur (display-capture) est-il autorise ?
       C'est lui qui capte les autres participants : sans lui, la route ne
       vaut rien pour des reunions a distance.

  Pas de guillemets doubles dans le HTML : ils fermeraient la chaine SAIL.
*/
a!httpResponse(
  statusCode: 200,
  headers: {
    a!httpHeader(name: "Content-Type", value: "text/html; charset=utf-8")
  },
  body: "<!DOCTYPE html>
<html lang='fr'><head><meta charset='utf-8'><title>Test de capture</title></head>
<body style='font:16px system-ui,sans-serif;padding:2rem;max-width:40rem'>
<h1>Test de capture audio dans Appian</h1>
<p id='js' style='font-weight:bold;color:#a61b1b'>JavaScript BLOQUE par Appian.</p>
<p><button id='micro'>1. Tester le micro</button>
   <button id='systeme'>2. Tester le son de l'ordinateur</button></p>
<pre id='journal' style='background:#f4f5f7;padding:1rem;white-space:pre-wrap'></pre>
<script>
  const js = document.getElementById('js');
  js.textContent = 'JavaScript actif.';
  js.style.color = '#14671f';
  const journal = document.getElementById('journal');
  const noter = (t) => { journal.textContent += t + '\n'; };
  noter('Contexte securise : ' + window.isSecureContext);

  document.getElementById('micro').onclick = async () => {
    try {
      const flux = await navigator.mediaDevices.getUserMedia({ audio: true });
      noter('Micro : OK');
      flux.getTracks().forEach((p) => p.stop());
    } catch (e) { noter('Micro : REFUSE (' + e.name + ') ' + e.message); }
  };

  document.getElementById('systeme').onclick = async () => {
    try {
      const flux = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
      noter(flux.getAudioTracks().length
        ? 'Son de l ordinateur : OK'
        : 'Son de l ordinateur : partage sans audio (cocher Partager l audio)');
      flux.getTracks().forEach((p) => p.stop());
    } catch (e) { noter('Son de l ordinateur : REFUSE (' + e.name + ') ' + e.message); }
  };
</script>
</body></html>"
)

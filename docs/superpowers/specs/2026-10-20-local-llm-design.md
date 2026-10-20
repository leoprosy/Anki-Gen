# Modèle local embarqué

## Objectif

Faire tourner, dans l'app elle-même, un petit modèle de langage pour les tâches légères, sans
compte, sans connexion après le téléchargement, et sans service tiers à lancer à côté (Ollama,
`llama-server`…). Première tâche : l'extraction de frise paragraphe par paragraphe.

## Décisions

- **llama.cpp dans le sidecar Flask**, via `llama-cpp-python`. Toute la chaîne d'extraction
  (prompt, validation, citations, fusion) est déjà en Python : le modèle s'y branche sans passer
  par Rust ni par un second processus. La roue CPU vient de l'index du projet
  (`--extra-index-url` en tête de `requirements.txt`), PyPI n'ayant pas de roue Windows.
- **CPU d'abord.** La roue CPU (AVX2, OpenMP) tourne partout. Vulkan, pour les GPU, viendra plus
  tard ; il faut la compiler en CI.
- **Téléchargement à la demande** (Réglages → Modèle local) dans `DATA_DIR/models`, via
  `.part`, vérifié par SHA-256. L'installateur ne grossit que du runtime (~41 Mo pour l'exe).
- **Un seul modèle : Qwen3-4B-Instruct-2507, Q4_K_M (2,5 Go).** Qwen3-1.7B a été mesuré : plus
  rapide (~1 min par paragraphe), mais il échoue sur 3 paragraphes sur 3 même après deux
  corrections (identifiants en double, pistes manquantes). Plusieurs modèles chargés ensemble
  doubleraient la RAM pour rien ; une tâche = un prompt et un schéma, pas un modèle.
- **Sortie contrainte par le schéma.** `static/schemas/timeline-v1.json` devient une grammaire
  llama.cpp : la réponse est toujours un JSON bien formé. Le validateur reste juge du fond (une
  date `1794-17-95` passe la grammaire, pas `timeline_schema`).
- **Corrections dans la conversation.** Le prompt de correction ne recopie pas le JSON fautif,
  car Claude l'a dans sa conversation ; le modèle local est sans mémoire. `LocalExtractor` rejoue
  donc toute la conversation (prompt, réponse refusée, correction), deux fois au plus, puis rend
  la dernière réponse.
- **Même chemin qu'un collage.** La réponse revient au client, qui la colle comme si elle venait
  du presse-papiers : validation, enregistrement, fusion et prompt de correction manuel restent
  ceux d'aujourd'hui. Le modèle reçoit toujours le prompt complet (jamais la version Skill), et
  le paragraphe visé est figé au clic.
- **Ressources.** Contexte de 8192 jetons (~1,2 Go de cache KV) : un prompt plus long est refusé
  avec un message qui renvoie à l'extraction paragraphe par paragraphe. Une inférence à la fois
  (verrou global). Le modèle se décharge après 10 minutes sans requête.
- **Runtime 2.** Nouvelle dépendance → nouvel installateur. Un exécutable antérieur ne montre ni
  la section Réglages ni le bouton (`local_llm.available()`), et l'updater refuse déjà un
  `app.zip` qui exige un runtime plus récent. La sonde `local_llm` de `runtime_probe.py` vérifie
  que les DLL sont chargées et que le schéma se compile en grammaire.

## Mesures (Windows, 16 threads logiques, CPU seul)

Sur trois paragraphes datés du cours « Fin du XVIIIe à nos jours » (~2 300 jetons de prompt),
de bout en bout avec `LocalExtractor` :

| Modèle | Paragraphes valides | Essais | Durée par paragraphe | Évènements |
|---|---|---|---|---|
| Qwen3-4B-Instruct-2507 | 3 / 3 | 2 (une correction) | 217 à 442 s | 11 à 17 |
| Qwen3-1.7B | 0 / 3 | 3 | 53 à 99 s | — |

~10 jetons/s en génération pour le 4B. Toutes les citations du 4B sont retrouvées dans le cours.
Chaque paragraphe a demandé une correction, ce qui double la durée : la piste d'accélération la
plus directe est de réduire ce que le prompt demande en mode local (champs facultatifs), avant le
GPU.

## Hors périmètre

GPU (Vulkan), génération de cartes Q/R (trop exigeante pour un 4B), extraction de la frise
entière d'un long cours d'un seul prompt, choix du modèle par l'utilisateur.

## Validation

- `.venv/Scripts/python.exe -m unittest discover -s tests` : téléchargement vérifié (URL
  `file://`), routes, boucle de correction avec un faux modèle.
- `node --test "tests/*.js"`.
- `pyinstaller --noconfirm flask-server.spec`, puis `flask-server.exe --self-check --app-dir
  build/app_bundle` : toutes les sondes passent, `llama_cpp\lib\*.dll` et `VCOMP140.DLL` sont
  dans l'exécutable.
- Dans le navigateur : Réglages → Modèle local (état, téléchargement, suppression), puis
  « Générer en local » sur une frise paragraphe par paragraphe.

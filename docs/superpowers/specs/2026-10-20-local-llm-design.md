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
- **Sortie contrainte par un schéma plus serré que le contrat.** `timeline_extract.local_schema()`
  part du schéma du contrat et devient une grammaire llama.cpp : la réponse est toujours un JSON
  bien formé, et toujours un `ankigen.timeline/1` ordinaire (le validateur et le reste de l'app
  ne changent pas). La grammaire rend impossibles les erreurs mesurées d'un 4B : dates
  impossibles (mois 17, année 0), plus d'une ère (deux ères d'un paragraphe se chevauchent), id
  d'ère qui reprend celui d'une période (préfixe `era_`), répétition sans fin (au plus 30
  évènements, 15 périodes, 5 pistes). Elle impose `track` et `source_quote` partout, et retire
  les champs facultatifs verbeux (`description`, `date_text`, `tags`, `origin`…) : le mode local
  est strict. Le validateur reste juge du reste (unicité des id entre périodes et évènements).
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

## Mesures (Windows, Ryzen 7 7700X, 8 cœurs / 16 threads, CPU seul)

Premières mesures, sur trois paragraphes datés du cours « Fin du XVIIIe à nos jours », de bout
en bout avec `LocalExtractor` et le schéma du contrat :

| Modèle | Paragraphes valides | Essais | Durée par paragraphe | Évènements |
|---|---|---|---|---|
| Qwen3-4B-Instruct-2507 | 3 / 3 | 2 (une correction) | 217 à 442 s | 11 à 17 |
| Qwen3-1.7B | 0 / 3 | 3 | 53 à 99 s | — |

### Grammaire locale (avant / après)

Qwen3-4B, paragraphes 0, 1 et 2 du même cours (~3 000 jetons de prompt), prompt complet
inchangé, mesurés à la suite dans un même processus. Avant : schéma du contrat. Après :
`local_schema()`.

| Paragraphe | Avant : statut | Essais | Durée | Jetons écrits (1er essai) | Après : statut | Essais | Durée | Jetons écrits | Éléments | Citations retrouvées |
|---|---|---|---|---|---|---|---|---|---|---|
| 0. Naissance des États-Unis | invalide (`json_invalid`) | 1 | 569 s | 5 091 | valide | 1 | 164 s | 1 218 | 14 | 14 / 14 |
| 1. Révolution française | invalide (`eras_overlap`) | 3 | 464 s | 1 457 | valide | 1 | 108 s | 989 | 12 | 12 / 12 |
| 2. Consulat et Empire | invalide (`json_invalid`) | 2 | 512 s | 2 644 | valide | 1 | 166 s | 1 435 | 17 | 17 / 17 |
| **Total** | **0 / 3** | 6 | **1 545 s** | | **3 / 3** | 3 | **438 s (−72 %)** | | | 43 / 43 |

Ce qui déclenchait les corrections, et ce qui les rend impossibles :

- **Répétition sans fin** (paragraphe 0) : en décodage glouton, le modèle recopie le même
  évènement ~40 fois jusqu'à remplir le contexte (5 091 jetons, 9 min), et il ne reste plus de
  place pour la correction. → plafonds d'éléments.
- **Ères qui se chevauchent** (paragraphe 1) : à température nulle, la correction renvoie la même
  réponse, trois fois. → une ère au plus.
- **Id en double entre ère, périodes et évènements** (paragraphe 2, et une date `"1789-17"` au
  paragraphe 0) ; la correction, longue, a été tronquée par le contexte. → préfixe `era_`, motif
  de date strict. Un doublon entre une période et un évènement reste possible (non observé
  après) : il passe par la correction.
- **Champs verbeux** : `description`, `date_text` et `tags` faisaient ~35 % des jetons écrits.
  La citation en fait 40 à 50 % ; la plafonner à 120 caractères a été essayé puis retiré : le
  modèle, bloqué au milieu d'un mot, a fini une citation par un jeton chinois (« des制裁 »), pour
  ~20 jetons gagnés.

### Réglages llama.cpp

Prompt de 2 955 jetons, 300 jetons générés sous grammaire, une mesure par réglage (les deux
premiers alternés deux fois) :

| Réglage | Prompt (prefill) | Génération |
|---|---|---|
| Défaut (`n_threads` 8, `n_threads_batch` 16, `n_batch` 512) | 31 s | 10,1 jetons/s |
| `n_threads` 16 / 6 | 31 s | 9,1 / 10,1 jetons/s |
| `n_batch` = `n_ubatch` = 1024 | 32 s | 10,2 jetons/s |
| `flash_attn` | 25 s | 9,0 jetons/s |
| `flash_attn` + cache KV `q8_0` | 68 s | 7,9 jetons/s |

On garde les réglages par défaut. `flash_attn` gagne 6 s sur le prompt mais perd 10 % en
génération, qui domine (~1 000 jetons par paragraphe) ; d'un paragraphe à l'autre, llama.cpp
réutilise déjà le cache KV du préfixe commun du prompt (consignes et exemple), si bien que seul
le premier paragraphe paie le prompt entier. Le cache quantifié est bien plus lent sur CPU.

Pistes suivantes : un prompt local sans les champs que la grammaire retire (gain sur le premier
paragraphe seulement, et il faudrait que le serveur construise le prompt), puis le GPU.

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

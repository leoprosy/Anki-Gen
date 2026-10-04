---
name: motion-design-studio
description: Setup, conçoit, développe, critique et exporte des motion designs professionnels directement en code. Utiliser ce skill dès que l'utilisateur demande un motion design, une vidéo de lancement produit, une animation UI, un showreel, une boucle animée, une landing-page reveal, un teaser SaaS, une animation HTML vers MP4, une vidéo publicitaire courte ou une vidéo générée par code. Le skill prend en charge le setup de l'environnement, le storyboard, la direction artistique, les animations déterministes, la prévisualisation, le rendu frame-perfect, le son, le contrôle qualité et l'export.
---

# Motion Design Studio

## 1. Rôle

Tu es simultanément :

- motion designer ;
- directeur artistique ;
- interaction designer ;
- ingénieur frontend ;
- ingénieur rendering ;
- sound designer léger ;
- superviseur qualité.

Ton objectif n'est PAS simplement de produire une animation qui fonctionne.

Ton objectif est de produire un **motion design qui semble avoir été conçu intentionnellement par un studio**, tout en restant :

- entièrement reproductible ;
- modifiable ;
- déterministe ;
- exportable frame par frame ;
- fidèle à la marque ;
- techniquement propre ;
- suffisamment simple pour être maintenu par un agent IA.

---

# 2. Principe fondamental

## Une vidéo est une fonction du temps

Le rendu doit être déterministe.

À n'importe quel instant `t`, l'application doit pouvoir afficher directement l'image correcte :

```js
window.seek(t)
```

où `t` est exprimé en secondes.

Appeler :

```js
seek(4.25)
```

doit toujours produire exactement la même frame.

### Interdictions dans le moteur d'animation

Ne PAS utiliser comme source temporelle principale :

```txt
setTimeout()
setInterval()
Date.now()
performance.now()
requestAnimationFrame() comme clock
CSS transitions non contrôlées
CSS animations autonomes
Math.random() non seedé
état accumulé entre les frames
```

`requestAnimationFrame()` peut être utilisé uniquement pour laisser Chromium finaliser le layout avant une capture.

Une frame doit dépendre de :

```txt
time + inputs + assets
```

et non de l'historique d'exécution.

---

# 3. Choix du moteur

Avant de commencer, inspecte le projet existant.

Choisis automatiquement la route la plus pertinente.

## ROUTE A — HTML + CSS + SVG/Canvas + seek(t)

### Route par défaut

À privilégier pour :

- motion design de 5 à 30 secondes ;
- launch video ;
- animation UI ;
- showreel ;
- boucle LinkedIn/X ;
- teaser SaaS ;
- landing reveal ;
- vidéo fortement customisée.

Stack :

```txt
HTML
CSS
JavaScript
SVG / Canvas si nécessaire
Playwright
Chromium
Python
FFmpeg
```

Avantages :

```txt
contrôle maximal
très peu de dépendances
seek(t) naturel
itérations rapides
excellent pour une IA
```

---

## ROUTE B — HyperFrames

Utiliser HyperFrames lorsque :

- HyperFrames est déjà présent ;
- l'utilisateur demande explicitement HyperFrames ;
- plusieurs compositions doivent être gérées ;
- le projet contient beaucoup de scènes, audio, captions ou composants réutilisables ;
- le workflow HTML → vidéo bénéficie de son Studio.

Installation recommandée :

```bash
npx skills add heygen-com/hyperframes
```

ou, si HyperFrames est déjà installé :

```bash
npx hyperframes skills update
```

Diagnostic :

```bash
npx hyperframes doctor
```

Preview :

```bash
npx hyperframes preview
```

Validation :

```bash
npx hyperframes lint
```

Render :

```bash
npx hyperframes render -o out/final.mp4
```

Ne mélange pas inutilement HyperFrames et un moteur custom.

---

## ROUTE C — Remotion

Utiliser Remotion lorsque le besoin principal est :

- template vidéo réutilisable ;
- génération de nombreuses vidéos ;
- vidéo pilotée par JSON/API/data ;
- bibliothèque de compositions ;
- intégration React existante ;
- personnalisation automatisée à grande échelle.

Installer les skills officiels :

```bash
npx skills add remotion-dev/skills
```

Dans ce cas, respecter en priorité :

```txt
/remotion-best-practices
/remotion-create
/remotion-markup
/remotion-studio
/remotion-render
```

Ne migre pas un petit motion design HTML vers Remotion sans raison.

---

# 4. Setup automatique

Au premier lancement dans un nouveau projet, inspecte l'environnement.

Vérifie :

```bash
node --version
python --version
ffmpeg -version
git --version
```

Si Claude Code est utilisé :

```bash
claude --version
```

## Règle d'installation

Ne lance jamais silencieusement une installation système importante.

Avant une installation :

1. indique brièvement ce qui manque ;
2. explique pourquoi c'est nécessaire ;
3. utilise ensuite la méthode adaptée au système.

Ne réinstalle jamais une dépendance fonctionnelle.

---

# 5. Setup Route A

Créer si nécessaire :

```txt
motion-studio/
├── CLAUDE.md
├── index.html
├── brand/
│   ├── logo.svg
│   ├── palette.md
│   ├── fonts/
│   ├── screenshots/
│   └── reference/
├── assets/
│   ├── images/
│   ├── video/
│   ├── audio/
│   └── sfx/
├── facts.md
├── brief.md
├── storyboard.md
├── render.py
├── audio.py
├── probe/
└── out/
```

Installer localement les dépendances nécessaires :

```bash
python -m pip install playwright pillow numpy
python -m playwright install chromium
```

FFmpeg doit être disponible dans le PATH.

Évite les dépendances inutiles.

## Templates fournis

Ce skill embarque des points de départ testés dans `templates/` (à côté de ce fichier) :

```txt
templates/CLAUDE.md   invariants du projet (section 6)
templates/index.html  composition seek(t) + __MOTION__ + player preview (sections 16, 20, 21)
templates/render.py   renderer Playwright → FFmpeg : probes, contact sheet, draft, master,
                      motion blur, test de loop (sections 23, 26–29, 36)
```

Copie-les dans `motion-studio/` au setup, puis adapte-les. Ne les considère pas comme une direction artistique : la scène de démonstration de `index.html` doit être entièrement remplacée.

Usage de `render.py` :

```bash
python render.py probe 1.2 5.0 9.5 14.2   # stills + probe/contact-sheet.png
python render.py draft                     # out/draft.mp4  (960×540, 30 fps)
python render.py master                    # out/master.mp4 (taille/fps de __MOTION__)
python render.py master --blur 4           # motion blur, 4 sous-frames, shutter 180°
python render.py master --size 1080x1920 -o out/master-vertical.mp4
python render.py loop                      # compare première et dernière frame
```

---

# 6. Générer un CLAUDE.md minimal

Le workflow complet reste dans ce skill.

`CLAUDE.md` contient uniquement les invariants permanents du projet.

Créer un fichier similaire à :

```md
# Motion Studio Rules

## Rendering

Every movie is deterministic.

`window.seek(t)` must render the exact frame at time `t`.

Never use as animation clocks:
- setTimeout
- setInterval
- Date.now
- performance.now
- autonomous CSS animations
- autonomous CSS transitions
- non-seeded Math.random

Rendering must work frame-by-frame through Chromium.

## Quality

Prefer transformations between visual states over arbitrary cuts.

Use real brand assets.

Never invent product features, testimonials, prices or metrics.

Typography must remain readable on mobile.

Use at most one dominant accent color unless the brand system explicitly requires more.

Avoid generic AI aesthetics:
- excessive glow
- random particles
- rainbow gradients
- gratuitous 3D
- excessive glassmorphism
- cartoon bounce
- floating decorative objects without narrative purpose

## Production

Storyboard before expensive rendering.

Generate still probes before rendering the full video.

Always render a lightweight draft before the master.

Never overwrite source assets.
```

Adapte ces règles à la marque.

---

# 7. Collecte des inputs

Avant de concevoir la vidéo, inspecte tout ce qui a été fourni :

```txt
prompt utilisateur
site web
repository
screenshots
logo
palette
fontes
vidéos de référence
animations existantes
facts.md
copywriting
landing page
UI existante
```

Si un site ou repository est disponible, utilise en priorité ses vrais éléments de marque.

Ne redessine pas approximativement une interface existante si les vrais assets sont disponibles.

---

# 8. Facts.md : vérité produit

Tout chiffre ou claim spécifique doit avoir une origine identifiable.

Exemple :

```md
# Product facts

- 12,400 teams
  Source: /customers
  Retrieved: 2026-10-04

- Saves 38% of processing time
  Source: customer study PDF

- €29/month
  Source: pricing page
```

Ne jamais inventer :

```txt
nombre d'utilisateurs
croissance
revenus
prix
témoignages
fonctionnalités
benchmarks
logos clients
récompenses
```

Si aucune donnée réelle n'est disponible, préfère une animation conceptuelle.

---

# 9. Director Brief

Avant de coder le motion design, créer `brief.md`.

Format :

```md
# Director Brief

## Movie
Duration:
Master resolution:
FPS draft:
FPS master:
Formats:
Primary platform:

## Product
Name:
Promise:
Audience:
CTA:

## Art direction
Reference:
Visual language:
Background:
Foreground:
Accent:
Typography:

## Narrative
What changes between frame 0 and the final frame?

## Primary visual system
One recurring shape / component / device / line / window / card:

## Product facts
List only verified claims.

## Audio
Silence / SFX / music / voiceover.

## Loop
Yes / No.
```

Une vidéo réussie doit pouvoir être résumée par une transformation simple.

Exemple :

```txt
"A search bar becomes the final product interface."
```

Si la vidéo nécessite trois phrases pour être expliquée, simplifie-la.

---

# 10. Storyboard temporel

Créer `storyboard.md`.

Limiter généralement un motion de 15 secondes à environ 5–8 beats.

Exemple :

```txt
0.00–1.80  Hook
1.80–4.00  Object introduction
4.00–7.20  Transformation
7.20–10.00 Product/UI reveal
10.00–12.80 Proof
12.80–15.00 Logo + CTA
```

Chaque beat doit définir :

```txt
objectif
élément principal
texte visible
mouvement principal
état entrant
état sortant
événement audio éventuel
```

Évite plusieurs idées concurrentes dans un même beat.

---

# 11. Validation interactive

Si l'utilisateur travaille de façon interactive :

### Gate 1

Présente :

```txt
direction
storyboard
durées
layers
sound plan
```

avant le développement lourd.

### Gate 2

Produis quatre stills représentatifs avant le rendu complet.

Par exemple :

```txt
t = 1.2
t = 5.0
t = 9.5
t = 14.2
```

### Mode autonome

Si l'utilisateur demande explicitement de tout produire sans interruption :

ne bloque pas le workflow.

Effectue toi-même les deux validations avec la grille QA de ce skill et continue uniquement si le concept atteint un niveau suffisant.

---

# 12. Direction artistique

## Priorité

La hiérarchie visuelle doit être immédiatement compréhensible.

À chaque instant, le spectateur doit savoir où regarder.

## Règle du mouvement principal

Dans la majorité des plans :

```txt
1 mouvement principal
+
éventuellement 1 mouvement secondaire discret
```

Ne fais pas bouger chaque élément simultanément.

---

# 13. Anti « AI Motion Slop »

Évite par défaut :

```txt
glow néon générique
gradients arc-en-ciel
particules gratuites
bokeh
chrome liquide
glassmorphism partout
ombres énormes
emoji décoratifs
texte minuscule
objets qui flottent sans raison
bounce cartoon
flip 3D gratuit
morphing sans fonction narrative
trop de zooms
trop de cuts
fausses interfaces
fausses données
```

Préférer :

```txt
grandes masses graphiques
bonne typographie
espaces négatifs
transformations cohérentes
shared elements
contraste élevé
mouvement précis
peu d'éléments
vrais assets produit
```

---

# 14. Design par états

Ne pense pas d'abord en « effets ».

Pense en états.

Exemple :

```txt
STATE 0 — dot
STATE 1 — button
STATE 2 — search bar
STATE 3 — command palette
STATE 4 — product window
STATE 5 — chart
STATE 6 — logo lockup
```

Puis définis les transformations entre les états.

Cela produit généralement un motion plus cohérent qu'une succession de scènes indépendantes.

---

# 15. Continuité

Lorsque possible :

un élément visuel présent au début doit survivre ou se transformer jusqu'à la fin.

Exemple :

```txt
dot
→ button
→ input
→ window
→ chart
→ logo mark
```

Privilégie les transformations aux cuts.

Les hard cuts restent autorisés lorsqu'ils servent réellement le rythme.

---

# 16. Timing

Créer les fonctions d'interpolation nécessaires.

Exemple conceptuel :

```js
const clamp01 = (x) => Math.max(0, Math.min(1, x));

const progress = (t, start, end) =>
  clamp01((t - start) / (end - start));
```

Utiliser ensuite :

```txt
lerp
smoothstep
easeInOut
closed-form spring
```

Ne pas accumuler les positions d'une frame à l'autre.

---

# 17. Springs

Pour les interfaces modernes, préférer des springs contrôlées à des easings artificiels.

Objectifs :

```txt
mouvement rapide
settling propre
overshoot faible
aucun bounce cartoon
```

La valeur exacte dépend du moteur.

Une damping ratio aux alentours de `0.72+` constitue un bon point de départ pour les animations qui ne doivent pas rebondir fortement.

---

# 18. Typographie

La typographie est un élément de motion à part entière.

Priorités :

```txt
lisibilité
contraste
hiérarchie
rythme
taille sur mobile
```

Évite plus de deux familles typographiques sauf nécessité de marque.

Les titres doivent rester lisibles lorsque la vidéo est affichée à petite taille.

---

# 19. Safe zones

Toujours anticiper les recadrages sociaux.

Conserver les informations essentielles dans une zone centrale compatible avec :

```txt
16:9
1:1
9:16
```

Le logo, la proposition principale et le CTA ne doivent jamais dépendre exclusivement des extrémités du 16:9.

---

# 20. Construire index.html

Pour Route A, utiliser de préférence un fichier `index.html` autonome ou une architecture très légère.

Il doit exposer :

```js
window.seek = function (t) {
  // Render exact state at t seconds
};
```

Il doit également déclarer :

```js
window.__MOTION__ = {
  duration: 15,
  width: 1920,
  height: 1080,
  fps: 60
};
```

ou un objet équivalent lisible par `render.py`.

---

# 21. Preview

Fournir un mode preview avec :

```txt
Play
Pause
Replay
seek bar
current time
```

Raccourcis recommandés :

```txt
Space       play/pause
Left        frame précédent
Right       frame suivant
Shift+Left  -1 seconde
Shift+Right +1 seconde
R           replay
```

Le player preview peut utiliser `requestAnimationFrame()`.

Mais :

le moteur de la vidéo reste basé sur `seek(t)`.

---

# 22. Fonts et assets

Avant toute capture :

```js
await document.fonts.ready;
```

S'assurer que tous les assets nécessaires sont chargés.

Ne dépend pas d'une ressource distante fragile pour le rendu final si elle peut être stockée localement.

Utilise les vrais logos SVG lorsque disponibles.

---

# 23. Still probes

Avant tout rendu vidéo complet :

capture plusieurs frames clés.

Créer par exemple :

```txt
probe/
├── 01-hook.png
├── 02-development.png
├── 03-climax.png
├── 04-outro.png
└── contact-sheet.png
```

La contact sheet doit permettre de juger la vidéo comme une séquence graphique.

---

# 24. QA visuel

Noter chaque beat sur 10 selon :

```txt
readability
composition
visual hierarchy
brand fidelity
continuity
motion intention
timing
technical cleanliness
```

Calculer une appréciation globale.

Corriger obligatoirement les éléments ≤ 7/10.

Prioriser les corrections 8/10 uniquement si elles améliorent clairement le résultat.

Ne détruis pas une scène déjà excellente pour obtenir une homogénéité artificielle.

---

# 25. Questions de critique interne

À chaque revue, vérifier notamment :

```txt
Est-ce que je sais immédiatement où regarder ?

Le texte principal est-il lisible en miniature ?

Cette animation communique-t-elle quelque chose ?

Le mouvement est-il nécessaire ?

La transition conserve-t-elle une continuité spatiale ?

Le produit est-il reconnaissable ?

Le motion pourrait-il appartenir à n'importe quelle startup ?
Si oui : renforcer l'identité.

Le logo est-il le vrai logo ?

Un claim a-t-il été inventé ?

Les quatre frames principales forment-elles une bonne séquence graphique ?
```

---

# 26. Render.py

Pour Route A, générer un renderer Playwright.

Pipeline conceptuel :

```txt
launch Chromium
↓
open local page
↓
await fonts
↓
for each frame:
    calculate timestamp
    seek(timestamp)
    wait 2 requestAnimationFrame
    screenshot
↓
encode using ffmpeg
```

Le viewport doit correspondre exactement à la composition.

Pour le master 1080p :

```txt
1920 × 1080
deviceScaleFactor = 1
```

ou utiliser du supersampling uniquement lorsque cela améliore réellement le rendu.

---

# 27. Draft render

Toujours créer un draft avant le master.

Exemple :

```txt
960×540
30 fps
pas de motion blur
CRF ~23
preset rapide
```

Objectif :

juger le rythme.

PAS la netteté finale.

Exemple de sortie :

```txt
out/draft.mp4
```

---

# 28. Master render

Après validation du draft :

```txt
1920×1080
60 fps lorsque pertinent
H.264
yuv420p
CRF ≈ 16–18
faststart
```

Exemple :

```bash
ffmpeg \
  -framerate 60 \
  -i frames/%06d.png \
  -c:v libx264 \
  -preset slow \
  -crf 18 \
  -pix_fmt yuv420p \
  -movflags +faststart \
  out/master.mp4
```

Adapte la syntaxe au système d'exploitation.

---

# 29. Motion blur

Le motion blur est optionnel.

Pour un master haut de gamme :

rendre plusieurs sous-frames temporelles pour chaque frame finale.

Exemple :

```txt
4 subframes / output frame
180° shutter
```

Mélanger les sous-frames appartenant uniquement à la même frame.

Ne mélange jamais deux plans séparés par un hard cut.

N'utilise pas ce procédé pour les drafts.

---

# 30. Audio

Le motion design doit rester compréhensible sans son.

Le son améliore le rythme ; il ne doit pas sauver une animation incompréhensible.

Trois niveaux :

```txt
1. Silence
2. SFX
3. Music + SFX
```

---

# 31. Synchronisation SFX

Les effets sonores doivent correspondre à un événement visuel précis.

Exemples :

```txt
click → click UI
tick → compteur
impact → reveal
whoosh → déplacement réellement rapide
notification → apparition toast
```

Pas de whoosh décoratif sur chaque transition.

Placer le pic sonore sur l'événement perceptif réel.

---

# 32. Musique

Si une musique est utilisée :

analyser :

```txt
BPM
bar structure
attacks
drops
breaks
```

Synchroniser le climax visuel avec un événement musical fort lorsque cela sert le film.

Ne fais pas uniquement confiance à un détecteur automatique de beats : vérifier les événements importants.

---

# 33. Niveau audio

Pour une sortie web/social, viser par défaut environ :

```txt
Integrated loudness : -14 LUFS
True peak : ≤ -1 dBTP
```

Adapter si la plateforme ou le brief impose autre chose.

---

# 34. Droits médias

Ne récupère jamais arbitrairement musique, vidéo, photographie ou illustration protégée.

Utiliser en priorité :

```txt
assets de l'utilisateur
assets de marque
médias explicitement licenciés
sources libres compatibles
éléments générés spécifiquement pour le projet
```

Conserver la source/licence des médias externes dans un fichier lorsque nécessaire.

---

# 35. Responsive exports

Lorsque plusieurs formats sont demandés :

ne crée pas trois vidéos indépendantes.

Utilise la même timeline et adapte la composition.

Cibles usuelles :

```txt
16:9 — 1920×1080
1:1  — 1080×1080
9:16 — 1080×1920
```

Les timings narratifs restent identiques sauf nécessité manifeste.

---

# 36. Loop

Si une boucle est demandée :

frame initiale et frame finale doivent être compatibles en :

```txt
position
scale
rotation
opacity
shape
color
velocity
```

Une position identique avec une vitesse différente produit une rupture visible.

Tester automatiquement le seam.

---

# 37. Détection de problèmes

Après le master, inspecter :

```txt
first frame
last frame
scene boundaries
text rendering
1-frame flashes
unexpected empty frames
late font loading
layout shifts
alpha artifacts
color changes
loop seam
```

Créer automatiquement des captures autour des transitions suspectes.

---

# 38. Debugging

## Export qui saccade

Chercher :

```txt
timers
CSS animation
CSS transitions
state accumulation
random values
async asset loading
layout instability
```

---

## Texte flou

Vérifier :

```txt
viewport
device scale
font loading
CSS transforms
supersampling
encoding
```

---

## Motion trop « mou »

Réduire :

```txt
durée des easings
nombre d'objets animés
distance inutile
```

Renforcer :

```txt
contraste temporel
settling
poses
staging
```

---

## Motion trop « AI »

Supprimer d'abord :

```txt
glow
particles
gradient
floating cards
bounce
random decorative elements
```

Puis renforcer :

```txt
brand
typography
real UI
one visual system
meaningful transformation
```

---

## Film incompréhensible

Faire le test :

> Regarde la vidéo sans son et résume ce qui se passe en une phrase.

Si la phrase est confuse :

simplifier le concept avant de continuer à polir.

---

# 39. Utilisation d'une vidéo de référence

Une référence sert à analyser :

```txt
timing
rhythm
composition
camera
transitions
density
typography
movement hierarchy
```

Ne reproduis pas automatiquement ses assets, sa musique, ses personnages, ses logos ou son identité.

Cherche les principes visuels, pas la copie servile.

---

# 40. Référence UI / produit

Si un repository, une app ou des screenshots sont accessibles :

réutiliser les vrais :

```txt
tokens
spacing
border radius
fonts
colors
icons
screens
components
logos
copy
```

Ne jamais inventer une feature pour rendre l'animation plus impressionnante.

---

# 41. Hiérarchie d'effort du modèle

Ne lie pas ce skill à un nom de modèle précis.

Utilise le meilleur modèle disponible lorsque la tâche nécessite une véritable direction créative.

Approche recommandée :

```txt
concept / storyboard       → effort élevé
première implémentation    → effort élevé
critique visuelle          → effort élevé
petite correction CSS      → effort normal
timing +5 frames           → effort normal
micro-fix                  → effort normal
```

Évite de relancer une phase de conception complète pour chaque correction mineure.

---

# 42. Workflow complet

L'ordre de travail normal est :

```txt
INPUTS
↓
ENVIRONMENT CHECK
↓
ENGINE SELECTION
↓
PROJECT SETUP
↓
BRAND EXTRACTION
↓
FACT CHECK
↓
DIRECTOR BRIEF
↓
TIMED STORYBOARD
↓
BUILD
↓
4 STILL PROBES
↓
VISUAL CRITIQUE
↓
ITERATE
↓
DRAFT RENDER
↓
RHYTHM CRITIQUE
↓
AUDIO
↓
MASTER RENDER
↓
TECHNICAL QA
↓
ALTERNATE ASPECT RATIOS
↓
DELIVERY
```

Ne saute pas directement de :

```txt
prompt → master render
```

---

# 43. Optimisation de l'itération

Lorsque l'utilisateur demande une modification localisée :

ne réécris pas toute la vidéo.

Identifier :

```txt
scene
timestamp
layer
property
```

Modifier uniquement la zone concernée.

Puis recapturer :

```txt
frame avant
frame centrale
frame après
```

avant de refaire un master.

---

# 44. Deliverables finaux

À la fin d'un projet Route A réussi, conserver au minimum :

```txt
index.html
render.py
brief.md
storyboard.md
facts.md
brand/
assets/
probe/contact-sheet.png
out/draft.mp4
out/master.mp4
```

Et selon la demande :

```txt
out/master-square.mp4
out/master-vertical.mp4
out/final-audio.mp4
poster.png
```

---

# 45. Reporting final

À la fin, rester concis.

Donner :

```txt
moteur utilisé
durée
résolution / fps
chemin du master
variantes exportées
éventuels assets ou informations manquants
```

Ne noie pas l'utilisateur dans les détails du moteur si tout fonctionne.

---

# 46. Priorités absolues

En cas de conflit entre plusieurs règles, respecter cet ordre :

```txt
1. Fidélité factuelle
2. Fidélité à la marque
3. Lisibilité
4. Intention narrative
5. Continuité visuelle
6. Qualité du mouvement
7. Synchronisation audio
8. Complexité technique
```

Un système techniquement impressionnant mais visuellement mauvais est un échec.

---

# 47. Definition of Done

Le motion design est terminé uniquement lorsque :

```txt
✓ Le concept peut être résumé en une phrase.
✓ Les informations affichées sont vraies.
✓ Le branding est réel.
✓ Les principales frames sont visuellement solides.
✓ Le texte est lisible.
✓ Les animations sont déterministes.
✓ Aucun timer non déterministe ne pilote le rendu.
✓ Le draft a été vérifié.
✓ Les transitions ont été inspectées.
✓ Le master s'encode correctement.
✓ Il n'existe pas de flash d'une frame.
✓ Le loop ferme proprement si demandé.
✓ L'audio est synchronisé si présent.
✓ Les exports demandés existent.
```

Ne considère pas la tâche terminée simplement parce qu'un fichier MP4 a été créé.

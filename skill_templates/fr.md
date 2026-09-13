---
name: anki-flashcard-creator
description: Convertir des paragraphes de cours en cartes Anki exportables.
  Utiliser ce skill dès que l'utilisateur envoie un paragraphe de cours
  (économie, sociologie, philosophie, histoire, etc.) à transformer en
  flashcards. Déclencher aussi si l'utilisateur dit "génère des flashcards",
  "crée des cartes Anki", "transforme ce cours en cartes", "fais des anki",
  "mets en flashcards", ou toute formulation similaire. Ce skill s'applique à
  n'importe quelle matière académique, dès qu'il s'agit de mémoriser un
  contenu structuré.
---

# Générateur de flashcards Anki

Convertir chaque paragraphe de cours fourni par l'utilisateur en cartes Anki,
de manière exhaustive, précise et structurée.

## Règles de fonctionnement

### 1. Génération immédiate
À chaque paragraphe envoyé, générer les cartes directement. Ne jamais écrire de
phrase d'introduction, de confirmation ou de conclusion. Sortir uniquement les
lignes de cartes.

### 2. Zéro déperdition
Chaque information, mécanisme, chiffre, date, auteur et concept du paragraphe
doit être transformé en carte. Aucune information n'est omise comme "secondaire".

### 3. Une idée par carte
Une carte dont la réponse a besoin d'un "et" est deux cartes. La question doit
être répondable sans avoir le paragraphe sous les yeux.

### 4. Œuvres et articles
Si le paragraphe mentionne un ouvrage ou un article, générer systématiquement :
- une carte classique sur le contenu ou la thèse ;
- une carte dédiée à la mémorisation de l'œuvre, dans les deux sens
  (auteur → thèse, et thèse → œuvre).

Exemples de recto pour les cartes dédiées :
- `Quelle est la thèse centrale de [Auteur] dans [Œuvre] ([Date]) ?`
- `Dans quelle œuvre [Auteur] développe-t-il [thèse] ?`

## Format de sortie — c'est le contrat

Une ligne par carte, deux colonnes séparées par une tabulation :

    RECTO<TAB>VERSO

- Pas de ligne d'en-tête : l'application ajoute elle-même `#separator:tab`,
  `#html:true` et `#deck column:1`, ainsi que la colonne de deck.
- Pas de préambule, pas de commentaire, pas de bloc markdown.
- Tout le HTML d'une carte tient sur une seule ligne : un retour à la ligne
  dans une cellule coupe la carte en deux.

## Formatage HTML

Les cartes sont du HTML brut avec CSS inline. Garder la même convention sur tout
un paquet pour que les cartes se ressemblent :

| Élément | Balise |
|---|---|
| Dates | `<span style="color: red; font-weight: bold; text-decoration: underline;">1929</span>` |
| Citations | `<span style="background-color: plum; font-style: italic;">"…"</span>` |
| Œuvres | `<span style="background-color: yellow; font-style: italic;">Titre (Date) — Auteur</span>` |
| Articles | `<span style="background-color: yellow;">"Titre" (Date) — Auteur</span>` |
| Théorie, concept clé | `<span style="color: red; font-weight: bold;">terme</span>` |
| Énumérations | `<ul><li>…</li><li>…</li></ul>` |
| Mathématiques | `<anki-mathjax>Y = A K^\alpha L^{1-\alpha}</anki-mathjax>` |

Pour une formule en bloc : `<anki-mathjax block="true">…</anki-mathjax>`.
MathJax est intégré à Anki et ne demande rien à installer, contrairement à
`[latex]…[/latex]` qui exige une distribution LaTeX sur la machine.

## Images et tableaux — convention obligatoire

Le paragraphe peut contenir des marqueurs `[IMAGE n]` (avec une description) et
`[TABLEAU n]` (avec son contenu en markdown).

- Pour afficher une image, écrire exactement `{{IMG:n}}` à l'endroit voulu.
- Pour réutiliser un tableau, écrire exactement `{{TABLE:n}}`.
- Ne JAMAIS écrire de balise `<img>` et ne JAMAIS inventer de nom de fichier :
  l'application substitue ces marqueurs par le vrai fichier à l'export, une
  balise écrite à la main ne pointe vers rien.
- Un graphique ou un schéma mérite en général sa propre carte : question au
  recto, `{{IMG:n}}` plus l'interprétation au verso.
- Un tableau de données mérite une carte de restitution globale
  (`{{TABLE:n}}` au verso) ET des cartes ciblées sur les valeurs marquantes.
- Si une image n'a aucune description, ne pas deviner ce qu'elle montre.

## Exemples de cartes bien formées

Concept :

    Qu'est-ce que la destruction créatrice selon Schumpeter ?	Processus par lequel <span style="color: red; font-weight: bold;">l'innovation détruit les anciennes structures économiques</span> pour en créer de nouvelles. Théorisé dans <span style="background-color: yellow; font-style: italic;">Capitalisme, Socialisme et Démocratie (1942) — Schumpeter</span>.

Carte dédiée à une œuvre :

    Dans quelle œuvre Schumpeter développe-t-il la destruction créatrice ?	<span style="background-color: yellow; font-style: italic;">Capitalisme, Socialisme et Démocratie</span> (<span style="color: red; font-weight: bold; text-decoration: underline;">1942</span>)

Énumération :

    Quelles sont les trois fonctions de la monnaie ?	<ul><li>Unité de compte</li><li>Moyen d'échange</li><li>Réserve de valeur</li></ul>

Formule :

    Quelle est la fonction de production du modèle de Solow ?	<anki-mathjax>Y = A K^\alpha L^{1-\alpha}</anki-mathjax> où <ul><li><b>Y</b> = production</li><li><b>K</b> = capital</li><li><b>L</b> = travail</li><li><b>A</b> = productivité globale des facteurs</li></ul>

Image :

    Que montre la courbe de Phillips sur la période 1960-1970 ?	{{IMG:1}} Une relation décroissante entre <span style="color: red; font-weight: bold;">inflation</span> et <span style="color: red; font-weight: bold;">chômage</span>.

## Vérification avant de sortir les cartes

- [ ] Chaque information du paragraphe est couverte par au moins une carte
- [ ] Les œuvres et articles ont leurs cartes dédiées supplémentaires
- [ ] Tout le HTML est inline, aucun retour à la ligne dans une cellule
- [ ] Le séparateur est bien une tabulation, et il y a exactement deux colonnes
- [ ] Aucune ligne d'en-tête
- [ ] Aucune phrase de commentaire autour des cartes

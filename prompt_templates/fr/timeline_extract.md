<!--
Prompt d'extraction des frises chronologiques (contrat ankigen.timeline/1), en français.

timeline_prompt.py découpe ce fichier en blocs : chaque bloc commence par une ligne
qui ne contient qu'un commentaire HTML « @nom », et va jusqu'au suivant. Il les
assemble selon le mode (strict ou
enrichi), la stratégie (un seul prompt ou paragraphe par paragraphe) et l'option
« J'ai installé le Skill ». Le Skill téléchargeable est fait des mêmes blocs.

Les {{variables}} sont remplies par le code. Les limites viennent de timeline_schema :
ne les recopiez jamais à la main. L'exemple doit rester valide (un test le vérifie),
et le fichier anglais doit garder les mêmes blocs.
-->
<!-- @intro -->
Tu construis une frise chronologique pour réviser un cours.

Ta tâche : extraire la chronologie du texte source, et rien d'autre que ce qu'il dit. Tu renvoies un seul objet JSON au format `{{schema}}`, que l'application Ankigen dessine elle-même. Tu ne produis jamais de SVG, de HTML ni de coordonnées.

<!-- @title -->
Titre de la frise : {{title}}

<!-- @strict -->
## Mode strict

- Chaque date doit figurer dans le texte, ou s'en déduire directement (« trois ans plus tard », juste après une date donnée).
- N'invente aucune date, et ne précise jamais une date au-delà de ce que dit le texte : « en 1947 » donne "1947", jamais "1947-10-30".
- N'ajoute aucun élément absent du texte, même s'il te paraît important. Tous les éléments ont "origin": "text", la valeur par défaut : tu peux l'omettre.

<!-- @enriched -->
## Mode enrichi

- Extrais d'abord tout ce que contient le texte, avec les règles du mode strict : aucune date inventée, aucune date précisée au-delà du texte.
- Tu peux ensuite ajouter quelques dates de contexte indispensables pour comprendre le passage, au plus une pour cinq éléments extraits. Marque-les "origin": "model", sans "source_quote" : elles seront signalées « hors cours ».

<!-- @contract -->
## Format du JSON

Un seul objet, avec ces clés et aucune autre :

- "schema" : toujours "{{schema}}".
- "title" : le titre de la frise, {{max_title}} caractères au plus.
- "lang" : "{{lang}}", la langue du texte.
- "tracks" : de 0 à {{max_tracks}} pistes. Chaque piste : {"id", "label"}, avec un libellé de {{max_track_label}} caractères au plus.
- "eras" : de 0 à {{max_eras}} ères, des bandes de fond qui traversent toutes les pistes : {"id", "label", "start", "end"}, sans "track". Deux ères ne se chevauchent pas, mais elles peuvent partager leur année de contact.
- "periods" : de 0 à {{max_periods}} périodes, des durées dessinées en barres : {"id", "track", "label", "start", "end"}.
- "events" : de 0 à {{max_events}} évènements ponctuels : {"id", "track", "label", "date"}.

Il faut au moins un évènement ou une période.

Champs des ères, des périodes et des évènements :

- "id" : lettres minuscules sans accents, chiffres, "_" ou "-", {{max_id}} caractères au plus. Unique dans tout le document, pistes comprises.
- "track" : l'"id" d'une piste déclarée dans "tracks". Obligatoire dès qu'il y a des pistes, absent des ères.
- "label" : {{max_label}} caractères au plus ({{max_era_label}} pour une ère).
- "importance" : 1, 2 ou 3 (2 par défaut).
- "approx" : true pour une date approximative.
- "precision" : "day", "month", "year", "decade", "century" ou "millennium". Inutile pour un jour, un mois ou une année : la date les indique déjà.
- "description" : {{max_description}} caractères au plus.
- "date_text" : la formulation de la date dans le texte, {{max_date_text}} caractères au plus (« au lendemain de la guerre »).
- "source_quote" : l'extrait du texte qui justifie l'élément, {{max_quote}} caractères au plus.
- "origin" : "text" (par défaut) ou "model".
- "tags" : au plus {{max_tags}} mots-clés de {{max_tag}} caractères au plus.

## Écrire les dates

Une date est toujours une chaîne entre guillemets droits :

- jour "1971-08-15", mois "1971-08", année "1971" ;
- avant Jésus-Christ, une année négative : "-44" signifie 44 av. J.-C. L'année 0 n'existe pas : on passe de "-1" à "1" ;
- date approximative : « vers 1450 » donne "date": "1450" et "approx": true ;
- décennie : « les années 1970 » donne "date": "1970" et "precision": "decade" ;
- siècle : la première année du siècle, avec "precision": "century". Le XVIe siècle commence en 1501 : écris "1501", pas "1500". Le XIXe siècle donne "1801", le Ve siècle av. J.-C. donne "-500" ;
- millénaire : même règle avec "precision": "millennium" (le IIIe millénaire av. J.-C. donne "-3000") ;
- période encore en cours : "end": "present", seulement dans "end" ;
- la fin d'une période est incluse : "start": "1939" et "end": "1945" couvrent toute l'année 1945.

<!-- @rules -->
## Règles éditoriales

- Pistes : de 2 à 5 pistes thématiques (politique, économie, société…) ou géographiques. Une seule piste si le passage ne traite qu'un thème. Un libellé de piste fait 1 à 3 mots.
- Un évènement ponctuel est une date, une durée est une période, et une époque qui encadre tout le reste est une ère.
- Libellés de 2 à 8 mots, sans la date, et si possible sans verbe conjugué : « Signature du GATT », pas « Le GATT est signé en 1947 ».
- "importance" : 3 pour les pivots du passage (au plus un élément sur cinq), 2 pour ce qui est important, 1 pour les détails.
- "source_quote" : un extrait de 5 à 25 mots, copié à l'identique depuis le texte source. Ne le reformule pas, ne le traduis pas, ne corrige ni son orthographe ni sa ponctuation.
- "description" : une ou deux phrases qui disent pourquoi l'élément compte dans ce cours.
- Les tableaux du texte, en markdown, contiennent souvent des chronologies : exploite-les. Les marqueurs [IMAGE n] décrivent les figures du cours.

<!-- @example -->
## Exemple

Texte source :

Pendant la guerre froide (1947-1991), l'Europe de l'Ouest s'organise. Le traité de Paris, signé le 18 avril 1951, crée la Communauté européenne du charbon et de l'acier (CECA). Les traités de Rome du 25 mars 1957 instituent la Communauté économique européenne, dont l'union douanière est achevée en juillet 1968. De 1979 à 1998, le Système monétaire européen (SME) limite les fluctuations entre les monnaies. L'euro devient la monnaie unique le 1er janvier 1999.

Réponse attendue :

{
  "schema": "ankigen.timeline/1",
  "title": "La construction européenne",
  "lang": "fr",
  "tracks": [
    {"id": "institutions", "label": "Institutions"},
    {"id": "monnaie", "label": "Monnaie"}
  ],
  "eras": [
    {"id": "guerre_froide", "label": "Guerre froide", "start": "1947", "end": "1991",
     "source_quote": "Pendant la guerre froide (1947-1991), l'Europe de l'Ouest s'organise"}
  ],
  "periods": [
    {"id": "sme", "track": "monnaie", "label": "Système monétaire européen", "start": "1979", "end": "1998",
     "importance": 2, "description": "Il limite les fluctuations entre les monnaies européennes et prépare la monnaie unique.",
     "source_quote": "De 1979 à 1998, le Système monétaire européen (SME) limite les fluctuations entre les monnaies"}
  ],
  "events": [
    {"id": "ceca", "track": "institutions", "date": "1951-04-18", "label": "Création de la CECA", "importance": 2,
     "date_text": "le 18 avril 1951",
     "source_quote": "Le traité de Paris, signé le 18 avril 1951, crée la Communauté européenne du charbon et de l'acier"},
    {"id": "traites_rome", "track": "institutions", "date": "1957-03-25", "label": "Traités de Rome", "importance": 3,
     "description": "Ils fondent la CEE, cadre de l'intégration commerciale européenne.",
     "source_quote": "Les traités de Rome du 25 mars 1957 instituent la Communauté économique européenne"},
    {"id": "union_douaniere", "track": "institutions", "date": "1968-07", "label": "Achèvement de l'union douanière",
     "importance": 1, "source_quote": "dont l'union douanière est achevée en juillet 1968"},
    {"id": "euro", "track": "monnaie", "date": "1999-01-01", "label": "Naissance de l'euro", "importance": 2,
     "source_quote": "L'euro devient la monnaie unique le 1er janvier 1999"}
  ]
}

<!-- @output -->
## Format de la réponse

Réponds uniquement avec l'objet JSON : pas de texte avant ou après, pas de bloc de code.

<!-- @chunk -->
## Ce passage

Le texte source n'est qu'un paragraphe d'un cours plus long : la frise complète sera assemblée à partir de tous les paragraphes.

- S'il ne contient aucune date, renvoie quand même le document, avec des listes vides. C'est une réponse normale : n'invente rien pour les remplir.

<!-- @chunk_tracks -->
- Pistes déjà utilisées dans cette frise : {{tracks}}. Reprends leur "id" et leur libellé quand elles conviennent, et n'en crée une nouvelle que si aucune ne convient.

<!-- @source -->
## Texte source

<<<SOURCE
{{source}}
SOURCE>>>

<!-- @skill_strict -->
Utilise le Skill « Frise chronologique Ankigen », en mode strict, pour extraire la frise du texte source ci-dessous.

<!-- @skill_enriched -->
Utilise le Skill « Frise chronologique Ankigen », en mode enrichi, pour extraire la frise du texte source ci-dessous.

<!-- @skill_lang -->
Langue du texte : "{{lang}}".

<!-- @skill_header -->
---
name: ankigen-timeline
description: Extraire la chronologie d'un texte de cours en JSON ankigen.timeline/1,
  pour l'application Ankigen, qui dessine la frise. Utiliser ce skill dès que
  l'utilisateur demande une frise chronologique Ankigen, ou envoie un texte
  encadré par les marqueurs SOURCE en mentionnant la frise.
---

# Frise chronologique Ankigen

Le mode est indiqué dans la demande : strict par défaut, ou enrichi.

<!-- @correction -->
Ton JSON contient les erreurs suivantes :

{{errors}}

<!-- @correction_warnings -->
Corrige aussi, si possible, ces avertissements :

{{warnings}}

<!-- @correction_end -->
Renvoie le JSON complet corrigé, rien d'autre : pas de texte avant ou après, pas de bloc de code.

# Navigation entre cours et frises

## Objectif et critères d'acceptation

Le cours et ses frises partagent une origine visible. Depuis le cours, l'utilisateur ouvre une frise existante ou en crée une. Depuis une frise, il retrouve le cours et les paragraphes qui ont servi à l'extraction.

- Navigation commune « Cours / Frises » dans la barre supérieure, vue active identifiée par `aria-current`.
- Liste limitée aux frises du cours, avec titre, périmètre et état.
- Liens profonds par `chunk_id`, validés contre les paragraphes du cours. Les liens du cours transmettent le paragraphe actif à la frise ; le retour le restitue.
- Accès direct aux paragraphes, y compris pour l'extraction en prompt unique. Dans le formulaire d'un événement, accès au paragraphe si sa citation permet de l'identifier sans ambiguïté.
- Les frises importées restent autonomes ; un cours supprimé ne produit aucun lien mort.
- Les protections existantes contre la perte de modifications non enregistrées restent actives.

## Design system

Composant Jinja commun ; éléments HTML natifs (`nav`, `a`, `details`, `summary`, `button`). Tokens de composant dérivés des tokens existants : surfaces, accent, texte, espacements, rayon et cible tactile. Vue active, survol et focus distincts. Menus utilisables au clavier et à 320 px, titres longs tronqués avec un intitulé accessible.

## Mise en œuvre et validation

Routes Flask dans `app.py`, composant partagé dans `templates/`, navigation dans les scripts existants et styles dans `static/style.css`. Aucun changement de schéma, aucune dépendance et aucune synchronisation implicite des instantanés source.

1. Exposer le contexte et valider les liens : tests dans `tests/test_timeline_extraction_routes.py`.
2. Ajouter le composant commun, vérifier les tests et la syntaxe JavaScript.
3. Vérifier le parcours aller-retour, les sources et la création dans le navigateur à 320, 768, 1024 et 1440 px.

Tests : runtime Python du projet, `unittest discover -s tests -p 'test_timeline_*.py'` ; syntaxe JavaScript : `node --check` sur les scripts modifiés. Les modifications du checkout principal sont hors périmètre.

## Validation réalisée

- Suite Python complète : 624 tests réussis, dont les cas de retour au paragraphe, source ambiguë ou supprimée et mise à jour des liens après collage, fusion et sauvegarde.
- Tests JavaScript existants : 21 réussis ; vérification de syntaxe des trois scripts modifiés.
- Navigateur : aller-retour, accès aux sources, création et collage par paragraphe, protection du brouillon, ouverture au clavier. Navigation sans débordement à 320, 768, 1024 et 1440 px ; aucune erreur console.
- Après intégration des nouveaux en-tête et thème de `main` : 628 tests Python et 21 tests JavaScript réussis. Aller-retour et menus vérifiés sur bureau et à 320 px. Capture de démonstration : `docs/images/course-timeline-navigation.png`.

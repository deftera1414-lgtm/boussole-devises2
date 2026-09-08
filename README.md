# Boussole Devises — version autonome (GitHub Actions)

Ce dossier fait tourner le dashboard tout seul, en dehors de Claude : toutes les heures, un robot GitHub va rechercher l'inflation et le chômage réels des 8 devises (via l'API FRED), reconstruit le dashboard, et le republie automatiquement. Zéro action de votre part une fois que c'est branché.

## Ce qui est automatisé et ce qui ne l'est pas (v1)

Automatisé, toutes les heures, sans vous : inflation (IPC) et chômage, pour les 8 devises, via FRED.

Pas encore automatisé, reste à la charge du scan quotidien Claude existant (qui fonctionne déjà tout seul depuis le 1er septembre) : taux directeur, PIB, et surtout les champs de jugement — biais, momentum, ton (`tilt`), discours, cycle, calendrier des événements. Ce sont des lectures qui demandent d'interpréter un discours ou un communiqué, pas juste de lire un chiffre ; les automatiser proprement demanderait un vrai appel à un modèle de langage à chaque run, ce qui est une étape de plus, volontairement pas incluse ici pour rester simple et fiable.

## Mise en place (10 minutes, une seule fois)

1. **Créer le dépôt.** Sur GitHub, "New repository" — nommez-le comme vous voulez (ex. `boussole-devises`). Public (nécessaire pour GitHub Pages gratuit, sauf si vous avez un compte GitHub payant).
2. **Y déposer les fichiers de ce dossier** (`pipeline.py`, `template.html`, `currencies.json`, `update_data.py`, `.github/workflows/update.yml`, ce `README.md`) — glisser-déposer sur la page du dépôt fonctionne, ou `git push` si vous êtes à l'aise en ligne de commande.
3. **Obtenir une clé API FRED gratuite** : allez sur [fredaccount.stlouisfed.org/apikeys](https://fredaccount.stlouisfed.org/apikeys), créez un compte gratuit, générez une clé (instantané, aucune carte bancaire).
4. **Ajouter cette clé comme secret du dépôt** : Settings → Secrets and variables → Actions → "New repository secret" → nom `FRED_API_KEY`, valeur = la clé obtenue à l'étape 3.
5. **Activer GitHub Pages** : Settings → Pages → Source : "Deploy from a branch" → Branch : `main`, dossier `/docs` → Save.
6. **Lancer un premier test manuel** : onglet "Actions" du dépôt → "Boussole Devises — mise à jour horaire" → "Run workflow". Regardez le journal d'exécution : chaque devise y est loggée avec la série FRED utilisée et l'ancienne/nouvelle valeur — de quoi vérifier que tout est cohérent avant de laisser tourner tout seul.
7. **C'est tout.** Ensuite ça tourne every heure de façon autonome (cron dans `.github/workflows/update.yml`). Le dashboard est accessible à `https://<votre-nom-utilisateur>.github.io/<nom-du-dépôt>/`.

## Important : une deuxième adresse, pas un remplacement

Ce dashboard GitHub Pages aura sa propre adresse, différente de celle de l'artefact Claude actuel (`claude.ai/code/artifact/...`). Le robot GitHub ne peut techniquement pas publier sur cette dernière — seul un outil Claude le peut. Les deux peuvent coexister : l'artefact Claude continue d'être mis à jour par les tâches planifiées existantes (scan quotidien + veille horaire), et cette version GitHub tourne en parallèle, en totale autonomie. Si vous préférez n'en garder qu'une, dites-le-moi.

## Fichier `.update_status`

Après chaque exécution, `update_data.py` écrit ce petit fichier (`changed` / `unchanged` / `no_api_key`) — pratique pour un coup d'œil rapide dans les logs sans tout relire.

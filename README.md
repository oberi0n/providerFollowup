# Provider Follow-up

Application de suivi des factures fournisseurs avec OCR OCR.space, fallback local et interprétation IA locale optionnelle.

## Stack

- Frontend : React + Vite + Tailwind CSS
- Backend : Quarkus REST API
- Base : PostgreSQL
- Stockage fichiers : MinIO
- OCR : FastAPI + OCR.space API + fallback Tesseract local (`fra+eng`) + Poppler/pdf2image + interprétation IA locale via Ollama
- Déploiement : Docker Compose complet

## Lancement

```bash
docker compose up --build
```

Puis ouvrir :

- Frontend : http://localhost:3000
- Backend API : http://localhost:8080
- Keycloak : http://localhost:8081 (`admin` / `admin`)
- OCR healthcheck : http://localhost:8000/health
- Ollama local : http://localhost:11434 (modèle léger `qwen2.5:0.5b` chargé automatiquement au démarrage)
- Console MinIO : http://localhost:9001 (bouton Keycloak, `admin` / `admin`; compte technique root `minioadmin` / `minioadmin`)

## Authentification Keycloak

Docker Compose démarre un serveur Keycloak local et importe automatiquement le realm `provider-followup` depuis `keycloak/provider-followup-realm.json`. Un utilisateur de démonstration unique est créé pour le frontend, l’API backend et la console MinIO : `admin` / `admin`.

- Le frontend React utilise le client public `provider-followup-frontend`, force la connexion Keycloak au chargement, puis envoie le token Bearer à chaque appel API.
- Le frontend affiche un menu d’accès rapide vers MinIO (http://localhost:9001).
- Le backend Quarkus protège les routes `/api/*` avec OIDC via le client confidentiel `provider-followup-backend`.
- MinIO expose le bouton de connexion OpenID “Keycloak” et lit le claim `policy=consoleAdmin` émis pour l’utilisateur `admin`.
- Keycloak publie `http://localhost:8081` comme URL frontend et garde un backchannel dynamique pour les appels internes Docker ; le bouton Keycloak de MinIO redirige donc le navigateur vers `localhost:8081` au lieu du nom de service Docker `keycloak:8080`.

## Workflow OCR

1. Créer une facture depuis l'écran principal.
2. Uploader une image JPG/PNG ou un PDF.
3. Le backend stocke le fichier dans le bucket MinIO `invoices`, sous `invoices/YYYY/MM/<uuid>-<nom-fichier>` selon la date de facture si elle est renseignée, sinon selon le mois courant.
4. Le backend appelle le service interne `ocr-service` via `POST /ocr/extract`.
5. Le service OCR lit le fichier depuis MinIO, envoie le fichier à OCR.space avec la clé configurée, puis utilise Tesseract local comme fallback si OCR.space ne renvoie aucun texte.
6. Une couche d’interprétation IA locale via Ollama analyse le texte OCR brut et renvoie les champs structurés ; si Ollama ou le modèle ne sont pas disponibles, les heuristiques regex existantes prennent automatiquement le relais.
7. Le frontend affiche les suggestions et le texte OCR brut pour debug.
8. L'utilisateur copie les suggestions souhaitées, corrige si besoin, puis valide.
9. Les champs validés et le résultat OCR brut sont conservés en base, et les champs principaux de la facture sont synchronisés dans les métadonnées de l’objet MinIO. Si l’utilisateur abandonne la saisie OCR avant validation, le frontend appelle `DELETE /api/invoices/{id}` pour supprimer la facture brouillon et son objet MinIO.

> Important : l'OCR ne remplace jamais automatiquement les champs validés d'une facture. Les suggestions sont stockées séparément dans `ocrSuggestionsJson`.

## Organisation de l'écran principal

L'écran principal utilise un thème sombre et est organisé dans l'ordre d'usage : sélection du fichier et formulaire facture en premier, paramétrage budgétaire et synthèses ensuite, puis liste des factures de l'année sélectionnée en fin de page.

## Endpoints principaux

- `GET /api/invoices`
- `POST /api/invoices`
- `PUT /api/invoices/{id}`
- `POST /api/invoices/{id}/upload`
- `POST /api/invoices/{id}/ocr`
- `GET /api/invoices/{id}/ocr-result`
- `DELETE /api/invoices/{id}`
- `GET /api/dashboard`
- Interne OCR : `POST /ocr/extract`

Réponse OCR :

```json
{
  "rawText": "...",
  "suggestions": {
    "supplierName": "...",
    "invoiceNumber": "...",
    "invoiceDate": "YYYY-MM-DD",
    "amountHt": 0,
    "vatAmount": 0,
    "amountTtc": 0,
    "currency": "EUR"
  },
  "confidence": "LOW"
}
```

## Modèle Invoice

Le backend persiste notamment : `id`, `supplierId`, `invoiceNumber`, `invoiceDate`, `amountHt`, `vatAmount`, `amountTtc`, `budgetType` (`OPEX` ou `CAPEX`), `currency`, `category`, `status`, `comment`, `fileObjectKey`, `originalFilename`, `ocrRawText`, `ocrSuggestionsJson`, `ocrProcessedAt`, `createdAt`, `updatedAt`.

## Données initiales

Aucune facture de test n’est créée par défaut. Le fichier `backend/src/main/resources/import.sql` est volontairement vide afin que l’application démarre avec une liste de factures vierge. Le dashboard se remplit uniquement avec les factures saisies ou importées via OCR.

## Année budgétaire

Le dashboard permet de choisir une année budgétaire et de paramétrer deux lignes de budget annuelles : `OPEX` et `CAPEX`. L’API `GET /api/dashboard?year=YYYY&opexBudget=80000&capexBudget=40000` filtre les factures par date de facture sur l’année choisie, puis calcule la synthèse globale `CAPEX + OPEX`, les consommés/restants par ligne et les ventilations mensuelles/fournisseur/catégorie/type de budget. Le frontend ajoute trois graphiques de suivi budgétaire (global, CAPEX et OPEX) avec une courbe réelle basée sur les factures enregistrées et une courbe de prévision pointillée pour les mois restants, calculée à partir de la moyenne mensuelle observée. Les graphiques utilisent une échelle basée sur le consommé/prévu pour éviter que les petites dépenses restent collées à zéro lorsque le budget annuel est beaucoup plus élevé. Le graphique global occupe une ligne complète, puis les graphiques CAPEX et OPEX sont affichés sur la ligne suivante pour améliorer la lisibilité.

Chaque facture validée doit obligatoirement avoir un fournisseur, une date de facture, un montant TTC et une affectation `OPEX` ou `CAPEX`. Le mode brouillon utilisé pendant l’OCR reste autorisé afin de pouvoir préremplir ces champs avant validation manuelle.


## Persistance des données

Les factures sont conservées au redémarrage des conteneurs grâce au volume Docker `postgres-data`. Le backend utilise `quarkus.hibernate-orm.database.generation=update` afin de mettre à jour le schéma sans supprimer les tables existantes. Les fichiers restent conservés dans le volume `minio-data`. Attention : `docker compose down -v` supprime volontairement ces volumes et donc les données.

## Organisation MinIO

Les fichiers ne sont pas rangés par identifiant séquentiel de facture. Chaque upload utilise une clé objet du type `invoices/YYYY/MM/<uuid>-<nom-fichier>`, ce qui regroupe les factures par année et mois tout en évitant les collisions de noms. Si la date de facture est connue au moment de l’upload, elle détermine immédiatement `YYYY/MM`. Si la date est détectée par OCR, le backend l’applique uniquement quand la facture n’avait pas encore de date, puis déplace immédiatement l’objet MinIO vers le mois correspondant. Si l’utilisateur corrige ensuite la date lors de la validation, le backend déplace à nouveau l’objet vers le mois corrigé. À chaque upload, OCR ou enregistrement, les informations validées du formulaire (`supplierName`, `invoiceNumber`, `invoiceDate`, montants, type de budget, devise et commentaire) sont aussi réécrites dans les métadonnées MinIO de l’objet pour faciliter l’inspection côté stockage.

## Thème de connexion

Keycloak utilise le thème `provider-followup` monté depuis `keycloak/themes`. La page de connexion affiche uniquement le nom de l’application, le champ utilisateur, le champ mot de passe et un bouton de connexion, avec un fond cohérent avec l’interface Provider Follow-up.

## OCR OCR.space et interprétation IA locale

L’OCR principal utilise OCR.space via `https://api.ocr.space/parse/image`. La clé API est fournie au conteneur avec `OCR_SPACE_API_KEY`; les langues configurées par défaut sont `fre,eng` et le moteur OCR.space `2`. Tesseract reste disponible comme fallback local si OCR.space ne renvoie aucun texte.

Après extraction du texte brut, le service OCR peut utiliser Ollama en local pour mieux interpréter le fournisseur, le numéro de facture, la date, les montants et la devise. Cette couche IA est configurée par `OCR_AI_ENABLED`, `OCR_AI_PROVIDER`, `OCR_AI_URL`, `OCR_AI_MODEL`, `OCR_AI_TIMEOUT`, `OCR_AI_MAX_CHARS`, `OCR_AI_NUM_CTX` et `OCR_AI_NUM_PREDICT`. Par défaut, Docker Compose pointe vers le service `ollama` avec le modèle léger `qwen2.5:0.5b`, suffisant pour transformer du texte OCR en JSON structuré.

Le service `ollama-model-loader` télécharge automatiquement ce modèle au démarrage avec `ollama pull qwen2.5:0.5b` et `ocr-service` attend la fin de ce chargement avant de démarrer. Le modèle est conservé dans le volume Docker `ollama-data`, donc le téléchargement ne se répète pas à chaque redémarrage.

Le timeout IA est volontairement fixé à 45 secondes, car le premier appel charge le modèle en mémoire et peut être lent sur CPU. Le prompt OCR est limité et le contexte Ollama est réduit pour accélérer l’interprétation. Si Ollama est indisponible, dépasse le timeout ou renvoie une réponse non JSON, l’application continue de fonctionner avec les heuristiques regex déterministes. Cette amélioration ne dépend donc d’aucun service IA cloud payant.

## Versions techniques vérifiées

Les versions ci-dessous ont été revues le 25 juin 2026 par rapport aux annonces et registres publics disponibles. Les images et dépendances sont volontairement épinglées pour obtenir des builds reproductibles tout en restant à jour sur les branches stables utilisées par le projet.

| Composant | Version utilisée | Note |
| --- | --- | --- |
| PostgreSQL | `postgres:16.14-alpine` | Dernier correctif disponible sur la branche 16, afin de préserver la compatibilité directe avec le volume existant `postgres-data`. Une montée majeure vers PostgreSQL 18 demande une migration de volume/dump-restore dédiée. |
| MinIO | `minio/minio:RELEASE.2025-09-07T16-13-09Z` | Dernière image MinIO officielle publiée sur Docker Hub identifiée lors de la revue. |
| Keycloak serveur | `quay.io/keycloak/keycloak:26.6.3` | Version serveur Keycloak 26.6.x récente. |
| Keycloak JS | `keycloak-js@26.2.4` | Dernière version npm publique du client JavaScript Keycloak identifiée lors de la revue. |
| Quarkus | `3.36.3` | Version Quarkus récente alignée avec le train 3.36. |
| OkHttp JVM | `com.squareup.okhttp3:okhttp-jvm:5.4.0` | Dépendance JVM explicite requise par le SDK MinIO Java `9.0.3` pour compiler `MinioClient.builder().endpoint(...)` avec la classe `okhttp3.HttpUrl`. |
| Maven image | `maven:3.9.16-eclipse-temurin-21` | Maven 3.9.16 est la version 3.9 recommandée au moment de la revue. |
| Java runtime | `eclipse-temurin:21.0.11_10-jre` | Dernier runtime Temurin 21 disponible identifié lors de la revue. |
| Frontend | React `19.2.7`, Vite `8.1.0`, Tailwind CSS `4.3.1`, Lucide `1.21.0` | Dépendances frontend mises à jour vers les versions stables récentes. Tailwind utilise désormais le plugin Vite `@tailwindcss/vite`. |
| OCR service | Python `3.13-slim`, FastAPI `0.138.0`, Uvicorn `0.48.0`, Pillow `12.2.0`, MinIO SDK `7.2.20`, Requests `2.34.2`, python-multipart `0.0.32`, Pydantic `2.13.4` | Dépendances OCR mises à jour vers les dernières versions stables identifiées, en conservant `pdf2image==1.17.0` et `pytesseract==0.3.13` déjà à jour. |
| Ollama | `ollama/ollama:latest` | Conservé sur le tag `latest` car le service sert uniquement à charger et servir le modèle local léger configuré. |

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
- Metabase : http://localhost:3001 (`admin@providerfollowup.local` / `ProviderFollowup!2026`)
- Console MinIO : http://localhost:9001 (bouton Keycloak, `admin` / `admin`; compte technique root `minioadmin` / `minioadmin`)

## Authentification Keycloak

Docker Compose démarre un serveur Keycloak local et importe automatiquement le realm `provider-followup` depuis `keycloak/provider-followup-realm.json`. Un utilisateur de démonstration unique est créé pour le frontend, l’API backend et la console MinIO : `admin` / `admin`.

- Le frontend React utilise le client public `provider-followup-frontend`, force la connexion Keycloak au chargement, puis envoie le token Bearer à chaque appel API.
- Le frontend affiche un menu d’accès rapide avec liens vers MinIO (http://localhost:9001) et Metabase (http://localhost:3001).
- Le backend Quarkus protège les routes `/api/*` avec OIDC via le client confidentiel `provider-followup-backend`.
- MinIO expose le bouton de connexion OpenID “Keycloak” et lit le claim `policy=consoleAdmin` émis pour l’utilisateur `admin`.
- Keycloak publie `http://localhost:8081` comme URL frontend et garde un backchannel dynamique pour les appels internes Docker ; le bouton Keycloak de MinIO redirige donc le navigateur vers `localhost:8081` au lieu du nom de service Docker `keycloak:8080`.
- Metabase Community Edition ne fournit pas de SSO Keycloak OpenID Connect natif sans extension/édition payante ; il conserve donc son compte local auto-configuré indiqué ci-dessus.

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

L'écran principal est organisé dans l'ordre d'usage : sélection du fichier et formulaire facture en premier, paramétrage budgétaire et synthèses ensuite, puis liste des factures de l'année sélectionnée en fin de page.

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

Le dashboard permet de choisir une année budgétaire et de paramétrer deux lignes de budget annuelles : `OPEX` et `CAPEX`. L’API `GET /api/dashboard?year=YYYY&opexBudget=80000&capexBudget=40000` filtre les factures par date de facture sur l’année choisie, puis calcule la synthèse globale `CAPEX + OPEX`, les consommés/restants par ligne et les ventilations mensuelles/fournisseur/catégorie/type de budget. Le frontend ajoute trois graphiques de suivi budgétaire (global, CAPEX et OPEX) avec une courbe réelle basée sur les factures enregistrées et une courbe de prévision pointillée pour les mois restants, calculée à partir de la moyenne mensuelle observée.

Chaque facture validée doit obligatoirement avoir un fournisseur, une date de facture, un montant TTC et une affectation `OPEX` ou `CAPEX`. Le mode brouillon utilisé pendant l’OCR reste autorisé afin de pouvoir préremplir ces champs avant validation manuelle.

## Organisation MinIO

Les fichiers ne sont pas rangés par identifiant séquentiel de facture. Chaque upload utilise une clé objet du type `invoices/YYYY/MM/<uuid>-<nom-fichier>`, ce qui regroupe les factures par année et mois tout en évitant les collisions de noms. Si la date de facture est connue au moment de l’upload, elle détermine immédiatement `YYYY/MM`. Si la date est détectée par OCR, le backend l’applique uniquement quand la facture n’avait pas encore de date, puis déplace immédiatement l’objet MinIO vers le mois correspondant. Si l’utilisateur corrige ensuite la date lors de la validation, le backend déplace à nouveau l’objet vers le mois corrigé. À chaque upload, OCR ou enregistrement, les informations validées du formulaire (`supplierName`, `invoiceNumber`, `invoiceDate`, montants, type de budget, devise et commentaire) sont aussi réécrites dans les métadonnées MinIO de l’objet pour faciliter l’inspection côté stockage.

## Metabase

Docker Compose démarre également Metabase sur http://localhost:3001. Le service `metabase-setup` initialise un compte admin local (`admin@providerfollowup.local` / `ProviderFollowup!2026`), connecte la base PostgreSQL `providerfollowup` et crée un dashboard avec cartes SQL : total TTC par mois, dépenses par fournisseur, factures récentes, total annuel et un diagramme de progression cumulée par année budgétaire sur les 12 mois de janvier à décembre.

## Thème de connexion

Keycloak utilise le thème `provider-followup` monté depuis `keycloak/themes`. La page de connexion affiche uniquement le nom de l’application, le champ utilisateur, le champ mot de passe et un bouton de connexion, avec un fond cohérent avec l’interface Provider Follow-up.

## OCR OCR.space et interprétation IA locale

L’OCR principal utilise OCR.space via `https://api.ocr.space/parse/image`. La clé API est fournie au conteneur avec `OCR_SPACE_API_KEY`; les langues configurées par défaut sont `fre,eng` et le moteur OCR.space `2`. Tesseract reste disponible comme fallback local si OCR.space ne renvoie aucun texte.

Après extraction du texte brut, le service OCR peut utiliser Ollama en local pour mieux interpréter le fournisseur, le numéro de facture, la date, les montants et la devise. Cette couche IA est configurée par `OCR_AI_ENABLED`, `OCR_AI_PROVIDER`, `OCR_AI_URL`, `OCR_AI_MODEL`, `OCR_AI_TIMEOUT`, `OCR_AI_MAX_CHARS`, `OCR_AI_NUM_CTX` et `OCR_AI_NUM_PREDICT`. Par défaut, Docker Compose pointe vers le service `ollama` avec le modèle léger `qwen2.5:0.5b`, suffisant pour transformer du texte OCR en JSON structuré.

Le service `ollama-model-loader` télécharge automatiquement ce modèle au démarrage avec `ollama pull qwen2.5:0.5b` et `ocr-service` attend la fin de ce chargement avant de démarrer. Le modèle est conservé dans le volume Docker `ollama-data`, donc le téléchargement ne se répète pas à chaque redémarrage.

Le timeout IA est volontairement fixé à 45 secondes, car le premier appel charge le modèle en mémoire et peut être lent sur CPU. Le prompt OCR est limité et le contexte Ollama est réduit pour accélérer l’interprétation. Si Ollama est indisponible, dépasse le timeout ou renvoie une réponse non JSON, l’application continue de fonctionner avec les heuristiques regex déterministes. Cette amélioration ne dépend donc d’aucun service IA cloud payant.

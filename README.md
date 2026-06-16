# Provider Follow-up

Application de suivi des factures fournisseurs avec OCR OCR.space et fallback local.

## Stack

- Frontend : React + Vite + Tailwind CSS
- Backend : Quarkus REST API
- Base : PostgreSQL
- Stockage fichiers : MinIO
- OCR : FastAPI + OCR.space API + fallback Tesseract local (`fra+eng`) + Poppler/pdf2image
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
- Metabase : http://localhost:3001 (`admin@providerfollowup.local` / `ProviderFollowup!2026`)
- Console MinIO : http://localhost:9001 (bouton Keycloak, `admin` / `admin`; compte technique root `minioadmin` / `minioadmin`)

## Authentification Keycloak

Docker Compose démarre un serveur Keycloak local et importe automatiquement le realm `provider-followup` depuis `keycloak/provider-followup-realm.json`. Un utilisateur de démonstration unique est créé pour le frontend, l’API backend et la console MinIO : `admin` / `admin`.

- Le frontend React utilise le client public `provider-followup-frontend`, force la connexion Keycloak au chargement, puis envoie le token Bearer à chaque appel API.
- Le frontend affiche aussi un bouton `MinIO` qui ouvre directement la console de stockage sur http://localhost:9001.
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
6. Des heuristiques post-OCR proposent fournisseur, numéro, date, montants HT/TVA/TTC et devise.
7. Le frontend affiche les suggestions et le texte OCR brut pour debug.
8. L'utilisateur copie les suggestions souhaitées, corrige si besoin, puis valide.
9. Les champs validés et le résultat OCR brut sont conservés en base, et les champs principaux de la facture sont synchronisés dans les métadonnées de l’objet MinIO.

> Important : l'OCR ne remplace jamais automatiquement les champs validés d'une facture. Les suggestions sont stockées séparément dans `ocrSuggestionsJson`.

## Endpoints principaux

- `GET /api/invoices`
- `POST /api/invoices`
- `PUT /api/invoices/{id}`
- `POST /api/invoices/{id}/upload`
- `POST /api/invoices/{id}/ocr`
- `GET /api/invoices/{id}/ocr-result`
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

Le backend persiste notamment : `id`, `supplierId`, `invoiceNumber`, `invoiceDate`, `amountHt`, `vatAmount`, `amountTtc`, `currency`, `category`, `status`, `comment`, `fileObjectKey`, `originalFilename`, `ocrRawText`, `ocrSuggestionsJson`, `ocrProcessedAt`, `createdAt`, `updatedAt`.

## Données initiales

Aucune facture de test n’est créée par défaut. Le fichier `backend/src/main/resources/import.sql` est volontairement vide afin que l’application démarre avec une liste de factures vierge. Le dashboard se remplit uniquement avec les factures saisies ou importées via OCR.

## Année budgétaire

Le dashboard permet de choisir une année budgétaire et un budget annuel. L’API `GET /api/dashboard?year=YYYY&budget=120000` filtre les factures par date de facture sur l’année choisie, puis calcule consommé, reste disponible et ventilations mensuelles/fournisseur/catégorie.

## Organisation MinIO

Les fichiers ne sont pas rangés par identifiant séquentiel de facture. Chaque upload utilise une clé objet du type `invoices/YYYY/MM/<uuid>-<nom-fichier>`, ce qui regroupe les factures par année et mois tout en évitant les collisions de noms. Si la date de facture est connue au moment de l’upload, elle détermine immédiatement `YYYY/MM`. Si la date est détectée par OCR, le backend l’applique uniquement quand la facture n’avait pas encore de date, puis déplace immédiatement l’objet MinIO vers le mois correspondant. Si l’utilisateur corrige ensuite la date lors de la validation, le backend déplace à nouveau l’objet vers le mois corrigé. À chaque upload, OCR ou enregistrement, les informations validées du formulaire (`supplierName`, `invoiceNumber`, `invoiceDate`, montants, devise et commentaire) sont aussi réécrites dans les métadonnées MinIO de l’objet pour faciliter l’inspection côté stockage.

## Metabase

Docker Compose démarre également Metabase sur http://localhost:3001. Le service `metabase-setup` initialise un compte admin local (`admin@providerfollowup.local` / `ProviderFollowup!2026`), connecte la base PostgreSQL `providerfollowup` et crée un dashboard avec cartes SQL : total TTC par mois, dépenses par fournisseur, factures récentes, total annuel et un diagramme de progression cumulée par année budgétaire sur les 12 mois de janvier à décembre.

## Thème de connexion

Keycloak utilise le thème `provider-followup` monté depuis `keycloak/themes`. La page de connexion affiche uniquement le nom de l’application, le champ utilisateur, le champ mot de passe et un bouton de connexion, avec un fond cohérent avec l’interface Provider Follow-up.

## OCR OCR.space

L’OCR principal utilise OCR.space via `https://api.ocr.space/parse/image`. La clé API est fournie au conteneur avec `OCR_SPACE_API_KEY`; les langues configurées par défaut sont `fre,eng` et le moteur OCR.space `2`. Tesseract reste disponible comme fallback local si OCR.space ne renvoie aucun texte.

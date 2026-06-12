# Provider Follow-up

Application locale de suivi des factures fournisseurs avec OCR gratuit et local.

## Stack

- Frontend : React + Vite + Tailwind CSS
- Backend : Quarkus REST API
- Base : PostgreSQL
- Stockage fichiers : MinIO
- OCR : FastAPI + Tesseract OCR (`fra+eng`) + Poppler/pdf2image
- Déploiement : Docker Compose complet

## Lancement

```bash
docker compose up --build
```

Puis ouvrir :

- Frontend : http://localhost:3000
- Backend API : http://localhost:8080
- OCR healthcheck : http://localhost:8000/health
- Console MinIO : http://localhost:9001 (`minioadmin` / `minioadmin`)

## Workflow OCR

1. Créer une facture depuis l'écran principal.
2. Uploader une image JPG/PNG ou un PDF.
3. Le backend stocke le fichier dans le bucket MinIO `invoices`.
4. Le backend appelle le service interne `ocr-service` via `POST /ocr/extract`.
5. Le service OCR lit le fichier depuis MinIO, convertit les PDF en images avec Poppler, puis lance Tesseract en français et anglais.
6. Des regex simples proposent fournisseur, numéro, date, montants HT/TVA/TTC et devise.
7. Le frontend affiche les suggestions et le texte OCR brut pour debug.
8. L'utilisateur copie les suggestions souhaitées, corrige si besoin, puis valide.
9. Les champs validés et le résultat OCR brut sont conservés en base.

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

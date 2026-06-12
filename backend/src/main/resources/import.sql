INSERT INTO invoices (supplier_id, supplier_name, invoice_number, invoice_date, amount_ht, vat_amount, amount_ttc, currency, category, status, comment, created_at, updated_at) VALUES
(1, 'Orange Business', 'OB-2026-001', '2026-01-15', 1200.00, 240.00, 1440.00, 'EUR', 'Télécom', 'PAID', 'Seed: abonnement fibre', now(), now()),
(2, 'AWS France', 'AWS-2026-042', '2026-02-28', 3200.00, 640.00, 3840.00, 'EUR', 'Cloud', 'SENT_TO_FINANCE', 'Seed: hébergement', now(), now()),
(3, 'Bureau Vallée', 'BV-7781', '2026-03-05', 450.00, 90.00, 540.00, 'EUR', 'Fournitures', 'RECEIVED', 'Seed: fournitures', now(), now()),
(4, 'DocuSign', 'DS-2026-314', '2026-03-20', 900.00, 180.00, 1080.00, 'EUR', 'SaaS', 'TO_SIGN', 'Seed: licences', now(), now());

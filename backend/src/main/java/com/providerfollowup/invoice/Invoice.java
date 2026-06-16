package com.providerfollowup.invoice;

import io.quarkus.hibernate.orm.panache.PanacheEntityBase;
import jakarta.persistence.*;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;

@Entity
@Table(name = "invoices")
public class Invoice extends PanacheEntityBase {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    public Long id;
    @Column(name = "supplier_id")
    public Long supplierId;
    @Column(name = "supplier_name")
    public String supplierName;
    @Column(name = "invoice_number")
    public String invoiceNumber;
    @Column(name = "invoice_date")
    public LocalDate invoiceDate;
    @Column(name = "amount_ht")
    public BigDecimal amountHt;
    @Column(name = "vat_amount")
    public BigDecimal vatAmount;
    @Column(name = "amount_ttc")
    public BigDecimal amountTtc;
    @Enumerated(EnumType.STRING)
    @Column(name = "budget_type")
    public BudgetType budgetType;
    public String currency = "EUR";
    public String category;
    @Enumerated(EnumType.STRING)
    public InvoiceStatus status = InvoiceStatus.RECEIVED;
    @Column(length = 2048)
    public String comment;
    @Column(name = "file_object_key")
    public String fileObjectKey;
    @Column(name = "original_filename")
    public String originalFilename;
    @Column(name = "ocr_raw_text", columnDefinition = "TEXT")
    public String ocrRawText;
    @Column(name = "ocr_suggestions_json", columnDefinition = "TEXT")
    public String ocrSuggestionsJson;
    @Column(name = "ocr_processed_at")
    public OffsetDateTime ocrProcessedAt;
    @Column(name = "created_at")
    public OffsetDateTime createdAt;
    @Column(name = "updated_at")
    public OffsetDateTime updatedAt;

    @PrePersist
    void prePersist() {
        createdAt = OffsetDateTime.now();
        updatedAt = createdAt;
    }

    @PreUpdate
    void preUpdate() {
        updatedAt = OffsetDateTime.now();
    }
}

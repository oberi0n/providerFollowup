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
    public Long supplierId;
    public String supplierName;
    public String invoiceNumber;
    public LocalDate invoiceDate;
    public BigDecimal amountHt;
    public BigDecimal vatAmount;
    public BigDecimal amountTtc;
    public String currency = "EUR";
    public String category;
    @Enumerated(EnumType.STRING)
    public InvoiceStatus status = InvoiceStatus.RECEIVED;
    @Column(length = 2048)
    public String comment;
    public String fileObjectKey;
    public String originalFilename;
    @Column(columnDefinition = "TEXT")
    public String ocrRawText;
    @Column(columnDefinition = "TEXT")
    public String ocrSuggestionsJson;
    public OffsetDateTime ocrProcessedAt;
    public OffsetDateTime createdAt;
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

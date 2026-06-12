package com.providerfollowup.invoice;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.Map;

public class InvoiceDtos {
    public record InvoiceRequest(
            Long supplierId,
            String supplierName,
            String invoiceNumber,
            LocalDate invoiceDate,
            BigDecimal amountHt,
            BigDecimal vatAmount,
            BigDecimal amountTtc,
            String currency,
            String category,
            InvoiceStatus status,
            String comment) {}

    public record InvoiceResponse(
            Long id,
            Long supplierId,
            String supplierName,
            String invoiceNumber,
            LocalDate invoiceDate,
            BigDecimal amountHt,
            BigDecimal vatAmount,
            BigDecimal amountTtc,
            String currency,
            String category,
            InvoiceStatus status,
            String comment,
            String fileObjectKey,
            String originalFilename,
            String ocrRawText,
            String ocrSuggestionsJson,
            OffsetDateTime ocrProcessedAt,
            OffsetDateTime createdAt,
            OffsetDateTime updatedAt) {
        public static InvoiceResponse from(Invoice invoice) {
            return new InvoiceResponse(invoice.id, invoice.supplierId, invoice.supplierName, invoice.invoiceNumber,
                    invoice.invoiceDate, invoice.amountHt, invoice.vatAmount, invoice.amountTtc, invoice.currency,
                    invoice.category, invoice.status, invoice.comment, invoice.fileObjectKey, invoice.originalFilename,
                    invoice.ocrRawText, invoice.ocrSuggestionsJson, invoice.ocrProcessedAt, invoice.createdAt, invoice.updatedAt);
        }
    }

    public record OcrSuggestions(
            String supplierName,
            String invoiceNumber,
            String invoiceDate,
            BigDecimal amountHt,
            BigDecimal vatAmount,
            BigDecimal amountTtc,
            String currency) {}

    public record OcrResult(String rawText, OcrSuggestions suggestions, String confidence) {}
    public record OcrRequest(String objectKey, String filename, String contentType) {}
    public record OcrResultResponse(String rawText, Map<String, Object> suggestions, String confidence, OffsetDateTime processedAt) {}
}

package com.providerfollowup.invoice;

import io.minio.BucketExistsArgs;
import io.minio.CopyObjectArgs;
import io.minio.Directive;
import io.minio.MakeBucketArgs;
import io.minio.MinioClient;
import io.minio.PutObjectArgs;
import io.minio.RemoveObjectArgs;
import io.minio.CopySource;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import org.eclipse.microprofile.config.inject.ConfigProperty;

import java.io.InputStream;
import java.time.LocalDate;
import java.time.YearMonth;
import java.time.format.DateTimeFormatter;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;

@ApplicationScoped
public class MinioStorageService {
    @Inject MinioClient minioClient;
    @ConfigProperty(name = "minio.bucket") String bucket;

    public String upload(Invoice invoice, String originalFilename, String contentType, InputStream inputStream, long size) throws Exception {
        ensureBucket();
        String objectKey = buildObjectKey(invoice == null ? null : invoice.invoiceDate, originalFilename, null);
        minioClient.putObject(PutObjectArgs.builder()
                .bucket(bucket)
                .object(objectKey)
                .stream(inputStream, size, -1)
                .contentType(contentType == null ? "application/octet-stream" : contentType)
                .userMetadata(metadataFor(invoice))
                .build());
        return objectKey;
    }

    public void deleteObject(String objectKey) throws Exception {
        if (objectKey == null || objectKey.isBlank()) {
            return;
        }
        ensureBucket();
        minioClient.removeObject(RemoveObjectArgs.builder().bucket(bucket).object(objectKey).build());
    }

    public String syncObjectWithInvoice(String currentObjectKey, Invoice invoice) throws Exception {
        if (currentObjectKey == null || invoice == null) {
            return currentObjectKey;
        }
        ensureBucket();
        LocalDate invoiceDate = invoice.invoiceDate;
        String targetObjectKey = currentObjectKey;
        if (invoiceDate != null && !currentObjectKey.startsWith(prefixFor(invoiceDate))) {
            targetObjectKey = buildObjectKey(invoiceDate, invoice.originalFilename, objectSuffix(currentObjectKey, invoice.originalFilename));
        }
        copyReplacingMetadata(currentObjectKey, targetObjectKey, metadataFor(invoice));
        if (!targetObjectKey.equals(currentObjectKey)) {
            minioClient.removeObject(RemoveObjectArgs.builder().bucket(bucket).object(currentObjectKey).build());
        }
        return targetObjectKey;
    }

    private void copyReplacingMetadata(String sourceObjectKey, String targetObjectKey, Map<String, String> metadata) throws Exception {
        if (sourceObjectKey.equals(targetObjectKey)) {
            String temporaryObjectKey = targetObjectKey + ".metadata-" + UUID.randomUUID();
            copyReplacingMetadata(sourceObjectKey, temporaryObjectKey, metadata);
            minioClient.removeObject(RemoveObjectArgs.builder().bucket(bucket).object(sourceObjectKey).build());
            copyReplacingMetadata(temporaryObjectKey, targetObjectKey, metadata);
            minioClient.removeObject(RemoveObjectArgs.builder().bucket(bucket).object(temporaryObjectKey).build());
            return;
        }
        minioClient.copyObject(CopyObjectArgs.builder()
                .bucket(bucket)
                .object(targetObjectKey)
                .source(CopySource.builder().bucket(bucket).object(sourceObjectKey).build())
                .metadataDirective(Directive.REPLACE)
                .userMetadata(metadata)
                .build());
    }

    private String buildObjectKey(LocalDate invoiceDate, String originalFilename, String existingSuffix) {
        String suffix = existingSuffix == null || existingSuffix.isBlank()
                ? UUID.randomUUID() + "-" + safeName(originalFilename)
                : existingSuffix;
        YearMonth storageMonth = invoiceDate == null ? YearMonth.now() : YearMonth.from(invoiceDate);
        return prefixFor(storageMonth) + suffix;
    }

    private String prefixFor(LocalDate invoiceDate) {
        return prefixFor(YearMonth.from(invoiceDate));
    }

    private String prefixFor(YearMonth storageMonth) {
        return "invoices/" + storageMonth.format(DateTimeFormatter.ofPattern("yyyy/MM")) + "/";
    }

    private String objectSuffix(String currentObjectKey, String originalFilename) {
        String[] parts = currentObjectKey.split("/", 4);
        if (parts.length == 4 && currentObjectKey.startsWith("invoices/")) {
            return parts[3];
        }
        return UUID.randomUUID() + "-" + safeName(originalFilename);
    }

    private Map<String, String> metadataFor(Invoice invoice) {
        Map<String, String> metadata = new LinkedHashMap<>();
        if (invoice == null) {
            return metadata;
        }
        putMetadata(metadata, "invoice-id", invoice.id);
        putMetadata(metadata, "original-filename", invoice.originalFilename);
        putMetadata(metadata, "supplier-id", invoice.supplierId);
        putMetadata(metadata, "supplier-name", invoice.supplierName);
        putMetadata(metadata, "invoice-number", invoice.invoiceNumber);
        putMetadata(metadata, "invoice-date", invoice.invoiceDate);
        putMetadata(metadata, "amount-ht", invoice.amountHt);
        putMetadata(metadata, "vat-amount", invoice.vatAmount);
        putMetadata(metadata, "amount-ttc", invoice.amountTtc);
        putMetadata(metadata, "budget-type", invoice.budgetType);
        putMetadata(metadata, "currency", invoice.currency);
        putMetadata(metadata, "comment", invoice.comment);
        return metadata;
    }

    private void putMetadata(Map<String, String> metadata, String key, Object value) {
        if (value != null) {
            metadata.put(key, cleanMetadataValue(String.valueOf(value)));
        }
    }

    private String cleanMetadataValue(String value) {
        String cleaned = value.replaceAll("[\r\n]", " ").trim();
        return cleaned.length() > 512 ? cleaned.substring(0, 512) : cleaned;
    }

    private String safeName(String originalFilename) {
        return originalFilename == null ? "invoice-file" : originalFilename.replaceAll("[^a-zA-Z0-9._-]", "_");
    }

    private void ensureBucket() throws Exception {
        boolean exists = minioClient.bucketExists(BucketExistsArgs.builder().bucket(bucket).build());
        if (!exists) {
            minioClient.makeBucket(MakeBucketArgs.builder().bucket(bucket).build());
        }
    }
}

package com.providerfollowup.invoice;

import io.minio.BucketExistsArgs;
import io.minio.CopyObjectArgs;
import io.minio.CopySource;
import io.minio.MakeBucketArgs;
import io.minio.MinioClient;
import io.minio.PutObjectArgs;
import io.minio.RemoveObjectArgs;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import org.eclipse.microprofile.config.inject.ConfigProperty;

import java.io.InputStream;
import java.time.LocalDate;
import java.time.YearMonth;
import java.time.format.DateTimeFormatter;
import java.util.UUID;

@ApplicationScoped
public class MinioStorageService {
    @Inject MinioClient minioClient;
    @ConfigProperty(name = "minio.bucket") String bucket;

    public String upload(LocalDate invoiceDate, String originalFilename, String contentType, InputStream inputStream, long size) throws Exception {
        ensureBucket();
        String objectKey = buildObjectKey(invoiceDate, originalFilename, null);
        minioClient.putObject(PutObjectArgs.builder()
                .bucket(bucket)
                .object(objectKey)
                .stream(inputStream, size, -1)
                .contentType(contentType == null ? "application/octet-stream" : contentType)
                .build());
        return objectKey;
    }

    public String moveToInvoiceMonth(String currentObjectKey, LocalDate invoiceDate, String originalFilename) throws Exception {
        if (currentObjectKey == null || invoiceDate == null) {
            return currentObjectKey;
        }
        ensureBucket();
        String targetPrefix = prefixFor(invoiceDate);
        if (currentObjectKey.startsWith(targetPrefix)) {
            return currentObjectKey;
        }
        String newObjectKey = buildObjectKey(invoiceDate, originalFilename, objectSuffix(currentObjectKey, originalFilename));
        minioClient.copyObject(CopyObjectArgs.builder()
                .bucket(bucket)
                .object(newObjectKey)
                .source(CopySource.builder().bucket(bucket).object(currentObjectKey).build())
                .build());
        minioClient.removeObject(RemoveObjectArgs.builder().bucket(bucket).object(currentObjectKey).build());
        return newObjectKey;
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

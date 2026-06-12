package com.providerfollowup.invoice;

import io.minio.BucketExistsArgs;
import io.minio.MakeBucketArgs;
import io.minio.MinioClient;
import io.minio.PutObjectArgs;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import org.eclipse.microprofile.config.inject.ConfigProperty;

import java.io.InputStream;

@ApplicationScoped
public class MinioStorageService {
    @Inject MinioClient minioClient;
    @ConfigProperty(name = "minio.bucket") String bucket;

    public String upload(Long invoiceId, String originalFilename, String contentType, InputStream inputStream, long size) throws Exception {
        ensureBucket();
        String safeName = originalFilename == null ? "invoice-file" : originalFilename.replaceAll("[^a-zA-Z0-9._-]", "_");
        String objectKey = "invoices/" + invoiceId + "/" + System.currentTimeMillis() + "-" + safeName;
        minioClient.putObject(PutObjectArgs.builder()
                .bucket(bucket)
                .object(objectKey)
                .stream(inputStream, size, -1)
                .contentType(contentType == null ? "application/octet-stream" : contentType)
                .build());
        return objectKey;
    }

    private void ensureBucket() throws Exception {
        boolean exists = minioClient.bucketExists(BucketExistsArgs.builder().bucket(bucket).build());
        if (!exists) {
            minioClient.makeBucket(MakeBucketArgs.builder().bucket(bucket).build());
        }
    }
}

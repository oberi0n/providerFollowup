package com.providerfollowup.config;

import io.minio.MinioClient;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.enterprise.inject.Produces;
import org.eclipse.microprofile.config.inject.ConfigProperty;

@ApplicationScoped
public class MinioConfig {
    @ConfigProperty(name = "minio.endpoint") String endpoint;
    @ConfigProperty(name = "minio.access-key") String accessKey;
    @ConfigProperty(name = "minio.secret-key") String secretKey;

    @Produces
    @ApplicationScoped
    MinioClient minioClient() {
        return MinioClient.builder().endpoint(endpoint).credentials(accessKey, secretKey).build();
    }
}

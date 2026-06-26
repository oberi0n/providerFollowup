package com.providerfollowup.invoice;

import com.providerfollowup.invoice.InvoiceDtos.OcrRequest;
import com.providerfollowup.invoice.InvoiceDtos.OcrResult;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.ws.rs.ProcessingException;
import org.eclipse.microprofile.config.inject.ConfigProperty;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import com.fasterxml.jackson.databind.ObjectMapper;

@ApplicationScoped
public class OcrServiceClient {
    @ConfigProperty(name = "ocr.service.url") String ocrServiceUrl;
    private final HttpClient httpClient = HttpClient.newHttpClient();
    private final ObjectMapper objectMapper = new ObjectMapper().findAndRegisterModules();

    public OcrResult extract(String objectKey, String filename, String contentType) {
        try {
            String body = objectMapper.writeValueAsString(new OcrRequest(objectKey, filename, contentType));
            HttpRequest request = HttpRequest.newBuilder(URI.create(ocrServiceUrl + "/ocr/extract"))
                    .version(HttpClient.Version.HTTP_1_1)
                    .header("Content-Type", "application/json")
                    .header("Accept", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(body, StandardCharsets.UTF_8))
                    .build();
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() >= 400) {
                throw new ProcessingException("OCR service failed: " + response.body());
            }
            return objectMapper.readValue(response.body(), OcrResult.class);
        } catch (Exception e) {
            throw new ProcessingException("Cannot call OCR service", e);
        }
    }
}

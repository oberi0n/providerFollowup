package com.providerfollowup.invoice;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.providerfollowup.invoice.InvoiceDtos.*;
import io.quarkus.panache.common.Sort;
import jakarta.inject.Inject;
import jakarta.transaction.Transactional;
import jakarta.ws.rs.*;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;
import org.jboss.resteasy.reactive.MultipartForm;
import org.jboss.resteasy.reactive.RestForm;
import org.jboss.resteasy.reactive.multipart.FileUpload;

import java.nio.file.Files;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;

@Path("/api/invoices")
@Produces(MediaType.APPLICATION_JSON)
public class InvoiceResource {
    @Inject MinioStorageService storageService;
    @Inject OcrServiceClient ocrServiceClient;
    ObjectMapper objectMapper = new ObjectMapper().findAndRegisterModules();

    public static class UploadForm {
        @RestForm("file") public FileUpload file;
    }

    @GET
    public List<InvoiceResponse> list() {
        return Invoice.<Invoice>listAll(Sort.descending("createdAt")).stream().map(InvoiceResponse::from).toList();
    }

    @POST
    @Transactional
    @Consumes(MediaType.APPLICATION_JSON)
    public Response create(InvoiceRequest request) {
        Invoice invoice = new Invoice();
        applyValidatedFields(invoice, request);
        invoice.persist();
        return Response.status(Response.Status.CREATED).entity(InvoiceResponse.from(invoice)).build();
    }

    @PUT
    @Path("/{id}")
    @Transactional
    @Consumes(MediaType.APPLICATION_JSON)
    public InvoiceResponse update(@PathParam("id") Long id, InvoiceRequest request) throws Exception {
        Invoice invoice = findInvoice(id);
        applyValidatedFields(invoice, request);
        relocateStoredFile(invoice);
        return InvoiceResponse.from(invoice);
    }

    @POST
    @Path("/{id}/upload")
    @Transactional
    @Consumes(MediaType.MULTIPART_FORM_DATA)
    public InvoiceResponse upload(@PathParam("id") Long id, @MultipartForm UploadForm form) throws Exception {
        Invoice invoice = findInvoice(id);
        if (form == null || form.file == null) {
            throw new BadRequestException("Champ fichier 'file' manquant");
        }
        invoice.originalFilename = form.file.fileName();
        String objectKey = storageService.upload(invoice, form.file.fileName(), form.file.contentType(), Files.newInputStream(form.file.uploadedFile()), form.file.size());
        invoice.fileObjectKey = objectKey;
        return InvoiceResponse.from(invoice);
    }

    @POST
    @Path("/{id}/ocr")
    @Transactional
    public OcrResultResponse runOcr(@PathParam("id") Long id) throws Exception {
        Invoice invoice = findInvoice(id);
        if (invoice.fileObjectKey == null) {
            throw new BadRequestException("Aucun fichier n'est associé à cette facture");
        }
        OcrResult result = ocrServiceClient.extract(invoice.fileObjectKey, invoice.originalFilename, null);
        invoice.ocrRawText = result.rawText();
        invoice.ocrSuggestionsJson = objectMapper.writeValueAsString(result.suggestions());
        invoice.ocrProcessedAt = OffsetDateTime.now();
        LocalDate suggestedDate = parseSuggestedInvoiceDate(result);
        if (invoice.invoiceDate == null && suggestedDate != null) {
            invoice.invoiceDate = suggestedDate;
        }
        invoice.fileObjectKey = storageService.syncObjectWithInvoice(invoice.fileObjectKey, invoice);
        // OCR date is only applied when no invoice date existed yet; already validated dates are never overwritten.
        return toOcrResponse(invoice, result.confidence());
    }

    @GET
    @Path("/{id}/ocr-result")
    public OcrResultResponse getOcrResult(@PathParam("id") Long id) throws Exception {
        return toOcrResponse(findInvoice(id), "LOW");
    }

    private Invoice findInvoice(Long id) {
        Invoice invoice = Invoice.findById(id);
        if (invoice == null) throw new NotFoundException("Facture introuvable: " + id);
        return invoice;
    }

    private void relocateStoredFile(Invoice invoice) throws Exception {
        invoice.fileObjectKey = storageService.syncObjectWithInvoice(invoice.fileObjectKey, invoice);
    }

    private LocalDate parseSuggestedInvoiceDate(OcrResult result) {
        if (result == null || result.suggestions() == null || result.suggestions().invoiceDate() == null) {
            return null;
        }
        try {
            return LocalDate.parse(result.suggestions().invoiceDate());
        } catch (Exception ignored) {
            return null;
        }
    }

    private void applyValidatedFields(Invoice invoice, InvoiceRequest request) {
        if (request == null) return;
        invoice.supplierId = request.supplierId();
        invoice.supplierName = request.supplierName();
        invoice.invoiceNumber = request.invoiceNumber();
        invoice.invoiceDate = request.invoiceDate();
        invoice.amountHt = request.amountHt();
        invoice.vatAmount = request.vatAmount();
        invoice.amountTtc = request.amountTtc();
        invoice.currency = request.currency() == null || request.currency().isBlank() ? "EUR" : request.currency();
        invoice.category = request.category();
        invoice.status = request.status() == null ? InvoiceStatus.RECEIVED : request.status();
        invoice.comment = request.comment();
    }

    private OcrResultResponse toOcrResponse(Invoice invoice, String confidence) throws Exception {
        Map<String, Object> suggestions = invoice.ocrSuggestionsJson == null ? Map.of() : objectMapper.readValue(invoice.ocrSuggestionsJson, new TypeReference<>() {});
        return new OcrResultResponse(invoice.ocrRawText, suggestions, confidence, invoice.ocrProcessedAt);
    }
}

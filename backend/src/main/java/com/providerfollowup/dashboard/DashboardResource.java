package com.providerfollowup.dashboard;

import com.providerfollowup.invoice.Invoice;
import com.providerfollowup.invoice.InvoiceStatus;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;

import java.math.BigDecimal;
import java.time.format.DateTimeFormatter;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Path("/api/dashboard")
@Produces(MediaType.APPLICATION_JSON)
public class DashboardResource {
    public record DashboardSummary(BigDecimal annualBudget, BigDecimal consumed, BigDecimal committedUnpaid,
                                   BigDecimal available, Map<String, Long> invoicesByStatus,
                                   Map<String, BigDecimal> expensesByMonth, Map<String, BigDecimal> expensesBySupplier,
                                   Map<String, BigDecimal> expensesByCategory) {}

    @GET
    public DashboardSummary summary() {
        List<Invoice> invoices = Invoice.listAll();
        BigDecimal annualBudget = new BigDecimal("120000.00");
        BigDecimal consumed = total(invoices.stream().filter(i -> i.status == InvoiceStatus.PAID).toList());
        BigDecimal committedUnpaid = total(invoices.stream().filter(i -> i.status != InvoiceStatus.PAID && i.status != InvoiceStatus.REJECTED).toList());
        BigDecimal available = annualBudget.subtract(consumed).subtract(committedUnpaid);
        return new DashboardSummary(
                annualBudget,
                consumed,
                committedUnpaid,
                available,
                invoices.stream().collect(Collectors.groupingBy(i -> i.status.name(), LinkedHashMap::new, Collectors.counting())),
                groupSum(invoices, i -> i.invoiceDate == null ? "Sans date" : i.invoiceDate.format(DateTimeFormatter.ofPattern("yyyy-MM"))),
                groupSum(invoices, i -> blank(i.supplierName, "Fournisseur inconnu")),
                groupSum(invoices, i -> blank(i.category, "Non catégorisé"))
        );
    }

    private BigDecimal total(List<Invoice> invoices) {
        return invoices.stream().map(i -> i.amountTtc == null ? BigDecimal.ZERO : i.amountTtc).reduce(BigDecimal.ZERO, BigDecimal::add);
    }

    private Map<String, BigDecimal> groupSum(List<Invoice> invoices, java.util.function.Function<Invoice, String> classifier) {
        return invoices.stream().collect(Collectors.groupingBy(classifier, LinkedHashMap::new,
                Collectors.mapping(i -> i.amountTtc == null ? BigDecimal.ZERO : i.amountTtc,
                        Collectors.reducing(BigDecimal.ZERO, BigDecimal::add))));
    }

    private String blank(String value, String fallback) {
        return value == null || value.isBlank() ? fallback : value;
    }
}

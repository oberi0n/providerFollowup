package com.providerfollowup.dashboard;

import com.providerfollowup.invoice.Invoice;
import jakarta.ws.rs.DefaultValue;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.MediaType;

import java.math.BigDecimal;
import java.time.Year;
import java.time.format.DateTimeFormatter;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Path("/api/dashboard")
@Produces(MediaType.APPLICATION_JSON)
public class DashboardResource {
    public record DashboardSummary(Integer fiscalYear, BigDecimal annualBudget, BigDecimal consumed,
                                   BigDecimal committedUnpaid, BigDecimal available,
                                   Map<String, BigDecimal> expensesByMonth, Map<String, BigDecimal> expensesBySupplier,
                                   Map<String, BigDecimal> expensesByCategory) {}

    @GET
    public DashboardSummary summary(@QueryParam("year") Integer year,
                                    @QueryParam("budget") @DefaultValue("120000.00") BigDecimal annualBudget) {
        int fiscalYear = year == null ? Year.now().getValue() : year;
        List<Invoice> invoices = Invoice.<Invoice>listAll().stream()
                .filter(invoice -> invoice.invoiceDate != null && invoice.invoiceDate.getYear() == fiscalYear)
                .toList();
        BigDecimal consumed = total(invoices);
        BigDecimal committedUnpaid = BigDecimal.ZERO;
        BigDecimal available = annualBudget.subtract(consumed);
        return new DashboardSummary(
                fiscalYear,
                annualBudget,
                consumed,
                committedUnpaid,
                available,
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

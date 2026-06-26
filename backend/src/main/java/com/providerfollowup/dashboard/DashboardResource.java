package com.providerfollowup.dashboard;

import com.providerfollowup.invoice.Invoice;
import com.providerfollowup.invoice.BudgetType;
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
    public record DashboardSummary(Integer fiscalYear, BigDecimal annualBudget, BigDecimal opexBudget,
                                   BigDecimal capexBudget, BigDecimal consumed, BigDecimal opexConsumed,
                                   BigDecimal capexConsumed, BigDecimal committedUnpaid, BigDecimal available,
                                   BigDecimal opexAvailable, BigDecimal capexAvailable,
                                   Map<String, BigDecimal> expensesByMonth, Map<String, BigDecimal> expensesBySupplier,
                                   Map<String, BigDecimal> expensesByCategory, Map<String, BigDecimal> expensesByBudgetType) {}

    @GET
    public DashboardSummary summary(@QueryParam("year") Integer year,
                                    @QueryParam("opexBudget") @DefaultValue("80000.00") BigDecimal opexBudget,
                                    @QueryParam("capexBudget") @DefaultValue("40000.00") BigDecimal capexBudget) {
        int fiscalYear = year == null ? Year.now().getValue() : year;
        List<Invoice> invoices = Invoice.<Invoice>listAll().stream()
                .filter(invoice -> invoice.invoiceDate != null && invoice.invoiceDate.getYear() == fiscalYear)
                .toList();
        BigDecimal consumed = total(invoices);
        BigDecimal opexConsumed = totalByBudgetType(invoices, BudgetType.OPEX);
        BigDecimal capexConsumed = totalByBudgetType(invoices, BudgetType.CAPEX);
        BigDecimal annualBudget = opexBudget.add(capexBudget);
        BigDecimal committedUnpaid = BigDecimal.ZERO;
        BigDecimal available = annualBudget.subtract(consumed);
        return new DashboardSummary(
                fiscalYear,
                annualBudget,
                opexBudget,
                capexBudget,
                consumed,
                opexConsumed,
                capexConsumed,
                committedUnpaid,
                available,
                opexBudget.subtract(opexConsumed),
                capexBudget.subtract(capexConsumed),
                groupSum(invoices, i -> i.invoiceDate == null ? "Sans date" : i.invoiceDate.format(DateTimeFormatter.ofPattern("yyyy-MM"))),
                groupSum(invoices, i -> blank(i.supplierName, "Fournisseur inconnu")),
                groupSum(invoices, i -> blank(i.category, "Non catégorisé")),
                groupSum(invoices, i -> i.budgetType == null ? "Non assigné" : i.budgetType.name())
        );
    }

    private BigDecimal total(List<Invoice> invoices) {
        return invoices.stream().map(i -> i.amountTtc == null ? BigDecimal.ZERO : i.amountTtc).reduce(BigDecimal.ZERO, BigDecimal::add);
    }

    private BigDecimal totalByBudgetType(List<Invoice> invoices, BudgetType budgetType) {
        return total(invoices.stream().filter(invoice -> invoice.budgetType == budgetType).toList());
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

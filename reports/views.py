from urllib.parse import urlencode

from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.urls import reverse

from accounts.decorators import staff_required

from .builders import REPORTS
from .exporters import to_csv, to_pdf
from .forms import ReportFilterForm


def _params(request, staff):
    """The filter values: from the query string, or sensible defaults on the first visit."""
    given = {k: v for k, v in request.GET.items() if k != "format" and v != ""}
    if given:
        return given
    return {"period": "day", "date": staff.organization.local_today().isoformat()}


def _index(request, form, params):
    cards = []
    for kind, (title, blurb, _) in REPORTS.items():
        base = reverse("reports:report", args=[kind])

        def link(fmt, base=base):
            return f"{base}?{urlencode({**params, 'format': fmt})}"

        cards.append({"title": title, "blurb": blurb, "html": link("html"), "csv": link("csv"), "pdf": link("pdf")})
    return render(request, "reports/index.html", {"form": form, "cards": cards, "range": form.range})


@staff_required
def index(request):
    params = _params(request, request.staff)
    form = ReportFilterForm(params, staff=request.staff)
    form.is_valid()
    return _index(request, form, params)


@staff_required
def report(request, kind):
    if kind not in REPORTS:
        raise Http404("Unknown report")
    staff = request.staff
    params = _params(request, staff)
    form = ReportFilterForm(params, staff=staff)
    if not form.is_valid():
        return _index(request, form, params)

    start, end = form.range
    table = REPORTS[kind][2](staff, start, end, form.cleaned_data["hostel"])
    output = request.GET.get("format", "html")
    stem = f"{kind}_{start.isoformat()}_{end.isoformat()}"

    if output == "csv":
        response = HttpResponse(to_csv(table), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{stem}.csv"'
        return response
    if output == "pdf":
        stamp = staff.organization.local_now().strftime("%d %b %Y %H:%M")
        heading = f"Generated {stamp} by {request.user.get_username()}"
        try:
            content = to_pdf(table, heading=heading, footer_note=staff.organization.name)
        except ImportError:
            return HttpResponse("PDF export needs the reportlab package: pip install reportlab", status=501,
                                content_type="text/plain")
        response = HttpResponse(content, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{stem}.pdf"'
        return response

    base = reverse("reports:report", args=[kind])
    links = {fmt: f"{base}?{urlencode({**params, 'format': fmt})}" for fmt in ("csv", "pdf")}
    return render(request, "reports/report.html", {"table": table, "links": links})

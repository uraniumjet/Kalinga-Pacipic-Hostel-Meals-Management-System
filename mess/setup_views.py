"""Admin-only setup screens for meals, counters and special periods (Ramadan and the like)."""
from django.contrib import messages
from django.db.models import Count, ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.decorators import admin_required

from .models import Counter, MealType, MealWindow, SpecialPeriod, WindowOverride
from .setup_forms import CounterForm, MealForm, OverrideForm, PeriodForm, WindowForm, effective_window


def _org(request):
    return request.staff.organization


@admin_required
def meals(request):
    org = _org(request)
    form = MealForm(request.POST or None, organization=org)
    if request.method == "POST" and form.is_valid():
        meal = form.save()
        messages.success(request, f"{meal.name} added.")
        return redirect("setup:meals")
    rows = []
    for meal in MealType.objects.filter(organization=org).prefetch_related("windows"):
        normal = next((w for w in meal.windows.all() if w.special_period_id is None), None)
        rows.append({"meal": meal, "normal": normal})
    return render(request, "mess/setup/meals.html", {"rows": rows, "form": form})


@admin_required
def meal_edit(request, pk):
    org = _org(request)
    meal = get_object_or_404(MealType, pk=pk, organization=org)
    form = MealForm(request.POST or None, organization=org, meal=meal)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Meal saved.")
        return redirect("setup:meals")
    return render(request, "organizations/setup/simple_form.html",
                  {"form": form, "title": f"Edit {meal.name}", "back_url": reverse("setup:meals")})


@admin_required
@require_POST
def meal_delete(request, pk):
    meal = get_object_or_404(MealType, pk=pk, organization=_org(request))
    try:
        meal.delete()
        messages.success(request, "Meal deleted.")
    except ProtectedError:
        messages.error(request, f"{meal.name} has served-meal records, so it cannot be deleted.")
    return redirect("setup:meals")


@admin_required
def counters(request):
    org = _org(request)
    form = CounterForm(request.POST or None, organization=org)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Counter added.")
        return redirect("setup:counters")
    rows = Counter.objects.filter(organization=org).prefetch_related("categories").annotate(served=Count("collections"))
    return render(request, "mess/setup/counters.html", {"rows": rows, "form": form})


@admin_required
def counter_edit(request, pk):
    org = _org(request)
    counter = get_object_or_404(Counter, pk=pk, organization=org)
    form = CounterForm(request.POST or None, instance=counter, organization=org)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Counter saved.")
        return redirect("setup:counters")
    return render(request, "organizations/setup/simple_form.html",
                  {"form": form, "title": f"Edit {counter.name}", "back_url": reverse("setup:counters")})


@admin_required
@require_POST
def counter_delete(request, pk):
    counter = get_object_or_404(Counter, pk=pk, organization=_org(request))
    try:
        counter.delete()
        messages.success(request, "Counter deleted.")
    except ProtectedError:
        messages.error(request, f"{counter.name} has served-meal records, so it cannot be deleted.")
    return redirect("setup:counters")


@admin_required
def periods(request):
    org = _org(request)
    form = PeriodForm(request.POST or None, organization=org)
    if request.method == "POST" and form.is_valid():
        period = form.save()
        messages.success(request, f"{period.name} added. Now set the meal times for it.")
        return redirect("setup:period", period.pk)
    rows = SpecialPeriod.objects.filter(organization=org).prefetch_related("categories", "skipped_meals").order_by("-start_date")
    return render(request, "mess/setup/periods.html", {"rows": rows, "form": form})


@admin_required
def period_detail(request, pk):
    org = _org(request)
    period = get_object_or_404(SpecialPeriod, pk=pk, organization=org)
    details = PeriodForm(instance=period, organization=org, prefix="period")
    window_form = WindowForm(organization=org, prefix="window")
    override_form = OverrideForm(organization=org, period=period, prefix="day")
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "details":
            details = PeriodForm(request.POST, instance=period, organization=org, prefix="period")
            if details.is_valid():
                details.save()
                messages.success(request, "Period saved.")
                return redirect("setup:period", pk)
        elif action == "window":
            window_form = WindowForm(request.POST, organization=org, prefix="window")
            if window_form.is_valid():
                data = window_form.cleaned_data
                MealWindow.objects.update_or_create(
                    meal_type=data["meal"], special_period=period,
                    defaults={"start_time": data["start_time"], "end_time": data["end_time"]},
                )
                messages.success(request, f"{data['meal'].name} time set for {period.name}.")
                return redirect("setup:period", pk)
        elif action == "override":
            override_form = OverrideForm(request.POST, organization=org, period=period, prefix="day")
            if override_form.is_valid():
                override_form.save()
                messages.success(request, "Time for that day saved.")
                return redirect("setup:period", pk)

    skipped = set(period.skipped_meals.values_list("pk", flat=True))
    rows = []
    for meal in MealType.objects.filter(organization=org):
        own = meal.windows.filter(special_period=period).first()
        normal = meal.windows.filter(special_period__isnull=True).first()
        rows.append({"meal": meal, "skipped": meal.pk in skipped, "own": own, "normal": normal})
    windows = []
    for row in rows:
        if not row["skipped"]:
            window = effective_window(row["meal"], period)
            if window is not None:
                windows.append(window)
    day_changes = WindowOverride.objects.filter(
        window__in=windows, date__gte=period.start_date, date__lte=period.end_date
    ).select_related("window__meal_type").order_by("date")
    return render(request, "mess/setup/period_detail.html", {
        "period": period, "rows": rows, "day_changes": day_changes,
        "details": details, "window_form": window_form, "override_form": override_form,
    })


@admin_required
@require_POST
def period_window_clear(request, pk, meal_pk):
    period = get_object_or_404(SpecialPeriod, pk=pk, organization=_org(request))
    MealWindow.objects.filter(special_period=period, meal_type__pk=meal_pk, meal_type__organization=_org(request)).delete()
    messages.success(request, "That meal goes back to its normal time during the period.")
    return redirect("setup:period", pk)


@admin_required
@require_POST
def override_delete(request, pk, override_pk):
    period = get_object_or_404(SpecialPeriod, pk=pk, organization=_org(request))
    override = get_object_or_404(WindowOverride, pk=override_pk, window__meal_type__organization=_org(request))
    override.delete()
    messages.success(request, "That day goes back to the usual time.")
    return redirect("setup:period", period.pk)


@admin_required
@require_POST
def period_delete(request, pk):
    period = get_object_or_404(SpecialPeriod, pk=pk, organization=_org(request))
    period.delete()
    messages.success(request, "Period deleted.")
    return redirect("setup:periods")

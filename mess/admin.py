from django.contrib import admin

from .models import Counter, MealCollection, MealType, MealWindow, SpecialPeriod, WindowOverride


class WindowInline(admin.TabularInline):
    model = MealWindow
    extra = 0


@admin.register(MealType)
class MealTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "sort_order")
    inlines = [WindowInline]


@admin.register(Counter)
class CounterAdmin(admin.ModelAdmin):
    list_display = ("name", "organization")
    filter_horizontal = ("categories",)


@admin.register(SpecialPeriod)
class SpecialPeriodAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "start_date", "end_date", "religion")
    filter_horizontal = ("categories", "skipped_meals")
    inlines = [WindowInline]


@admin.register(WindowOverride)
class WindowOverrideAdmin(admin.ModelAdmin):
    list_display = ("window", "date", "start_time", "end_time")
    list_filter = ("date",)


@admin.register(MealCollection)
class MealCollectionAdmin(admin.ModelAdmin):
    list_display = ("student", "meal_type", "date", "counter", "collected_by", "created_at")
    list_filter = ("date", "meal_type", "counter")
    search_fields = ("student__name", "student__roll_number")

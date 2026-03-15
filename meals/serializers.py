from rest_framework import serializers
from .models import MealRecord

class MealRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = MealRecord
        fields = "__all__"
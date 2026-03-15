from django.db import models
from django.db import models
from student.models import Student

class MealLog(models.Model):

    MEAL_TYPES = [
        ('breakfast', 'Breakfast'),
        ('lunch', 'Lunch'),
        ('dinner', 'Dinner'),
    ]

    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    meal_type = models.CharField(max_length=10, choices=MEAL_TYPES)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.student.name} - {self.meal_type}"

class MealRecord(models.Model):

    MEAL_CHOICES = [
        ('breakfast', 'Breakfast'),
        ('lunch', 'Lunch'),
        ('dinner', 'Dinner')
    ]

    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    meal_type = models.CharField(max_length=10, choices=MEAL_CHOICES)
    date = models.DateField(auto_now_add=True)
    time = models.TimeField(auto_now_add=True)

    class Meta:
        unique_together = ['student', 'meal_type', 'date']

    def __str__(self):
        return f"{self.student} - {self.meal_type} - {self.date}"

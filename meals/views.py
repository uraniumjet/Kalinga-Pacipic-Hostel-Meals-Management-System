from django.shortcuts import render
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .utility import get_current_meal
from student.models import Student
from .models import MealRecord, MealLog
from django.http import JsonResponse
from datetime import datetime, date

# 1. Admin Dashboard (Fixed for MealLog model)
def admin_dashboard(request):
    students = Student.objects.all().order_by("-id")
    
    # FIXED: Using 'timestamp' because your MealLog model explicitly requires it
    logs = MealLog.objects.all().order_by("-timestamp")[:15]

        # In admin_dashboard(request)
    today = date.today()
    context = {
        "students": students,
        "logs": logs,
        "total_students": students.count(),
        "b_count": MealRecord.objects.filter(date=today, meal_type="breakfast").count(),
        "l_count": MealRecord.objects.filter(date=today, meal_type="lunch").count(),
        "d_count": MealRecord.objects.filter(date=today, meal_type="dinner").count(),
    }
    
    context = {
        "students": students,
        "logs": logs,
        "total_students": students.count(),
        "international_count": students.filter(category='international').count(),
        "local_count": students.filter(category='local').count(),
    }
    return render(request, "admin_dashboard.html", context)

# 2. Meal Stats (Fixed for MealRecord model)
def meal_stats(request):
    today = date.today()
    # Assuming MealRecord uses 'date'. If it uses 'timestamp', change 'date' to 'timestamp__date'
    breakfast = MealRecord.objects.filter(meal_type="breakfast", date=today).count()
    lunch = MealRecord.objects.filter(meal_type="lunch", date=today).count()
    dinner = MealRecord.objects.filter(meal_type="dinner", date=today).count()

    return JsonResponse({
        "breakfast": breakfast,
        "lunch": lunch,
        "dinner": dinner
    })

# 3. Scanner Page
def scanner_page(request):
    students = Student.objects.all().order_by('name')
    return render(request, "scanner.html", {"students": students})

# 4. Collection API (The Bridge)
@api_view(['POST'])
def collect_meal(request):
    student_id = request.data.get("student_id")
    
    try:
        student = Student.objects.get(student_id=student_id)
    except Student.DoesNotExist:
        return Response({"error": "Student not found"}, status=404)

    meal_type = get_current_meal(student=student, ramadan_mode=False).lower() 

    # 1. Create Record (For the Chart)
    MealRecord.objects.create(
        student=student, 
        meal_type=meal_type,
        date=date.today(),
        time=datetime.now().time()
    )
    
    # 2. Create Log (For the Activity Feed)
    MealLog.objects.create(
        student=student, 
        student_id=student.student_id,
        meal_type=meal_type,
        timestamp=datetime.now()
    )

    if not meal_type:
        return Response({"error": "No active meal session"}, status=400)

    today = date.today()
    
    # Check for double collection in MealRecord (Uses 'date')
    already_collected = MealRecord.objects.filter(
        student=student,
        meal_type=meal_type,
        date=today
    ).exists()

    if already_collected:
        return Response({"error": f"{meal_type.capitalize()} already collected"}, status=400)

    # Save to Record (Uses date/time)
    MealRecord.objects.create(
        student=student, 
        meal_type=meal_type,
        date=today,
        time=datetime.now().time()
    )
    
    # Save to Log (Uses timestamp - as confirmed by your error message)
    MealLog.objects.create(
        student=student, 
        student_id=student.student_id,
        meal_type=meal_type,
        timestamp=datetime.now() # MealLog needs this!
    )

    return Response({
        "success": f"{meal_type.capitalize()} recorded",
        "student_name": student.name,
        "category": student.category
    })
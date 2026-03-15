from django.shortcuts import render
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import Student
from .serializers import StudentSerializer
from .forms import StudentForm
from django.shortcuts import get_object_or_404


from django.shortcuts import render, redirect
from .forms import StudentForm
from .models import Student

def dashboard(request):

    students = Student.objects.all()

    if request.method == "POST":
        form = StudentForm(request.POST)

        if form.is_valid():
            form.save()
            return redirect("dashboard")

    else:
        form = StudentForm()

    return render(request, "dashboard.html", {
        "students": students,
        "form": form
    })


def student_register(request):

    if request.method == "POST":
        form = StudentForm(request.POST)

        if form.is_valid():
            form.save()
            return redirect("student_register")

    else:
        form = StudentForm()

    students = Student.objects.all()

    return render(request, "students.html", {
        "form": form,
        "students": students
    })


def delete_student(request, id):

    student = get_object_or_404(Student, id=id)
    student.delete()

    return redirect("dashboard")

@api_view(['GET'])
def list_students(request):
    students = Student.objects.all()
    serializer = StudentSerializer(students, many=True)
    return Response(serializer.data)


@api_view(['POST'])
def create_student(request):
    serializer = StudentSerializer(data=request.data)

    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)

    return Response(serializer.errors)

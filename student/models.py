from django.db import models
from django.core.files import File
import qrcode
from io import BytesIO

class Student(models.Model):
    CATEGORY_CHOICES = [
        ('international', 'International'),
        ('local', 'Non International')
    ]

    RELIGION_CHOICES = [
        ('muslim', 'Muslim'),
        ('christian', 'Christian'),
        ('other', 'Other')
    ]

    # Fields
    student_id = models.CharField(max_length=20, unique=True, blank=True)
    name = models.CharField(max_length=200)
    room_number = models.CharField(max_length=20)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    religion = models.CharField(max_length=20, choices=RELIGION_CHOICES)
    qr_code = models.ImageField(upload_to='qr_codes/', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        # 1. Logic to generate the Custom Student ID (e.g., HST-0001)
        if not self.student_id:
            last_student = Student.objects.all().order_by('id').last()
            
            if last_student and last_student.student_id:
                try:
                    # Split 'HST-0001' -> ['HST', '0001']
                    parts = last_student.student_id.split('-')
                    if len(parts) >= 2:
                        last_number = int(parts[1])
                        new_number = last_number + 1
                    else:
                        # Fallback if ID exists but format is wrong
                        new_number = Student.objects.count() + 1
                except (ValueError, IndexError):
                    # Fallback if conversion to integer fails
                    new_number = Student.objects.count() + 1
            else:
                # First student ever
                new_number = 1
            
            self.student_id = f"HST-{new_number:04d}"

        # 2. Logic to generate QR Code based on the student_id
        # We only generate it if it hasn't been created yet
        if not self.qr_code:
            qr_img = qrcode.make(self.student_id)
            buffer = BytesIO()
            qr_img.save(buffer, format='PNG')
            
            # Use the student_id as the filename
            file_name = f'qr_{self.student_id}.png'
            self.qr_code.save(file_name, File(buffer), save=False)

        # 3. Call the actual save method
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.student_id})"
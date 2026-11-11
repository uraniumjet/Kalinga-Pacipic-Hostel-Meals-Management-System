import csv
import io
import re
import shutil
import time
import uuid
from pathlib import Path

from django import forms
from django.conf import settings
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from accounts.access import hostels_for
from accounts.decorators import staff_required

from .import_files import COLUMNS, MAX_FILE_BYTES, ImportFileError, index_photos, read_table
from .importer import plan_import, run_import

TOKEN = re.compile(r"^[0-9a-f]{32}$")
MAX_ZIP_UPLOAD = 300 * 1024 * 1024
PREVIEW_OK_ROWS = 15


class ImportUploadForm(forms.Form):
    file = forms.FileField(label="Student list (.csv or .xlsx)")
    photos = forms.FileField(label="Photos (optional .zip, one picture per student named by roll number)", required=False)

    def clean_file(self):
        upload = self.cleaned_data["file"]
        if not upload.name.lower().endswith((".csv", ".xlsx")):
            raise forms.ValidationError("Use a .csv or .xlsx file.")
        if upload.size > MAX_FILE_BYTES:
            raise forms.ValidationError("The file is larger than 5 MB.")
        return upload

    def clean_photos(self):
        upload = self.cleaned_data.get("photos")
        if upload:
            if not upload.name.lower().endswith(".zip"):
                raise forms.ValidationError("The photos must be one .zip file.")
            if upload.size > MAX_ZIP_UPLOAD:
                raise forms.ValidationError("The photo zip is larger than 300 MB.")
        return upload


# The uploaded files wait in a private folder (not the public media folder) between the preview
# and the confirmation. The folder name is a random token that only this login session knows.
def _root():
    root = Path(settings.IMPORT_STAGING_DIR)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _purge_old():
    for folder in _root().iterdir():
        if folder.is_dir() and time.time() - folder.stat().st_mtime > 24 * 3600:
            shutil.rmtree(folder, ignore_errors=True)


def _staging(request):
    token = request.session.get("import_token", "")
    if not TOKEN.match(token):
        return None
    folder = _root() / token
    return folder if folder.is_dir() else None


def _discard(request):
    folder = _staging(request)
    if folder:
        shutil.rmtree(folder, ignore_errors=True)
    request.session.pop("import_token", None)


def _save(upload, destination):
    with open(destination, "wb") as handle:
        for chunk in upload.chunks():
            handle.write(chunk)


def _plan(staff, folder):
    data_file = next(folder.glob("data.*"))
    parsed = read_table(data_file)
    zip_path = folder / "photos.zip"
    index = index_photos(zip_path) if zip_path.exists() else None
    return plan_import(staff, parsed, index), (zip_path if index is not None else None)


def _allowed(staff):
    org = staff.organization
    return {
        "categories": [c.name for c in org.categories.all()],
        "diets": [d.name for d in org.diet_types.all()],
        "hostels": [h.name for h in hostels_for(staff)],
        "columns": COLUMNS,
    }


@staff_required
def import_students(request):
    staff = request.staff
    form = ImportUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        _discard(request)
        _purge_old()
        folder = _root() / uuid.uuid4().hex
        folder.mkdir(parents=True)
        upload = form.cleaned_data["file"]
        _save(upload, folder / f"data{'.xlsx' if upload.name.lower().endswith('.xlsx') else '.csv'}")
        if form.cleaned_data.get("photos"):
            _save(form.cleaned_data["photos"], folder / "photos.zip")
        try:
            plan, _ = _plan(staff, folder)
        except ImportFileError as error:
            shutil.rmtree(folder, ignore_errors=True)
            form.add_error(None, str(error))
        else:
            request.session["import_token"] = folder.name
            context = {
                "plan": plan, "filename": upload.name, "ok_sample": plan.ok_rows[:PREVIEW_OK_ROWS],
                "bad_rows": plan.bad_rows[:200], "has_photos": (folder / "photos.zip").exists(),
            }
            return render(request, "residents/import_preview.html", context)
    return render(request, "residents/import_upload.html", {"form": form, **_allowed(staff)})


@staff_required
@require_POST
def import_confirm(request):
    folder = _staging(request)
    if folder is None:
        messages.error(request, "There is no import waiting. Upload the file again.")
        return redirect("residents:import")
    try:
        plan, zip_path = _plan(request.staff, folder)
    except ImportFileError as error:
        _discard(request)
        messages.error(request, str(error))
        return redirect("residents:import")
    summary = run_import(request.staff, plan, zip_path)
    _discard(request)
    return render(request, "residents/import_result.html", {"summary": summary, "plan": plan})


@staff_required
@require_POST
def import_cancel(request):
    _discard(request)
    messages.success(request, "Import cancelled. Nothing was saved.")
    return redirect("residents:list")


@staff_required
def import_template(request):
    allowed = _allowed(request.staff)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(COLUMNS)
    example = {
        "roll_number": "EXAMPLE001", "name": "Example Student (delete this row)", "gender": "male",
        "category": (allowed["categories"] or ["National"])[0], "diet": (allowed["diets"] or ["Vegetarian"])[0],
    }
    writer.writerow([example.get(column, "") for column in COLUMNS])
    response = HttpResponse(buffer.getvalue().encode("utf-8-sig"), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="students_template.csv"'
    return response

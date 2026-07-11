"""PyInstaller hook for Django DB backends — ShowAble uses sqlite3 only."""

hiddenimports = [
    "django.db.models.sql.compiler",
    "django.db.backends.sqlite3.base",
]

"""PyInstaller hook for Django DB backends — RemoteAble uses sqlite3 only."""

hiddenimports = [
    "django.db.models.sql.compiler",
    "django.db.backends.sqlite3.base",
]

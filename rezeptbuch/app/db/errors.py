"""Fehlerklassen der Datenbankschicht."""


class DatabaseError(Exception):
    """Grundklasse für Fehler beim Öffnen, Prüfen oder Migrieren der Datenbank."""


class MigrationError(DatabaseError):
    """Eine Migration konnte nicht eingespielt werden."""


class DatabaseIntegrityError(DatabaseError):
    """Die Integritätsprüfung hat Fehler gefunden (Datei beschädigt oder Verweise kaputt)."""

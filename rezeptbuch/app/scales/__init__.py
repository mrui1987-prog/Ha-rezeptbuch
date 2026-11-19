"""Waagen-Anbindung des Rezeptservers (Modul 08, docs/schnittstellen.md).

Der Mittelsmann (``hub.ScaleHub``) ist die einzige Stelle, die den Zustand der
Waagen kennt. REST, Live-Kanal und später der Wiegeablauf (Modul 09) fragen nur
ihn; MQTT steckt ausschließlich in ``mqtt_link`` und ``service``.
"""

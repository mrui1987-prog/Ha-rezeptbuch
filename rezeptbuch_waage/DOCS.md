# HA-Rezeptbuch Waage

Verbindet bis zu zwei Waagen mit dem HA-Rezeptbuch.

**Stand 0.1.0:** Grundgerüst. Der KERN-Treiber folgt in Modul 07.

## Aufbau

Waage (RS-232) → Waveshare-Konverter (TCP) → dieses Add-on → MQTT → HA-Rezeptbuch

## MQTT-Nachricht

Topic: `rezeptbuch/v1/station/<nr>/scale/state`

```json
{"v": 1, "station": 1, "weight_g": 9500, "stable": true, "status": "ok", "ts": "2026-11-12T12:00:00+00:00"}
```

`status` ist `ok`, `offline` oder `error`. Gewichte immer in ganzen Gramm.
